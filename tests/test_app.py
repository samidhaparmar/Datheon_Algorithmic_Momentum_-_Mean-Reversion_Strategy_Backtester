import importlib.util
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "dashboard extra not installed")
class DashboardAppTests(unittest.TestCase):
    def test_synthetic_demo_runs_without_vendor_access(self):
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path)).run(timeout=30)
        self.assertFalse(app.exception)
        app.button[0].click().run(timeout=120)
        self.assertFalse(app.exception)
        self.assertIn("Net return", [metric.label for metric in app.metric])
        self.assertTrue(app.warning)


if __name__ == "__main__":
    unittest.main()
