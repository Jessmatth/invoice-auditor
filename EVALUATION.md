# Evaluation

Every number here is reproducible:

```bash
python3 scripts/evaluate.py --seed 7
```

## Corpus

76 invoices from [`katanaml-org/invoices-donut-data-v1`](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1)
(test + validation splits), each with human-annotated ground truth covering line
items and totals. Invoices run 0–7 line items.

**These are synthetic documents, and the composition matters when reading every
number below:**

| Property | Value |
|---|---|
| IBAN country prefix | `GB` on all 74 that have one |
| Postal addresses | United States, 49 states, US ZIP codes |
| Tax ID format | `NNN-NN-NNNN` (US SSN/EIN shape) |
| Currency symbol | `$` |
| Decimal convention | European comma, space-grouped thousands (`16 800,00`) |
| VAT rate | **10% on 300 of 300 line items** |
| Distinct header templates | 3 |

No real jurisdiction issues an invoice with a US address, a British IBAN, dollar
amounts and comma decimals under a VAT heading. This is Faker output from
essentially one template, so the corpus tests parsing hazards and arithmetic well
and tests layout and tax-regime diversity not at all.

The single-rate monoculture is the sharpest limit: nothing in this corpus exercises
a mixed-rate invoice, a zero-rated line, or a US sales-tax invoice with no VAT
column. Section 5 covers those separately with hand-built fixtures.

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

- **`validation-047`**: the annotation shifted a column, recording line 1's *net
  worth* (8,400.00) into the *net price* field and leaving net worth empty. The
  source invoice is internally correct: qty 3,00 × net price 2 800,00 = 8 400,00.
  The audit caught a mislabeled record in a public training dataset with no model in
  the loop.
- **`test-013`**: gross total annotated as `1 579 929,37` where net (143,572.15) +
  VAT (14,357.22) = `157,929.37`. A stray digit.

The one `unverifiable` document has an empty ground truth block and correctly
reports that there is nothing to cross-check.

### What changed between v1 and v2

v1 flagged four documents. Three were caused by a line missing its net amount, and
v1 reported them at the document level: *"line net amounts do not sum to the stated
net total."* True, but it blamed the wrong thing and gave the user nowhere to look.

v2 reconciles each line through two independent routes, `quantity × unit price` and
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
corruptions are planted in the 73 clean documents, the specific ways OCR and LLM
extraction actually fail, and the detection rate measured per class.

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
invisible **by design**. Without that allowance, ordinary rounding would flag most
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

## 5. Shapes the corpus does not contain

Because every corpus line item is 10% VAT, the common real-world shapes are tested
with hand-built fixtures in `tests/shapes/`, each with a hand-computed expected
outcome:

```bash
python3 scripts/test_shapes.py
```

| Fixture | Expected | Result |
|---|---|---|
| EU mixed rates, 20% and 5% on one invoice | clean | pass |
| Reduced-rate line charged at the standard rate | flagged | pass |
| US sales tax, no per-line tax column | clean | pass |
| US sales tax, grand total overstated by $10 | flagged | pass |
| Zero-rated line beside a standard-rated one | clean | pass |
| Discount carried as a negative line | clean | pass |
| Blended rate wrongly applied to the VAT total | flagged | pass |
| Untaxed shipping line beside taxed goods | clean | pass |

8 of 8. The checks are structural identities rather than rate-specific formulas,
which is why a document-level `net + tax = gross` behaves the same whether the tax
is 10% VAT, two VAT rates, or Ohio sales tax. Worth stating that this was verified
rather than assumed: the uniform corpus could not have revealed a rate-specific bug.

## 6. A second corpus: real photographed receipts

The synthetic corpus cannot show what real documents do. CORD (`naver-clova-ix/cord-v2`,
test split) is the opposite of it in every way that matters: 100 photographed
Indonesian receipts, Rupiah, no VAT column, service charges, discounts, and both
`,` and `.` used as thousands separators in the same corpus.

```bash
python3 scripts/fetch_cord.py
python3 scripts/verify.py --dir tests/corpus_cord/truth
```

| | Synthetic corpus | CORD |
|---|---|---|
| Documents | 76 | 100 |
| Clean | 73 | 83 |
| Flagged | 2 | 15 |
| Unverifiable | 1 | 2 |
| Check pass rate | 99.7% | 93.2% |

Real documents are messier, and the gap is the honest part of this table.

### Two real defects it found in the tool

**A parser bug worth 3 orders of magnitude.** `Rp. 111,000` parsed to `111.000`.
The currency stripper removed `Rp` and the space but left the period from the
abbreviation, producing `.111,000`, which the separator heuristic then read as a
European decimal. Silently dividing an amount by 1000 is exactly the error class
this tool exists to catch. Fixed, and `scripts/test_parsing.py` now covers 30 cases.

**Tax-inclusive line pricing.** 30 of the 100 receipts quote line prices *after*
tax, so the lines sum to the grand total rather than the pre-tax subtotal. The
verifier assumed tax-exclusive pricing universally and reported a false mismatch
on every one of them. It now accepts whichever convention reconciles and records
which. That change moved CORD from 67 clean to 83, and moved 18 documents out of
`unverifiable`.

Neither defect was visible in the synthetic corpus, because a single generator
producing one layout cannot disagree with itself.

### What the remaining 15 flags are

Not all of them are errors in the receipts. CORD's `subtotal_price` is sometimes a
pre-tax base while the line prices are rounded menu prices, so the two legitimately
differ by rounding. Some are genuine annotation noise. This is remapped third-party
ground truth and the mapping in `scripts/fetch_cord.py` is a best reading of their
schema, not an authority. Treat 93.2% as a floor for a real corpus rather than a
verdict on the receipts.

## 7. Sales tax and US state brackets

A VAT invoice states a rate on every line, which gives a second independent route
to each net amount. US sales tax is a single document-level number with nothing
behind it, so `subtotal + tax = total` confirms internal consistency and says
nothing about whether the rate is right.

| | VAT invoice (2 lines) | Sales-tax invoice (2 lines) |
|---|---|---|
| Checks run | 9 | 4 |
| Tax inflated, total adjusted | caught | passes clean |

Three ways to close that gap, in order of how much the user has to supply:

1. **Nothing.** The audit reports the effective rate and warns that it is
   uncorroborated, rather than quietly reporting clean.
2. **`--state TX`.** Checks the effective rate against that state's maximum possible
   combined rate, from `references/us_sales_tax_rates.json` (Tax Foundation, effective
   2026-01-01). The ceiling is a hard bound, so exceeding it is an error. A rate
   *below* the state rate is only a warning, because exempt lines legitimately drag
   the effective rate down.
3. **`--expect-rate 8.25%`.** The known rate for the address, checked exactly.

There are over 13,000 US sales-tax jurisdictions and rates change quarterly, so the
state table gives a bracket and never a point. It says a 14.4% charge cannot be
California. It cannot say what San Jose owes today.

## Honest summary

- 0 false positives on 76 synthetic invoices from a single template family
- 83 of 100 real photographed receipts reconcile cleanly; 93.2% of checks pass
- 100% detection across 583 planted arithmetic errors
- 0 detection below the 1-cent tolerance floor
- 0 detection on the three corruption classes arithmetic cannot reach
- 8 of 8 invoice shapes outside the corpus handled correctly
- 2 real annotation errors found in a public dataset, unprompted
- 2 real defects in the tool, both found by the real corpus and invisible in the synthetic one
- US sales tax gets roughly half the coverage of VAT, and the tool now says so
