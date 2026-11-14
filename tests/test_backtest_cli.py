import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from datheon_data.backtest_cli import run
from datheon_data.execution import ExecutionConfig
from datheon_data.signals import build_signals


class BacktestCliTests(unittest.TestCase):
    def test_end_to_end_reports_and_curves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = pd.date_range("2024-01-01", periods=80, tz="UTC", name="timestamp")
            closes = [100 + i * 0.2 + (i % 7) for i in range(80)]
            bars = pd.DataFrame({
                "adjusted_open": closes, "adjusted_close": closes,
                "volume": [100_000.0] * 80, "symbol": "TEST", "frequency": "daily",
            }, index=index)
            bar_dir = root / "processed" / "daily"
            signal_dir = root / "signals" / "daily"
            bar_dir.mkdir(parents=True)
            signal_dir.mkdir(parents=True)
            bars.to_parquet(bar_dir / "TEST.parquet")
            build_signals(bars).to_parquet(signal_dir / "TEST.parquet")
            settings = ExecutionConfig().to_dict()
            settings["periods_per_year"] = None
            self.assertEqual(run(root / "processed", root / "signals", root / "backtests",
                                 ["momentum", "mean_reversion"], settings, 0.0,
                                 20, None, 5, 0.5, 42), 0)
            report_path = root / "backtests" / "daily" / "TEST" / "momentum" / "risk_report.json"
            report = json.loads(report_path.read_text())
            manifest = json.loads((root / "backtests" / "manifest.json").read_text())
            self.assertEqual(len(manifest["results"]), 2)
            self.assertEqual(report["execution_parameters"]["periods_per_year"], 252.0)
            self.assertIn("probability_of_ruin", report["monte_carlo"])
            self.assertEqual(len(pd.read_parquet(report_path.parent / "equity_curve.parquet")), 80)


if __name__ == "__main__":
    unittest.main()
