"""
Live integration test — POST /assess with the CRIBS GuestyPay CSV.
Validates the full pipeline: extract → calc → ticket → workbook.
"""
import base64, json, requests

CSV_PATH = "/Users/gil.almog/Documents/Claude/Projects/Rolling Reserve Assesment/guestypay_cribs.csv"

with open(CSV_PATH, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "ticket_id": "TEST-001",
    "test_mode": True,
    "merchant": {
        "guesty_id": "test-guesty-id",
        "guesty_name": "CRIBS (GuestyPay test)",
        "guestypay": "3090.1 - Cribs",
        "region": "USA",
        "bank": "GuestyPay",
        "segment": "SME",
        "avg_mrr": "10000$",
        "active_listings": "50",
        "requested_change": "waive"
    },
    "statements": [
        {"filename": "guestypay_cribs.csv", "mime": "text/csv", "bytes_b64": b64}
    ],
    "flat_amount": None
}

r = requests.post("http://127.0.0.1:8000/assess", json=payload, timeout=30)
print(f"Status: {r.status_code}")

if r.status_code != 200:
    print("ERROR:", r.text)
    exit(1)

data = r.json()

print(f"\n📊 Source type : {data['extraction']['source_type']}")
print(f"🔍 Needs review: {data['extraction']['needs_review']}")
print(f"\n💰 Volume 90d  : ${data['volume_90d']:,.2f}")
print(f"📈 Highest CHB%: {data['highest_chb_rate']*100:.4f}%")
print(f"📈 Highest RFU%: {data['highest_refund_rate']*100:.4f}%")
print(f"💵 Flat amount : ${data['flat_amount']:,.0f}")

print(f"\n=== EXPOSURE SCENARIOS ===")
for k, v in data['exposure'].items():
    sign = "✅" if v >= 0 else "🔴"
    print(f"  {sign} {k:20s}: ${v:>10,}")

print(f"\n=== MONTHS ===")
for m in data['months']:
    print(f"  {m['label']}: Sales=${m['sales']:>12,.2f}  Refunds=${m['refunds']:>10,.2f}  CHB=${m['chargebacks']:>10,.2f}  CHB%={m['chb_rate']*100:.4f}%  RFU%={m['refund_pct']*100:.4f}%")

print(f"\n=== QA TABLE ===")
print(data['qa_table_markdown'])

print(f"\n=== WORKBOOK ===")
wb_b64 = data.get('filled_workbook_b64', '')
if wb_b64:
    wb_bytes = base64.b64decode(wb_b64)
    out_path = "/tmp/rr_filled_test.xlsx"
    with open(out_path, "wb") as f:
        f.write(wb_bytes)
    print(f"  ✅ Workbook written to {out_path} ({len(wb_bytes):,} bytes)")
else:
    print("  ⚠️  No workbook returned")

print(f"\n=== TICKET (first 20 lines) ===")
for line in data['ticket_markdown'].split('\n')[:20]:
    print(" ", line)
