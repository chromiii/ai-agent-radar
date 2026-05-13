from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python send_email.py REPORT_PATH SUBJECT")

    report_path = Path(sys.argv[1])
    subject = sys.argv[2]
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")

    username = env("QQ_MAIL_USERNAME")
    password = env("QQ_MAIL_PASSWORD")
    mail_to = env("QQ_MAIL_TO")
    if not username or not password or not mail_to:
        # Local runs and forks should not fail just because mail secrets are absent.
        print("QQ mail secrets are not fully set; skipping email.")
        return

    smtp_host = env("QQ_SMTP_HOST") or "smtp.qq.com"
    smtp_port = int(env("QQ_SMTP_PORT") or "465")
    mail_from = env("QQ_MAIL_FROM") or username

    body = report_path.read_text(encoding="utf-8")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(body)

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)

    print(f"Sent email to {mail_to}: {subject}")


if __name__ == "__main__":
    main()
