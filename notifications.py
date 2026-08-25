import smtplib
from email.message import EmailMessage


def send_whatsapp(cfg, body: str) -> None:
    from twilio.rest import Client
    client = Client(cfg.twilio_account_sid, cfg.twilio_auth_token)
    client.messages.create(
        from_=cfg.twilio_whatsapp_from,
        to=cfg.notify_whatsapp_to,
        body=body[:1500],  # WhatsApp message length limit
    )


def send_email(cfg, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.notify_email_to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port) as server:
        server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)


def build_notifier(cfg):
    """Prefer WhatsApp; fall back to email; fall back to stdout."""
    def notify(summary: str) -> None:
        if cfg.twilio_account_sid and cfg.twilio_auth_token:
            try:
                send_whatsapp(cfg, summary)
                return
            except Exception as exc:
                print(f"[notify] WhatsApp failed ({exc}); falling back to email.")
        if cfg.smtp_user:
            send_email(cfg, "Job agent run summary", summary)
            return
        print("[notify] No channel configured. Summary:\n" + summary)
    return notify