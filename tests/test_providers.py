import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from datheon_data.providers import AlphaVantage, ProviderError


class AlphaVantageTests(unittest.TestCase):
    def test_monthly_hourly_is_adjusted_and_converted_to_utc(self):
        response = Mock()
        response.json.return_value = {"Time Series (60min)": {
            "2024-01-02 10:00:00": {"1. open": "100", "2. high": "102", "3. low": "99", "4. close": "101", "5. volume": "1000"}
        }}
        session = Mock()
        session.get.return_value = response
        provider = AlphaVantage("test-key", session=session)
        bars = provider.hourly("TEST", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(bars.index[0].hour, 15)  # 10:00 ET in January.
        self.assertEqual(bars["adjusted_close"].iloc[0], 101)
        self.assertEqual(session.get.call_args.kwargs["params"]["month"], "2024-01")

    def test_vendor_rate_limit_is_explicit_error(self):
        response = Mock()
        response.json.return_value = {"Note": "rate limit"}
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(ProviderError, "rate limit"):
            AlphaVantage("test-key", session=session).daily(
                "TEST", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 2, 1, tzinfo=timezone.utc)
            )

    def test_completed_historical_month_uses_cache(self):
        response = Mock()
        response.json.return_value = {"Time Series (60min)": {
            "2020-01-02 10:00:00": {"1. open": "100", "2. high": "102", "3. low": "99", "4. close": "101", "5. volume": "1000"}
        }}
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            provider = AlphaVantage("test-key", session=session, cache_dir=Path(directory))
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            end = datetime(2020, 2, 1, tzinfo=timezone.utc)
            provider.hourly("TEST", start, end)
            provider.hourly("TEST", start, end)
            self.assertEqual(session.get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
