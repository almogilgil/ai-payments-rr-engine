# RR Assessment Engine

Stateless HTTP service that turns a merchant's payment statements into rolling-reserve exposure results, a filled calculator workbook, and a ready risk-ticket body.

Called by an external n8n workflow. All logic validated to the cent against Rosen and Live Suite golden examples.

---

## Endpoints

### `POST /assess`

**Auth:** Cloud Run IAM invoker (recommended). For dev/testing, set `RR_BEARER_TOKEN` and pass `Authorization: Bearer <token>`.

**Request (application/json):**
```json
{
  "ticket_id": "12345",
  "test_mode": false,
  "merchant": {
    "guesty_id": "...",
    "guesty_name": "Rosen Vacations",
    "guestypay": "3090.1 - Cribs",
    "region": "USA",
    "bank": "Stripe",
    "segment": "SME",
    "avg_mrr": "12087$",
    "active_listings": "220",
    "requested_change": "waive"
  },
  "statements": [
    { "filename": "payments.csv", "mime": "text/csv", "bytes_b64": "<base64>" }
  ],
  "flat_amount": null
}
```

**Response (200):** `months`, `volume_90d`, `highest_chb_rate`, `highest_refund_rate`, `flat_amount`, `exposure`, `ticket_markdown`, `qa_table_markdown`, `filled_workbook_b64`, `extraction`.

**Error:** `422 {error, detail}` for bad/unsupported input.

---

## Supported statement formats

| Format | Detection | Notes |
|---|---|---|
| GuestyPay dashboard CSV | `transactionType` + `amount_usd` columns | All 3 types in one file |
| Stripe payments export | `id` (ch_…), `Amount`, `Amount Refunded` | Dedup by id; separate disputes CSV for chargebacks |
| External bank PDF | PDF mime / `.pdf` extension | AI extraction via Claude |

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | For PDF extraction | — | Claude API key |
| `CONFIDENCE_THRESHOLD` | No | `0.85` | Below this score → `needs_review=true` |
| `PORT` | No | `8080` | HTTP port (Cloud Run sets this) |

---

## Running locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://localhost:8000/health
```

## Running tests

```bash
pytest tests/test_calc.py -v   # golden cases — must pass
pytest tests/ -v               # all tests (extraction needs fixture CSVs)
```

## Deploying to Cloud Run

```bash
gcloud builds submit --tag gcr.io/<PROJECT>/rr-engine
gcloud run deploy rr-engine \
  --image gcr.io/<PROJECT>/rr-engine \
  --region us-central1 \
  --no-allow-unauthenticated \
  --set-env-vars ANTHROPIC_API_KEY=<key>
```

The `--no-allow-unauthenticated` flag means only Cloud Run IAM invokers can call the service — the n8n service account needs the `roles/run.invoker` role.

---

## Calculation rules (summary)

- Rates rounded to 4 decimals (ROUND(MAX(...),4)) — matches the spreadsheet exactly.
- `Waiver_noCHB`: 0 if refund rate < 13%; else `-estimated_refund` (chargebacks excluded).
- `Projected Exposure (30d)`: intentionally blank — formula unconfirmed.
- Refunds bucketed by **original charge's created month**, not the refunded date.
- Stripe chargebacks require a separate disputes export; if absent, chargebacks = 0 + flag.

## Workbook template

Place `rr_calculator_template.xlsx` in `templates/`. If not present, a plain structured workbook is generated instead.
