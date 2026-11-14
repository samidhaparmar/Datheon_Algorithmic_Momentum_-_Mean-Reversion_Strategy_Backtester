import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "dashboard extra not installed")
class DashboardAppTests(unittest.TestCase):
    def test_synthetic_demo_runs_without_vendor_access(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file("app.py").run(timeout=30)
        self.assertFalse(app.exception)
        app.button[0].click().run(timeout=120)
        self.assertFalse(app.exception)
        self.assertIn("Net return", [metric.label for metric in app.metric])
        self.assertTrue(app.warning)


if __name__ == "__main__":
    unittest.main()
