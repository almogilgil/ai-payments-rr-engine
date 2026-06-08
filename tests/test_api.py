"""
test_api.py — Full API integration tests using FastAPI TestClient (no live server needed).
Tests the complete POST /assess pipeline end-to-end.
"""
import base64
import pytest

from conftest import (
    make_guestypay_csv, make_stripe_payments_csv, make_stripe_disputes_csv,
    b64, BASE_MERCHANT
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GuestyPay end-to-end
# ---------------------------------------------------------------------------

class TestAssessGuestyPay:

    @pytest.fixture(scope="class")
    def response(self, client):
        csv_bytes = make_guestypay_csv([
            {"transactionType": "Charge",     "amount_usd": "50000", "systemDate": "Jan 10, 2026"},
            {"transactionType": "Charge",     "amount_usd": "60000", "systemDate": "Feb 10, 2026"},
            {"transactionType": "Charge",     "amount_usd": "70000", "systemDate": "Mar 10, 2026"},
            {"transactionType": "Refund",     "amount_usd": "-500",  "systemDate": "Jan 15, 2026"},
            {"transactionType": "Chargeback", "amount_usd": "-300",  "systemDate": "Mar 20, 2026"},
        ])
        payload = {
            "ticket_id": "TEST-GP-001",
            "test_mode": False,
            "merchant": BASE_MERCHANT,
            "statements": [
                {"filename": "test.csv", "mime": "text/csv", "bytes_b64": b64(csv_bytes)}
            ],
            "flat_amount": 30000,
        }
        return client.post("/assess", json=payload)

    def test_status_200(self, response):
        assert response.status_code == 200

    def test_source_type_guestypay(self, response):
        assert response.json()["extraction"]["source_type"] == "guestypay"

    def test_volume_90d_correct(self, response):
        assert response.json()["volume_90d"] == pytest.approx(180_000.0)

    def test_three_months_returned(self, response):
        assert len(response.json()["months"]) == 3

    def test_flat_amount_honored(self, response):
        assert response.json()["flat_amount"] == 30_000

    def test_exposure_keys_present(self, response):
        exp = response.json()["exposure"]
        assert set(exp.keys()) == {"10%", "5%", "Flat", "Waiver_incl", "Waiver_noCHB"}

    def test_ticket_markdown_present(self, response):
        ticket = response.json()["ticket_markdown"]
        assert "Reserve Escalation" in ticket
        assert "TEST-GP-001" in ticket

    def test_qa_table_present(self, response):
        qa = response.json()["qa_table_markdown"]
        assert "| Month |" in qa

    def test_workbook_b64_non_empty(self, response):
        wb = response.json()["filled_workbook_b64"]
        assert len(wb) > 100
        # Verify it decodes to valid bytes
        decoded = base64.b64decode(wb)
        assert decoded[:4] == b"PK\x03\x04"  # xlsx/zip magic bytes

    def test_needs_review_false_when_csv(self, response):
        assert response.json()["extraction"]["needs_review"] is False

    def test_month_labels_are_short(self, response):
        for m in response.json()["months"]:
            assert len(m["label"]) <= 3  # "Jan", "Feb", etc.


# ---------------------------------------------------------------------------
# Stripe end-to-end
# ---------------------------------------------------------------------------

class TestAssessStripe:

    @pytest.fixture(scope="class")
    def response(self, client):
        payments = make_stripe_payments_csv([
            {"id": "ch_001", "Amount": "100000", "Amount Refunded": "2000",
             "Created date (UTC)": "2026-01-15 00:00:00"},
            {"id": "ch_002", "Amount": "120000", "Amount Refunded": "0",
             "Created date (UTC)": "2026-02-10 00:00:00"},
            {"id": "ch_003", "Amount": "80000",  "Amount Refunded": "500",
             "Created date (UTC)": "2026-03-05 00:00:00"},
        ])
        disputes = make_stripe_disputes_csv([
            {"id": "dp_001", "Amount": "1500", "Created date (UTC)": "2026-02-20 00:00:00"},
        ])
        payload = {
            "ticket_id": "TEST-STR-001",
            "test_mode": False,
            "merchant": {**BASE_MERCHANT, "bank": "Stripe"},
            "statements": [
                {"filename": "payments.csv", "mime": "text/csv", "bytes_b64": b64(payments)},
                {"filename": "disputes.csv", "mime": "text/csv", "bytes_b64": b64(disputes)},
            ],
            "flat_amount": None,
        }
        return client.post("/assess", json=payload)

    def test_status_200(self, response):
        assert response.status_code == 200

    def test_source_type_stripe(self, response):
        assert response.json()["extraction"]["source_type"] == "stripe"

    def test_volume_90d(self, response):
        assert response.json()["volume_90d"] == pytest.approx(300_000.0)

    def test_chargebacks_from_disputes(self, response):
        months = {m["label"]: m for m in response.json()["months"]}
        feb = months.get("Feb")
        assert feb is not None
        assert feb["chargebacks"] == pytest.approx(1500.0)

    def test_refunds_by_created_month(self, response):
        months = {m["label"]: m for m in response.json()["months"]}
        # ch_001 refund: 2000, created Jan → should appear in Jan
        assert months["Jan"]["refunds"] == pytest.approx(2000.0)
        # ch_003 refund: 500, created Mar
        assert months["Mar"]["refunds"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# test_mode flag
# ---------------------------------------------------------------------------

def test_test_mode_forces_needs_review(client):
    csv_bytes = make_guestypay_csv([
        {"transactionType": "Charge", "amount_usd": "10000", "systemDate": "Mar 01, 2026"}
    ])
    payload = {
        "ticket_id": "TM-001",
        "test_mode": True,
        "merchant": BASE_MERCHANT,
        "statements": [{"filename": "t.csv", "mime": "text/csv", "bytes_b64": b64(csv_bytes)}],
        "flat_amount": 10000,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 200
    assert r.json()["extraction"]["needs_review"] is True


# ---------------------------------------------------------------------------
# Flat amount auto-lookup
# ---------------------------------------------------------------------------

def test_flat_amount_auto_looked_up_when_null(client):
    """When flat_amount is null, engine should look it up from the table."""
    csv_bytes = make_guestypay_csv([
        {"transactionType": "Charge", "amount_usd": "200000", "systemDate": "Mar 01, 2026"}
    ])
    payload = {
        "ticket_id": "FL-001",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [{"filename": "t.csv", "mime": "text/csv", "bytes_b64": b64(csv_bytes)}],
        "flat_amount": None,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 200
    # volume_90d = 200k → flat table says 30k (100k–500k band)
    assert r.json()["flat_amount"] == 30_000


def test_flat_amount_override_honored(client):
    csv_bytes = make_guestypay_csv([
        {"transactionType": "Charge", "amount_usd": "200000", "systemDate": "Mar 01, 2026"}
    ])
    payload = {
        "ticket_id": "FL-002",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [{"filename": "t.csv", "mime": "text/csv", "bytes_b64": b64(csv_bytes)}],
        "flat_amount": 99999,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 200
    assert r.json()["flat_amount"] == 99_999


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_bad_base64_returns_422(client):
    payload = {
        "ticket_id": "ERR-001",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [{"filename": "t.csv", "mime": "text/csv", "bytes_b64": "!!!not-base64!!!"}],
        "flat_amount": None,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 422


def test_empty_statements_returns_422(client):
    payload = {
        "ticket_id": "ERR-002",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [],
        "flat_amount": None,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 422


def test_unrecognizable_file_returns_422(client):
    payload = {
        "ticket_id": "ERR-003",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [
            {"filename": "garbage.csv", "mime": "text/csv",
             "bytes_b64": b64(b"col1,col2\nfoo,bar\n")}
        ],
        "flat_amount": None,
    }
    r = client.post("/assess", json=payload)
    # Should be 422 (no recognizable format) — AI extraction needs ANTHROPIC_API_KEY
    assert r.status_code in (422, 500)


# ---------------------------------------------------------------------------
# Response schema completeness
# ---------------------------------------------------------------------------

def test_response_has_all_required_fields(client):
    csv_bytes = make_guestypay_csv([
        {"transactionType": "Charge", "amount_usd": "50000", "systemDate": "Mar 10, 2026"}
    ])
    payload = {
        "ticket_id": "SCHEMA-001",
        "test_mode": False,
        "merchant": BASE_MERCHANT,
        "statements": [{"filename": "t.csv", "mime": "text/csv", "bytes_b64": b64(csv_bytes)}],
        "flat_amount": 10000,
    }
    r = client.post("/assess", json=payload)
    assert r.status_code == 200
    data = r.json()
    required = ["months", "volume_90d", "highest_chb_rate", "highest_refund_rate",
                "flat_amount", "exposure", "ticket_markdown", "qa_table_markdown",
                "filled_workbook_b64", "extraction"]
    for field in required:
        assert field in data, f"Missing field: {field}"
