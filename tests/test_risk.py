import unittest

import numpy as np
import pandas as pd

from datheon_data.risk import monte_carlo_equity, performance_metrics


class RiskTests(unittest.TestCase):
    def test_drawdown_duration_and_ratios(self):
        curve = pd.DataFrame({
            "equity": [100.0, 110.0, 99.0, 99.0, 110.0],
            "net_return": [0.0, 0.1, -0.1, 0.0, 110 / 99 - 1],
            "drawdown": [0.0, 0.0, -0.1, -0.1, 0.0],
        })
        report = performance_metrics(curve, 100, periods_per_year=4)
        self.assertAlmostEqual(report["maximum_drawdown"], 0.1)
        self.assertEqual(report["maximum_drawdown_duration_bars"], 2)
        self.assertAlmostEqual(report["total_return"], 0.1)
        self.assertIsNotNone(report["sharpe_ratio"])
        self.assertIsNotNone(report["sortino_ratio"])
        self.assertAlmostEqual(report["calmar_ratio"], report["annualized_return"] / 0.1)

    def test_bootstrap_ruin_and_seed_reproducibility(self):
        returns = np.array([-0.2, -0.2])
        summary, curves = monte_carlo_equity(returns, 100, paths=20, horizon=4,
                                             block_size=2, ruin_fraction=0.5, seed=7)
        again, other = monte_carlo_equity(returns, 100, paths=20, horizon=4,
                                          block_size=2, ruin_fraction=0.5, seed=7)
        self.assertEqual(summary, again)
        pd.testing.assert_frame_equal(curves, other)
        self.assertEqual(summary["probability_of_ruin"], 1.0)
        self.assertAlmostEqual(curves["p50"].iloc[-1], 100 * 0.8**4)


if __name__ == "__main__":
    unittest.main()
