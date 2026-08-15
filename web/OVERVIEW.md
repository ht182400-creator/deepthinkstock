# 持仓管理 · 客户工具（Web 版）

> 把周频量化策略（质量+动量+Regime 门控）包装成**客户可直接使用的持仓管理工具**：左侧录入持仓 → 保存并分析 → 输出持仓操作卡、本周推荐、自动调仓记录，并提供回测对比、HTML/MD 报告与日志。

## 文件清单

| 文件 | 用途 |
|------|------|
| `web/server.py` | FastAPI 后端：标的池 / 持仓 CRUD / 分析引擎 / 报告 / 日志 |
| `web/static/index.html` | 前端主页面（浅色主题） |
| `web/static/app.js` | 前端渲染逻辑（Chart.js 图表 + API 调用 + 日志着色） |
| `web/static/style.css` | 浅色卡片化样式 |
| `web/start.bat` | 一键启动（先杀 8899 旧进程再启动，纯 ASCII） |

## 快速开始

```bash
cd web
python server.py --port 8899    # 或双击 start.bat
# 浏览器打开 http://localhost:8899
```

**首次使用**：先在左侧录入持仓（标的下拉搜索代码/名称 → 输入金额 → 可选"定投"）→ 点击 **【保存并分析】**（后台跑 `current_candidates(B)`，约 1-3 分钟）→ 右侧 7 个 Tab 填充结果。

## 左侧栏

1. **客户持仓录入**：分类（全部/沪市/深市/北交所）、标的搜索下拉（1771 只，代码+名称）、买入金额、定投标记、添加/更新/删除
2. **当前持仓**：表格展示（标的/金额/定投/买入日期），点击行可选中批量删除
3. **每周定投预算 / 新建仓预算**：`auto_track` 自动跟踪、`weekly` 定投、`newpos` 新建仓预算

## 右侧 7 个 Tab

| Tab | 内容 |
|-----|------|
| ① 持仓操作卡 | 每只持仓的 评分/建议/本周操作/说明（加仓/持有/减仓/清仓/观望），已与当前持仓交叉校验 |
| ② 本周推荐 | **⭐本周最值得买入**（selected，已过资金可行性筛选，整行标红+占预算%）+ **📋更多候选**（超预算的标"超预算X%"）|
| ③ 自动调仓记录 | 开启自动跟踪后每次分析的调仓明细 |
| ④ 历史回测 | 5 方案年化/夏普柱状图 + 汇总表 + B vs current 净值曲线（对数轴） |
| ⑤ HTML 报告 | iframe 打开最新 `dashboard_<信号日>.html` |
| ⑥ MD 报告 | 生成并下载 Markdown 报告（持仓操作卡+推荐+回测） |
| ⑦ 下载日志 | 级别着色日志（绿成功/黄警告/红错误）+ 统计条 + 筛选 + 复制 |

## API 一览

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/pool?cls=` | GET | 标的池（all/sh/sz/bj） |
| `/api/holdings` | GET/POST | 持仓列表 / 添加更新 |
| `/api/holdings/delete` | POST | 批量删除持仓 |
| `/api/settings` | GET/POST | 读取 / 保存设置 |
| `/api/analyze` | POST | **保存并分析**（后台线程，分析完自动落盘 txt + 生成 dashboard html） |
| `/api/analyze/status` | GET | 分析进度 / 最近结果 |
| `/api/backtest` | GET | 回测汇总（5 方案 × 2 窗口） |
| `/api/curves` | GET | 净值曲线数据 |
| `/api/compare` | GET | 本周 vs 上周对比 |
| `/api/action_log` | GET | 自动调仓记录 |
| `/api/logs` + `/api/logs/download` | GET | 日志查看 / 下载 |
| `/api/report/md?download=1` | GET | 生成 / 下载 MD 报告 |
| `/report/latest` | GET | 打开最新 HTML 报告 |
| `/docs` | GET | Swagger API 文档 |

## 数据存储（`web/data/`，运行时生成，不提交仓库）

| 文件 | 内容 |
|------|------|
| `holdings.json` | 客户持仓列表 |
| `settings.json` | 自动跟踪 / 定投预算 / 新建仓预算 |
| `action_log.json` | 自动调仓历史 |
| `logs/analyze.log` | 运行日志（含级别信息） |
| `reports/report_<信号日>.md` | MD 报告 |

## 分析引擎判定规则（B 方案）

- **买入候选**：质量门（ROE≥10% + FCF/N>0 + ≥3年财报）+ 52周动量正 + 站上56周均线 + 段指数站上56周均线
- **持仓操作卡**：selected→加仓/买入；buy 池→持有；观察池（段 DOWN/动量负/未站线）→减仓/观望；均不在→清仓
- **⭐本周最值得买入** = `current_candidates` 的 `selected`（按资金可行性筛选：价格×100 ≤ 单仓预算，默认 11250 元）
- **📋更多候选** = buy 池其余高分票（价格超单仓预算的会标注"超预算X%"）

## 已验证

- 完整分析管线（录入持仓 → 保存并分析 → 操作卡/推荐/回测）端到端通过
- 持仓删除后操作卡自动过滤（不显示陈旧数据）
- analyze 完成后自动落盘 `live_buy_list_<信号日>.txt` + `dashboard_<信号日>.html`
