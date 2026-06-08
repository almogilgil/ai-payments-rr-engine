"""
calc.py — Deterministic Rolling Reserve exposure engine.
Ported from rr_tool.py, validated to the cent against Rosen and Live Suite.
"""

FLAT_AMOUNT_TABLE = [
    (75_000, 100_000, 10_000),
    (100_000, 500_000, 30_000),
    (500_000, 1_000_000, 60_000),
    (1_000_000, 2_000_000, 100_000),
]


def lookup_flat_amount(volume_90d: float) -> float:
    for lo, hi, flat in FLAT_AMOUNT_TABLE:
        if lo <= volume_90d < hi:
            return flat
    return 100_000  # above $2M: default to max, caller should log assumption


def rr_engine(volume_90d: float, highest_chb_rate: float,
              highest_refund_rate: float, flat_amount: float = 10_000) -> dict:
    """
    Compute Rolling Reserve exposure scenarios.

    Rates are rounded to 4 decimals (= 2 decimal-percent) to match
    the spreadsheet's ROUND(MAX(...),4). Skipping this rounding drifts
    every scenario by ~$100.
    """
    chb_rate = round(highest_chb_rate, 4) if highest_chb_rate else 0.0
    refund_rate = round(highest_refund_rate, 4) if highest_refund_rate else 0.0

    estimated_chb = volume_90d * chb_rate
    estimated_refund = volume_90d * refund_rate
    cnl = estimated_chb + estimated_refund

    def rr_scenario(rate):
        return volume_90d * rate * 3 - cnl

    exp_waiver_no_chb = (
        0.0 if refund_rate < 0.13 else (0.0 - estimated_refund)
    )

    return {
        "estimated_chb": round(estimated_chb, 2),
        "estimated_refund": round(estimated_refund, 2),
        "CNL": round(cnl, 2),
        "EXP": {
            "10%": round(rr_scenario(0.10)),
            "5%": round(rr_scenario(0.05)),
            "Flat": round(flat_amount - cnl),
            "Waiver_incl": round(0.0 - cnl),
            "Waiver_noCHB": round(exp_waiver_no_chb),
        },
    }


def monthly_rates(table: dict) -> dict:
    out = {}
    for m, d in table.items():
        sales = d.get("sales") or 0.0
        refunds = d.get("refunds")
        chb = d.get("chargebacks")
        refund_rate = (refunds / sales) if (sales and refunds is not None) else None
        chb_rate = (chb / sales) if (sales and chb is not None) else None
        out[m] = {
            "refund_rate": round(refund_rate, 6) if refund_rate is not None else None,
            "chb_rate": round(chb_rate, 6) if chb_rate is not None else None,
        }
    return out


def window_summary(table: dict, months: list) -> dict:
    rates = monthly_rates(table)
    volume_90d = sum((table[m].get("sales") or 0.0) for m in months if m in table)

    chb_rates = [rates[m]["chb_rate"] for m in months
                 if m in rates and rates[m]["chb_rate"] is not None]
    refund_rates = [rates[m]["refund_rate"] for m in months
                   if m in rates and rates[m]["refund_rate"] is not None]

    return {
        "volume_90d": round(volume_90d, 2),
        "highest_chb_rate": max(chb_rates) if chb_rates else 0.0,
        "highest_refund_rate": max(refund_rates) if refund_rates else 0.0,
    }
