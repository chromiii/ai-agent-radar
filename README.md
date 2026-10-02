# AI Agent Radar

一个跑在 GitHub Actions 上的 AI agent / AI 应用信息雷达。稳定主干仍然是 deterministic pipeline；Agent 能力以隔离实验逐步加入，不接管 Daily / Company / Weekly 的可靠性路径。

当前包含：

- **Daily Radar**：每日 AI agent / 多智能体 / AI 应用论文、项目、榜单简报。
- **Company Radar**：每日全球和中国 AI 公司动态简报。
- **Weekly Learning Radar**：每周六把趋势信号压缩成应用层学习周报，同时继续反哺 Daily Radar 的动态加分和降权。
- **Bounded Learning / Research Agent（实验性，V2.1）**：针对应用层学习问题扩展查询、检索外部来源，在步数和请求预算内生成带来源的学习发现。
- **Ask Radar（V2.2）**：在 Actions 输入自由问题，直接阅读和周报一致的学习卡，包含概念、应用场景、学习深度、小练习、完成标准及来源。

## 直接问一个问题

在 GitHub 仓库打开 **Actions → Ask Radar → Run workflow**，输入最多 600 字的问题，例如“我想用 MCP 给一个 Python 工具加接口，有哪些值得学的实现？”。运行后，打开该次运行的 Overview 阅读学习卡。需要查看来源记录时，下载 `ask-radar-answer`，其中 `answer.md` 是可读回答，`run.json` 是检索和运行记录；artifact 保留 7 天。

工作流在 GitHub 内使用已有的 `DEEPSEEK_API_KEY` Secret。此入口只生成回答，不发送邮件。新工作流需合并到默认分支后才会显示手动运行按钮；PR 阶段可用 `ask-radar-preview` 标签跑一个预览问题。

每张卡回答：30 秒概念、为什么值得了解、用在哪里、应用层学到这里、15–30 分钟的小练习、完成标准及来源。`先知道 / 值得动手 / 理解原因` 表示学习深度；练习时间是建议预算，内容质量仍需要阅读判断。

本地入口：

```bash
python ask_radar.py --question "最近 coding agent 有什么值得学？"
```

V2.2 的评测和范围见 [学习可用性说明](docs/V2_2_USABILITY.md)。

## 产品原则

```text
Reliable Pipeline
  fetch -> normalize -> dedupe -> rank -> publish
                         |
                         +-> bounded Agent experiments
```

Agent 目前不是生产主干。即使 Agent 实验失败，Daily / Company / Weekly 仍应正常运行。

## 结果目录

```text
inbox/YYYY-MM-DD.md              # Daily Radar
company/YYYY-MM-DD.md            # Company Radar
weekly/YYYY-MM-DD.md             # Weekly Learning Radar
state.json                       # Daily 已处理内容
state/company_seen.json          # Company 14 天内已处理链接
state/trending_terms.json        # Weekly 生成的趋势词
state/agent_runs/TASK_ID.json    # 按任务保存的 Agent 运行记录（默认不提交）
```

## 工作流

### Daily Radar

脚本：`radar.py`

Workflow：`.github/workflows/daily.yml`

流程：

```text
读取 config.yaml
  -> 读取 state.json 和 state/trending_terms.json
  -> 抓取 Hugging Face Daily Papers / Spaces / Competitions / arXiv
  -> HF Daily Papers 如果当天不可用，最多回退 3 天
  -> 按论文 ID 跨来源去重
  -> 规则打分，Weekly tier1/tier2 加分，downrank 降权
  -> 过滤已写入日报的 seen 内容
  -> 取最高分候选
  -> DeepSeek 做 must_read / scan / skip 分类
  -> 程序渲染 Markdown
  -> 写入 inbox/
  -> 更新 state.json
  -> 发送 QQ 邮件
```

### Company Radar

脚本：`company_radar.py`

Workflow：`.github/workflows/company-radar.yml`

```text
读取 config.yaml
  -> 读取 state/company_seen.json
  -> 抓取全球和中国公司页面
  -> 过滤导航 / 招聘 / footer 等噪音
  -> 过滤 14 天内已见链接
  -> 规则打分
  -> DeepSeek 紧凑 JSON 分类
  -> Markdown
  -> state/company_seen.json
  -> QQ 邮件
```

### Weekly Learning Radar

脚本：`weekly_trends.py`

Workflow：`.github/workflows/weekly-trends.yml`

```text
最近 7 天 HF Daily Papers / HF Spaces / arXiv
  -> 候选趋势词
  -> DeepSeek 精筛 tier1 / tier2 / downrank / noise
  -> 5–8 张应用层学习卡片（Know / Build / Understand Why）
  -> weekly/
  -> state/trending_terms.json
  -> 每周六邮件
```

纯科研内容只有在能解释工程设计、benchmark、failure mode 或 capability boundary 时才应该进入学习卡。

### Bounded Learning Agent（实验性）

脚本：`learning_agent.py`

这个实验回答的是一个非常具体的问题：**什么时候固定 pipeline 不够，需要让模型根据刚得到的 observation 决定下一步？**

