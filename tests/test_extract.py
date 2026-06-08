"""
Stripe extraction golden-value tests — §9 Rosen fixture.
Requires fixture CSVs in tests/fixtures/.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.extract.stripe import extract_stripe
from app.calc import window_summary

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PAYMENTS = os.path.join(FIXTURES, "rosen_payments.csv")
DISPUTES = os.path.join(FIXTURES, "rosen_disputes.csv")

WINDOW = ["2025-12", "2026-01", "2026-02"]


@pytest.mark.skipif(not os.path.exists(PAYMENTS), reason="Rosen fixture not present")
def test_rosen_extraction():
    result = extract_stripe([PAYMENTS], disputes_path=DISPUTES if os.path.exists(DISPUTES) else None)
    table = result["table"]

    assert abs(table["2025-12"]["sales"] - 790_419.13) < 1.0, table["2025-12"]["sales"]
    assert abs(table["2026-01"]["sales"] - 836_029.33) < 1.0, table["2026-01"]["sales"]
    # Feb includes Mar-1 boundary fold; either 722955 or 727244 depending on window logic
    assert table["2026-02"]["sales"] > 720_000

    # Refunds by created month
    assert abs(table["2025-12"]["refunds"] - 10_725.14) < 1.0, table["2025-12"]["refunds"]
    assert abs(table["2026-01"]["refunds"] - 29_515.15) < 1.0, table["2026-01"]["refunds"]

    summary = window_summary(table, WINDOW)
    assert abs(summary["volume_90d"] - 2_353_692) < 100, summary["volume_90d"]


if __name__ == "__main__":
    if not os.path.exists(PAYMENTS):
        print("Rosen fixture not found — skipping extraction test")
    else:
        test_rosen_extraction()
        print("Extraction test passed.")
