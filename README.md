# AI Payments — Rolling Reserve Assessment Engine

A stateless HTTP service that turns a merchant's payment statements into reserve-exposure calculations, a filled Excel workbook, and a ready Reserve-Escalation ticket body.

Replaces the manual analyst workflow. Called by an n8n flow — n8n handles the trigger, Zendesk, and Drive; this service is pure compute.

**Service URL:** `https://ai-payments-rr-engine-hoepmeihvq-uc.a.run.app`

---

## How It Works

```
n8n sends merchant identity + statement files (base64)
        ↓
Source detection → GuestyPay CSV | Stripe CSV | External PDF
        ↓
Extraction → normalized monthly {sales, refunds, chargebacks}
        ↓
Calculation engine → 5 exposure scenarios
        ↓
Returns: exposure results + filled .xlsx + ticket markdown + QA table
```

---

## API

### `POST /assess`

**Auth:** Cloud Run IAM. The `ai-team-n8n` service account requires `roles/run.invoker`.

**Request body:**
```json
{
  "ticket_id": "ZD-12345",
  "test_mode": false,
  "merchant": {
    "guesty_id": "abc123",
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
    {
      "filename": "payments.csv",
      "mime": "text/csv",
      "bytes_b64": "<base64 encoded file>"
    }
  ],
  "flat_amount": null
}
```

**Response (200):**
```json
{
  "months": [
    {
      "label": "Dec",
      "sales": 790419.13,
      "refunds": 10725.14,
      "chargebacks": 2177.68,
      "refund_pct": 0.0136,
      "chb_rate": 0.0028
    }
  ],
  "volume_90d": 2353692.0,
  "highest_chb_rate": 0.0039,
  "highest_refund_rate": 0.0353,
  "flat_amount": 10000,
  "exposure": {
    "10%": 613843,
    "5%": 260789,
    "Flat": -82265,
    "Waiver_incl": -92265,
    "Waiver_noCHB": 0
  },
  "ticket_markdown": "Reserve Escalation\n...",
  "qa_table_markdown": "| Month | ...",
  "filled_workbook_b64": "<base64 xlsx>",
  "extraction": {
    "source_type": "stripe",
    "needs_review": false,
    "confidence": []
  }
}
```

**Error:** `422 {error, detail}` for bad or unrecognized input. Never returns 200 with fabricated numbers.

### `GET /health`

Returns `{"status": "ok"}`. Use for uptime monitoring.

---

## Supported Statement Formats

| Format | Detection | Notes |
|---|---|---|
| GuestyPay dashboard CSV | `transactionType` + `amount_usd` columns | All 3 types in one file (Charge / Refund / Chargeback) |
| Stripe payments export | `id` (ch_…), `Amount`, `Amount Refunded` columns | Dedup by charge ID; send a second file for disputes |
| External bank PDF | `.pdf` extension or `application/pdf` mime | AI extraction via Gemini; returns per-figure confidence scores |

You can send multiple files in `statements[]` — e.g. a Stripe payments export + a disputes export together.

---

## Key Response Fields for n8n

| Field | How to use |
|---|---|
| `extraction.needs_review` | Gate on this — if `true`, route to human review before creating the ticket |
| `extraction.source_type` | `stripe` / `guestypay` / `pdf_ai` — log for traceability |
| `ticket_markdown` | Post directly as the Zendesk / SIIT ticket body |
| `filled_workbook_b64` | Base64-decode → upload to Google Drive as the audit artifact |
| `qa_table_markdown` | Attach to the ticket or Drive folder for reviewer QA |
| `exposure` | The 5 scenarios: `10%`, `5%`, `Flat`, `Waiver_incl`, `Waiver_noCHB` |

---

## Request Fields Reference

| Field | Required | Notes |
|---|---|---|
| `ticket_id` | No | Passed through for logging/traceability |
| `test_mode` | No | `true` forces `needs_review: true` — use for all test runs |
| `merchant.*` | Yes | Identity fields that appear in the ticket header |
| `merchant.guestypay` | Yes | Use `"N/A"` for external-bank merchants |
| `statements` | Yes | Array of files; each needs `filename`, `mime`, `bytes_b64` |
| `flat_amount` | No | Override the flat reserve amount. If `null`, auto-looked up by volume |

