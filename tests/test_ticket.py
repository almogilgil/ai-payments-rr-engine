"""
test_ticket.py — Ticket markdown rendering tests.
Validates that build_ticket() produces the expected structure and values.
"""
import pytest
from app.ticket import build_ticket


SAMPLE_HEADER = {
    "guesty_id": "abc123",
    "guesty_name": "Rosen Vacations",
    "guestypay": "3090.1 - Cribs",
    "zd_ticket": "ZD-9999",
    "region": "USA",
    "bank": "Stripe",
    "segment": "SME",
    "avg_mrr": "12087$",
    "active_listings": "220",
    "requested_change": "waive",
}

SAMPLE_MONTHS = [
    {"label": "Dec", "sales": 790_419.13, "chb_volume": 2_177.68, "refund_pct": 0.0136},
    {"label": "Jan", "sales": 836_029.33, "chb_volume": 2_252.58, "refund_pct": 0.0353},
    {"label": "Feb", "sales": 722_955.66, "chb_volume": 2_800.60, "refund_pct": 0.0024},
]

ROSEN_ENGINE = {
    "EXP": {
        "10%": 613_843,
        "5%": 260_789,
        "Flat": -82_265,
        "Waiver_incl": -92_265,
        "Waiver_noCHB": 0,
    }
}


@pytest.fixture(scope="module")
def ticket():
    return build_ticket(SAMPLE_HEADER, SAMPLE_MONTHS, ROSEN_ENGINE, flat_amount=10_000)


class TestTicketStructure:

    def test_starts_with_reserve_escalation(self, ticket):
        assert ticket.startswith("Reserve Escalation")

    def test_contains_guesty_id(self, ticket):
        assert "abc123" in ticket

    def test_contains_guesty_name(self, ticket):
        assert "Rosen Vacations" in ticket

    def test_contains_zd_ticket(self, ticket):
        assert "ZD-9999" in ticket

    def test_contains_requested_change(self, ticket):
        assert "waive" in ticket

    def test_recommendation_row_blank(self, ticket):
        assert "Your recommendation: " in ticket

    def test_contains_all_month_labels(self, ticket):
        for m in ["Dec", "Jan", "Feb"]:
            assert m in ticket

    def test_contains_sales_header(self, ticket):
        assert "Sales Volume $" in ticket

    def test_contains_chargeback_rate(self, ticket):
        assert "Chargeback Rate" in ticket


class TestTicketExposureTable:

    def test_10pct_row_present(self, ticket):
        assert "10%" in ticket

    def test_5pct_row_present(self, ticket):
        assert "5%" in ticket

    def test_flat_label_uses_k(self, ticket):
        # flat_amount=10000 → "10K$"
        assert "10K$" in ticket

    def test_waiver_incl_row_present(self, ticket):
        assert "Waiver" in ticket and "CHBS" in ticket

    def test_waiver_no_chb_row_present(self, ticket):
        assert "13 %" in ticket or "13%" in ticket

    def test_projected_exposure_blank(self, ticket):
        """Projected Exposure 30d must be present but value must be blank."""
        assert "Projected Exposure" in ticket
        lines = ticket.split("\n")
        proj_line = next(l for l in lines if "Projected Exposure" in l)
        # The value cell should be empty (two consecutive | |)
        assert proj_line.endswith("|  |")

    def test_recommended_row_blank(self, ticket):
        lines = ticket.split("\n")
        rec_line = next(l for l in lines if "Recommended" in l and "| Recommended |" in l)
        assert rec_line.endswith("|  |")


class TestTicketColours:

    def test_10pct_colour_green(self, ticket):
        lines = ticket.split("\n")
        line = next(l for l in lines if "| 10%" in l)
        assert "GREEN" in line

    def test_5pct_colour_orange(self, ticket):
        lines = ticket.split("\n")
        line = next(l for l in lines if "| 5%" in l)
        assert "Orange" in line

    def test_flat_colour_green(self, ticket):
        lines = ticket.split("\n")
        line = next(l for l in lines if "FLAT $" in l)
        assert "GREEN" in line

    def test_waiver_incl_colour_red(self, ticket):
        lines = ticket.split("\n")
        line = next(l for l in lines if "Including CHBS" in l)
        assert "RED" in line

    def test_waiver_no_chb_colour_green(self, ticket):
        lines = ticket.split("\n")
        line = next(l for l in lines if "under 13" in l)
        assert "GREEN" in line


class TestTicketMoneyFormatting:

    def test_positive_exposure_no_minus(self, ticket):
        # 10% exposure is $613,843 — must be positive
        assert "$613,843" in ticket

    def test_negative_exposure_has_minus(self, ticket):
        # Flat is -$82,265
        assert "-$82,265" in ticket

    def test_sales_formatted_with_cents(self, ticket):
        assert "$790,419.13" in ticket
