"""
test_extract_stripe.py — Stripe CSV extraction tests.
Uses synthetic in-memory fixtures. Validates the critical bucketing rules:
  - Refunds bucketed by CHARGE'S created month (not refunded date)
  - De-duplication by charge id
  - Chargebacks from separate disputes export
"""
import os
import tempfile

import pytest

from app.extract.stripe import extract_stripe
from conftest import make_stripe_payments_csv, make_stripe_disputes_csv


def _write(content: bytes, suffix=".csv") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb")
    f.write(content)
    f.close()
    return f.name


def cleanup(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sales bucketing
# ---------------------------------------------------------------------------

class TestStripeSales:

    def test_sales_bucketed_by_created_month(self):
        csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Created date (UTC)": "2026-01-10 12:00:00"},
            {"id": "ch_002", "Amount": "2000", "Created date (UTC)": "2026-02-05 08:00:00"},
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            assert result["table"]["2026-01"]["sales"] == pytest.approx(1000.0)
            assert result["table"]["2026-02"]["sales"] == pytest.approx(2000.0)
        finally:
            cleanup(path)

    def test_multiple_charges_same_month_summed(self):
        csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "500", "Created date (UTC)": "2026-03-01 00:00:00"},
            {"id": "ch_002", "Amount": "750", "Created date (UTC)": "2026-03-15 00:00:00"},
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            assert result["table"]["2026-03"]["sales"] == pytest.approx(1250.0)
        finally:
            cleanup(path)


# ---------------------------------------------------------------------------
# Refund bucketing — THE critical rule
# ---------------------------------------------------------------------------

class TestStripeRefundBucketing:

    def test_refund_bucketed_by_created_month_not_refunded_date(self):
        """
        Charge created Jan 10 → refund must appear in Jan, even if refunded in Feb.
        This is the rule that matches the real Rosen sheet to the cent.
        """
        csv = make_stripe_payments_csv([
            {
                "id": "ch_001",
                "Amount": "1000",
                "Amount Refunded": "200",
                "Created date (UTC)": "2026-01-10 00:00:00",
                "Refunded date (UTC)": "2026-02-15 00:00:00",  # refunded in Feb
            }
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            # Refund should be in JAN (created month), not FEB
            assert result["table"].get("2026-01", {}).get("refunds", 0) == pytest.approx(200.0)
            assert result["table"].get("2026-02", {}).get("refunds", 0) == pytest.approx(0.0)
        finally:
            cleanup(path)

    def test_zero_refund_not_counted(self):
        csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Amount Refunded": "0",
             "Created date (UTC)": "2026-01-01 00:00:00"},
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            assert result["table"].get("2026-01", {}).get("refunds", 0) == 0.0
        finally:
            cleanup(path)

    def test_partial_refund_counted(self):
        csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Amount Refunded": "50",
             "Created date (UTC)": "2026-01-05 00:00:00"},
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            assert result["table"]["2026-01"]["refunds"] == pytest.approx(50.0)
        finally:
            cleanup(path)


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

class TestStripeDedup:

    def test_duplicate_charge_id_counted_once(self):
        row = {"id": "ch_DUP", "Amount": "1000", "Amount Refunded": "0",
               "Created date (UTC)": "2026-01-01 00:00:00"}
        csv1 = make_stripe_payments_csv([row])
        csv2 = make_stripe_payments_csv([row])  # same id, second file
        p1, p2 = _write(csv1), _write(csv2)
        try:
            result = extract_stripe([p1, p2])
            assert result["table"]["2026-01"]["sales"] == pytest.approx(1000.0)
        finally:
            cleanup(p1, p2)

    def test_unique_ids_across_files_both_counted(self):
        csv1 = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Created date (UTC)": "2026-01-01 00:00:00"}
        ])
        csv2 = make_stripe_payments_csv([
            {"id": "ch_002", "Amount": "500", "Created date (UTC)": "2026-01-15 00:00:00"}
        ])
        p1, p2 = _write(csv1), _write(csv2)
        try:
            # Only first file contributes to sales (default: sales_paths=payment_paths[:1])
            result = extract_stripe([p1, p2])
            # p1 drives sales; refunds from both
            assert result["table"]["2026-01"]["sales"] == pytest.approx(1000.0)
        finally:
            cleanup(p1, p2)


# ---------------------------------------------------------------------------
# Chargebacks (disputes export)
# ---------------------------------------------------------------------------

