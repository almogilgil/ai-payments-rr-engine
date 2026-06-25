"""
Stripe export extractor.
- De-duplicates by charge id across all payment files.
- Sales = Amount by charge created-date month (master file only by default).
- Refunds = Amount Refunded by CHARGE'S created-date month (not refunded date).
  This is the rule that matches the real Rosen sheet to the cent.
- Chargebacks require a separate Stripe Disputes export; else returns None + note.
"""
import csv
from collections import defaultdict
from datetime import datetime


def _month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _parse_date(s: str):
    if not s or not s.strip():
        return None
    return datetime.strptime(s.strip().split(" ")[0], "%Y-%m-%d")


def _to_float(s) -> float:
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "").replace("$", "")
    return float(s) if s and s.lower() not in ("null", "na", "nan", "") else 0.0


def extract_stripe(payment_paths: list[str], disputes_path: str = None,
                   sales_paths: list[str] = None) -> dict:
    if sales_paths is None:
        sales_paths = payment_paths[:1]
    sales_set = set(sales_paths)

    seen_ids = set()
    sales = defaultdict(float)
    refunds = defaultdict(float)

    for path in payment_paths:
        contributes_sales = path in sales_set
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cid = (row.get("id") or "").strip()
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)

                created = _parse_date(row.get("Created date (UTC)", ""))
                if contributes_sales and created is not None:
                    sales[_month_key(created)] += _to_float(row.get("Amount"))

                # Refunds bucketed by original charge's CREATED month (not refunded date)
                status = (row.get("Status") or "").strip().lower()
                refunded_amt = _to_float(row.get("Amount Refunded"))
                if refunded_amt > 0 and status != "paid" and created is not None:
                    refunds[_month_key(created)] += refunded_amt

    chargebacks = None
    chb_note = "requires Stripe Disputes export (chargebacks set to 0)"

    if disputes_path:
        chargebacks = defaultdict(float)
        with open(disputes_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                amt = _to_float(row.get("Amount") or row.get("Disputed Amount"))
                date_str = (row.get("Created date (UTC)") or
                            row.get("Disputed On") or row.get("Created"))
                dt = _parse_date(date_str or "")
                if dt is not None:
                    chargebacks[_month_key(dt)] += abs(amt)
        chb_note = "from Stripe Disputes export"

    months = sorted(set(sales) | set(refunds) |
                    (set(chargebacks) if chargebacks else set()))
    table = {}
    latest_date = None
    for path in payment_paths[:1]:
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                dt = _parse_date(row.get("Created date (UTC)", ""))
                if dt and (latest_date is None or dt > latest_date):
                    latest_date = dt
    for m in months:
        table[m] = {
            "sales": round(sales.get(m, 0.0), 2),
            "refunds": round(refunds.get(m, 0.0), 2),
            "chargebacks": round(chargebacks[m], 2) if chargebacks else 0.0,
        }
    return {"table": table, "chargebacks_note": chb_note, "latest_date": latest_date}
