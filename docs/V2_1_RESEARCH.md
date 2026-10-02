# V2.1：从周报链接匹配到可检查的外部研究

本阶段回答一个真实问题：用户问“最近医药 Agent 有什么趋势？”，即使 Weekly 没有医疗内容，系统也应能补查外部资料，并如实说明能支持到什么程度。

## 代码检查发现

V1 学习周报已通过 PR #2 合并。V2 在 PR #3 中，基线有 12 项测试。它只能从 Weekly Markdown 链接标题中匹配关键词；`analyze` 只记录理由；`finish` 不要求引用；模型或 JSON 出错会中断运行；默认输出文件会覆盖上一轮。

本阶段扩展这个独立实验，生产 Daily / Company / Weekly 脚本及定时设置保持原有路径。

## 实际业务逻辑

1. 保留原问题，构造可追踪的查询计划。“医药”同时扩展到 healthcare、clinical workflow、biomedical、drug discovery。已知主题包括 coding、MCP、Multi-Agent、Memory、RAG；这是一份可测试的词表，不是通用语义理解。
2. 明确日期窗口。“最近”默认近 30 天，“这周”是近 7 天，按上海时区取参考日期。窗口不会被模型改写。
3. 使用固定 API 检索 HF 论文、GitHub 项目、arXiv、可选 Tavily 网页。GitHub 查询范围与实际读取的标题/简介一致；HF 多取候选后筛日期，避免高相关的旧论文挤掉新资料。HF 使用论文发布日期，而非 Hub 投稿日期。
4. 归一化 URL、去重、过滤日期和主题；同一篇 HF/arXiv 论文只计一次。当前排序使用词项、日期及工程相关词，没有 embedding、BM25 或独立语义重排。
5. 模型根据 observation 选择 `analyze / search_more / finish`。首次 Agent 搜索限制为两条查询，为补查留下预算；后续可按新发现改查询。`--retrieval-only` 会直接检查完整扩展查询集。
6. 模型输出结构化发现：主题、发现、信号/趋势等级、证据 ID、应用层意义、动手建议。程序检查引用并渲染链接。

| 控制 | 默认值 / 行为 |
| --- | --- |
| 模型步骤 | 5，CLI/API 可设置 1–10 |
| 搜索 API 请求 | 一次运行共享 8 次，配置上限 12 |
| 每轮查询 | 最多 4 条，首次 Agent 搜索最多 2 条 |
| 保留证据 | 最多 12 条 |
| 请求超时 | 12 秒 |
| 失败来源 | 本轮隔离，不隐式重试 |
| 重复查询 | 同来源同参数跳过 |
| 无进展 | 两次补查无新增来源后停止 |
| 结论校验失败 | 两次后停止 |
| 研究回答 | 至少两个不同来源 |
| 单条“趋势” | 该条发现至少两个发布日期来源 |

`pushed_at` 只能证明仓库有活动，不能证明新发布、真实业务落地或临床有效性。摘要/简介也不等于全文。Verifier 检查结构与来源，不证明语义蕴含、科学独立性或事实真伪；仍需要模型质量评测和人工阅读。

## 可用性场景

| ID | 问题 | 核心验收 |
| --- | --- | --- |
| medical-agent-trends | 最近医药 Agent 有什么趋势？ | 临床/制药扩展，外部来源，日期和证据等级 |
| coding-agent-learning | 最近 coding agent 有什么值得学？ | 工程方向与动手建议 |
| mcp-application-value | MCP 最近还值得学吗？ | 应用价值和工具边界 |
| multi-agent-application | Multi-Agent 有什么真正落地的东西？ | 引用真实来源，不能用仓库简介证明部署 |
| agent-memory-changes | Agent Memory 最近有什么变化？ | persistence/checkpoint 等同义方向 |
| agentic-rag-learning | RAG 有什么值得 Agent 工程师关注？ | Agent 相关性，排除普通分类资料 |
| medical-agent-engineering | 医疗 Agent 和普通 Agent 的工程区别？ | comparison 意图、跨来源应用总结 |
| weak-week | 这周没什么值得学的吗？ | 零证据时可以正常回答证据不足 |

数据集位于 `tests/eval_cases.json`。`tests/fixtures/research_sources.json` 全部是明确标注的合成资料；其链接与发现不是现实信息。

## 三种验证等级

```bash
python -m pytest -q
python research_eval.py --mode replay
python research_eval.py --mode retrieval --case medical-agent-trends
python research_eval.py --mode live --case medical-agent-trends
```

- **replay**：合成资料 + scripted decider，验证检索路径、停止条件、引用结构、应用字段；不能证明模型理解了问题。
- **retrieval**：真正联网，验证扩展、日期/主题过滤和来源数量；不生成趋势回答。输出分开记录 publication/activity 数量。
- **live**：使用配置中的 DeepSeek 模型，检查真实决策和答案；自动检查之后，还要人工判断相关性、引用是否支持主张、建议是否可操作。

本轮本地没有 `DEEPSEEK_API_KEY` 或 `TAVILY_API_KEY`。缺失模型密钥的 CLI 故障实验已验证：状态保存为 `failed_decision`，返回非零退出码，不输出编造的答案。不能将本轮结果称为“真实 DeepSeek 场景全部通过”。

