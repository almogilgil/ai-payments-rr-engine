"""
test_extract_pdf.py — PDF/AI extraction path tests (Gemini mocked, runs offline).

Locks in the fix for the all-zeros bug: a historical statement (e.g. Oct 2024)
must keep ITS months as the window — not today's trailing quarter, which
previously zeroed out every extracted figure.

Ground truth from the real LynnBrook test case (Lynnbook 2.pdf, D SANDS RENTALS):
  Processing Month 10-24 → sales 123,134.85 / refunds 5,268.39 / chargebacks 95.57
"""
import pytest

import app.extract as extract_mod
from app.extract import dispatch
from app.extract.pdf_ai import _normalize_label
from conftest import b64, BASE_MERCHANT

FAKE_PDF = {"filename": "Lynnbook 2.pdf", "mime": "application/pdf",
            "content": b"%PDF-1.4 fake"}

LYNNBROOK_RESULT = {
    "table": {
        "2024-10": {"sales": 123_134.85, "refunds": 5_268.39, "chargebacks": 95.57},
    },
    "confidence": [
        {"field": "sales", "month": "2024-10", "score": 1.0,
         "snippet": "** 434 123,134.85 Amount of Sales"},
        {"field": "refunds", "month": "2024-10", "score": 1.0,
         "snippet": "45 5,268.39 Amount of Credits"},
        {"field": "chargebacks", "month": "2024-10", "score": 0.9,
         "snippet": "Chargeback Totals 01 95.57"},
    ],
}


@pytest.fixture
def mock_pdf_ai(monkeypatch):
    """Patch the AI extractor inside dispatch with a canned LynnBrook result."""
    def fake(files):
        return {k: (dict(v) if isinstance(v, dict) else list(v))
                for k, v in LYNNBROOK_RESULT.items()}
    monkeypatch.setattr(extract_mod, "extract_pdf_ai", fake)
    return fake


# ---------------------------------------------------------------------------
# THE regression: historical statement months must survive the window filter
# ---------------------------------------------------------------------------

