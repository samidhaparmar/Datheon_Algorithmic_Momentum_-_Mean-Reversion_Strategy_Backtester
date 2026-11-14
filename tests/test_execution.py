import unittest

import pandas as pd

from datheon_data.execution import ExecutionConfig, simulate_execution


def fixture(targets, volumes=None, opens=None, closes=None):
    count = len(targets)
    index = pd.date_range("2024-01-01", periods=count, tz="UTC", name="timestamp")
    bars = pd.DataFrame({
        "adjusted_open": opens or [100.0] * count,
        "adjusted_close": closes or [100.0] * count,
        "volume": volumes or [1000.0] * count,
        "symbol": "TEST",
    }, index=index)
    signals = pd.DataFrame({
        "information_cutoff": index.to_series().shift(1),
        "known_adjusted_close": bars["adjusted_close"].shift(1),
        "momentum_position": targets,
        "mean_reversion_position": targets,
    }, index=index)
    return bars, signals


class ExecutionTests(unittest.TestCase):
    def test_spread_impact_commission_and_no_churn(self):
        bars, signals = fixture([0, 1, 1, 0])
        config = ExecutionConfig(initial_capital=10_000, allocation=0.5,
                                 half_spread_bps=10, linear_impact_bps=20,
                                 sqrt_impact_bps=40, max_participation=0.1,
                                 commission_per_share=0.1, minimum_commission=1,
                                 annual_borrow_rate=0)
        curve = simulate_execution(bars, signals, "momentum", config)
        self.assertAlmostEqual(curve["fill_shares"].iloc[1], 50)
        self.assertAlmostEqual(curve["participation"].iloc[1], 0.05)
        self.assertAlmostEqual(curve["spread_cost"].iloc[1], 5)
        self.assertAlmostEqual(curve["linear_impact_cost"].iloc[1], 0.5)
        self.assertAlmostEqual(curve["commission"].iloc[1], 5)
        self.assertAlmostEqual(curve["equity"].iloc[1],
                               10_000 - sum(curve[column].iloc[1] for column in
                                            ["spread_cost", "linear_impact_cost", "sqrt_impact_cost", "commission"]))
        self.assertEqual(curve["fill_shares"].iloc[2], 0)
        self.assertAlmostEqual(curve["fill_shares"].iloc[3], -50)

    def test_prior_volume_caps_and_partially_fills_orders(self):
        bars, signals = fixture([0, 1, 1, 1], volumes=[100, 100, 1000, 1000])
        config = ExecutionConfig(initial_capital=10_000, allocation=1,
                                 max_participation=0.1, half_spread_bps=0,
                                 linear_impact_bps=0, sqrt_impact_bps=0,
                                 commission_per_share=0, minimum_commission=0,
                                 annual_borrow_rate=0)
        curve = simulate_execution(bars, signals, "momentum", config)
        self.assertEqual(curve["fill_shares"].iloc[1], 10)
        self.assertEqual(curve["fill_shares"].iloc[2], 10)
        self.assertEqual(curve["fill_shares"].iloc[3], 80)
        self.assertEqual(curve["pending_shares"].iloc[1], 90)
        self.assertEqual(curve["prior_volume"].iloc[3], 1000)

    def test_short_borrow_is_charged_to_equity(self):
        bars, signals = fixture([0, -1, -1], closes=[100, 100, 100])
        config = ExecutionConfig(initial_capital=10_000, allocation=0.5,
                                 half_spread_bps=0, linear_impact_bps=0,
                                 sqrt_impact_bps=0, commission_per_share=0,
                                 minimum_commission=0, annual_borrow_rate=0.252,
                                 periods_per_year=252)
        curve = simulate_execution(bars, signals, "mean_reversion", config)
        self.assertAlmostEqual(curve["fill_shares"].iloc[1], -50)
        self.assertAlmostEqual(curve["borrow_fee"].iloc[2], 5)
        self.assertAlmostEqual(curve["equity"].iloc[2], 9_995)

    def test_signal_cutoff_must_match_prior_bar(self):
        bars, signals = fixture([0, 1, 1])
        signals.loc[signals.index[1], "information_cutoff"] = signals.index[1]
        with self.assertRaisesRegex(ValueError, "preceding observed bar"):
            simulate_execution(bars, signals, "momentum")

    def test_price_revision_invalidates_stale_signals(self):
        bars, signals = fixture([0, 1, 1])
        bars.loc[bars.index[1], "adjusted_close"] = 101
        with self.assertRaisesRegex(ValueError, "not generated from these"):
            simulate_execution(bars, signals, "momentum")

    def test_short_gap_can_ruin_account(self):
        bars, signals = fixture([0, -1, -1], opens=[100, 100, 300],
                                closes=[100, 100, 300], volumes=[100_000] * 3)
        config = ExecutionConfig(initial_capital=10_000, allocation=1,
                                 half_spread_bps=0, linear_impact_bps=0,
                                 sqrt_impact_bps=0, commission_per_share=0,
                                 minimum_commission=0, annual_borrow_rate=0)
        curve = simulate_execution(bars, signals, "momentum", config)
        self.assertEqual(curve["status"].iloc[2], "ruin")
        self.assertEqual(curve["equity"].iloc[2], 0)
        self.assertEqual(curve["net_return"].iloc[2], -1)


if __name__ == "__main__":
    unittest.main()
