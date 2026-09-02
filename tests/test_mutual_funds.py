import unittest
from datetime import date

from clients.base import MutualFundProvider
from models.schemas import FundScheme, NavPoint
from services.errors import FundError
from services.mutual_funds import MutualFundService


class FakeProvider(MutualFundProvider):
    source = "Test Provider"

    def __init__(self):
        self.scheme = FundScheme("1", "Test Fund - Direct Growth", "Test AMC")
        self.points = [
            NavPoint(date(2024, 1, 2), 100.0),
            NavPoint(date(2024, 12, 31), 110.0),
        ]

    def search_funds(self, query):
        return [self.scheme]

    def get_latest_nav(self, scheme_code):
        return self.scheme, self.points[-1]

    def get_nav_history(self, scheme_code, from_date, to_date):
        return self.scheme, self.points


class MutualFundServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = MutualFundService(FakeProvider())

    def test_history_includes_freshness_and_source(self):
        result = self.service.get_nav_history("1", "2024-01-01", "2024-12-31")
        self.assertEqual(result["source"], "Test Provider")
        self.assertEqual(result["data_as_of"], "2024-12-31")
        self.assertTrue(result["retrieved_at"].endswith("Z"))

    def test_metrics_expose_actual_observation_period(self):
        result = self.service.calculate_fund_metrics("1", "2024-01-01", "2024-12-31")
        self.assertEqual(
            result["observation_period"], {"from": "2024-01-02", "to": "2024-12-31"}
        )

    def test_date_validation(self):
        invalid = [
            ("01-01-2024", "2024-12-31"),
            ("2025-01-01", "2024-12-31"),
            ("2018-01-01", "2024-12-31"),
        ]
        for start, end in invalid:
            with self.subTest(start=start, end=end), self.assertRaises(FundError) as context:
                self.service.get_nav_history("1", start, end)
            self.assertEqual(context.exception.code, "INVALID_DATE_RANGE")

    def test_comparison_requires_distinct_codes(self):
        with self.assertRaises(FundError) as context:
            self.service.compare_funds(["1", "1"], "2024-01-01", "2024-12-31")
        self.assertEqual(context.exception.code, "INVALID_COMPARISON")


if __name__ == "__main__":
    unittest.main()

