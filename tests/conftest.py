"""
conftest.py — shared pytest fixtures for the RR Engine test suite.
"""
import base64
import csv
import io
import os
import sys

import pytest

# Make sure `app` is importable regardless of where pytest is run from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CRIBS_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "Rolling Reserve Assesment", "guestypay_cribs.csv"
)


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Synthetic CSV builders
# ---------------------------------------------------------------------------

def make_guestypay_csv(rows: list[dict]) -> bytes:
    """Build a minimal GuestyPay CSV in memory."""
    fieldnames = ["account_name", "transactionId", "transactionType",
                  "amount", "amount_usd", "currency", "status",
                  "systemDate", "merchantDate",
                  "CHBOrRetrievalReasonCode", "CHBOrRetrievalReasonDescription",
                  "subAccount"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {f: "" for f in fieldnames}
        row.update(r)
        w.writerow(row)
    return buf.getvalue().encode()


def make_stripe_payments_csv(rows: list[dict]) -> bytes:
    """Build a minimal Stripe payments CSV in memory."""
    fieldnames = ["id", "Amount", "Amount Refunded", "Created date (UTC)",
                  "Refunded date (UTC)", "Status", "Customer Email"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {f: "" for f in fieldnames}
        row.update(r)
        w.writerow(row)
    return buf.getvalue().encode()


def make_stripe_disputes_csv(rows: list[dict]) -> bytes:
    """Build a minimal Stripe disputes CSV in memory."""
    fieldnames = ["id", "Amount", "Created date (UTC)", "Status", "Reason"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {f: "" for f in fieldnames}
        row.update(r)
        w.writerow(row)
    return buf.getvalue().encode()


def b64(content: bytes) -> str:
    return base64.b64encode(content).decode()


# ---------------------------------------------------------------------------
# Shared merchant payload
# ---------------------------------------------------------------------------

BASE_MERCHANT = {
    "guesty_id": "test-id-001",
    "guesty_name": "Test Merchant",
    "guestypay": "N/A",
    "region": "USA",
    "bank": "Stripe",
    "segment": "SME",
    "avg_mrr": "10000$",
    "active_listings": "10",
    "requested_change": "waive",
}
