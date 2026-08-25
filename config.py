import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


def _req(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes")


def _security_answers() -> dict[str, str]:
    """Build {exact question text: answer} from ERP_SECURITY_Q1/A1, Q2/A2, Q3/A3.

    ERP registers 3 security questions per student and asks a different one
    (seemingly at random) on each login, so all 3 need to be configured —
    copy the exact wording of each question from the ERP page, since matching
    is exact-string.
    """
    answers: dict[str, str] = {}
    for i in (1, 2, 3):
        q = os.getenv(f"ERP_SECURITY_Q{i}")
        a = os.getenv(f"ERP_SECURITY_A{i}")
        if q and a:
            answers[q.strip()] = a
    if not answers:
        raise RuntimeError(
            "No security question/answer pairs configured. Set "
            "ERP_SECURITY_Q1 / ERP_SECURITY_A1 (and _Q2/_A2, _Q3/_A3) in "
            ".env — copy each question's exact wording from the ERP page."
        )
    return answers


@dataclass
class AppConfig:
    erp_username: str  # roll number
    erp_password: str
    erp_security_answers: dict[str, str]
    erp_otp_sender: str
    erp_jobs_url: str
    gmail_credentials_file: str
    gmail_token_file: str
    llm_model: str
    resume_file: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    notify_whatsapp_to: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    notify_email_to: str
    require_approval: bool
    headless: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        return cls(
            erp_username=_req("ERP_USERNAME"),
            erp_password=_req("ERP_PASSWORD"),
            erp_security_answers=_security_answers(),
            # ERP's OTP emails come from this address; "erpkgp@adm.iitkgp.ac.in"
            # is the sender used by the metaKGP tooling this was ported from.
            erp_otp_sender=os.getenv("ERP_OTP_SENDER", "erpkgp@adm.iitkgp.ac.in"),
            # The in-ERP URL of your placements/jobs listing page, opened
            # after login. There's no way to know this without your own
            # ERP session — log in, navigate to it, and paste the URL here.
            erp_jobs_url=os.getenv("ERP_JOBS_URL", ""),
            gmail_credentials_file=os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json"),
            gmail_token_file=os.getenv("GMAIL_TOKEN_FILE", "token.json"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            resume_file=os.getenv("RESUME_FILE", "resume.txt"),
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            twilio_whatsapp_from=os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"),
            notify_whatsapp_to=os.getenv("NOTIFY_WHATSAPP_TO", ""),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "465")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            notify_email_to=os.getenv("NOTIFY_EMAIL_TO", ""),
            require_approval=_flag("REQUIRE_APPROVAL", True),
            headless=_flag("HEADLESS", False),
        )
