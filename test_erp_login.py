import json
import unittest
from unittest.mock import MagicMock, patch

import erp_login


def _resp(text="", status=200, history=None, headers=None):
    r = MagicMock()
    r.text = text
    r.status_code = status
    r.history = history or []
    r.headers = headers or {}
    r.raise_for_status = MagicMock()
    return r


class GetSessionTokenTests(unittest.TestCase):
    def test_reads_token_from_hidden_field(self):
        session = MagicMock()
        session.get.return_value = _resp(
            '<html><input id="sessionToken" value="ABC123"></html>'
        )
        token = erp_login.get_session_token(session)
        self.assertEqual(token, "ABC123")

    def test_raises_when_field_missing(self):
        session = MagicMock()
        session.get.return_value = _resp("<html>no token here</html>")
        with self.assertRaises(erp_login.ErpLoginError):
            erp_login.get_session_token(session)


class GetSecurityQuestionTests(unittest.TestCase):
    def test_returns_question_text(self):
        session = MagicMock()
        session.post.return_value = _resp("What is your pet's name?")
        q = erp_login.get_security_question(session, "25MA60R29")
        self.assertEqual(q, "What is your pet's name?")

    def test_raises_on_false(self):
        session = MagicMock()
        session.post.return_value = _resp("FALSE")
        with self.assertRaises(erp_login.ErpLoginError):
            erp_login.get_security_question(session, "bad_roll_no")


class RequestOtpTests(unittest.TestCase):
    def test_success_returns_login_details(self):
        session = MagicMock()
        session.post.return_value = _resp(json.dumps({"msg": "OTP has been sent to your email"}))
        details = erp_login.request_otp(
            session, roll_number="25MA60R29", password="pw",
            answer="Fluffy", session_token="tok",
        )
        self.assertEqual(details["user_id"], "25MA60R29")
        self.assertEqual(details["typeee"], "SI")

    def test_wrong_answer_raises(self):
        session = MagicMock()
        session.post.return_value = _resp(json.dumps({"msg": "Answer does not match"}))
        with self.assertRaises(erp_login.ErpLoginError):
            erp_login.request_otp(
                session, roll_number="25MA60R29", password="pw",
                answer="wrong", session_token="tok",
            )

    def test_wrong_password_raises(self):
        session = MagicMock()
        session.post.return_value = _resp(json.dumps({"msg": "Password does not match"}))
        with self.assertRaises(erp_login.ErpLoginError):
            erp_login.request_otp(
                session, roll_number="25MA60R29", password="wrong",
                answer="Fluffy", session_token="tok",
            )


class SignInTests(unittest.TestCase):
    def test_extracts_sso_token_from_redirect(self):
        session = MagicMock()
        redirect = MagicMock()
        redirect.headers = {"Location": "https://erp.iitkgp.ac.in/IIT_ERP3/?ssoToken=XYZ789"}
        session.post.return_value = _resp("", history=[MagicMock(), redirect])
        token = erp_login.sign_in(session, {"user_id": "25MA60R29"}, "482913")
        self.assertEqual(token, "XYZ789")

    def test_raises_when_no_redirect(self):
        session = MagicMock()
        session.post.return_value = _resp("some page with no redirect", history=[])
        with self.assertRaises(erp_login.ErpLoginError):
            erp_login.sign_in(session, {"user_id": "25MA60R29"}, "000000")


class PlaywrightCookiesTests(unittest.TestCase):
    def test_converts_requests_cookies(self):
        session = MagicMock()
        cookie = MagicMock(name="ssoToken", value="XYZ789", domain="erp.iitkgp.ac.in",
                           path="/", secure=True)
        cookie.name = "ssoToken"
        session.cookies = [cookie]
        cookies = erp_login.playwright_cookies(session)
        self.assertEqual(cookies, [{
            "name": "ssoToken", "value": "XYZ789",
            "domain": "erp.iitkgp.ac.in", "path": "/", "secure": True,
        }])


if __name__ == "__main__":
    unittest.main()
