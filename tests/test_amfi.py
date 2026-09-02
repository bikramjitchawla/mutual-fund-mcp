import unittest
from datetime import date

from clients.amfi import AMFIProvider
from services.errors import FundError

LATEST = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

PPFAS Mutual Fund
122639;INF879O01027;-;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;100.2500;01-Sep-2026
123456;INF000000001;-;Another Equity Fund - Regular Plan - Growth;20.5;01-Sep-2026
"""

HISTORY_ONE = """Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date

Open Ended Schemes ( Equity Scheme - Flexi Cap Fund )

PPFAS Mutual Fund
122639;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;INF879O01027;;100.0;;;01-Jan-2024
122639;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;INF879O01027;;101.0;;;02-Jan-2024
"""

HISTORY_TWO = """Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date

Open Ended Schemes ( Equity Scheme - Flexi Cap Fund )

PPFAS Mutual Fund
122639;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;INF879O01027;;101.0;;;02-Jan-2024
122639;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;INF879O01027;;102.0;;;03-Jan-2024
"""


class AMFIProviderTests(unittest.TestCase):
    def test_search_and_latest_parse_official_format(self):
        provider = AMFIProvider(fetcher=lambda _: LATEST)

        matches = provider.search_funds("parag flexi")
        scheme, point = provider.get_latest_nav("122639")

        self.assertEqual([item.scheme_code for item in matches], ["122639"])
        self.assertEqual(scheme.fund_house, "PPFAS Mutual Fund")
        self.assertEqual(point.nav, 100.25)
        self.assertEqual(point.date, date(2026, 9, 1))

    def test_history_chunks_and_deduplicates(self):
        requested_urls = []

        def fetch(url):
            requested_urls.append(url)
            return HISTORY_ONE if len(requested_urls) == 1 else HISTORY_TWO

        provider = AMFIProvider(history_chunk_days=2, fetcher=fetch)
        scheme, points = provider.get_nav_history(
            "122639", date(2024, 1, 1), date(2024, 1, 3)
        )

        self.assertEqual(scheme.scheme_code, "122639")
        self.assertEqual([point.date for point in points], [
            date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)
        ])
        self.assertEqual(len(requested_urls), 2)
        self.assertIn("frmdt=01-Jan-2024", requested_urls[0])
        self.assertIn("todt=02-Jan-2024", requested_urls[0])

    def test_invalid_scheme_code_never_reaches_network(self):
        provider = AMFIProvider(fetcher=lambda _: self.fail("network should not be called"))
        with self.assertRaises(FundError) as context:
            provider.get_latest_nav("../bad")
        self.assertEqual(context.exception.code, "SCHEME_NOT_FOUND")

    def test_html_is_rejected_by_parsers(self):
        provider = AMFIProvider(fetcher=lambda _: "<html>maintenance</html>")
        with self.assertRaises(FundError) as context:
            provider.get_latest_nav("122639")
        self.assertEqual(context.exception.code, "INVALID_PROVIDER_RESPONSE")


if __name__ == "__main__":
    unittest.main()

