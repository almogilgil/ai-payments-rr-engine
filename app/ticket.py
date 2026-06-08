"""
ticket.py — Build the Reserve-Escalation ticket markdown.
Ported from rr_tool.py build_ticket(). Output matches Luba's Live Suite ticket exactly.
"""

_RR_ROW_COLOURS = {
    "10%": "GREEN",
    "5%": "Orange",
    "Flat": "GREEN",
    "Waiver_incl": "RED",
    "Waiver_noCHB": "GREEN",
}


def _money(v: float) -> str:
    v = round(v)
    return ("-$%s" % f"{abs(v):,}") if v < 0 else ("$%s" % f"{v:,}")


def _money2(v: float) -> str:
    return ("-$%s" % f"{abs(v):,.2f}") if v < 0 else ("$%s" % f"{v:,.2f}")


def _flat_label(flat_amount: float) -> str:
    return f"{int(round(flat_amount / 1000))}K$"


def build_ticket(header: dict, months: list[dict], engine: dict,
                 flat_amount: float = 10_000) -> str:
    """
    header: merchant fields (guesty_id, guesty_name, guestypay, zd_ticket,
            region, bank, segment, avg_mrr, active_listings, looker_link,
            requested_change)
    months: [{"label": str, "sales": float, "chb_volume": float, "refund_pct": float}]
    engine: output of calc.rr_engine()
    """
    h = lambda k: header.get(k, "")
    L = []
    L.append("Reserve Escalation")
    L.append("")
    for label, key in [
        ("Guesty ID", "guesty_id"),
        ("Guesty Name", "guesty_name"),
        ("GuestyPay", "guestypay"),
        ("ZD ticket", "zd_ticket"),
        ("Region", "region"),
        ("Bank", "bank"),
        ("Segment", "segment"),
        ("Avg. MRR", "avg_mrr"),
        ("Active Listings", "active_listings"),
    ]:
        L.append(f"- {label}: {h(key)}")
    L.append("")
    if h("looker_link"):
        L.append(h("looker_link"))
        L.append("")
    L.append(f"Requested reserve change: {h('requested_change')}")
    L.append("Your recommendation: ")
    L.append("")

    # Monthly table
    mlabels = [m["label"] for m in months]
    L.append("| Month | " + " | ".join(mlabels) + " |")
    L.append("|" + "---|" * (len(mlabels) + 1))
    L.append("| Sales Volume $ | " +
             " | ".join(_money2(m["sales"]) for m in months) + " |")
    L.append("| Chargeback Volume $ | " +
             " | ".join(_money2(m["chb_volume"]) for m in months) + " |")
    L.append("| Chargeback Rate % $ | " +
             " | ".join(
                 f"{(m['chb_volume'] / m['sales'] * 100):.2f}%"
                 if m["sales"] else "n/a"
                 for m in months
             ) + " |")
    L.append("| Refund %$ | " +
             " | ".join(f"{m['refund_pct'] * 100:.2f}%" for m in months) + " |")
    L.append("")

    # Options table
    exp = engine["EXP"]
    L.append("| | RR Options | Days option | Exposure$ |")
    L.append("|---|---|---|---|")
    L.append(f"| {_RR_ROW_COLOURS['10%']} | 10% | 90 | {_money(exp['10%'])} |")
    L.append(f"| {_RR_ROW_COLOURS['5%']} | 5% | 90 | {_money(exp['5%'])} |")
    L.append(f"| {_RR_ROW_COLOURS['Flat']} | FLAT $ | {_flat_label(flat_amount)} | {_money(exp['Flat'])} |")
    L.append(f"| {_RR_ROW_COLOURS['Waiver_incl']} | Waiver$ Including CHBS+rfu |  | {_money(exp['Waiver_incl'])} |")
    L.append(f"| {_RR_ROW_COLOURS['Waiver_noCHB']} | Waiver$ No CHBS ,RFU under 13 % |  | {_money(exp['Waiver_noCHB'])} |")
    # Projected Exposure formula is unconfirmed — intentionally left blank
    L.append("| Projected Exposure from Prossesing Volume |  | 30 |  |")
    L.append("| Recommended |  |  |  |")
    return "\n".join(L)
