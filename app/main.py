"""
main.py — FastAPI HTTP entrypoint for the Rolling Reserve Assessment Engine.
POST /assess: merchant identity + statement files → exposure results + workbook + ticket.
"""
import base64
import logging
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .models import AssessRequest
from .calc import rr_engine, window_summary, lookup_flat_amount
from .extract import dispatch
from .ticket import build_ticket
from .workbook import fill_workbook

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="RR Assessment Engine", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/assess")
def assess(req: AssessRequest):
    log.info("ticket_id=%s merchant=%s test_mode=%s",
             req.ticket_id, req.merchant.guesty_name, req.test_mode)

    # Decode statement files
    statements = []
    for s in req.statements:
        try:
            content = base64.b64decode(s.bytes_b64)
        except Exception as e:
            raise HTTPException(422, detail=f"Could not decode {s.filename}: {e}")
        statements.append({"filename": s.filename, "mime": s.mime, "content": content})

    # Extract monthly data
    try:
        # Pass ref_date=None so dispatch auto-detects it from the data's latest date
        extraction = dispatch(statements, test_mode=req.test_mode, ref_date=None)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    except Exception as e:
        log.exception("Extraction failed")
        raise HTTPException(500, detail=f"Extraction error: {e}")

    table = extraction["table"]
    window_months = extraction["window_months"]

    # Compute rates and summary
    summary = window_summary(table, window_months)
    volume_90d = summary["volume_90d"]
    highest_chb_rate = summary["highest_chb_rate"] or 0.0
    highest_refund_rate = summary["highest_refund_rate"] or 0.0

    # Flat amount
    flat_amount = req.flat_amount if req.flat_amount is not None else lookup_flat_amount(volume_90d)
    if volume_90d > 2_000_000 and req.flat_amount is None:
        log.warning("volume_90d=%.2f exceeds flat table; defaulting flat_amount=100000", volume_90d)

    # Engine
    engine = rr_engine(volume_90d, highest_chb_rate, highest_refund_rate, flat_amount)
    # Stash for workbook
    engine["_volume_90d"] = volume_90d
    engine["_highest_chb_rate"] = highest_chb_rate
    engine["_highest_refund_rate"] = highest_refund_rate

    exp = engine["EXP"]

    # Build month rows for ticket + response
    from .calc import monthly_rates
    rates = monthly_rates(table)
    month_rows = []
    for mk in window_months:
        d = table.get(mk, {"sales": 0.0, "refunds": 0.0, "chargebacks": 0.0})
        r = rates.get(mk, {})
        # Short label e.g. "Dec"
        try:
            label = datetime.strptime(mk, "%Y-%m").strftime("%b")
        except Exception:
            label = mk
        month_rows.append({
            "label": label,
            "sales": d["sales"],
            "refunds": d["refunds"],
            "chargebacks": d["chargebacks"],
            "chb_volume": d["chargebacks"],
            "refund_pct": r.get("refund_rate") or 0.0,
            "chb_rate": r.get("chb_rate") or 0.0,
        })

    # Ticket
    merchant_dict = req.merchant.model_dump()
    merchant_dict["zd_ticket"] = req.ticket_id
    ticket_md = build_ticket(merchant_dict, month_rows, engine, flat_amount)

    # QA table
    qa_lines = ["| Month | Sales (extracted) | Refunds (extracted) | Chargebacks (extracted) |",
                "|---|---|---|---|"]
    for mr in month_rows:
        qa_lines.append(
            f"| {mr['label']} | ${mr['sales']:,.2f} | ${mr['refunds']:,.2f} | ${mr['chargebacks']:,.2f} |"
        )
    # For AI-extracted statements, append per-figure confidence + source snippet
    # so the reviewer can verify each number against the document.
    if extraction["confidence"]:
        qa_lines.append("")
        qa_lines.append("| Month | Field | Confidence | Source snippet |")
        qa_lines.append("|---|---|---|---|")
        for c in extraction["confidence"]:
            snippet = str(c.get("snippet", "")).replace("|", "\\|").replace("\n", " ")
            qa_lines.append(
                f"| {c['month']} | {c['field']} | {c['score']:.2f} | {snippet} |"
            )
    qa_table = "\n".join(qa_lines)

    # Workbook
    wb_bytes = fill_workbook(
        merchant_dict,
        [{"label": mk, "sales": table[mk]["sales"], "refunds": table[mk]["refunds"],
          "chargebacks": table[mk]["chargebacks"]} for mk in window_months],
        engine, flat_amount, window_months,
    )
    wb_b64 = base64.b64encode(wb_bytes).decode() if wb_bytes else ""

    # Build response months list (API contract)
    resp_months = [
        {
            "label": mr["label"],
            "sales": mr["sales"],
            "refunds": mr["refunds"],
            "chargebacks": mr["chargebacks"],
            "refund_pct": round(mr["refund_pct"], 6),
            "chb_rate": round(mr["chb_rate"], 6),
        }
        for mr in month_rows
    ]

    log.info("ticket_id=%s source=%s volume=%.2f exp10=%d",
             req.ticket_id, extraction["source_type"], volume_90d, exp["10%"])

    return {
        "months": resp_months,
        "volume_90d": volume_90d,
        "highest_chb_rate": highest_chb_rate,
        "highest_refund_rate": highest_refund_rate,
        "flat_amount": flat_amount,
        "exposure": exp,
        "ticket_markdown": ticket_md,
        "qa_table_markdown": qa_table,
        "filled_workbook_b64": wb_b64,
        "extraction": {
            "source_type": extraction["source_type"],
            "needs_review": extraction["needs_review"],
            "confidence": extraction["confidence"],
            "chargebacks_note": extraction.get("chargebacks_note", ""),
        },
    }
