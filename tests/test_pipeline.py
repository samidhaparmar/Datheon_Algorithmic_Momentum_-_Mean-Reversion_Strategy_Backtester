import unittest

import numpy as np
import pandas as pd

from datheon_data.pipeline import prepare_bars, stationarity_report


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame(
            {
                "open": [100.0, 51.0, 52.0], "high": [102.0, 53.0, 54.0],
                "low": [99.0, 50.0, 51.0], "close": [100.0, 52.0, 53.0],
                "adjusted_close": [49.0, 50.96, 53.0], "volume": [1000, 2000, 2100],
                "dividend": [0.0, 0.0, 0.0], "split_ratio": [0.0, 2.0, 0.0],
            },
            index=pd.date_range("2024-01-01", periods=3, tz="UTC", name="timestamp"),
        )

    def test_adjusted_ohlc_and_returns(self):
        bars = prepare_bars(self.raw, "TEST", "daily", "yahoo")
        self.assertAlmostEqual(bars["adjusted_open"].iloc[0], 49.0)
        self.assertAlmostEqual(bars["adjustment_factor"].iloc[1], 0.98)
        self.assertAlmostEqual(bars["log_return"].iloc[1], np.log(50.96 / 49.0))
        self.assertTrue(np.isnan(bars["log_return"].iloc[0]))
        self.assertEqual(bars["split_ratio"].iloc[1], 2.0)

    def test_duplicate_and_bad_ohlc_rejected(self):
        duplicate = pd.concat([self.raw, self.raw.iloc[:1]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            prepare_bars(duplicate, "TEST", "daily", "yahoo")
        bad = self.raw.copy()
        bad.loc[bad.index[1], "high"] = 49
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            prepare_bars(bad, "TEST", "daily", "yahoo")

    def test_short_series_is_not_claimed_stationary(self):
        report = stationarity_report(prepare_bars(self.raw, "TEST", "daily", "yahoo"))
        self.assertIsNone(report["stationary_at_5pct"])
        self.assertEqual(report["status"], "insufficient_variation_or_observations")


if __name__ == "__main__":
    unittest.main()
