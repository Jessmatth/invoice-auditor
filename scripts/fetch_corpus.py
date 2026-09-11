"""Fetch the evaluation corpus.

76 invoices with human ground truth from katanaml-org/invoices-donut-data-v1
(MIT licensed). Ground truth JSON is vendored in the repo; the page images are
not, because they are 54MB. Run this to pull them.

    python3 scripts/fetch_corpus.py
"""
import io, json, os, urllib.request, pyarrow.parquet as pq
from PIL import Image

BASE = "https://huggingface.co/api/datasets/katanaml-org/invoices-donut-data-v1/parquet/default"
OUT  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "corpus")
os.makedirs(f"{OUT}/images", exist_ok=True)
os.makedirs(f"{OUT}/truth",  exist_ok=True)

manifest = []
for split in ("test", "validation"):
    url = f"{BASE}/{split}/0.parquet"
    print(f"fetching {split} ...", flush=True)
    raw = urllib.request.urlopen(url, timeout=180).read()
    tbl = pq.read_table(io.BytesIO(raw)).to_pylist()
    print(f"  {len(tbl)} rows")
    for i, row in enumerate(tbl):
        rid = f"{split}-{i:03d}"
        img = Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB")
        img.save(f"{OUT}/images/{rid}.png")
        gt = json.loads(row["ground_truth"])["gt_parse"]
        json.dump(gt, open(f"{OUT}/truth/{rid}.json", "w"), indent=2)
        manifest.append({"id": rid, "split": split,
                         "image": f"images/{rid}.png", "truth": f"truth/{rid}.json",
                         "n_items": len(gt.get("items", [])), "size": list(img.size)})
json.dump(manifest, open(f"{OUT}/manifest.json", "w"), indent=2)
print(f"\ntotal {len(manifest)} invoices")
print("line-item counts:", sorted({m['n_items'] for m in manifest}))