V2.1 的默认 CLI 模式是外部检索。原来的 Weekly 链接匹配保留为 `--mode weekly`，用于回归比较；Python API 的 `AgentState` 默认仍为 weekly，外部模式需显式设置 `search_mode="external"`。

```text
user query
   -> original query + alias expansion + explicit date window
   -> bounded search (HF papers / GitHub / arXiv / optional Tavily)
   -> canonical dedup + date filter + lexical relevance
   -> model chooses analyze / search_more / finish
   -> finding/citation validation + deterministic rendering
   -> state/agent_runs/TASK_ID.json
```

State 至少包含：

```text
task_id
user_query
current_step
max_steps
observations
selected_items
last_action
no_progress_count
status
final_answer
```

关键边界：

- `max_steps` 默认 5，CLI 只允许 1–10。
- 连续两次 `search_more` 没有新增 evidence 会停止。
- action 只允许 `analyze / search_more / finish`。
- 外部检索默认最多 8 次 API 请求、每轮最多 4 条查询、最多保留 12 条证据；失败来源在该次运行内隔离。
- “最近”默认近 30 天，“这周”取近 7 天，可解析“过去 N 天/周”。Agent 日期使用 `learning_agent.timezone`（Asia/Shanghai）。
- 医药查询覆盖 healthcare、clinical workflow、biomedical、drug discovery。当前扩展是可追踪的词表规则，不是 embedding / BM25 / 通用语义搜索。
- 每条发现包含主题、信号/趋势等级、引用、应用层意义、动手建议。研究回答至少引用两个不同来源；“趋势”需要该条发现有两个带发布日期的来源。
- 仓库 `pushed_at` 只表示活动日期；无日期和窗口外资料不能支撑“最近”。同一篇 HF/arXiv 论文只计一条来源。
- 模型 JSON 出错、引用编造、结论校验失败会留下记录并停止；证据不足可正常返回 `finished_insufficient_evidence`。
- 网页摘要、论文摘要及 Weekly Markdown 都是 untrusted evidence，不能给 Agent 新权限。
- 达到预算仍未 finish 时状态为 `stopped_max_steps`，交给人决定是否继续。

本地运行：

```bash
python -m pip install -r requirements.txt
python learning_agent.py "最近医药 Agent 有什么趋势？" --max-steps 5
```

指定周报：

```bash
python learning_agent.py "LangGraph checkpoint 为什么值得学？" --mode weekly --weekly weekly/2026-09-27.md
```

测试：

```bash
python -m pytest -q
python research_eval.py --mode replay
python research_eval.py --mode retrieval --case medical-agent-trends
python research_eval.py --mode live --case medical-agent-trends
```

`replay` 使用明确标注的合成资料与脚本决策，验证可重复的产品契约；`retrieval` 真正联网但不调用模型；`live` 才调用 DeepSeek。结构测试通过不代表语义质量、引用蕴含关系或真实部署效果已被证明。

只检查真实来源、无需模型密钥：

```bash
python learning_agent.py "最近医药 Agent 有什么趋势？" --retrieval-only
```

也可在 GitHub Actions 的 **Research usability evaluation** 中手动选择模式和案例。设计、故障复现及本阶段验证见 [V2.1 阶段说明](docs/V2_1_RESEARCH.md)。

> 当前状态：这是隔离实验，不是 Daily / Company / Weekly 的生产依赖；也还不是 Multi-Agent。

## GitHub Secrets

### DeepSeek

```text
DEEPSEEK_API_KEY
```

Agent 外部检索可选环境变量 / GitHub Secrets：

```text
TAVILY_API_KEY   # 网页检索；缺失时报告覆盖限制，论文/项目检索继续
GITHUB_TOKEN    # 可选，提高 GitHub API 额度；Actions 可使用内置 token
```

外部 Agent 不发送邮件；生产周报继续按现有每周六设置投递。

### QQ 邮箱

```text
QQ_MAIL_USERNAME
QQ_MAIL_PASSWORD
QQ_MAIL_TO
```

可选：

```text
QQ_SMTP_HOST
QQ_SMTP_PORT
QQ_MAIL_FROM
```

## 定时设置

```text
Daily Radar:   00:00 Australia/Sydney -> 14:00 UTC (AEST baseline)
Company Radar: 00:30 Australia/Sydney -> 14:30 UTC (AEST baseline)
Weekly Radar:  Saturday 10:00 AEST / 11:00 AEDT -> Saturday 00:00 UTC
```

## 当前实现 vs Roadmap

已实现：稳定三条 pipeline、Weekly 学习卡、趋势 state、bounded single-Agent 实验、有限外部检索、可追踪查询扩展、引用结构校验和八个可用性场景。

尚未实现：语义检索/重排、独立语义 Verifier、LangGraph runtime、跨运行 Agent memory、历史 RAG、Research/Analyst/Verifier Multi-Agent、Web UI、完整 tracing/evaluation。具体演进见 `ROADMAP_AGENT.md`。
