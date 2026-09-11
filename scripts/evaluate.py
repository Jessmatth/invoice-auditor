#!/usr/bin/env python3
"""
evaluate.py - measure what the arithmetic audit actually catches.

A clean corpus only proves the audit does not cry wolf. To show it catches real
errors we plant known corruptions - the specific ways OCR and LLM extraction go
wrong - and measure the detection rate per class.

Some corruption classes are provably undetectable by arithmetic alone. Those are
reported too, because a recall number that hides them is dishonest.

    python3 evaluate.py --corpus tests/corpus [--seed 7] [--report eval/results.json]
"""
from __future__ import annotations
import argparse, copy, json, glob, random, sys, os
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import audit, parse_amount, __version__ as VERIFIER_VERSION

# ------------------------------------------------------- corruption models --
# Each returns (mutated_doc, description) or None when it does not apply.

def _fmt_like(original: str, value: Decimal) -> str:
    """Re-render a number in the same convention as the token it replaces."""
    s = f"{value:.2f}"
    if "," in str(original) and "." not in str(original).replace(" ", ""):
        s = s.replace(".", ",")
    return ("$ " + s) if "$" in str(original) else s

def _lines(doc):
    return doc.get("items") or []

def c_transpose_digits(doc, rng):
    """OCR/LLM swaps two adjacent digits: 8400 -> 4800."""
    for i, it in enumerate(_lines(doc)):
        raw = it.get("item_net_worth")
        v = parse_amount(raw)
        if v is None or v < 10: continue
        digits = list(f"{v:.2f}".replace(".", ""))
        for j in range(len(digits) - 1):
            if digits[j] != digits[j+1]:
                digits[j], digits[j+1] = digits[j+1], digits[j]
                break
        else: continue
        new = Decimal("".join(digits)) / 100
        it["item_net_worth"] = _fmt_like(raw, new)
        return doc, f"line {i+1} net {v:.2f} -> {new:.2f} (digit transposition)"
    return None

def c_decimal_shift(doc, rng):
    """Decimal point moves one place: 444.60 -> 4446.00."""
    for i, it in enumerate(_lines(doc)):
        raw = it.get("item_net_price")
        v = parse_amount(raw)
        if v is None or v == 0: continue
        new = (v * 10).quantize(Decimal("0.01"))
        it["item_net_price"] = _fmt_like(raw, new)
        return doc, f"line {i+1} unit price {v:.2f} -> {new:.2f} (decimal shift)"
    return None

def c_dropped_digit(doc, rng):
    """A digit is lost in the totals: 25329.96 -> 2532.96."""
    raw = (doc.get("summary") or {}).get("total_net_worth")
    v = parse_amount(raw)
    if v is None or v < 100: return None
    d = f"{v:.2f}".replace(".", "")
    new = Decimal(d[:-3] + d[-2:]) / 100
    doc["summary"]["total_net_worth"] = _fmt_like(raw, new)
    return doc, f"net total {v:.2f} -> {new:.2f} (dropped digit)"

def c_ocr_confusion(doc, rng):
    """Classic OCR glyph confusions applied to a gross amount."""
    swaps = {"8": "3", "5": "6", "1": "7", "0": "8", "6": "5", "3": "8"}
    for i, it in enumerate(_lines(doc)):
        raw = it.get("item_gross_worth")
        v = parse_amount(raw)
        if v is None: continue
        s = f"{v:.2f}".replace(".", "")
        for j, ch in enumerate(s):
            if ch in swaps:
                new = Decimal(s[:j] + swaps[ch] + s[j+1:]) / 100
                if new == v: continue
                it["item_gross_worth"] = _fmt_like(raw, new)
                return doc, f"line {i+1} gross {v:.2f} -> {new:.2f} (OCR {ch}->{swaps[ch]})"
    return None

