# AI Agent Radar

一个跑在 GitHub Actions 上的 AI agent / AI 应用信息雷达。它每天自动收集公开来源，生成 Markdown 简报，提交到 GitHub，并可通过 QQ 邮箱发送到手机。

当前包含三个模块：

- **Daily Radar**：每日 AI agent / 多智能体 / AI 应用论文、项目、榜单简报。
- **Company Radar**：每日全球和中国 AI 公司动态简报。
- **Weekly Trend Radar**：每周热词雷达，用来反哺 Daily Radar 的动态加分和降权。

## 结果目录

```text
inbox/YYYY-MM-DD.md              # Daily Radar
company/YYYY-MM-DD.md            # Company Radar
weekly/YYYY-MM-DD.md             # Weekly Trend Radar
state.json                       # Daily 已处理内容
state/company_seen.json          # Company 14 天内已处理链接
state/trending_terms.json        # Weekly 生成的趋势词
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
  -> 附加“发给 ChatGPT 的精读请求”
  -> 写入 inbox/
  -> 更新 state.json
  -> 发送 QQ 邮件
```

Daily 不再自动做“精读”。它只生成适合复制到 ChatGPT App 的候选简报，避免用 API 对摘要做伪精读。

### Company Radar

脚本：`company_radar.py`

Workflow：`.github/workflows/company-radar.yml`

流程：

```text
读取 config.yaml
  -> 读取 state/company_seen.json
  -> 抓取全球和中国公司页面
  -> 过滤导航、招聘、社交、footer、普通页面噪音
  -> 过滤 14 天内已见过的公司链接
  -> 规则打分
  -> DeepSeek 做紧凑 JSON 分类
  -> 程序渲染 Markdown
  -> 附加“发给 ChatGPT 的公司动态解读请求”
  -> 写入 company/
  -> 更新 state/company_seen.json
  -> 发送 QQ 邮件
```

Company 的历史记录是带 TTL 的，不会永久屏蔽同一个 URL。默认 14 天内重复链接不再推送。

### Weekly Trend Radar

脚本：`weekly_trends.py`

Workflow：`.github/workflows/weekly-trends.yml`

流程：

```text
抓取最近 7 天 HF Daily Papers / HF Spaces / arXiv
  -> 规则抽取候选热词
  -> DeepSeek 精筛 tier1 / tier2 / downrank / noise
  -> 写入 weekly/
  -> 更新 state/trending_terms.json
```

Daily 会读取 `state/trending_terms.json`：

- `tier1`：强加分
- `tier2`：中等加分
- `downrank`：降权
- `noise`：只在 Weekly 报告中展示

如果 Weekly AI 精筛失败，会写入安全空状态，避免旧的垃圾热词污染 Daily。

## GitHub Secrets

进入：

```text
GitHub repository
  -> Settings
  -> Secrets and variables
  -> Actions
  -> New repository secret
```

### DeepSeek

```text
DEEPSEEK_API_KEY
```

如果没有配置，脚本会使用规则版 Markdown 兜底。

### QQ 邮箱

```text
QQ_MAIL_USERNAME   # 你的 QQ 邮箱，例如 123456@qq.com
QQ_MAIL_PASSWORD   # QQ 邮箱 SMTP 授权码，不是 QQ 密码
QQ_MAIL_TO         # 接收简报的邮箱
```

默认 SMTP：

```text
Host: smtp.qq.com
Port: 465
SSL:  true
```

可选覆盖：

```text
QQ_SMTP_HOST
QQ_SMTP_PORT
QQ_MAIL_FROM
```

如果 QQ 邮箱 secrets 没有配置，邮件步骤会跳过，不会让 workflow 失败。

## QQ 邮箱授权码

1. 打开 QQ 邮箱网页版。
2. 进入设置。
3. 进入账号。
4. 找到 POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务。
5. 开启 POP3/SMTP 或 IMAP/SMTP。
6. 生成授权码。
7. 把授权码填入 GitHub Secret：`QQ_MAIL_PASSWORD`。

注意：授权码不是 QQ 密码。

## 推荐首次运行顺序

1. 运行 **Agent Weekly Trend Radar**
   - 生成 `state/trending_terms.json`
2. 运行 **AI Agent Radar**
   - 生成 `inbox/YYYY-MM-DD.md`
3. 运行 **AI Company Radar**
   - 生成 `company/YYYY-MM-DD.md`

之后三个 workflow 会按定时任务自动运行。

## 定时设置

当前 cron 按 AEST UTC+10 写死：

```text
Daily Radar:   00:00 Australia/Sydney -> 14:00 UTC
Company Radar: 00:30 Australia/Sydney -> 14:30 UTC
Weekly Radar:  Sunday 00:15 Australia/Sydney -> Saturday 14:15 UTC
```

如果进入澳洲夏令时，需要手动调整 workflow 里的 cron，除非你不在意精确的本地时钟时间。

## 成本

免费部分：

- GitHub Actions 免费额度
- Hugging Face 公开 API
- arXiv 公开 API
- OpenAlex 公开 API
- 公司公开网页
- QQ 邮箱 SMTP

可能付费：

- DeepSeek API 调用

Daily 和 Company 都限制了传给 DeepSeek 的候选数量和输出长度，避免不必要的 token 消耗。

## 配置入口

主要改 `config.yaml`。

常用字段：

```yaml
max_items_per_source: 12
max_digest_items: 30
hf_daily_fallback_days: 3

company:
  max_items_for_ai: 20
  max_summary_chars_per_item: 420
  seen_ttl_days: 14

ai:
  model: deepseek-v4-flash
  max_tokens_daily: 3500
  max_tokens_weekly: 6000
  max_tokens_company: 2200
  max_items: 15
```

## 手机使用方式

每天你会收到 Daily 和 Company 邮件。

在安卓手机上：

1. 打开邮件。
2. 复制整封简报，或者复制其中重要部分。
3. 打开 ChatGPT App。
4. 粘贴简报。
5. 使用邮件末尾自带的“发给 ChatGPT 的请求”做二次解读。

这个设计的分工是：

```text
GitHub Actions：自动收集、去重、初筛、发邮件
ChatGPT App：手机端交互式精读和解释
Codex：维护和优化这个仓库
```

## 故障排查

### HF Daily Papers 400

这是常见情况，尤其在悉尼 0 点运行时，HF 当天 daily papers 可能还没生成。Daily Radar 会自动回退最多 3 天。

### Company Radar 输出过长或 JSON 失败

Company Prompt 已经限制为紧凑 JSON：

- 全球重点最多 4 条
- 中国重点最多 4 条
- 观察项最多 4 条
- 不要求输出 noise 列表

如果 DeepSeek 仍失败，会使用规则兜底版，并最多展示 12 条。

### 没收到 QQ 邮件

检查：

- `QQ_MAIL_USERNAME`
- `QQ_MAIL_PASSWORD`
- `QQ_MAIL_TO`
- QQ 邮箱是否开启 SMTP
- 授权码是否填错

可以在 Actions 日志里搜索：

```text
Sent email
QQ mail secrets are not fully set
```

### Rerun 没有生成新日报

Daily 有 `state.json` 去重。只有进入报告的 `digest_items` 会写入 seen。无新内容时不会写空报告，也不会调用 DeepSeek。

Company 有 `state/company_seen.json` 去重。默认 14 天内同 URL 不重复推送。
