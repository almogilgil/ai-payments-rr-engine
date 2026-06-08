"""
test_extract_guestypay.py — GuestyPay CSV extraction tests.
Uses both the real CRIBS CSV (when available) and synthetic in-memory fixtures.
"""
import os
import tempfile

import pytest

from app.extract.guestypay import extract_guestypay
from conftest import make_guestypay_csv

CRIBS_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "Rolling Reserve Assesment", "guestypay_cribs.csv"
)


# ---------------------------------------------------------------------------
# Synthetic tests (always run)
# ---------------------------------------------------------------------------

class TestGuestyPaySynthetic:

    def _write_and_extract(self, rows):
        content = make_guestypay_csv(rows)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as f:
            f.write(content)
            path = f.name
        try:
            return extract_guestypay(path)
        finally:
            os.unlink(path)

    def test_charge_sums_to_sales(self):
        rows = [
            {"transactionType": "Charge", "amount_usd": "1000.00", "systemDate": "Jan 15, 2026"},
            {"transactionType": "Charge", "amount_usd": "500.50",  "systemDate": "Jan 20, 2026"},
        ]
        result = self._write_and_extract(rows)
        assert result["table"]["2026-01"]["sales"] == pytest.approx(1500.50)

    def test_refund_and_partial_refund_sum_as_abs(self):
        rows = [
            {"transactionType": "Charge",         "amount_usd": "1000.00", "systemDate": "Jan 10, 2026"},
            {"transactionType": "Refund",          "amount_usd": "-200.00", "systemDate": "Jan 12, 2026"},
            {"transactionType": "Partial Refund",  "amount_usd": "-50.00",  "systemDate": "Jan 14, 2026"},
        ]
        result = self._write_and_extract(rows)
        assert result["table"]["2026-01"]["refunds"] == pytest.approx(250.00)

    def test_chargeback_summed_as_abs(self):
        rows = [
            {"transactionType": "Charge",     "amount_usd": "1000.00", "systemDate": "Feb 01, 2026"},
            {"transactionType": "Chargeback", "amount_usd": "-350.00", "systemDate": "Feb 10, 2026"},
        ]
        result = self._write_and_extract(rows)
        assert result["table"]["2026-02"]["chargebacks"] == pytest.approx(350.00)

    def test_multi_month_bucketing(self):
        rows = [
            {"transactionType": "Charge", "amount_usd": "1000", "systemDate": "Jan 01, 2026"},
            {"transactionType": "Charge", "amount_usd": "2000", "systemDate": "Feb 01, 2026"},
            {"transactionType": "Charge", "amount_usd": "3000", "systemDate": "Mar 01, 2026"},
        ]
        result = self._write_and_extract(rows)
        t = result["table"]
        assert t["2026-01"]["sales"] == 1000.0
        assert t["2026-02"]["sales"] == 2000.0
        assert t["2026-03"]["sales"] == 3000.0

    def test_unknown_transaction_type_ignored(self):
        rows = [
            {"transactionType": "Charge",  "amount_usd": "500", "systemDate": "Jan 01, 2026"},
            {"transactionType": "Unknown", "amount_usd": "999", "systemDate": "Jan 01, 2026"},
        ]
        result = self._write_and_extract(rows)
        assert result["table"]["2026-01"]["sales"] == 500.0

    def test_latest_date_detected(self):
        rows = [
            {"transactionType": "Charge", "amount_usd": "100", "systemDate": "Jan 01, 2026"},
            {"transactionType": "Charge", "amount_usd": "200", "systemDate": "Mar 28, 2026"},
            {"transactionType": "Charge", "amount_usd": "150", "systemDate": "Feb 15, 2026"},
        ]
        result = self._write_and_extract(rows)
        from datetime import datetime
        assert result["latest_date"] == datetime(2026, 3, 28)

    def test_returns_table_and_latest_date_keys(self):
        rows = [{"transactionType": "Charge", "amount_usd": "100", "systemDate": "Jan 01, 2026"}]
        result = self._write_and_extract(rows)
        assert "table" in result
        assert "latest_date" in result


# ---------------------------------------------------------------------------
# Real CRIBS CSV tests (skipped if file not present)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(CRIBS_CSV), reason="CRIBS CSV not available")
class TestGuestyPayCRIBSReal:

    @pytest.fixture(scope="class")
    def result(self):
        return extract_guestypay(CRIBS_CSV)

    def test_has_march_sales(self, result):
        assert result["table"]["2026-03"]["sales"] > 0

    def test_latest_date_is_march_2026(self, result):
        assert result["latest_date"].year == 2026
        assert result["latest_date"].month == 3

    def test_march_has_chargebacks(self, result):
        assert result["table"]["2026-03"]["chargebacks"] > 0

    def test_sales_gt_refunds(self, result):
        for month, d in result["table"].items():
            if d["sales"] > 0:
                assert d["sales"] > d["refunds"], f"Sales < refunds in {month}"
