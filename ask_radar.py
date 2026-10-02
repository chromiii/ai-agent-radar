"""Ask one application-layer question and save readable learning cards."""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from learning_agent import AgentState, PROMPT_VERSION, load_config, run_agent
from learning_cards import markdown_text


def run_request(question, config, output_dir, *, decide=None, searcher=None):
    state = AgentState(task_id=uuid4().hex[:12], user_query=question, search_mode="external")
    started = time.monotonic()
    kwargs = {"searcher": searcher}
    if decide is not None:
        kwargs["decide"] = decide
    state = run_agent(state, "", config, **kwargs)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"prompt_version": PROMPT_VERSION, "model": config.get('ai', {}).get('model'),
              "latency_ms": round((time.monotonic() - started) * 1000), "state": asdict(state)}
    (output_dir / 'run.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    answer = f"# Ask Radar 学习卡\n\n**你的问题**：{markdown_text(question)}\n\n{state.final_answer}\n"
    (output_dir / 'answer.md').write_text(answer, encoding='utf-8')
    return state, answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', default=os.environ.get('RADAR_QUESTION', ''), help='1–600 characters; also accepts RADAR_QUESTION')
    parser.add_argument('--output-dir', type=Path, default=Path('ask_results'))
    args = parser.parse_args()
    if not args.question.strip() or len(args.question) > 600:
        parser.error('问题需要 1–600 个字符。')
    state, answer = run_request(args.question, load_config(), args.output_dir)
    if summary_path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary_path).open('a', encoding='utf-8') as summary:
            summary.write(answer)
    print(f"Ask Radar: status={state.status}; answer={args.output_dir / 'answer.md'}")
    if state.status not in ('finished', 'finished_insufficient_evidence'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