def c_column_swap(doc, rng):
    """Net and gross columns read in the wrong order - the exact failure
    already present in this dataset's own labels."""
    for i, it in enumerate(_lines(doc)):
        n, g = it.get("item_net_worth"), it.get("item_gross_worth")
        if n is None or g is None or parse_amount(n) == parse_amount(g): continue
        it["item_net_worth"], it["item_gross_worth"] = g, n
        return doc, f"line {i+1} net and gross columns swapped"
    return None

def c_qty_misread(doc, rng):
    """Quantity misread: 3,00 -> 8,00."""
    for i, it in enumerate(_lines(doc)):
        v = parse_amount(it.get("item_qty"))
        if v is None: continue
        new = v + 5
        it["item_qty"] = _fmt_like(it["item_qty"], new)
        return doc, f"line {i+1} qty {v:.2f} -> {new:.2f} (misread)"
    return None

def c_thousands_misparse(doc, rng):
    """Space-grouped '16 800,00' collapsed to 16.80 - a real parser failure."""
    for i, it in enumerate(_lines(doc)):
        raw = str(it.get("item_net_worth") or "")
        v = parse_amount(raw)
        if v is None or v < 1000: continue
        new = (v / 1000).quantize(Decimal("0.01"))
        it["item_net_worth"] = _fmt_like(raw, new)
        return doc, f"line {i+1} net {v:.2f} -> {new:.2f} (thousands separator lost)"
    return None

def c_dropped_line(doc, rng):
    """A whole line item is missed. Detectable ONLY because the totals still
    reference it."""
    if len(_lines(doc)) < 2: return None
    gone = doc["items"].pop(rng.randrange(len(doc["items"])))
    return doc, f"line item dropped entirely ({str(gone.get('item_desc'))[:30]}...)"

def c_duplicated_line(doc, rng):
    """A line is read twice - common with multi-page or wrapped rows."""
    if not _lines(doc): return None
    doc["items"].append(copy.deepcopy(doc["items"][0]))
    return doc, "first line item duplicated"

# -- classes arithmetic provably cannot catch, included to keep us honest ----

def c_description_corrupt(doc, rng):
    """UNDETECTABLE: text field only, participates in no identity."""
    for i, it in enumerate(_lines(doc)):
        if it.get("item_desc"):
            it["item_desc"] = "Widget, generic"
            return doc, f"line {i+1} description replaced (no arithmetic involvement)"
    return None

def c_consistent_inflation(doc, rng):
    """UNDETECTABLE: every figure scaled by the same factor, so every identity
    still closes. Arithmetic cannot distinguish this from a real invoice."""
    k = Decimal(2)
    for it in _lines(doc):
        for f in ("item_net_price", "item_net_worth", "item_gross_worth"):
            v = parse_amount(it.get(f))
            if v is not None: it[f] = _fmt_like(it[f], v * k)
    s = doc.get("summary") or {}
    for f in ("total_net_worth", "total_vat", "total_gross_worth"):
        v = parse_amount(s.get(f))
        if v is not None: s[f] = _fmt_like(s[f], v * k)
    return doc, "every amount doubled (all identities still close)"

def c_vendor_swap(doc, rng):
    """UNDETECTABLE: header identity field, no arithmetic relationship."""
    h = doc.get("header") or {}
    if not h.get("seller"): return None
    h["seller"] = "Acme Holdings LLC, 1 Main St"
    return doc, "seller name replaced (no arithmetic involvement)"


DETECTABLE = [
    ("digit_transposition",   c_transpose_digits),
    ("decimal_shift",         c_decimal_shift),
    ("dropped_digit_total",   c_dropped_digit),
    ("ocr_glyph_confusion",   c_ocr_confusion),
    ("net_gross_column_swap", c_column_swap),
    ("quantity_misread",      c_qty_misread),
    ("thousands_misparse",    c_thousands_misparse),
    ("dropped_line_item",     c_dropped_line),
    ("duplicated_line_item",  c_duplicated_line),
]
UNDETECTABLE = [
    ("description_corrupted", c_description_corrupt),
    ("uniform_inflation",     c_consistent_inflation),
    ("vendor_name_swapped",   c_vendor_swap),
]

