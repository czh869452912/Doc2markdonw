from pathlib import Path
import unittest


STATIC_DIR = Path(__file__).parents[1] / "app" / "static"


class StaticUiTests(unittest.TestCase):
    def test_frontend_initializes_session_scoped_job_history(self):
        javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        self.assertIn('fetch("api/session")', javascript)
        self.assertIn("md-convert-jobs:${session.session_id}", javascript)
        self.assertIn("removeJob(job.job_id)", javascript)
        self.assertIn('id="submit-button" type="submit" disabled', html)

    def test_frontend_exposes_compact_mermaid_controls(self):
        javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        for control_id in (
            "mermaid_format",
            "mermaid_layout",
            "mermaid_direction",
            "mermaid_density",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn('value="auto" selected', html)
        self.assertIn('value="source" selected', html)
        self.assertIn('value="standard" selected', html)
        self.assertIn("syncMermaidControls", javascript)
        self.assertIn("control.disabled = !renderMermaid.checked", javascript)


if __name__ == "__main__":
    unittest.main()
