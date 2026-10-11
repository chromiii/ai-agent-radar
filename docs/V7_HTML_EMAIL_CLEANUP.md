# V7 · Email-first briefing & archive cleanup

## Why

Users should receive a finished, scannable email, **not** a raw Markdown file or an action item to process the news themselves.

## Email experience

- The Saturday workflow generates `briefings/YYYY-MM-DD.md`, then renders `briefings/YYYY-MM-DD.html` and sends via `send_email.py` as MIME `multipart/alternative`.
- The HTML is a single-column, responsive, email-client-compatible newsletter using inline styles and escaped source text. Each relevant headline contains a clickable HTTPS source link.
- Its first section contains up to three curated Weekly Radar learning cards rewritten deterministically into practical **what changed / why it matters / try this** guidance. This is drawn from source-linked, validated Weekly cards, not invented news.
- Research and company coverage is limited to a smaller, deduplicated list; Breaking candidates are visibly marked *pending verification* and are not auto-notified.
- The plain-text fallback is readable even when images or HTML are blocked; the source `.md` is not required for reading the email.

## Normal cadence

- Daily/Company collectors continue silently.
- One normal Saturday newsletter is sent only after the combined brief is built and committed.
- The Breaking watcher continues separately but only a manually approved candidate can send an exceptional message.

## Cleanup

The user explicitly requested removing legacy accumulated news while preserving the project and learning progress.

- V7's initial tree commit removed **119 old inbox, 136 old company, and 21 old Weekly Markdown files** (276 altogether) from the active branch.
- For immediate weekly delivery context, the initial cleanup retained **14 days** of Daily/Company reports and the **two latest** Weekly reports.
- After future successful Saturday delivery, `archive_retention.py --apply` keeps the latest 14 days of Daily/Company, the latest 2 Weekly reports, and the latest 4 briefing issues, including their HTML counterparts.
- `state.json` is trimmed from 2,000 legacy seen IDs to the newest 300 for a compact rolling dedup baseline. Existing company seen IDs within their normal TTL are retained.
- **Never prune:** public `state/learning_progress.json`, `state/learning_path.json`, curriculum, code, tests, Breaking News manual decisions, API secrets or other project artifacts.
- This removes files from the *current repository tree* only. Previous Git commits still contain historical blobs. Purging Git history would be a separate destructive operation and is not performed.

## Preview & delivery validation

On a same-repository owner PR, use label `html-newsletter-preview` to generate the rendered HTML and source Markdown as a seven-day GitHub artifact **without sending**.

One-time label `html-newsletter-send-once` runs the same preview, checks that the QQ SMTP sender/recipient/password secrets exist and sends the requested sample mail. This label is not scheduled or automatically triggered. The normal weekly schedule remains independent.

## Security and limitations

- Scraped text is HTML-escaped. Only recognized HTTP(S) links are clickable. Inline code/bold and headings are rendered using a conservative Markdown subset; arbitrary raw HTML is never trusted.
- No remote fonts, trackers, CSS or embedded images are needed. Mail rendering is deterministic, so it does not create an additional LLM cost.
- SMTP requires configured GitHub Secrets. A successful CI preview does **not** prove delivery; check the sending workflow logs/status separately.
- Mail clients vary in CSS support; the layout is intentionally conservative, using tables and inline styles for broad compatibility.
- Retention shrinks on-branch historic raw data, so V4's historical index can only rebuild from the retained reports. Important long-term learning state remains separately stored. Historical index scale in older V4 docs describes pre-cleanup data, not current corpus size.
