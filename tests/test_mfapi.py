import unittest
from datetime import date

from clients.mfapi import MFAPIProvider
from services.errors import FundError

FUND = {
    "meta": {
        "fund_house": "HDFC Mutual Fund",
        "scheme_code": 125497,
        "scheme_name": "HDFC Top 100 Fund - Direct Plan - Growth",
        "isin_growth": "INF179K01BB2",
        "isin_div_reinvestment": None,
    },
    "data": [
        {"date": "03-01-2024", "nav": "102.0"},
        {"date": "02-01-2024", "nav": "101.0"},
        {"date": "01-01-2024", "nav": "100.0"},
    ],
    "status": "SUCCESS",
}


class MFAPIProviderTests(unittest.TestCase):
    def test_search_normalizes_results_without_inventing_fund_house(self):
        provider = MFAPIProvider(
            fetcher=lambda _: [{"schemeCode": 125497, "schemeName": "HDFC Top 100 Fund"}]
        )
        results = provider.search_funds("HDFC")
        self.assertEqual(results[0].scheme_code, "125497")
        self.assertIsNone(results[0].fund_house)

    def test_latest_uses_newest_point(self):
        provider = MFAPIProvider(fetcher=lambda _: FUND)
        scheme, point = provider.get_latest_nav("125497")
        self.assertEqual(scheme.fund_house, "HDFC Mutual Fund")
        self.assertEqual(point.date, date(2024, 1, 3))

    def test_history_filters_and_orders_provider_data(self):
        provider = MFAPIProvider(fetcher=lambda _: FUND)
        _, points = provider.get_nav_history("125497", date(2024, 1, 2), date(2024, 1, 3))
        self.assertEqual([point.nav for point in points], [101.0, 102.0])

    def test_mismatched_scheme_is_rejected(self):
        provider = MFAPIProvider(fetcher=lambda _: FUND)
        with self.assertRaises(FundError) as context:
            provider.get_latest_nav("999999")
        self.assertEqual(context.exception.code, "INVALID_PROVIDER_RESPONSE")


if __name__ == "__main__":
    unittest.main()
