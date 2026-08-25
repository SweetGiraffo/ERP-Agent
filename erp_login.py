"""IIT KGP ERP login.

erp.iitkgp.ac.in's login is NOT a plain HTML form you can fill and submit —
it's a 3-step AJAX handshake:

  1. GET the ERP homepage and pull a hidden `sessionToken` out of the markup.
  2. POST your roll number to get back the text of *your* security question
     (ERP picks one of your 3 registered questions each time).
  3. POST roll number + password + the answer to that question. If those are
     right, ERP emails you an OTP.
  4. POST the OTP. On success ERP 302-redirects to a URL containing
     `ssoToken=...` and sets session cookies — that's what actually logs
     you in.

This mirrors the protocol reverse-engineered by the metaKGP org's own tools
(https://github.com/metakgp/iitkgp-erp-auto-login, the browser extension you
linked, and https://github.com/metakgp/iitkgp-erp-login-pypi, which documents
the exact endpoints). Driving this through Playwright DOM clicks would be
brittle since the page is JS-heavy; instead we talk to the endpoints
directly with `requests`, then hand the authenticated cookies over to
Playwright (see `playwright_cookies`) so the rest of the agent can keep
using a normal browser session for scraping/applying.
"""
from __future__ import annotations

import json
import re

import requests
from bs4 import BeautifulSoup

HOMEPAGE_URL = "https://erp.iitkgp.ac.in/IIT_ERP3/"
WELCOMEPAGE_URL = "https://erp.iitkgp.ac.in/IIT_ERP3/welcome.jsp"  # 404s once logged in
LOGIN_URL = "https://erp.iitkgp.ac.in/SSOAdministration/auth.htm"
SECRET_QUESTION_URL = "https://erp.iitkgp.ac.in/SSOAdministration/getSecurityQues.htm"
OTP_URL = "https://erp.iitkgp.ac.in/SSOAdministration/getEmilOTP.htm"  # ERP's own typo, not ours

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_COOKIE_DOMAIN = "erp.iitkgp.ac.in"


class ErpLoginError(Exception):
    """Raised for any failure during the ERP login handshake."""


def get_session_token(session: requests.Session) -> str:
    """Step 1: load the ERP homepage and read the hidden sessionToken field."""
    try:
        r = session.get(HOMEPAGE_URL, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ErpLoginError(f"Could not reach the ERP homepage: {exc}") from exc

    soup = BeautifulSoup(r.text, "html.parser")
    field = soup.find(id="sessionToken")
    if not field or not field.get("value"):
        raise ErpLoginError(
            "Could not find a sessionToken on the ERP homepage. Either "
            "erp.iitkgp.ac.in is down/under maintenance, or the login "
            "page markup has changed since this was written."
        )
    return field["value"]


def get_security_question(session: requests.Session, roll_number: str) -> str:
    """Step 2: ask ERP which of the user's 3 security questions to answer."""
    try:
        r = session.post(
            SECRET_QUESTION_URL,
            data={"user_id": roll_number},
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        r.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ErpLoginError(f"Could not fetch the security question: {exc}") from exc

    text = r.text.strip()
    if text == "FALSE" or not text:
        raise ErpLoginError(f"ERP rejected roll number {roll_number!r} as invalid.")
    return text


def request_otp(
    session: requests.Session,
    *,
    roll_number: str,
    password: str,
    answer: str,
    session_token: str,
) -> dict:
    """Step 3: submit password + security answer; ERP emails an OTP on success.

    Returns the login_details payload (minus the OTP) so it can be reused
    for the final sign-in POST.
    """
    login_details = {
        "user_id": roll_number,
        "password": password,
        "answer": answer,
        "typeee": "SI",
        "sessionToken": session_token,
        "requestedUrl": HOMEPAGE_URL,
    }
    try:
        r = session.post(OTP_URL, data=login_details, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ErpLoginError(f"Could not request an OTP: {exc}") from exc

    try:
        res = json.loads(r.text)
    except json.JSONDecodeError as exc:
        raise ErpLoginError(f"Unexpected response requesting OTP: {r.text[:200]!r}") from exc

    msg = str(res.get("msg", ""))
    low = msg.lower()
    if "answer" in low and ("match" in low or "wrong" in low or "invalid" in low):
        raise ErpLoginError(
            f"ERP says the security question answer is wrong for: {answer and '(hidden)'}"
        )
    if "password" in low and ("match" in low or "wrong" in low or "invalid" in low):
        raise ErpLoginError("ERP says the password is wrong.")
    if "otp" not in low or "sent" not in low:
        raise ErpLoginError(f"Failed to request OTP, ERP said: {msg!r}")

    return login_details


def sign_in(session: requests.Session, login_details: dict, otp: str) -> str:
    """Step 4: submit the OTP; on success ERP redirects with an ssoToken."""
    payload = {**login_details, "email_otp": otp}
    try:
        r = session.post(LOGIN_URL, data=payload, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ErpLoginError(f"ERP sign-in request failed: {exc}") from exc

    if re.search(r"otp.{0,20}(invalid|mismatch|incorrect)", r.text, re.IGNORECASE):
        raise ErpLoginError("ERP rejected the OTP (wrong or expired).")

    try:
        redirect_location = r.history[1].headers["Location"]
        sso_token = re.search(r"[?&]ssoToken=([^&]+)", redirect_location).group(1)
    except (IndexError, AttributeError, KeyError) as exc:
        raise ErpLoginError(
            "ERP did not redirect with an ssoToken after the OTP step — "
            "login likely failed (wrong OTP, or the session expired while "
            "waiting for the OTP email)."
        ) from exc

    return sso_token


def is_session_alive(session: requests.Session) -> bool:
    """True if this session is already logged in (ERP returns a fixed-size page when not)."""
    try:
        r = session.get(WELCOMEPAGE_URL, headers=DEFAULT_HEADERS, timeout=20)
    except requests.exceptions.RequestException:
        return False
    return r.headers.get("Content-Length") == "741"


def playwright_cookies(session: requests.Session) -> list[dict]:
    """Convert an authenticated requests.Session's cookies into Playwright's cookie format."""
    cookies = []
    for c in session.cookies:
        cookies.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain or _COOKIE_DOMAIN,
                "path": c.path or "/",
                "secure": bool(c.secure),
            }
        )
    return cookies
