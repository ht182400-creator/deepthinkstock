# DeepThinkStock · A股周频量化策略与持仓管理工具

> 用本地通达信全历史日线（.day）+ 前复权 + 东方财富基本面，跑"质量 + 动量 + Regime 门控"周频选股策略，并提供**持仓管理 · 客户工具** Web 界面。
>
> **声明：本仓库仅供量化研究与学习参考，不构成任何投资建议。**

---

## ✨ 核心功能

| 模块 | 说明 |
|------|------|
| **策略内核** | 质量门（ROE≥10% + 自由现金流转正 + ≥3 年财报）+ 52 周动量为正 + 站上 56 周均线 + 板块 Regime 门控 |
| **五方案回测** | current(上证56w) / A(中证全指56w) / B(分市场段56w) / C(内生无Regime) / E(上证200w尾部) 全样本 + 2014+ 双窗口对比 |
| **实时买仓清单** | 5 万元 / 3–4 仓 / 100 股手数约束，按资金可行性自动集中到可整手买入的标的 |
| **Web 客户工具** | 持仓录入 → 保存并分析 → 持仓操作卡 / 本周推荐 / 自动调仓记录 / 历史回测 / HTML+MD 报告 / 日志下载 |
| **数据管线** | 通达信 .day 本地解密 + gbbq 权息前复权（`read_qfq`）+ 东财基本面抓取（沪深+北交所 1771 只） |

## 📊 回测结论（方案 B 修复后，1687 只含北交所，周线 1990+）

| 方案 | 全样本年化 | 2014+ 年化 | 夏普 | 最大回撤 | 空仓占比 |
|------|-----------|-----------|------|---------|---------|
| current(上证) | 11.4% | 9.8% | 0.50 | -52% | 46% |
| **B(分市场段, 修复后)** | **10.8%** | **7.2%** | **0.41** | **-56%** | 0% |
| C(内生无Regime) | 9.2% | 2.5% | 0.29 | -68% | 0% |
| A(中证全指) | 6.7% | -1.8% | 0.29 | -57% | 45% |
| E(上证200w尾部) | 1.7% | -3.5% | -0.02 | -74% | 45% |

**结论**：B 方案（分市场段门控）在修复"段指数缺失退化为无脑放行"的缺陷（改为回退上证门控）后，长期与上证单指数门控基本持平，回撤显著收敛，**作为实时买仓默认 gate**；E 方案（尾部降仓）经多参数验证被否定。

## 🚀 快速开始

### 环境要求
- Windows（通达信数据源依赖本地 D 盘路径，可改）
- Python 3.10+
- 通达信客户端（用于下载 .day 日线数据）

### 1. 安装依赖
```bash
pip install fastapi uvicorn
```

### 2. 准备数据
- 在通达信客户端**手动下载**沪/深/北交所日线（.day 文件到 `D:/new_tdx64/vipdoc/{sh,sz,bj}/lday/`）
- 首次运行 `fetch_fund_broad.py` + `fetch_fund_bj.py` 抓取基本面（季度刷新一次即可）

### 3. 跑回测
```bash
python dump_curves.py        # 重算回测汇总 + 净值曲线（约 5 分钟）
python regime_layer2_backtest.py live B 50000 4   # 生成实时买仓清单
```

### 4. 启动 Web 客户工具
```bash
cd web
python server.py --port 8899    # 或直接双击 start.bat
# 浏览器打开 http://localhost:8899
```

## 🗂 目录结构

```
deepthinkstock/
├── regime_layer2_backtest.py   # 核心：Layer2 回测引擎 + 实时买仓 (B方案)
├── tdx_day_reader.py           # 通达信 .day 读取 + gbbq 前复权
├── decode_gbbq.py              # 通达信权息文件解密（自定义 Feistel 密码）
├── dump_curves.py              # 重算回测指标 + 净值曲线
├── live_compare.py             # 本周 vs 上周信号对比
├── fetch_fund_broad.py         # 沪深基本面抓取（东财 DMSK 三表）
├── fetch_fund_bj.py            # 北交所基本面抓取
├── fetch_names.py              # 证券名称补全（腾讯行情接口）
├── backtest_fund.py            # 质量+动量 500 池回测
├── backtest_v3.py / v4.py      # 价值/质量策略演化版本
├── build_dashboard.py          # 生成 dashboard_<信号日>.html 报告
├── build_buylist*.py           # 买仓清单 HTML 生成
├── weekly_friday.bat           # 周五例行批处理（下载数据→跑清单→出报告）
└── web/                        # Web 客户工具（FastAPI + Chart.js）
    ├── server.py               #   API 后端
    ├── start.bat               #   一键启动（先杀旧进程再启动）
    ├── static/                 #   前端 (index.html / app.js / style.css)
    └── data/                   #   运行时数据（不提交）
```

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| `strategy_v3.md` | 最优方案：质量+价值(GARP)+低波 三维复合策略设计 |
| `strategy_v2.md` | 集中式质量复利策略设计 |
| `report.md` | 价值投资 3 年回归测试报告 |
| `regime_paradox.md` | Regime 门控"以偏带全"问题研究 |
| `tdx_README.md` | 通达信本地数据读取说明 |
| `tdx_rights_guide.md` | 权息前复权指南 |
| `tdx_audit.md` | 通达信数据审计 |
| `通达信公式_质量动量策略.md` | 通达信公式：K线信号标记 |
| `data_verification.md` | 数据校验记录 |
| `web/OVERVIEW.md` | Web 工具交付说明 |

## ⚠️ 数据文件说明

以下大文件/运行时文件**不提交**到仓库，需本地生成：

| 文件 | 大小 | 生成方式 |
|------|------|---------|
| `daily_broad.json` | ~133MB | `fetch_broad.py`（全宇宙日线缓存）|
| `all_xdxr.csv` | ~18MB | `decode_gbbq.py`（权息记录）|
| `fundamentals_broad.json` | ~6MB | `fetch_fund_broad.py` + `fetch_fund_bj.py` |
| `universe*.json` / `daily_kc.json` | ~11MB | 对应抓取脚本 |
| `web/data/` | — | Web 运行时自动生成 |

## 🛠 周五例行流程

1. **手动**打开通达信，下载沪/深/北交所日线（脚本无法下载行情）
2. 双击 `weekly_friday.bat`：
   - [0/3] 杀旧进程 → [1/3] 依赖检查 → [START]
   - 生成实时买仓 + 本周对比 → 刷新回测曲线 → 重生成面板 → 自动打开浏览器

## 📄 License

MIT（见 `LICENSE`）。

---

*本仓库所有策略、回测结果仅供研究参考，不构成个人投资建议。数据来源：通达信本地行情、东方财富基本面、腾讯行情。历史表现不代表未来收益。*
