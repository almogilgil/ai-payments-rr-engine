"""
extract/ — Source detection and dispatch to normalized monthly table.
Returns: {"table": {month: {sales, refunds, chargebacks}}, "source_type": str,
          "confidence": [...], "needs_review": bool, "chargebacks_note": str}
"""
import base64
import io
import os
import tempfile
from datetime import datetime, timedelta

from .guestypay import extract_guestypay
from .stripe import extract_stripe
from .pdf_ai import extract_pdf_ai

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))


def _is_guestypay(content: bytes, filename: str) -> bool:
    try:
        text = content.decode("utf-8", errors="ignore")
        return "transactionType" in text and "amount_usd" in text
    except Exception:
        return False


def _is_stripe(content: bytes, filename: str) -> bool:
    try:
        text = content.decode("utf-8", errors="ignore")
        return ("Created date (UTC)" in text and
                ("Amount Refunded" in text or "ch_" in text))
    except Exception:
        return False


def _is_stripe_disputes(content: bytes, filename: str) -> bool:
    try:
        text = content.decode("utf-8", errors="ignore")
        return ("Disputed" in text or "dispute" in filename.lower()) and "Amount" in text
    except Exception:
        return False


def _trailing_months(ref_date: datetime, n_months: int = 3) -> list[str]:
    """Return list of 'YYYY-MM' for the n calendar months ending with ref_date's month."""
    months = []
    year, month = ref_date.year, ref_date.month
    for _ in range(n_months):
        months.insert(0, f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return months


def dispatch(statements: list[dict], test_mode: bool = False, ref_date: datetime = None) -> dict:
    """
    statements: [{"filename": str, "content": bytes}]
    Returns normalized dict ready for calc.py.
    """
    # Categorize files
    guestypay_files = []
    stripe_payment_files = []
    stripe_dispute_files = []
    pdf_files = []

    for s in statements:
        fname = s["filename"].lower()
        content = s["content"]
        mime = s.get("mime", "")

        if fname.endswith(".pdf") or mime == "application/pdf":
            pdf_files.append(s)
        elif fname.endswith(".csv") or "csv" in mime:
            if _is_guestypay(content, fname):
                guestypay_files.append(s)
            elif _is_stripe_disputes(content, fname):
                stripe_dispute_files.append(s)
            elif _is_stripe(content, fname):
                stripe_payment_files.append(s)
            else:
                pdf_files.append(s)  # fallback: try AI extraction
        else:
            pdf_files.append(s)

    confidence = []
    needs_review = test_mode
    chargebacks_note = ""

    with tempfile.TemporaryDirectory() as tmpdir:
        data_latest_date = None

        if guestypay_files:
            # Write to temp file and extract
            path = os.path.join(tmpdir, "guestypay.csv")
            with open(path, "wb") as f:
                f.write(guestypay_files[0]["content"])
            result = extract_guestypay(path)
            table = result["table"]
            data_latest_date = result.get("latest_date")
            source_type = "guestypay"
            # CSV extraction is deterministic: confidence 1.0
        elif stripe_payment_files:
            payment_paths = []
            for i, s in enumerate(stripe_payment_files):
                p = os.path.join(tmpdir, f"stripe_payments_{i}.csv")
                with open(p, "wb") as f:
                    f.write(s["content"])
                payment_paths.append(p)

            disputes_path = None
            if stripe_dispute_files:
                disputes_path = os.path.join(tmpdir, "stripe_disputes.csv")
                with open(disputes_path, "wb") as f:
                    f.write(stripe_dispute_files[0]["content"])

            result = extract_stripe(payment_paths, disputes_path=disputes_path)
            table = result["table"]
            chargebacks_note = result["chargebacks_note"]
            data_latest_date = result.get("latest_date")
            source_type = "stripe"
            if not stripe_dispute_files:
                needs_review = True
        elif pdf_files:
            # AI extraction for PDF/screenshots
            result = extract_pdf_ai(pdf_files)
            table = result["table"]
            confidence = result.get("confidence", [])
            source_type = "pdf_ai"
            if not table:
                raise ValueError(
                    "AI extraction found no monthly figures in the PDF statement(s); "
                    "refusing to return zeros. Submit a clearer statement or use a CSV export."
                )
            if any(c["score"] < CONFIDENCE_THRESHOLD for c in confidence):
                needs_review = True
        else:
            raise ValueError("No recognizable statement files provided")

    if source_type == "pdf_ai":
        # A statement's period IS the window: use the extracted months themselves
        # (latest 3). Anchoring to today's date would zero out historical
        # statements — e.g. an Oct 2024 statement assessed in June 2026.
        window_months = sorted(table.keys())[-3:]
    else:
        # Use data's latest date as ref if no explicit ref_date provided
        effective_ref = ref_date or data_latest_date or datetime.utcnow()
        window_months = _trailing_months(effective_ref, 3)

    # Filter table to window months only
    filtered = {m: table.get(m, {"sales": 0.0, "refunds": 0.0, "chargebacks": 0.0})
                for m in window_months}

    # volume_90d = sum of sales in window
    volume_90d = sum(filtered[m]["sales"] for m in window_months)

    return {
        "table": filtered,
        "window_months": window_months,
        "volume_90d": round(volume_90d, 2),
        "source_type": source_type,
        "needs_review": needs_review,
        "confidence": confidence,
        "chargebacks_note": chargebacks_note,
    }
