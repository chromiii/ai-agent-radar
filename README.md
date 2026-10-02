# AI Agent Radar

一个跑在 GitHub Actions 上的 AI agent / AI 应用信息雷达。稳定主干仍然是 deterministic pipeline；Agent 能力以隔离实验逐步加入，不接管 Daily / Company / Weekly 的可靠性路径。

当前包含：

- **Daily Radar**：每日 AI agent / 多智能体 / AI 应用论文、项目、榜单简报。
- **Company Radar**：每日全球和中国 AI 公司动态简报。
- **Weekly Learning Radar**：每周六把趋势信号压缩成应用层学习周报，同时继续反哺 Daily Radar 的动态加分和降权。
- **Bounded Learning Agent（实验性）**：针对一条应用层学习问题，在已有 Weekly evidence 内做有限步 `analyze / search_more / finish` 决策。

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
state/learning_agent_run.json    # 本地 bounded Agent 实验输出（运行后生成）
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

第一版故意不接开放 Web，也不改三个生产 workflow。Agent 只能在 Weekly 已收集的 evidence 中执行：

```text
user query
   -> AgentState
   -> analyze
      | search_more (仅从 Weekly evidence 选择更多来源)
      | finish
   -> max_steps / no-progress guard
   -> state/learning_agent_run.json
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
- `search_more` 不代表开放联网；只在当前 Weekly Markdown 的真实 URL 中补证据。
- Weekly Markdown 被明确视为 untrusted evidence，不能给 Agent 新权限。
- 达到预算仍未 finish 时状态为 `stopped_max_steps`，交给人决定是否继续。

本地运行：

```bash
python learning_agent.py "这周 Agent memory 应用层需要学什么？" --max-steps 5
```

指定周报：

```bash
python learning_agent.py "LangGraph checkpoint 为什么值得学？" --weekly weekly/2026-10-03.md
```

测试：

```bash
python -m pytest tests/test_learning_agent.py
```

测试覆盖非法 action、grounded evidence selection、正常 finish、连续无进展停止和 max_steps 停止。

> 当前状态：这是隔离实验，不是 Daily / Company / Weekly 的生产依赖；也还不是 Multi-Agent。

## GitHub Secrets

### DeepSeek

```text
DEEPSEEK_API_KEY
```

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

已实现：稳定三条 pipeline、Weekly 学习卡、趋势 state、bounded single-Agent 实验。

尚未实现：开放工具搜索、LangGraph runtime、跨运行 Agent memory、RAG、Research/Analyst/Verifier Multi-Agent、Web UI、完整 tracing/evaluation。具体演进见 `ROADMAP_AGENT.md`。
