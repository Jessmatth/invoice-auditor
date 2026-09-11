#!/usr/bin/env python3
"""
test_shapes.py - does the audit hold up on invoice shapes the corpus doesn't contain?

The evaluation corpus is synthetic and uniform: every one of its 300 line items
carries 10% VAT. That makes it useless for answering whether the audit survives
a mixed-rate EU invoice, a US sales-tax invoice with no VAT column at all, or a
credit line carried as a negative amount. These fixtures cover those shapes with
hand-computed expected outcomes.

    python3 scripts/test_shapes.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import audit

HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHAPES = os.path.join(HERE, "tests", "shapes")

CASES = [
    ("A_mixed_rates_clean",        "clean",   "EU mixed rates, 20% and 5% on one invoice"),
    ("B_mixed_rates_bad_line",     "flagged", "reduced-rate line charged at the standard rate"),
    ("C_us_sales_tax_clean",       "clean",   "US sales tax, no per-line tax column"),
    ("D_us_sales_tax_bad_total",   "flagged", "US sales tax, grand total overstated by $10"),
    ("E_zero_rated_clean",         "clean",   "zero-rated line beside a standard-rated one"),
    ("F_discount_line_clean",      "clean",   "discount carried as a negative line"),
    ("G_mixed_rates_bad_vat_total","flagged", "blended rate wrongly applied to the VAT total"),
    ("H_shipping_line_clean",      "clean",   "untaxed shipping line beside taxed goods"),
    ("I_sales_tax_inflated",       "clean",   "inflated sales tax with the total adjusted to match"),
    ("J_document_rate_clean",      "clean",   "document-level tax rate stated and correct"),
    ("K_document_rate_bad",        "flagged", "document-level rate does not produce the stated total"),
]

# I_sales_tax_inflated is expected to pass, and that is the point. A single
# document-level tax amount has no redundancy behind it, so arithmetic alone
# cannot tell a correct 8.25% from an invented 14.4%. The audit reports the
# effective rate and warns that it is uncorroborated; --expect-rate closes it.
EXPECT_RATE_CASES = [
    ("I_sales_tax_inflated", "8.25%", "flagged", "the same invoice, with the rate supplied"),
    ("C_us_sales_tax_clean", "8.25%", "clean",   "correct invoice, with the rate supplied"),
]

def main():
    print(f"{'shape':<32}{'expect':<10}{'actual':<12}result")
    print("-" * 64)
    fails = []
    for name, expect, desc in CASES:
        r = audit(json.load(open(os.path.join(SHAPES, f"{name}.json"))), name)
        ok = r.status == expect
        if not ok:
            fails.append((name, expect, r, desc))
        print(f"{name:<32}{expect:<10}{r.status:<12}{'PASS' if ok else 'FAIL'}")
    print(f"\n--- with a known jurisdiction rate supplied ---")
    for name, rate, expect, desc in EXPECT_RATE_CASES:
        r = audit(json.load(open(os.path.join(SHAPES, f"{name}.json"))), name, expect_rate=rate)
        ok = r.status == expect
        if not ok:
            fails.append((name, expect, r, desc))
        print(f"{name+' @'+rate:<32}{expect:<10}{r.status:<12}{'PASS' if ok else 'FAIL'}")

    print(f"\n{len(CASES)+len(EXPECT_RATE_CASES)-len(fails)} passed, {len(fails)} failed")
    for name, expect, r, desc in fails:
        print(f"\n{name} ({desc}): expected {expect}, got {r.status}")
        for f in r.findings:
            print(f"   {f.severity.upper()} {f.rule} line={f.line} :: {f.message}")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
