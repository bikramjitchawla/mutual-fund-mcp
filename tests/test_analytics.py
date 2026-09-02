import math
import unittest
from datetime import date

from models.schemas import NavPoint
from services.analytics import calculate_metrics
from services.errors import FundError


class AnalyticsTests(unittest.TestCase):
    def test_metrics_are_deterministic(self):
        points = [
            NavPoint(date(2023, 1, 1), 100.0),
            NavPoint(date(2023, 1, 2), 110.0),
            NavPoint(date(2024, 1, 1), 121.0),
        ]

        metrics = calculate_metrics(points)

        self.assertEqual(metrics["absolute_return_pct"], 21.0)
        self.assertAlmostEqual(metrics["cagr_pct"], 21.0153, places=4)
        self.assertEqual(metrics["max_drawdown_pct"], 0.0)
        self.assertEqual(metrics["annualized_volatility_pct"], 0.0)

    def test_drawdown_and_sample_volatility(self):
        points = [
            NavPoint(date(2024, 1, 1), 100.0),
            NavPoint(date(2024, 1, 2), 120.0),
            NavPoint(date(2024, 1, 3), 90.0),
        ]

        metrics = calculate_metrics(points)

        expected_volatility = math.sqrt(2) * 0.225 * math.sqrt(252) * 100
        self.assertAlmostEqual(metrics["annualized_volatility_pct"], expected_volatility, places=3)
        self.assertEqual(metrics["max_drawdown_pct"], -25.0)

    def test_requires_two_distinct_dates(self):
        with self.assertRaises(FundError) as context:
            calculate_metrics([NavPoint(date(2024, 1, 1), 100.0)])
        self.assertEqual(context.exception.code, "NO_NAV_DATA")

    def test_rejects_non_positive_nav(self):
        with self.assertRaises(FundError) as context:
            calculate_metrics(
                [NavPoint(date(2024, 1, 1), 100.0), NavPoint(date(2024, 1, 2), 0.0)]
            )
        self.assertEqual(context.exception.code, "CALCULATION_ERROR")


if __name__ == "__main__":
    unittest.main()