**Flat amount auto-lookup table** (used when `flat_amount` is null):

| Volume 90d | Flat Amount |
|---|---|
| $75K – $100K | $10K |
| $100K – $500K | $30K |
| $500K – $1M | $60K |
| $1M – $2M | $100K |
| > $2M | $100K (default — override recommended) |

---

## Calling from n8n

The HTTP Request node must authenticate as the `ai-team-n8n` service account using a GCP identity token.

**Step 1 — Get identity token** (HTTP Request node):
- Method: `GET`
- URL: `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=https://ai-payments-rr-engine-hoepmeihvq-uc.a.run.app`
- Header: `Metadata-Flavor: Google`

**Step 2 — Call the service** (HTTP Request node):
- Method: `POST`
- URL: `https://ai-payments-rr-engine-hoepmeihvq-uc.a.run.app/assess`
- Header: `Authorization: Bearer {{ $json.token }}`
- Body: JSON payload as above

> **Note:** `roles/run.invoker` must be granted to `ai-team-n8n@ai-innovation-484111.iam.gserviceaccount.com` on this service. IT request pending.

---

## Calculation Rules

All logic is validated to the cent against two real filled calculators (Rosen and Live Suite).

- **Rates** rounded to 4 decimals — matches the sheet's `ROUND(MAX(...), 4)`. Skipping this drifts results by ~$100.
- **Refunds** bucketed by the original **charge's created month**, not the refunded date.
- **Chargebacks** bucketed by the **dispute's created date**.
- **`Waiver_noCHB`**: `0` if refund rate < 13%; otherwise `-estimated_refund` (chargebacks excluded).
- **Projected Exposure (30d)**: intentionally blank — formula unconfirmed.
- **Stripe chargebacks**: require a separate disputes export. If absent, chargebacks = 0 with a flag in `extraction`.

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload
# → http://localhost:8000/health
```

## Running Tests

```bash
./run_tests.sh          # all 102 tests (~1.2 seconds)
./run_tests.sh -k calc  # just the golden calc tests
./run_tests.sh -q       # quiet mode
```

Tests cover: golden calc values (Rosen + Live Suite), GuestyPay extraction, Stripe extraction (including the critical refund-by-created-month rule), ticket rendering, and full API end-to-end.

---

## Deploying

```bash
gcloud run deploy ai-payments-rr-engine \
  --source . \
  --region us-central1 \
  --no-allow-unauthenticated \
  --set-secrets GOOGLE_AI_API_KEY=GOOGLE_AI_API_KEY:latest \
  --memory 512Mi \
  --timeout 120 \
  --project ai-innovation-484111
```

---

## Environment / Secrets

| Name | Source | Purpose |
|---|---|---|
| `GOOGLE_AI_API_KEY` | GCP Secret Manager | Gemini API key for PDF extraction |
| `CONFIDENCE_THRESHOLD` | Env var (default `0.85`) | Below this score → `needs_review: true` |

No database. No state. Scales to zero when idle.

---

## Repo Structure

```
app/
  main.py           # FastAPI entrypoint — POST /assess
  calc.py           # Deterministic exposure engine
  ticket.py         # Reserve-Escalation ticket renderer
  workbook.py       # Excel workbook filler
  models.py         # Request/response models
  extract/
    __init__.py     # Source detection + dispatch
    guestypay.py    # GuestyPay CSV parser
    stripe.py       # Stripe CSV parser
    pdf_ai.py       # Gemini AI extraction for PDFs
templates/
  rr_calculator_template.xlsx
tests/
  test_calc.py              # Golden value tests (Rosen + Live Suite)
  test_extract_guestypay.py
  test_extract_stripe.py
  test_ticket.py
  test_api.py               # Full end-to-end API tests
```
