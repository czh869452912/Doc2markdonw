import base64
import unittest

from app.sessions import COOKIE_NAME, resolve_session, set_session_cookie


class FakeResponse:
    def __init__(self):
        self.cookies = []

    def set_cookie(self, **kwargs):
        self.cookies.append(kwargs)


class SessionTests(unittest.TestCase):
    def test_resolve_session_creates_256_bit_token_and_stable_identity(self):
        created = resolve_session(None)
        decoded = base64.urlsafe_b64decode(created.token + "=")

        self.assertEqual(len(decoded), 32)
        self.assertTrue(created.is_new)
        self.assertEqual(len(created.owner_hash), 64)
        self.assertEqual(created.fingerprint, created.owner_hash[:16])

        reused = resolve_session(created.token)
        self.assertFalse(reused.is_new)
        self.assertEqual(reused, created.__class__(
            token=created.token,
            owner_hash=created.owner_hash,
            fingerprint=created.fingerprint,
            is_new=False,
        ))

    def test_resolve_session_replaces_malformed_token(self):
        identity = resolve_session("not-a-valid-session")

        self.assertTrue(identity.is_new)
        self.assertNotEqual(identity.token, "not-a-valid-session")

    def test_set_session_cookie_uses_browser_session_security_flags(self):
        response = FakeResponse()
        identity = resolve_session(None)

        set_session_cookie(response, identity, secure=True)

        self.assertEqual(len(response.cookies), 1)
        cookie = response.cookies[0]
        self.assertEqual(cookie["key"], COOKIE_NAME)
        self.assertEqual(cookie["value"], identity.token)
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "lax")
        self.assertEqual(cookie["path"], "/")
        self.assertNotIn("max_age", cookie)
        self.assertNotIn("expires", cookie)


if __name__ == "__main__":
    unittest.main()
