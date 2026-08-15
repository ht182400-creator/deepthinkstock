#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓管理 · 客户工具 —— FastAPI 后端（Web 版）。

用法: python server.py [--port 8899]
功能:
  标的池 / 持仓录入 / 保存并分析(持仓操作卡+本周推荐+自动调仓) / 历史回测 / HTML/MD 报告 / 日志下载。
"""
import os, sys, json, glob, re, threading, time, subprocess
from datetime import datetime, date
from pathlib import Path

# 确保能 import 父目录的现有模块
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT)

try:
    from fastapi import FastAPI, BackgroundTasks, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
    import uvicorn
except ImportError:
    print("[server] 缺少依赖, 正在安装 FastAPI + uvicorn ...")
    subprocess_run = __import__('subprocess').run
    subprocess_run([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "-q"])
    from fastapi import FastAPI, BackgroundTasks, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
    import uvicorn

import regime_layer2_backtest as R

# ==================== 常量 ====================
WORK = PARENT
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(WEB_DIR, "static")
DATA_DIR = os.path.join(WEB_DIR, "data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
for _d in (DATA_DIR, LOGS_DIR, REPORTS_DIR):
    os.makedirs(_d, exist_ok=True)

HOLDINGS = os.path.join(DATA_DIR, "holdings.json")
SETTINGS = os.path.join(DATA_DIR, "settings.json")
ACTION_LOG = os.path.join(DATA_DIR, "action_log.json")
LOG_FILE = os.path.join(LOGS_DIR, "analyze.log")

DEFAULT_SETTINGS = {"auto_track": False, "weekly": 10000, "newpos": 5000, "cash": 50000, "N": 4}

# ==================== 全局状态 ====================
ANALYZE = {"running": False, "message": "", "percent": 0,
           "last_result": None, "last_ts": None}

app = FastAPI(title="持仓管理 · 客户工具", version="2.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ==================== 数据存取 ====================
def _load(p, default):
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def _save(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

def _mkt(code):
    if code.startswith(("920", "8", "4")):
        return "bj"
    if code.startswith(("60", "68", "90")):
        return "sh"
    return "sz"

def _log_line(s):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    return line

# ==================== 标的池 ====================
_POOL_CACHE = None
def get_pool():
    global _POOL_CACHE
    if _POOL_CACHE is not None:
        return _POOL_CACHE
    fund = _load(os.path.join(WORK, "fundamentals_broad.json"), {})
    pool = []
    for code, f in fund.items():
        pool.append(dict(code=code,
                         name=f.get("name") or code,
                         industry=f.get("industry") or "",
                         market=_mkt(code)))
    pool.sort(key=lambda r: r["code"])
    _POOL_CACHE = pool
    return pool

# ==================== 持仓 ====================
def get_holdings():
    return _load(HOLDINGS, [])

def get_settings():
    s = DEFAULT_SETTINGS.copy()
    s.update(_load(SETTINGS, {}))
    return s

def get_action_log():
    return _load(ACTION_LOG, [])

# ==================== 分析引擎 ====================
def _score_for(rec):
    """把回测打分(0~1)映射为 0~100。"""
    return round(min(99.0, max(1.0, (rec.get("score") or 0) * 100)), 1)

def _analyze_job(force_refresh, auto_track, cash, N):
    try:
        ANALYZE["running"] = True
        ANALYZE["message"] = "构建宇宙 (读取通达信 .day 前复权)..."
        ANALYZE["percent"] = 5
        _log_line(f"开始分析 force_refresh={force_refresh} auto_track={auto_track} cash={cash} N={N}")

        # 核心: 跑一次 current_candidates(B 方案)
        res = R.current_candidates(scheme="B", cash=cash, N=N)
        ANALYZE["percent"] = 60
        ANALYZE["message"] = "生成持仓操作卡..."

        buy_map = {r["code"]: r for r in res["buy"]}
        sel_map = {r["code"]: r for r in res["selected"]}
        obs_map = {}
        for r in res["observation"] + res.get("bj_observe", []):
            obs_map.setdefault(r["code"], r)

        holdings = get_holdings()
        holdings_map = {h["code"]: h for h in holdings}

        # ---- 持仓操作卡 ----
        cards = []
        for h in holdings:
            code = h["code"]
            r = buy_map.get(code) or obs_map.get(code)
            market = _mkt(code)
            base = dict(code=code, name=h.get("name", code),
                        industry=h.get("industry", ""), market=market,
                        amount=h.get("amount", 0), dingtou=h.get("dingtou", False),
                        date=h.get("date", ""))
            if code in sel_map:
                base.update(score=_score_for(sel_map[code]), advice="加仓",
                            action="买入", desc="入选本周建仓清单（质量+动量+站线全过）")
            elif code in buy_map:
                base.update(score=_score_for(buy_map[code]), advice="持有",
                            action="持有", desc="通过质量+动量+站线+段regime，未进本轮建仓")
            elif code in obs_map:
                fail = obs_map[code].get("fail", "")
                if "段regime" in fail or "DOWN" in fail:
                    base.update(score=50.0, advice="减仓", action="观望",
                                desc=f"板块指数在 56 周线下方（{fail}）")
                elif "动量负" in fail:
                    base.update(score=45.0, advice="减仓", action="减仓",
                                desc="近 52 周收益为负（动量转弱）")
                elif "未站线" in fail:
                    base.update(score=58.0, advice="持有", action="观望",
                                desc="未站上 56 周均线，等信号回暖")
                else:
                    base.update(score=50.0, advice="观望", action="观望",
                                desc=f"观察中（{fail}）")
            else:
                base.update(score=30.0, advice="清仓", action="卖出",
                            desc="未通过质量门（ROE/FCF）或数据缺失，建议剔除")
            cards.append(base)

        # ---- 本周推荐：⭐精选(selected,模型最该买的N只) + 更多候选(buy池其余)----
        held = {h["code"]: h for h in holdings}
        sel_codes = {r["code"] for r in res["selected"]}

        # ⭐ 本周最值得买入（HTML报告里的"实际建仓清单" = selected，已通过资金可行性筛选）
        selected_recs = []
        per_pos_max = res.get("per_pos") or (cash * res.get("expo_base", 0.9) / N)  # 单仓预算上限
        for r in res["selected"]:
            is_held = r["code"] in held
            h = held.get(r["code"], {})
            lots = r.get("lots", 0)
            cap = r.get("capital", 0)
            one_hand = r.get("price", 0) * 100
            selected_recs.append(dict(
                code=r["code"], name=r.get("name", r["code"]),
                industry=r.get("sind", ""), market=_mkt(r["code"]),
                score=_score_for(r),
                advice="加仓" if is_held else "买入",
                action="加仓(已持仓)" if is_held else "建议建仓",
                held=is_held, is_top=True,
                held_amount=h.get("amount", 0),
                price=r.get("price", 0),
                lots=lots, capital=cap,
                one_hand=one_hand,
                fea_ratio=round(one_hand / per_pos_max * 100, 1) if per_pos_max > 0 else 0,
                desc=f"ROE {r.get('roe', 0)*100:.1f}% · 52w动量 +{r.get('mom', 0)*100:.0f}% · 段 {r.get('seg', '')} UP"
                     f" · {lots}手 ≈ {cap:.0f}元"))

        # 📋 更多候选（buy 池中除 selected 之外，按"持仓→评分"排序）
        recs = [r for r in res["buy"] if r["code"] not in sel_codes]
        recs.sort(key=lambda r: (0 if r["code"] in held else 1, -r.get("score", 0)))
        recommends = []
        for r in recs[:12]:
            is_held = r["code"] in held
            h = held.get(r["code"], {})
            one_hand = r.get("price", 0) * 100
            over_budget = one_hand > per_pos_max
            over_msg = f" · 一手 {one_hand:.0f}元 > 单仓预算{per_pos_max:.0f}元(超预算)" if over_budget else ""
            recommends.append(dict(
                code=r["code"], name=r.get("name", r["code"]),
                industry=r.get("sind", ""), market=_mkt(r["code"]),
                score=_score_for(r),
                advice="加仓" if is_held else "买入",
                action="加仓(已持仓)" if is_held else "建议建仓",
                held=is_held, is_top=False,
                held_amount=h.get("amount", 0),
                price=r.get("price", 0),
                one_hand=one_hand,
                fea_ratio=round(one_hand / per_pos_max * 100, 1) if per_pos_max > 0 else 0,
                desc=f"ROE {r.get('roe', 0)*100:.1f}% · 52w动量 +{r.get('mom', 0)*100:.0f}% · 段 {r.get('seg', '')} UP{over_msg}"))

        # ---- 自动调仓 ----
        actions = []
        settings = get_settings()
        if auto_track and settings.get("auto_track"):
            ANALYZE["message"] = "自动跟踪调仓..."
            newpos = settings.get("newpos", 5000)
            changed = []
            for card in cards:
                code = card["code"]
                if card["advice"] == "清仓":
                    changed.append(dict(code=code, name=card["name"], op="卖出",
                                        detail=f"金额 {card['amount']:.0f} → 0（清仓）"))
                elif card["advice"] == "加仓":
                    old = card["amount"]
                    holdings_map[code]["amount"] = old + newpos
                    changed.append(dict(code=code, name=card["name"], op="加仓",
                                        detail=f"金额 {old:.0f} → {old+newpos:.0f}（+新建仓预算）"))
                else:
                    changed.append(dict(code=code, name=card["name"], op="维持",
                                        detail=f"金额 {card['amount']:.0f} 不变"))
            if changed:
                actions.append(dict(ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    signal=res["signal_date"], items=changed))
                holdings = [h for h in holdings if h["code"] not in
                            {c["code"] for c in cards if c["advice"] == "清仓"}]
                _save(HOLDINGS, holdings)
            _save(ACTION_LOG, (actions + get_action_log())[:200])
            _log_line(f"自动调仓: {len(changed)} 项变更")

        # ---- 结果汇总 ----
        result = dict(
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal_date=res["signal_date"], regime_up=res["regime_up"],
            scheme=res["scheme"], n_stocks=res["n_stocks"],
            cards=cards, recommends=recommends,
            selected_recommends=selected_recs,
            summary=dict(
                held=len(cards), buy_pool=len(res["buy"]),
                selected=len(res["selected"]), obs=len(res["observation"]),
                recommend=len(recommends),
                total_amt=sum(c.get("amount", 0) for c in cards),
                regime_cn="全部上涨 → 建议建仓" if res["regime_up"] else "存在下跌段 → 空仓观望",
            ),
        )
        ANALYZE["last_result"] = result
        ANALYZE["last_ts"] = result["ts"]
        ANALYZE["percent"] = 100
        ANALYZE["message"] = "分析完成"
        _log_line(f"分析完成 signal={res['signal_date']} 持仓{len(cards)} 推荐{len(recommends)}")

        # ---- 落盘: 写 txt + 生成新 dashboard html（让"打开 HTML 报告"能拿到最新信号日）----
        try:
            from regime_layer2_backtest import format_live_report
            txt = format_live_report(res)
            txt_path = os.path.join(WORK, f"live_buy_list_{res['signal_date']}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            _log_line(f"已写 txt: {txt_path}")
            # 生成 dashboard html (耗时 1-3 秒, 跑在后台线程不影响 API)
            r = subprocess.run(
                [sys.executable, "build_dashboard.py"],
                cwd=WORK, capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                _log_line("dashboard html 已刷新")
            else:
                _log_line(f"dashboard html 刷新失败 rc={r.returncode} err={r.stderr[:200]}")
        except Exception as e:
            _log_line(f"落盘 dashboard 异常: {e}")
    except Exception as e:
        _log_line(f"分析异常: {e}")
        ANALYZE["message"] = f"异常: {e}"
        import traceback
        traceback.print_exc()
    finally:
        ANALYZE["running"] = False


# ==================== API ====================
@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat(),
            "os": sys.platform, "python": sys.version.split()[0]}

@app.get("/api/pool")
async def api_pool(cls: str = "all"):
    """标的池。cls: all/sh/sz/bj"""
    pool = get_pool()
    if cls and cls != "all":
        pool = [p for p in pool if p["market"] == cls]
    return {"total": len(pool), "items": pool}


# ==================== 历史回测 / 曲线 / 周对比 ====================
@app.get("/api/backtest")
async def api_backtest():
    """回测对比汇总（5 方案 × 2 窗口）。"""
    data = _load(os.path.join(WORK, "results_layer2_fresh.json"), None)
    if not data:
        return JSONResponse({"error": "尚未生成回测数据，请先运行 dump_curves.py"},
                           status_code=404)
    return data

@app.get("/api/curves")
async def api_curves():
    """净值曲线数据（B + current 方案）。"""
    data = _load(os.path.join(WORK, "results_layer2_curves.json"), None)
    if not data:
        return JSONResponse({"error": "尚未生成曲线数据"}, status_code=404)
    return data

@app.get("/api/compare")
async def api_compare():
    """本周 vs 上周对比（来自 live_compare.json）。"""
    data = _load(os.path.join(WORK, "live_compare.json"), None)
    if not data:
        return JSONResponse({"error": "尚未生成对比数据，请先运行 live_compare.py"},
                           status_code=404)
    return data

@app.post("/api/refresh")
async def api_refresh(background_tasks: BackgroundTasks):
    """后台触发完整数据刷新（live_compare + dump_curves）。约 5 分钟。"""
    if ANALYZE["running"]:
        return JSONResponse({"error": "刷新任务进行中"}, status_code=409)
    def _run():
        global ANALYZE
        ANALYZE["running"] = True
        ANALYZE["message"] = "启动全管线刷新..."
        ANALYZE["percent"] = 2
        try:
            _log_line("触发完整管线刷新 (live_compare + dump_curves)")
            subprocess.run([sys.executable, "live_compare.py"], cwd=WORK, timeout=900)
            ANALYZE["percent"] = 60
            ANALYZE["message"] = "回测曲线..."
            subprocess.run([sys.executable, "dump_curves.py"], cwd=WORK, timeout=900)
            ANALYZE["percent"] = 100
            ANALYZE["message"] = "刷新完成"
            _log_line("完整管线刷新完成")
        except Exception as e:
            _log_line(f"刷新失败: {e}")
            ANALYZE["message"] = f"异常: {e}"
        finally:
            ANALYZE["running"] = False
    threading.Thread(target=_run, daemon=True).start()
    return {"message": "刷新已提交", "running": True}


@app.get("/api/holdings")
async def api_holdings():
    return {"items": get_holdings()}

@app.post("/api/holdings")
async def api_holdings_add(body: dict):
    code = str(body.get("code", "")).strip()
    amount = float(body.get("amount", 0) or 0)
    dingtou = bool(body.get("dingtou", False))
    if not code:
        raise HTTPException(400, "标的代码不能为空")
    pool_map = {p["code"]: p for p in get_pool()}
    if code not in pool_map:
        raise HTTPException(400, f"标的 {code} 不在可投资池中")
    holdings = get_holdings()
    for h in holdings:
        if h["code"] == code:
            h["amount"] = amount
            h["dingtou"] = dingtou
            break
    else:
        holdings.append(dict(code=code,
                             name=pool_map[code]["name"],
                             industry=pool_map[code]["industry"],
                             amount=amount, dingtou=dingtou,
                             date=date.today().strftime("%Y-%m-%d")))
    _save(HOLDINGS, holdings)
    _log_line(f"添加/更新持仓 {code} amount={amount} dingtou={dingtou}")
    return {"items": holdings}

@app.post("/api/holdings/delete")
async def api_holdings_delete(body: dict):
    codes = set(body.get("codes", []))
    holdings = [h for h in get_holdings() if h["code"] not in codes]
    _save(HOLDINGS, holdings)
    _log_line(f"删除持仓 {sorted(codes)}")
    return {"items": holdings}

@app.get("/api/settings")
async def api_settings():
    return get_settings()

@app.post("/api/settings")
async def api_settings_save(body: dict):
    s = get_settings()
    for k in ("auto_track", "weekly", "newpos", "cash", "N"):
        if k in body:
            s[k] = body[k]
    _save(SETTINGS, s)
    _log_line(f"更新设置 {s}")
    return s

@app.post("/api/analyze")
async def api_analyze(body: dict = None):
    """保存并分析（后台任务）。body: {force_refresh, auto_track}"""
    if ANALYZE["running"]:
        return JSONResponse({"error": "分析正在进行中"}, status_code=409)
    body = body or {}
    settings = get_settings()
    force_refresh = bool(body.get("force_refresh", False))
    auto_track = bool(body.get("auto_track", False))
    t = threading.Thread(target=_analyze_job,
                         args=(force_refresh, auto_track,
                               settings.get("cash", 50000), settings.get("N", 4)),
                         daemon=True)
    t.start()
    _log_line(f"提交分析任务 force_refresh={force_refresh} auto_track={auto_track}")
    return {"message": "分析已提交", "running": True}

@app.get("/api/analyze/status")
async def api_analyze_status():
    return {"running": ANALYZE["running"], "message": ANALYZE["message"],
            "percent": ANALYZE["percent"], "result": ANALYZE["last_result"],
            "ts": ANALYZE["last_ts"]}

@app.get("/api/action_log")
async def api_action_log():
    return {"items": get_action_log()}

@app.get("/api/logs")
async def api_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
        return {"items": lines[-200:]}
    return {"items": []}

@app.get("/api/logs/download")
async def api_logs_download():
    if not os.path.exists(LOG_FILE):
        raise HTTPException(404, "暂无日志")
    return FileResponse(LOG_FILE, filename="analyze.log",
                        media_type="text/plain; charset=utf-8")

@app.get("/report/latest")
async def report_latest():
    """打开最近一份 HTML 看盘报告。"""
    files = sorted(glob.glob(os.path.join(WORK, "dashboard_*.html")))
    if not files:
        raise HTTPException(404, "暂无 HTML 报告，请先保存并分析")
    return FileResponse(files[-1])

@app.get("/api/report/md")
async def report_md(download: int = 0):
    """生成 MD 报告。download=1 下载。"""
    res = ANALYZE["last_result"]
    bt = _load(os.path.join(WORK, "results_layer2_fresh.json"), {})
    if not res:
        raise HTTPException(404, "暂无分析结果，请先保存并分析")
    lines = []
    lines.append(f"# 持仓分析报告（{res['signal_date']}）\n")
    lines.append(f"- 生成时间：{res['ts']}")
    lines.append(f"- 市场状态：{res['summary']['regime_cn']}")
    lines.append(f"- 持仓 {res['summary']['held']} 只 / 合格池 {res['summary']['buy_pool']} 只 / 本周推荐 {res['summary']['recommend']} 只\n")
    lines.append("## 一、持仓操作卡\n")
    lines.append("| 代码 | 名称 | 行业 | 市场 | 金额(元) | 评分 | 建议 | 本周操作 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in res["cards"]:
        lines.append(f"| {c['code']} | {c['name']} | {c['industry'] or '-'} | {c['market']} | "
                     f"{c.get('amount',0):.0f} | {c['score']:.0f} | {c['advice']} | {c['action']} | {c['desc']} |")
    lines.append("\n## 二、本周推荐（未持仓候选）\n")
    lines.append("| 代码 | 名称 | 行业 | 评分 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for r in res["recommends"]:
        lines.append(f"| {r['code']} | {r['name']} | {r['industry'] or '-'} | {r['score']:.0f} | {r['desc']} |")
    lines.append("\n## 三、历史回测对比（全样本 1996+）\n")
    lines.append("| 方案 | 年化 | 夏普 | 最大回撤 | 空仓占比 |")
    lines.append("|---|---|---|---|---|")
    for lab, key in [("current(上证)", "current_全样本1996+"), ("B(分市场段)", "B_全样本1996+"),
                     ("C(内生)", "C_全样本1996+"), ("A(全指)", "A_全样本1996+"),
                     ("E(尾部)", "E_全样本1996+")]:
        r = bt.get(key)
        if r:
            lines.append(f"| {lab} | {r['annualized']*100:.1f}% | {r['sharpe']:.2f} | "
                         f"{r['max_drawdown']*100:.0f}% | {r['empty_frac']*100:.0f}% |")
    lines.append("\n---\n*本报告仅供参考，不构成个人投资建议。数据来源：通达信本地行情 + 东方财富基本面。*\n")
    md = "\n".join(lines)
    if download:
        fn = f"report_{res['signal_date']}.md"
        p = os.path.join(REPORTS_DIR, fn)
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)
        return FileResponse(p, filename=fn, media_type="text/markdown; charset=utf-8")
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")

@app.get("/")
async def root():
    idx = os.path.join(STATIC, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return JSONResponse({"message": "index.html not found"}, status_code=404)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", type=str, default="0.0.0.0")
    args = ap.parse_args()
    print(f"\n{'='*60}")
    print(f"  持仓管理 · 客户工具（Web）")
    print(f"  地址: http://localhost:{args.port}")
    print(f"  API:  http://localhost:{args.port}/docs")
    print(f"  工作目录: {WORK}")
    print(f"{'='*60}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
