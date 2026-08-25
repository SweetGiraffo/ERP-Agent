import base64
import os
import re
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
OTP_PATTERN = re.compile(r"\b(\d{4,8})\b")


def get_gmail_service(credentials_file: str, token_file: str):
    """First run opens a browser consent screen and caches token.json."""
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def extract_otp(text: str) -> str | None:
    match = OTP_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_text(payload: dict) -> str:
    body = payload.get("body", {})
    if payload.get("mimeType", "").startswith("text/") and body.get("data"):
        return base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        text = _extract_text(part)
        if text:
            return text
    return ""


def wait_for_otp(service, sender: str, since_epoch: int,
                 timeout: float = 180, poll_interval: float = 4) -> str:
    """Poll Gmail until a fresh unread OTP email arrives; mark it read and return the code."""
    deadline = time.time() + timeout
    query = f"from:{sender} is:unread after:{since_epoch}"
    while time.time() < deadline:
        results = service.users().messages().list(userId="me", q=query).execute()
        for stub in results.get("messages", []):
            msg = service.users().messages().get(
                userId="me", id=stub["id"], format="full"
            ).execute()
            text = _extract_text(msg.get("payload", {})) or msg.get("snippet", "")
            otp = extract_otp(text)
            if otp:
                service.users().messages().modify(
                    userId="me", id=stub["id"], body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                return otp
        time.sleep(poll_interval)
    raise TimeoutError(f"No OTP email from {sender} within {timeout}s")