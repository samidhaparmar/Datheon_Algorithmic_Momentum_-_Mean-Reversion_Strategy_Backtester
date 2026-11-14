import unittest

import numpy as np
import pandas as pd

from datheon_data.dashboard import (aligned_benchmark, candidate_configs,
                                    curve_from_returns, optimize_train_test,
                                    rolling_drawdown)
from datheon_data.execution import ExecutionConfig
from datheon_data.signals import SignalConfig


class DashboardCoreTests(unittest.TestCase):
    def test_benchmark_and_rolling_drawdown(self):
        index = pd.date_range("2024-01-01", periods=4, tz="UTC")
        equity = pd.Series([100, 110, 99, 108], index=index)
        benchmark = pd.Series([50, 55, 52, 54], index=index)
        comparison = aligned_benchmark(equity, benchmark, 100)
        self.assertAlmostEqual(comparison["benchmark"].iloc[1], 110)
        self.assertAlmostEqual(rolling_drawdown(equity, window=3).iloc[2], -0.1)
        segment = curve_from_returns(pd.Series([0.1, -0.1], index=index[:2]), 100)
        self.assertAlmostEqual(segment["equity"].iloc[-1], 99)

    def test_training_selection_ignores_holdout_prices(self):
        index = pd.bdate_range("2022-01-01", periods=120, tz="UTC")
        prices = 100 * np.exp(np.cumsum(np.sin(np.arange(120) / 5) * 0.01 + 0.0005))
        bars = pd.DataFrame({
            "adjusted_open": prices, "adjusted_close": prices,
            "volume": [100_000.0] * 120,
        }, index=index)
        execution = ExecutionConfig(commission_per_share=0, minimum_commission=0,
                                    half_spread_bps=0, linear_impact_bps=0,
                                    sqrt_impact_bps=0, annual_borrow_rate=0)
        configs = candidate_configs("momentum", SignalConfig(), [5, 10], [20, 30])
        original = optimize_train_test(bars, "momentum", configs, execution)
        changed = bars.copy()
        changed.iloc[84:, changed.columns.get_loc("adjusted_open")] *= 1.5
        changed.iloc[84:, changed.columns.get_loc("adjusted_close")] *= 1.5
        revised = optimize_train_test(changed, "momentum", configs, execution)
        self.assertEqual(original["selected_config"], revised["selected_config"])
        self.assertEqual(original["train_metrics"], revised["train_metrics"])
        self.assertEqual(original["split_timestamp"], index[84])
        self.assertNotEqual(original["test_metrics"]["total_return"],
                            revised["test_metrics"]["total_return"])


if __name__ == "__main__":
    unittest.main()
