"""
test_calc.py — Golden-value tests for the deterministic RR exposure engine.
These are the acceptance bar from ENGINE_BUILD_SPEC §9. ALL must pass.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.calc import rr_engine, lookup_flat_amount, window_summary, monthly_rates


# ---------------------------------------------------------------------------
# §9 Golden cases
# ---------------------------------------------------------------------------

class TestRosenGolden:
    """Rosen Vacations — validated to the cent against the filled calculator."""

    def test_10pct(self):
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["EXP"]["10%"] == 613_843

    def test_5pct(self):
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["EXP"]["5%"] == 260_789

    def test_flat(self):
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["EXP"]["Flat"] == -82_265

    def test_waiver_incl(self):
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["EXP"]["Waiver_incl"] == -92_265

    def test_waiver_no_chb(self):
        """Rosen refund% 3.53% < 13% → must be 0."""
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["EXP"]["Waiver_noCHB"] == 0


class TestLiveSuiteGolden:
    """Live Suite — validates the Waiver_noCHB ≥13% branch."""

    def test_10pct(self):
        r = rr_engine(3_335_083.99, 0.0157, 0.1347, flat_amount=60_000)
        assert r["EXP"]["10%"] == 498_929

    def test_5pct(self):
        r = rr_engine(3_335_083.99, 0.0157, 0.1347, flat_amount=60_000)
        assert r["EXP"]["5%"] == -1_334

    def test_flat(self):
        r = rr_engine(3_335_083.99, 0.0157, 0.1347, flat_amount=60_000)
        assert r["EXP"]["Flat"] == -441_597

    def test_waiver_incl(self):
        r = rr_engine(3_335_083.99, 0.0157, 0.1347, flat_amount=60_000)
        assert r["EXP"]["Waiver_incl"] == -501_597

    def test_waiver_no_chb(self):
        """Live Suite refund% 13.47% ≥ 13% → must equal -estimated_refund (not CNL)."""
        r = rr_engine(3_335_083.99, 0.0157, 0.1347, flat_amount=60_000)
        assert r["EXP"]["Waiver_noCHB"] == -449_236


# ---------------------------------------------------------------------------
# Waiver_noCHB boundary logic
# ---------------------------------------------------------------------------

class TestWaiverNoCHBBoundary:

    def test_just_below_13pct_is_zero(self):
        r = rr_engine(1_000_000, 0.01, 0.1299, flat_amount=30_000)
        assert r["EXP"]["Waiver_noCHB"] == 0

    def test_exactly_13pct_is_negative(self):
        """At exactly 13% → refund-only exposure (not 0)."""
        r = rr_engine(1_000_000, 0.01, 0.13, flat_amount=30_000)
        assert r["EXP"]["Waiver_noCHB"] < 0

    def test_above_13pct_excludes_chb(self):
        """Waiver_noCHB must NOT equal Waiver_incl when CHB rate > 0."""
        r = rr_engine(1_000_000, 0.02, 0.15, flat_amount=30_000)
        assert r["EXP"]["Waiver_noCHB"] != r["EXP"]["Waiver_incl"]
        assert r["EXP"]["Waiver_noCHB"] > r["EXP"]["Waiver_incl"]

    def test_waiver_no_chb_equals_negative_refund_volume(self):
        """Above 13%: Waiver_noCHB = -(volume_90d * refund_rate)."""
        volume = 1_000_000
        chb_rate = 0.02
        refund_rate = 0.15
        r = rr_engine(volume, chb_rate, refund_rate, flat_amount=30_000)
        expected = round(-(volume * round(refund_rate, 4)))
        assert r["EXP"]["Waiver_noCHB"] == expected


# ---------------------------------------------------------------------------
# Rate rounding
# ---------------------------------------------------------------------------

class TestRateRounding:

    def test_rates_rounded_to_4_decimals(self):
        """Engine must round input rates to 4 decimals before computing."""
        # 0.00394999 rounds to 0.0039; 0.00395 rounds to 0.0040
        r_low  = rr_engine(1_000_000, 0.003949, 0.035, flat_amount=10_000)
        r_high = rr_engine(1_000_000, 0.003950, 0.035, flat_amount=10_000)
        # The two should differ (rounding changed the rate)
        assert r_low["EXP"]["10%"] != r_high["EXP"]["10%"]

    def test_cnl_components(self):
        r = rr_engine(2_353_692, 0.0039, 0.0353, flat_amount=10_000)
        assert r["estimated_chb"] == round(2_353_692 * 0.0039, 2)
        assert r["estimated_refund"] == round(2_353_692 * 0.0353, 2)
        assert r["CNL"] == round(r["estimated_chb"] + r["estimated_refund"], 2)


# ---------------------------------------------------------------------------
# Flat amount lookup table
# ---------------------------------------------------------------------------

class TestFlatAmountLookup:

    def test_75k(self):
        assert lookup_flat_amount(75_000) == 10_000

    def test_100k(self):
        assert lookup_flat_amount(100_000) == 30_000

    def test_500k(self):
        assert lookup_flat_amount(500_000) == 60_000

    def test_1m(self):
        assert lookup_flat_amount(1_000_000) == 100_000

    def test_above_2m_defaults_to_100k(self):
        assert lookup_flat_amount(3_000_000) == 100_000


# ---------------------------------------------------------------------------
# Monthly rates helper
# ---------------------------------------------------------------------------

class TestMonthlyRates:

    def test_basic(self):
        table = {
            "2026-01": {"sales": 100_000, "refunds": 1_000, "chargebacks": 500},
        }
        rates = monthly_rates(table)
        assert abs(rates["2026-01"]["refund_rate"] - 0.01) < 0.000001
        assert abs(rates["2026-01"]["chb_rate"] - 0.005) < 0.000001

    def test_zero_sales_returns_none(self):
        table = {"2026-01": {"sales": 0.0, "refunds": 100, "chargebacks": 50}}
        rates = monthly_rates(table)
        assert rates["2026-01"]["refund_rate"] is None
        assert rates["2026-01"]["chb_rate"] is None

    def test_window_summary_picks_highest(self):
        table = {
            "2026-01": {"sales": 100_000, "refunds": 1_000, "chargebacks": 200},
            "2026-02": {"sales": 100_000, "refunds": 5_000, "chargebacks": 100},
            "2026-03": {"sales": 100_000, "refunds": 2_000, "chargebacks": 800},
        }
        summary = window_summary(table, ["2026-01", "2026-02", "2026-03"])
        assert summary["highest_refund_rate"] == pytest.approx(0.05, rel=1e-4)
        assert summary["highest_chb_rate"] == pytest.approx(0.008, rel=1e-4)
        assert summary["volume_90d"] == 300_000