class TestHistoricalStatementWindow:

    def test_window_is_statement_period_not_today(self, mock_pdf_ai):
        result = dispatch([FAKE_PDF])
        assert result["window_months"] == ["2024-10"]

    def test_figures_not_zeroed(self, mock_pdf_ai):
        result = dispatch([FAKE_PDF])
        month = result["table"]["2024-10"]
        assert month["sales"] == pytest.approx(123_134.85)
        assert month["refunds"] == pytest.approx(5_268.39)
        assert month["chargebacks"] == pytest.approx(95.57)

    def test_volume_90d_from_statement(self, mock_pdf_ai):
        result = dispatch([FAKE_PDF])
        assert result["volume_90d"] == pytest.approx(123_134.85)

    def test_source_type(self, mock_pdf_ai):
        assert dispatch([FAKE_PDF])["source_type"] == "pdf_ai"

    def test_confidence_passthrough(self, mock_pdf_ai):
        result = dispatch([FAKE_PDF])
        assert len(result["confidence"]) == 3
        assert result["confidence"][0]["snippet"]

    def test_high_confidence_no_review_flag(self, mock_pdf_ai):
        # All scores >= 0.85 threshold → no review needed (unless test_mode)
        assert dispatch([FAKE_PDF])["needs_review"] is False

    def test_low_confidence_flags_review(self, monkeypatch):
        low = {
            "table": {"2024-10": {"sales": 100.0, "refunds": 0.0, "chargebacks": 0.0}},
            "confidence": [{"field": "sales", "month": "2024-10", "score": 0.4,
                            "snippet": "blurry"}],
        }
        monkeypatch.setattr(extract_mod, "extract_pdf_ai", lambda files: low)
        assert dispatch([FAKE_PDF])["needs_review"] is True

    def test_multi_month_keeps_latest_three(self, monkeypatch):
        multi = {
            "table": {
                "2024-08": {"sales": 1.0, "refunds": 0.0, "chargebacks": 0.0},
                "2024-09": {"sales": 2.0, "refunds": 0.0, "chargebacks": 0.0},
                "2024-10": {"sales": 3.0, "refunds": 0.0, "chargebacks": 0.0},
                "2024-07": {"sales": 9.0, "refunds": 0.0, "chargebacks": 0.0},
            },
            "confidence": [],
        }
        monkeypatch.setattr(extract_mod, "extract_pdf_ai", lambda files: multi)
        result = dispatch([FAKE_PDF])
        assert result["window_months"] == ["2024-08", "2024-09", "2024-10"]
        assert result["volume_90d"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Never 200-with-zeros: empty extraction must raise (→ 422 at the API layer)
# ---------------------------------------------------------------------------

def test_empty_extraction_raises(monkeypatch):
    monkeypatch.setattr(extract_mod, "extract_pdf_ai",
                        lambda files: {"table": {}, "confidence": []})
    with pytest.raises(ValueError, match="no monthly figures"):
        dispatch([FAKE_PDF])


# ---------------------------------------------------------------------------
# Month label normalization (Gemini output hygiene)
# ---------------------------------------------------------------------------

class TestNormalizeLabel:

    @pytest.mark.parametrize("raw,expected", [
        ("2024-10", "2024-10"),
        ("10-24", "2024-10"),
        ("10/24", "2024-10"),
        ("October 2024", "2024-10"),
        ("Oct 2024", "2024-10"),
        ("10/2024", "2024-10"),
    ])
    def test_valid_formats(self, raw, expected):
        assert _normalize_label(raw) == expected

    @pytest.mark.parametrize("raw", ["", "garbage", "month ten", "2024"])
    def test_unparseable_returns_empty(self, raw):
        assert _normalize_label(raw) == ""


# ---------------------------------------------------------------------------
# Full API path with mocked extractor
# ---------------------------------------------------------------------------

class TestAssessPdfEndToEnd:

    @pytest.fixture
    def response(self, client, mock_pdf_ai):
        payload = {
            "ticket_id": "PDF-001",
            "test_mode": False,
            "merchant": {**BASE_MERCHANT, "bank": "LynnBrook", "guestypay": "N/A"},
            "statements": [
                {"filename": "Lynnbook 2.pdf", "mime": "application/pdf",
                 "bytes_b64": b64(b"%PDF-1.4 fake")}
            ],
            "flat_amount": None,
        }
        return client.post("/assess", json=payload)

    def test_status_200(self, response):
        assert response.status_code == 200

    def test_single_october_month(self, response):
        months = response.json()["months"]
        assert len(months) == 1
        assert months[0]["label"] == "Oct"
        assert months[0]["sales"] == pytest.approx(123_134.85)
        assert months[0]["refunds"] == pytest.approx(5_268.39)
        assert months[0]["chargebacks"] == pytest.approx(95.57)

    def test_volume_and_flat(self, response):
        data = response.json()
        assert data["volume_90d"] == pytest.approx(123_134.85)
        assert data["flat_amount"] == 30_000  # 100K–500K band

    def test_exposure_nonzero(self, response):
        exp = response.json()["exposure"]
        assert exp["10%"] != 0
        assert exp["Waiver_incl"] < 0

    def test_qa_table_has_confidence_section(self, response):
        qa = response.json()["qa_table_markdown"]
        assert "Confidence" in qa
        assert "Amount of Sales" in qa  # snippet surfaced for the reviewer

    def test_empty_extraction_returns_422(self, client, monkeypatch):
        monkeypatch.setattr(extract_mod, "extract_pdf_ai",
                            lambda files: {"table": {}, "confidence": []})
        payload = {
            "ticket_id": "PDF-002",
            "test_mode": False,
            "merchant": BASE_MERCHANT,
            "statements": [
                {"filename": "blank.pdf", "mime": "application/pdf",
                 "bytes_b64": b64(b"%PDF-1.4 fake")}
            ],
            "flat_amount": None,
        }
        r = client.post("/assess", json=payload)
        assert r.status_code == 422
