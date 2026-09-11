# Evaluation

Every number here is reproducible:

```bash
python3 scripts/evaluate.py --seed 7
```

## Corpus

76 invoices from [`katanaml-org/invoices-donut-data-v1`](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1)
(test + validation splits), each with human-annotated ground truth covering line
items and totals. Invoices run 0–7 line items and use European decimal commas with
space-grouped thousands (`16 800,00`) under a `$` symbol — a genuine parsing hazard,
and a useful one to be tested against.

## 1. Precision: does it cry wolf?

Run the audit over the untouched ground truth. Anything it flags is either a real
error or a false positive, and every flag was inspected by hand against the source
image.

| | v1 | v2 |
|---|---|---|
| Clean | 71 | **73** |
| Flagged | 4 | **2** |
| Unverifiable | 1 | 1 |
| Arithmetic checks run | 890 | **1,118** |
| Checks passed | 98.9% | **99.7%** |
| Values recovered by derivation | 0 | **3** |

**False positives: 0.** Both surviving flags are real errors in the dataset's own
human annotations:

- **`validation-047`** — the annotation shifted a column, recording line 1's *net
  worth* (8,400.00) into the *net price* field and leaving net worth empty. The
  source invoice is internally correct: qty 3,00 × net price 2 800,00 = 8 400,00.
  The audit caught a mislabeled record in a public training dataset with no model in
  the loop.
- **`test-013`** — gross total annotated as `1 579 929,37` where net (143,572.15) +
  VAT (14,357.22) = `157,929.37`. A stray digit.

The one `unverifiable` document has an empty ground truth block and correctly
reports that there is nothing to cross-check.

### What changed between v1 and v2

v1 flagged four documents. Three were caused by a line missing its net amount, and
v1 reported them at the document level: *"line net amounts do not sum to the stated
net total."* True, but it blamed the wrong thing and gave the user nowhere to look.

v2 reconciles each line through two independent routes — `quantity × unit price` and
`gross ÷ (1 + VAT)`. When a value is absent and both routes agree, it is recovered
and the document verifies. When they disagree, the finding names the line and the
field:

> line 1: net amount is absent and the two ways of deriving it disagree
> (quantity × unit price = 25,200.00, gross ÷ (1 + VAT) = 8,400.00);
> at least one input field on this line is wrong

Two false alarms removed, 228 additional checks enabled, and the remaining flags
point at a field instead of a document.

## 2. Recall: does it catch real errors?

A clean corpus proves only that the audit is quiet. To show it catches errors, known
corruptions are planted in the 73 clean documents — the specific ways OCR and LLM
extraction actually fail — and the detection rate measured per class.

| Corruption | Planted | Caught | Rate |
|---|---:|---:|---:|
| Digit transposition (`8400` → `4800`) | 70 | 70 | 100% |
| Decimal shift (`444.60` → `4446.00`) | 72 | 72 | 100% |
| Dropped digit in total | 64 | 64 | 100% |
| OCR glyph confusion (`8`→`3`, `5`→`6`, `1`→`7`) | 72 | 72 | 100% |
| Net/gross column swap | 72 | 72 | 100% |
| Quantity misread | 72 | 72 | 100% |
| Thousands separator lost (`16 800,00` → `16.80`) | 29 | 29 | 100% |
| Line item dropped | 60 | 60 | 100% |
| Line item duplicated | 72 | 72 | 100% |
| **Total** | **583** | **583** | **100%** |

100% is the expected result, not a surprising one: every corruption above moves a
figure that participates in an identity by more than the tolerance, so the identity
must break. The number worth trusting is the one below.

## 3. Boundary: how small an error can be and still be caught

| Error size | Planted | Caught | Rate |
|---|---:|---:|---:|
| 1 cent | 72 | 0 | **0%** |
| 5 cents | 72 | 72 | 100% |
| 50 cents | 72 | 72 | 100% |

Tolerance is one cent per independently rounded term, so sub-cent discrepancies are
invisible **by design** — without that allowance, ordinary rounding would flag most
legitimate invoices. The floor sits between 1 and 5 cents. This is a real limitation
and it is published rather than hidden.

## 4. Control: what arithmetic provably cannot catch

| Corruption | Planted | False alarms |
|---|---:|---:|
| Description replaced | 72 | 0 |
| Every amount doubled | 73 | 0 |
| Vendor name replaced | 72 | 0 |

These pass verification while still being wrong, and they should. Arithmetic
validates only figures that participate in an identity. A vendor name, an address,
and a tax ID have no arithmetic relationship to anything; if every figure is scaled
by the same factor, every identity still closes.

**A clean audit means the document is internally consistent. It does not mean the
extraction is right, and it does not mean the charge is owed.** Stating that plainly
is part of the skill.

## Honest summary

- 0 false positives on 76 real invoices
- 100% detection across 583 planted arithmetic errors
- 0 detection below the 1-cent tolerance floor
- 0 detection on the three corruption classes arithmetic cannot reach
- 2 real annotation errors found in a public dataset, unprompted
