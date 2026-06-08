"""
GuestyPay dashboard CSV extractor.
Columns: transactionType, amount_usd, systemDate
All statuses included.
"""
import csv
from collections import defaultdict
from datetime import datetime


def _month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%b %d, %Y")


def _to_float(s) -> float:
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "").replace("$", "")
    return float(s) if s and s.lower() not in ("null", "na", "nan", "") else 0.0


def extract_guestypay(path: str) -> dict:
    table = defaultdict(lambda: {"sales": 0.0, "refunds": 0.0, "chargebacks": 0.0})
    latest_date = None
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ttype = (row.get("transactionType") or "").strip()
            dt = _parse_date(row["systemDate"])
            if latest_date is None or dt > latest_date:
                latest_date = dt
            month = _month_key(dt)
            amt = _to_float(row.get("amount_usd"))
            if ttype == "Charge":
                table[month]["sales"] += amt
            elif ttype in ("Refund", "Partial Refund"):
                table[month]["refunds"] += abs(amt)
            elif ttype == "Chargeback":
                table[month]["chargebacks"] += abs(amt)
    result = {m: {k: round(v, 2) for k, v in d.items()}
              for m, d in sorted(table.items())}
    return {"table": result, "latest_date": latest_date}
