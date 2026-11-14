import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from datheon_data.cli import run


class CliTests(unittest.TestCase):
    def test_end_to_end_writes_parquet_and_manifest(self):
        raw = pd.DataFrame({
            "open": [10.0, 11.0], "high": [11.0, 12.0],
            "low": [9.0, 10.0], "close": [10.0, 11.0],
            "adjusted_close": [10.0, 11.0], "volume": [100, 120],
        }, index=pd.date_range("2024-01-02", periods=2, tz="UTC", name="timestamp"))
        with tempfile.TemporaryDirectory() as directory, patch("datheon_data.cli.yahoo_history", return_value=raw):
            args = argparse.Namespace(symbols=["TEST"], universe_csv=None, sp500_current=False,
                                      frequency="daily", daily_provider="yahoo", hourly_provider="alpha",
                                      start="2024-01-01", end="2024-02-01", years=10,
                                      alpha_pause=0, output=directory)
            self.assertEqual(run(args), 0)
            bars = pd.read_parquet(Path(directory) / "daily" / "TEST.parquet")
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertEqual(len(bars), 2)
            self.assertEqual(manifest["results"][0]["rows"], 2)
            self.assertEqual(manifest["results"][0]["stationarity"]["status"],
                             "insufficient_variation_or_observations")


if __name__ == "__main__":
    unittest.main()