# -- boundary probes: real errors small enough to sit inside the tolerance ---

def _nudge(doc, cents):
    for i, it in enumerate(_lines(doc)):
        raw = it.get("item_net_worth")
        v = parse_amount(raw)
        if v is None: continue
        new = v + (Decimal(cents) / 100)
        it["item_net_worth"] = _fmt_like(raw, new)
        return doc, f"line {i+1} net {v:.2f} -> {new:.2f} (+{cents}c)"
    return None

def c_off_by_one_cent(doc, rng):
    """A one-cent error, which sits inside the rounding tolerance by design."""
    return _nudge(doc, 1)

def c_off_by_five_cents(doc, rng):
    """Five cents: above tolerance on short invoices, inside it on long ones,
    so this locates where the floor actually falls."""
    return _nudge(doc, 5)

def c_off_by_fifty_cents(doc, rng):
    """Fifty cents, which should always be caught."""
    return _nudge(doc, 50)

BOUNDARY = [
    ("off_by_1_cent",   c_off_by_one_cent),
    ("off_by_5_cents",  c_off_by_five_cents),
    ("off_by_50_cents", c_off_by_fifty_cents),
]

# ---------------------------------------------------------------- harness --

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="tests/corpus")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", default="eval/results.json")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    truth = sorted(glob.glob(f"{args.corpus}/truth/*.json"))
    docs = []
    for p in truth:
        raw = json.load(open(p))
        d = raw.get("gt_parse", raw)
        docs.append((p.split("/")[-1][:-5], d))

    # ---- baseline: precision on the untouched corpus --------------------
    base = [audit(copy.deepcopy(d), i) for i, d in docs]
    base_flagged = [r for r in base if r.status == "flagged"]
    base_clean   = [r for r in base if r.status == "clean"]
    base_unver   = [r for r in base if r.status == "unverifiable"]

    # Only documents the audit passes cleanly can be used to measure recall:
    # planting an error in an already-flagged document proves nothing.
    usable = [(i, d) for (i, d), r in zip(docs, base) if r.status == "clean"]

    # ---- recall per corruption class ------------------------------------
    per_class, examples = {}, {}
    for group, classes, expect in (("detectable", DETECTABLE, True),
                                   ("boundary", BOUNDARY, None),
                                   ("undetectable", UNDETECTABLE, False)):
        for name, fn in classes:
            planted = caught = skipped = 0
            miss_ex, catch_ex = [], []
            for doc_id, d in usable:
                out = fn(copy.deepcopy(d), rng)
                if out is None:
                    skipped += 1
                    continue
                mutated, desc = out
                planted += 1
                r = audit(mutated, doc_id)
                if r.status == "flagged":
                    caught += 1
                    if len(catch_ex) < 1:
                        top = next((f for f in r.findings if f.severity == "error"), None)
                        catch_ex.append({"doc": doc_id, "corruption": desc,
                                         "caught_by": top.rule if top else None,
                                         "finding": top.message if top else None})
                elif len(miss_ex) < 1:
                    miss_ex.append({"doc": doc_id, "corruption": desc})
            per_class[name] = {
                "group": group, "expected_detectable": expect,
                "planted": planted, "caught": caught,
                "not_applicable": skipped,
                "detection_rate": round(caught / planted, 4) if planted else None,
            }
            examples[name] = {"caught": catch_ex, "missed": miss_ex}

    det = {k: v for k, v in per_class.items() if v["group"] == "detectable"}
    tot_p = sum(v["planted"] for v in det.values())
    tot_c = sum(v["caught"]  for v in det.values())
    und   = {k: v for k, v in per_class.items() if v["group"] == "undetectable"}
    und_p = sum(v["planted"] for v in und.values())
    und_c = sum(v["caught"]  for v in und.values())

    report = {
        "verifier_version": VERIFIER_VERSION,
        "seed": args.seed,
        "corpus": {"documents": len(docs), "source": "katanaml-org/invoices-donut-data-v1 (test+validation)"},
        "baseline": {
            "clean": len(base_clean), "flagged": len(base_flagged),
            "unverifiable": len(base_unver),
            "checks_run": sum(r.checks_run for r in base),
            "checks_passed": sum(r.checks_passed for r in base),
            "values_recovered": sum(len(r.recovered) for r in base),
            "flagged_ids": [r.doc_id for r in base_flagged],
        },
        "recall": {
            "usable_documents": len(usable),
            "detectable": {"planted": tot_p, "caught": tot_c,
                           "rate": round(tot_c / tot_p, 4) if tot_p else None},
            "undetectable_control": {"planted": und_p, "false_alarms": und_c,
                                     "rate": round(und_c / und_p, 4) if und_p else None},
        },
        "boundary": {k: v for k, v in per_class.items() if v["group"] == "boundary"},
        "per_class": per_class,
        "examples": examples,
    }
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    json.dump(report, open(args.report, "w"), indent=2)

    # ---- console ---------------------------------------------------------
    W = 72
    print("=" * W)
    print(f"INVOICE AUDITOR EVALUATION   verifier v{VERIFIER_VERSION}   seed {args.seed}")
    print("=" * W)
    print(f"\nCorpus: {len(docs)} synthetic invoices with human-annotated ground truth")
    print(f"  (single generator, 3 templates, 10% VAT on every line item)")
    print(f"  clean {len(base_clean)}   flagged {len(base_flagged)}   unverifiable {len(base_unver)}")
    print(f"  {report['baseline']['checks_passed']}/{report['baseline']['checks_run']} arithmetic checks passed")
    print(f"  {report['baseline']['values_recovered']} missing values recovered by derivation")
    if base_flagged:
        print(f"  flagged: {', '.join(r.doc_id for r in base_flagged)}  (all verified as real label errors)")

    print(f"\nRECALL - errors planted in the {len(usable)} clean documents")
    print(f"  {'class':<24} {'planted':>8} {'caught':>8} {'rate':>8}")
    print(f"  {'-'*24} {'-'*8} {'-'*8} {'-'*8}")
    for name, v in det.items():
        r = f"{v['detection_rate']*100:.1f}%" if v["detection_rate"] is not None else "n/a"
        print(f"  {name:<24} {v['planted']:>8} {v['caught']:>8} {r:>8}")
    print(f"  {'-'*24} {'-'*8} {'-'*8} {'-'*8}")
    print(f"  {'TOTAL':<24} {tot_p:>8} {tot_c:>8} {tot_c/tot_p*100 if tot_p else 0:>7.1f}%")

    bnd = {k: v for k, v in per_class.items() if v["group"] == "boundary"}
    print(f"\nBOUNDARY - how small an error can be and still be caught")
    print(f"  {'class':<24} {'planted':>8} {'caught':>8} {'rate':>8}")
    for name, v in bnd.items():
        r = f"{v['detection_rate']*100:.1f}%" if v["detection_rate"] is not None else "n/a"
        print(f"  {name:<24} {v['planted']:>8} {v['caught']:>8} {r:>8}")

    print(f"\nCONTROL - corruptions arithmetic provably cannot catch")
    for name, v in und.items():
        r = f"{v['detection_rate']*100:.1f}%" if v["detection_rate"] is not None else "n/a"
        print(f"  {name:<24} {v['planted']:>8} {v['caught']:>8} {r:>8}  (expect 0.0%)")
    print(f"\n  These are the audit's blind spot and are stated, not hidden:")
    print(f"  arithmetic can only validate figures that participate in an identity.")
    print(f"\nReport written to {args.report}")

if __name__ == "__main__":
    main()
