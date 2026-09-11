#!/usr/bin/env python3
"""
fetch_cord.py - fetch a second, genuinely different corpus.

The primary corpus is synthetic: one generator, three templates, 10% VAT on
every line. CORD is the opposite in every way that matters. Real photographed
Indonesian receipts, Rupiah, no VAT column, service charges and discounts, and
both ',' and '.' used as thousands separators. It exists here to test the audit
against documents nobody designed to be tidy.

Ground truth is remapped from CORD's schema onto the invoice schema.

    python3 scripts/fetch_cord.py
"""
import io, json, os, urllib.request
import pyarrow.parquet as pq

URL  = "https://huggingface.co/api/datasets/naver-clova-ix/cord-v2/parquet/default/test/0.parquet"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "tests", "corpus_cord")

def remap(gt):
    """CORD's schema onto ours. menu may be a dict (single line) or a list."""
    menu = gt.get("menu")
    menu = [menu] if isinstance(menu, dict) else (menu or [])
    st   = gt.get("sub_total") or {}
    tot  = gt.get("total") or {}
    items = []
    for m in menu:
        if not isinstance(m, dict):
            continue
        items.append({
            "description": m.get("nm"),
            "quantity":    m.get("cnt"),
            "unit_price":  m.get("unitprice"),
            "amount":      m.get("price"),
        })
    return {
        "line_items": items,
        "totals": {
            "subtotal":       st.get("subtotal_price"),
            "discount_price": st.get("discount_price"),
            "service_charge": st.get("service_price"),
            "tax_amount":     st.get("tax_price"),
            "total":          tot.get("total_price"),
        },
    }

def main():
    os.makedirs(f"{OUT}/truth", exist_ok=True)
    print("fetching CORD test split ...", flush=True)
    raw = urllib.request.urlopen(URL, timeout=180).read()
    rows = pq.read_table(io.BytesIO(raw)).to_pylist()
    print(f"  {len(rows)} receipts")
    manifest = []
    for i, row in enumerate(rows):
        rid = f"cord-{i:03d}"
        gt  = json.loads(row["ground_truth"])["gt_parse"]
        doc = remap(gt)
        json.dump(doc, open(f"{OUT}/truth/{rid}.json", "w"), indent=2)
        manifest.append({"id": rid, "n_items": len(doc["line_items"])})
    json.dump(manifest, open(f"{OUT}/manifest.json", "w"), indent=2)
    print(f"wrote {len(manifest)} receipts to {OUT}/truth")
    print("line counts:", sorted({m["n_items"] for m in manifest}))

if __name__ == "__main__":
    main()
