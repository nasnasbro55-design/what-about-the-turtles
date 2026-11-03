"""Stretch: email (or text, via the carrier's email-to-SMS address) the responder when a flight makes high alerts.

Off unless these are set (put them in .env, never in git):
    TURTLE_SMTP_HOST=smtp.gmail.com  TURTLE_SMTP_PORT=587
    TURTLE_SMTP_USER=you@gmail.com   TURTLE_SMTP_PASS=<app password>
    TURTLE_NOTIFY_TO=tanya@example.org,5715550123@vtext.com      (comma separated)
    TURTLE_APP_URL=https://<your tunnel>                         (optional: link in the message)
Without them it prints what it would have sent, so a demo never fails on mail.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List


def message(alerts: List[Dict[str, Any]], flight_id: str) -> tuple[str, str]:
    n = len(alerts)
    subject = f"A.E.R.O.: {n} likely turtle{'s' if n != 1 else ''} ({flight_id})"
    lines = [f"Spot {a.get('number')}: {a['lat']:.6f}, {a['lon']:.6f} (score {a.get('score') or 0:.2f})" for a in alerts]
    if url := os.environ.get("TURTLE_APP_URL"): lines.append(f"Open the app: {url}")
    return subject, "\n".join(lines)


def high_alerts(alerts: List[Dict[str, Any]], flight_id: str) -> bool:
    subject, body = message(alerts, flight_id)
    host, to = os.environ.get("TURTLE_SMTP_HOST"), [t.strip() for t in os.environ.get("TURTLE_NOTIFY_TO", "").split(",") if t.strip()]
    if not host or not to:
        print(f"  notify (off, no TURTLE_SMTP_HOST/TURTLE_NOTIFY_TO): {subject}"); return False
    m = EmailMessage(); m["Subject"], m["To"] = subject, ", ".join(to)
    m["From"] = os.environ.get("TURTLE_SMTP_USER", "aero@localhost"); m.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("TURTLE_SMTP_PORT", 587)), timeout=10) as s:
            s.starttls()
            if os.environ.get("TURTLE_SMTP_USER"): s.login(os.environ["TURTLE_SMTP_USER"], os.environ.get("TURTLE_SMTP_PASS", ""))
            s.send_message(m)
        print(f"  notified {len(to)} recipient(s): {subject}"); return True
    except Exception as e:
        print(f"  notify failed (alerts are still saved): {e}"); return False