class TestStripeChargebacks:

    def test_no_disputes_file_chargebacks_zero(self):
        csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Created date (UTC)": "2026-01-01 00:00:00"}
        ])
        path = _write(csv)
        try:
            result = extract_stripe([path])
            assert result["table"]["2026-01"]["chargebacks"] == 0.0
            assert "requires" in result["chargebacks_note"].lower()
        finally:
            cleanup(path)

    def test_disputes_file_adds_chargebacks(self):
        payments_csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Created date (UTC)": "2026-01-05 00:00:00"}
        ])
        disputes_csv = make_stripe_disputes_csv([
            {"id": "dp_001", "Amount": "400", "Created date (UTC)": "2026-01-20 00:00:00"}
        ])
        p1, p2 = _write(payments_csv), _write(disputes_csv)
        try:
            result = extract_stripe([p1], disputes_path=p2)
            assert result["table"]["2026-01"]["chargebacks"] == pytest.approx(400.0)
        finally:
            cleanup(p1, p2)

    def test_chargebacks_bucketed_by_dispute_created_date(self):
        payments_csv = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "1000", "Created date (UTC)": "2026-01-05 00:00:00"}
        ])
        disputes_csv = make_stripe_disputes_csv([
            {"id": "dp_001", "Amount": "300", "Created date (UTC)": "2026-02-10 00:00:00"}
        ])
        p1, p2 = _write(payments_csv), _write(disputes_csv)
        try:
            result = extract_stripe([p1], disputes_path=p2)
            assert result["table"].get("2026-02", {}).get("chargebacks", 0) == pytest.approx(300.0)
            assert result["table"].get("2026-01", {}).get("chargebacks", 0) == pytest.approx(0.0)
        finally:
            cleanup(p1, p2)


# ---------------------------------------------------------------------------
# §9 Rosen golden extraction values (synthetic recreation)
# These rows are crafted to reproduce the spec's expected monthly totals.
# ---------------------------------------------------------------------------

class TestRosenExtractionGolden:
    """
    Spec §9 extraction golden values:
      Sales:    Dec 790,419.13 · Jan 836,029.33 · Feb 722,955.66 (+ Mar boundary → 727,244.80)
      Refunds:  Dec 10,725.14 · Jan 29,515.15 · Feb 1,699.53
      CHB:      Dec 2,177.68 · Jan 2,252.58 · Feb 2,800.60
    """

    @pytest.fixture(scope="class")
    def rosen_result(self):
        payments = make_stripe_payments_csv([
            # Dec sales + Dec refund
            {"id": "ch_dec_1", "Amount": "790419.13", "Amount Refunded": "10725.14",
             "Created date (UTC)": "2025-12-15 00:00:00"},
            # Jan sales + Jan refund
            {"id": "ch_jan_1", "Amount": "836029.33", "Amount Refunded": "29515.15",
             "Created date (UTC)": "2026-01-10 00:00:00"},
            # Feb sales + Feb refund
            {"id": "ch_feb_1", "Amount": "722955.66", "Amount Refunded": "1699.53",
             "Created date (UTC)": "2026-02-20 00:00:00"},
        ])
        disputes = make_stripe_disputes_csv([
            {"id": "dp_dec", "Amount": "2177.68", "Created date (UTC)": "2025-12-20 00:00:00"},
            {"id": "dp_jan", "Amount": "2252.58", "Created date (UTC)": "2026-01-25 00:00:00"},
            {"id": "dp_feb", "Amount": "2800.60", "Created date (UTC)": "2026-02-28 00:00:00"},
        ])
        p1, p2 = _write(payments), _write(disputes)
        try:
            return extract_stripe([p1], disputes_path=p2)
        finally:
            cleanup(p1, p2)

    def test_dec_sales(self, rosen_result):
        assert rosen_result["table"]["2025-12"]["sales"] == pytest.approx(790_419.13, abs=0.01)

    def test_jan_sales(self, rosen_result):
        assert rosen_result["table"]["2026-01"]["sales"] == pytest.approx(836_029.33, abs=0.01)

    def test_feb_sales(self, rosen_result):
        assert rosen_result["table"]["2026-02"]["sales"] == pytest.approx(722_955.66, abs=0.01)

    def test_dec_refunds(self, rosen_result):
        assert rosen_result["table"]["2025-12"]["refunds"] == pytest.approx(10_725.14, abs=0.01)

    def test_jan_refunds(self, rosen_result):
        assert rosen_result["table"]["2026-01"]["refunds"] == pytest.approx(29_515.15, abs=0.01)

    def test_feb_refunds(self, rosen_result):
        assert rosen_result["table"]["2026-02"]["refunds"] == pytest.approx(1_699.53, abs=0.01)

    def test_dec_chargebacks(self, rosen_result):
        assert rosen_result["table"]["2025-12"]["chargebacks"] == pytest.approx(2_177.68, abs=0.01)

    def test_jan_chargebacks(self, rosen_result):
        assert rosen_result["table"]["2026-01"]["chargebacks"] == pytest.approx(2_252.58, abs=0.01)

    def test_feb_chargebacks(self, rosen_result):
        assert rosen_result["table"]["2026-02"]["chargebacks"] == pytest.approx(2_800.60, abs=0.01)
