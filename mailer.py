"""
Provider-agnostic email sender (plain SMTP).

Configure via env vars — works with Postmark, Gmail, Resend, Brevo, etc.:
  SMTP_HOST   e.g. smtp.postmarkapp.com  (Gmail: smtp.gmail.com)
  SMTP_PORT   587
  SMTP_USER   Postmark: the Server API Token   (Gmail: your address)
  SMTP_PASS   Postmark: the same Server API Token (Gmail: an App Password)
  EMAIL_FROM  a verified sender address

Falls back to SendGrid SMTP if only SENDGRID_API_KEY/FROM are set (legacy), so
nothing breaks during the switch. Returns True on success, never raises.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _config():
    host = os.getenv("SMTP_HOST", "").strip()
    if host:
        return {
            "host": host,
            "port": int(os.getenv("SMTP_PORT", "587") or "587"),
            "user": os.getenv("SMTP_USER", "").strip(),
            "password": os.getenv("SMTP_PASS", "").strip(),
            "from": (os.getenv("EMAIL_FROM") or os.getenv("SENDGRID_FROM_EMAIL") or "").strip(),
        }
    # Legacy fallback: SendGrid SMTP via API key
    key = os.getenv("SENDGRID_API_KEY", "").strip()
    if key:
        return {
            "host": "smtp.sendgrid.net", "port": 587,
            "user": "apikey", "password": key,
            "from": os.getenv("SENDGRID_FROM_EMAIL", "").strip(),
        }
    return None


def is_configured() -> bool:
    cfg = _config()
    return bool(cfg and cfg.get("host") and cfg.get("from"))


def send_email(to_email: str, subject: str, html_body: str, reply_to: str = "jjwoods@gmail.com") -> bool:
    cfg = _config()
    if not cfg or not cfg.get("host") or not cfg.get("from") or not to_email:
        print("mailer: not configured (set SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_FROM)")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["from"]
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                pass  # some hosts/ports are already TLS
            if cfg.get("user"):
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"mailer: send failed: {e}")
        return False
