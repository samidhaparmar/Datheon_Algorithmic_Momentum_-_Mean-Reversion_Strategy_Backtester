import unittest

import pandas as pd

from datheon_data.signals import SignalConfig, build_signals


PRICES = [100, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110,
          111, 112, 113, 114, 100, 101, 102, 103, 104, 105, 106, 107, 108]
CONFIG = SignalConfig(macd_fast=2, macd_slow=4, macd_signal=2,
                      ma_fast=2, ma_slow=4, bb_window=4, bb_width=1.0,
                      volatility_fast=2, volatility_slow=5)


def bars(prices=PRICES):
    return pd.DataFrame({"adjusted_close": prices, "symbol": "TEST", "frequency": "daily"},
                        index=pd.date_range("2024-01-01", periods=len(prices), tz="UTC", name="timestamp"))


class SignalTests(unittest.TestCase):
    def test_decision_row_cannot_see_its_own_or_future_close(self):
        original = bars()
        changed = original.copy()
        changed.loc[changed.index[17], "adjusted_close"] = 150.0
        before = build_signals(original, CONFIG)
        after = build_signals(changed, CONFIG)
        pd.testing.assert_frame_equal(before.iloc[:18], after.iloc[:18])
        self.assertEqual(before["known_adjusted_close"].iloc[17], original["adjusted_close"].iloc[16])
        self.assertEqual(before["information_cutoff"].iloc[17], original.index[16])
        self.assertNotEqual(before["known_adjusted_close"].iloc[18], after["known_adjusted_close"].iloc[18])

    def test_momentum_cross_and_position_follow_observation_bar(self):
        signals = build_signals(bars(), CONFIG)
        self.assertEqual(signals["momentum_position"].iloc[5], 1)
        self.assertEqual(signals["macd_cross"].iloc[16], 0)
        self.assertEqual(signals["ma_cross"].iloc[16], 0)
        self.assertEqual(signals["macd_cross"].iloc[17], -1)
        self.assertEqual(signals["ma_cross"].iloc[17], -1)
        self.assertEqual(signals["momentum_position"].iloc[17], -1)

    def test_bollinger_entry_and_midline_exit(self):
        short = build_signals(bars(), CONFIG)
        self.assertEqual(short["mean_reversion_action"].iloc[6], "enter_short")
        self.assertEqual(short["mean_reversion_action"].iloc[17], "exit_short")
        long = build_signals(bars([200 - value for value in PRICES]), CONFIG)
        self.assertEqual(long["mean_reversion_action"].iloc[6], "enter_long")
        self.assertEqual(long["mean_reversion_action"].iloc[17], "exit_long")

    def test_warmup_and_invalid_parameters(self):
        signals = build_signals(bars(), CONFIG)
        self.assertFalse(signals["momentum_ready"].iloc[0])
        self.assertFalse(signals["mean_reversion_ready"].iloc[0])
        self.assertEqual(signals["momentum_position"].iloc[0], 0)
        with self.assertRaisesRegex(ValueError, "Fast MACD"):
            build_signals(bars(), SignalConfig(macd_fast=30, macd_slow=20))


if __name__ == "__main__":
    unittest.main()