真实医疗检索的故障实验：最初在 6 次调用后仅保留 1 条来源；arXiv 请求失败，GitHub 在 README 中命中但只读取简介，导致召回不足。调整 GitHub 查询字段、补充 HF、保留复数 agents、提高 HF 候选池后，一轮 8 次请求保留 12 条来源，其中 1 条发布日期论文、11 条仓库更新信号。多数 HF 资料因窗口外被剔除。该结果证明真实来源链路，不能单独证明近期行业趋势。可复查 `docs/eval/medical-retrieval-summary.json`。

### GitHub Secret 实测补充

2026-10-02，在 PR #3 的 GitHub runner 中使用现有 `DEEPSEEK_API_KEY` 成功完成四次模型决策，确认 Secret 可用于调用。本次 arXiv 也正常返回，检索保留 12 条来源（8 条发布日期、4 条仓库活动）。第 5 次模型输出出现 JSON 解析错误，终态 `failed_decision`；原版本没有记录 `finish_reason`，不能确定是长度截断还是其他格式问题。

针对实测失败调整：提示不再向模型展示内部相关性词表，避免将 MCP 等 OR 匹配别名误当额外任务；证据只展示一次，observation 保留来源 ID；提示尽早收尾、最后一步必须结束，并限制结论长度。输出上限从 2400 提高到 3600 tokens。

响应处理新增 `finish_reason` 与 token 数诊断，截断/中断响应明确失败，不从残缺结果中拼接答案。HTTP 错误仅记录状态码，不记录响应正文、请求头或异常原文。新增 7 项回归测试，本地共 63 项通过；8 个合成回放仍通过。

第一次修复后的 live 复测成功：2 步、约 15 秒，保留 12 条来源（8 条发布日期、4 条仓库活动），输出三组带引用和动手建议的发现。两个模型响应均自然结束，共记录 7188 tokens（包含输入）。人工检查发现“从单模型问答转向”和“技能库快速扩张”缺少历史基线支持，因此继续收紧提示：趋势仅表述本轮近期研究的共同方向；没有基线就不能断言产业转型、增长速度或普及程度。结构检查通过不等于引用蕴含或行业趋势已得到证明。

最终 live 复测：2 步、约 12 秒，三组发现使用 6 篇发布日期论文；全部结构检查通过，两个模型响应自然结束，共记录 6770 tokens（包含输入）。摘要级人工检查可支持近期研究方向与工程学习建议；其中成本/安全代价来自体检解读实验，不能泛化为医院路由或所有医疗应用的结论。保留报告位于 `docs/eval/medical-live-summary.json`，包含评测 commit、Actions 链接、来源日期、模型诊断与人工检查范围。只有这个医疗场景做了 live，其他七个场景仍是合成回放。

## 故障与边界测试

覆盖：非法动作、缺失参数、无引用结束、未知引用、旧/未来/无日期资料、HF 投稿日期与论文日期区分、跨源重复论文、私网/凭证 URL、请求预算、重复查询、来源失败隔离、模型 JSON 出错、证据中的指令文本、信号冒充趋势、零来源结果和 API 步数边界。

证据里的指令不会被执行器当作新的 action。此测试证明执行权限边界，不证明真实模型对所有 prompt injection 都有抵抗力。

## 运行和回滚

```bash
python learning_agent.py "最近医药 Agent 有什么趋势？" --retrieval-only
python learning_agent.py "最近医药 Agent 有什么趋势？"
python learning_agent.py "Agent memory" --mode weekly --weekly weekly/2026-09-27.md
```

输出默认为 `state/agent_runs/TASK_ID.json`，便于查看日期、查询、trace、来源、校验错误和结论；它不是可恢复 checkpoint 或长期记忆。`--mode weekly` 保留原实验行为。V2.1 是独立提交，可在 PR 分支中 revert；现有生产 pipeline 不依赖新增模块。

Research usability evaluation workflow 支持手动选择 replay / retrieval / live。合并后可在 Actions 中手动运行，下载评测 artifact；新增工作流在合并到默认分支前不一定出现在手动运行列表。

合并前的真实评测入口：给仓库所有者创建、且分支位于本仓库的 PR 添加 `research-live-test` 标签，运行一个 `medical-agent-trends` live 场景。标签只在添加时触发，后续提交不会自动消耗模型调用；要评测新提交，移除后重新添加标签。Fork PR 不使用此入口。

工作流通过环境变量使用现有 `DEEPSEEK_API_KEY` Secret，缺失时明确失败；不读取或展示密钥值，也不把它写入评测报告。先前本地缺失密钥不代表仓库 Secret 缺失。Tavily 仍为可选来源。此入口不发送邮件。

## 面试时可以如何解释

“我先用一个真实的医疗 Agent 趋势问题发现了检索瓶颈。原来 Agent 只在周报标题里匹配，换编排框架不能补齐信息源。我保留稳定 pipeline，在独立有界 Agent 中加入可追踪查询扩展和外部来源，区分发布日期与仓库活动，要求结论引用实际检索到的证据。单元测试、离线回放和真实模型评测分别验证程序、契约和答案质量。现在仍是词表检索加模型总结；是否加入语义重排或 LangGraph，要由下一轮错误样本决定。”

下一阶段的入口是 live 评测和人工判断引用蕴含，再按实际失败决定语义筛选、重排或 orchestration。没有提前实现 Multi-Agent、向量数据库或网页产品。
