import re
import unittest

from fastapi.testclient import TestClient

from app.main import app


class UiCacheTests(unittest.TestCase):
    def test_html_versions_assets_and_all_entrypoints_disable_cache(self):
        with TestClient(app) as client:
            for path in ("/", "/index.html"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                assets = re.findall(r'"((?:app.js|styles.css)\?v=[a-f0-9]{16})"', response.text)
                self.assertEqual(len(assets), 2)
                for asset in assets:
                    fetched = client.get("/" + asset)
                    self.assertEqual(fetched.status_code, 200)
                    self.assertEqual(fetched.headers["cache-control"], "no-store")
            session = client.get("/api/session")
            self.assertEqual(session.headers["cache-control"], "no-store")
            self.assertTrue(session.json()["session_id"])
            self.assertEqual(session.json(), client.get("/api/session").json())
