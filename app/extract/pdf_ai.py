"""
AI extraction for external/bank PDFs and screenshots.
Uses pdfplumber for text, then Google Gemini to parse into normalized schema.
Never invents values — low confidence if a figure isn't clearly present.
"""
import json
import os

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


PROMPT = """You are a financial data extractor for payment processing statements.
Extract ONLY the monthly Sales, Refunds (returns/credits), and Chargebacks totals.
Return ONLY a JSON object. Do not add commentary.

Rules:
- Never invent or estimate a value. If a figure is not clearly present, set it to null and confidence to 0.0.
- Prefer returning fewer months over guessing.
- Include a snippet (the exact text you read the number from) for QA purposes.
- Confidence: 1.0 = clearly stated, 0.7 = inferred/ambiguous, 0.0 = not found.

Output schema (strict):
{
  "months": [
    {
      "label": "YYYY-MM",
      "sales": <number or null>,
      "sales_confidence": <0.0-1.0>,
      "sales_snippet": "<text>",
      "refunds": <number or null>,
      "refunds_confidence": <0.0-1.0>,
      "refunds_snippet": "<text>",
      "chargebacks": <number or null>,
      "chargebacks_confidence": <0.0-1.0>,
      "chargebacks_snippet": "<text>"
    }
  ]
}"""


def _extract_text(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf") and HAS_PDFPLUMBER:
        import io
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return content.decode("utf-8", errors="replace")


def extract_pdf_ai(files: list[dict]) -> dict:
    """
    files: [{"filename": str, "content": bytes}]
    Returns: {"table": {month: {sales, refunds, chargebacks}}, "confidence": [...]}
    """
    api_key = os.environ.get("GOOGLE_AI_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_AI_API_KEY not set; cannot perform AI extraction")
    if not HAS_GENAI:
        raise EnvironmentError("google-generativeai not installed")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-pro-latest",
        generation_config={"response_mime_type": "application/json"},
    )

    all_text = []
    for f in files:
        text = _extract_text(f["content"], f["filename"])
        all_text.append(f"=== {f['filename']} ===\n{text}")

    combined = "\n\n".join(all_text)
    full_prompt = f"{PROMPT}\n\nExtract monthly Sales, Refunds, and Chargebacks from this payment statement:\n\n{combined}"

    response = model.generate_content(full_prompt)
    raw = response.text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    parsed = json.loads(raw)

    table = {}
    confidence = []

    for m in parsed.get("months", []):
        label = m.get("label", "")
        if not label:
            continue
        table[label] = {
            "sales": m.get("sales") or 0.0,
            "refunds": m.get("refunds") or 0.0,
            "chargebacks": m.get("chargebacks") or 0.0,
        }
        for field in ("sales", "refunds", "chargebacks"):
            score = m.get(f"{field}_confidence", 0.0)
            confidence.append({"field": field, "month": label, "score": score,
                               "snippet": m.get(f"{field}_snippet", "")})

    return {"table": table, "confidence": confidence}
