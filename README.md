# invoice-auditor
<img width="1408" height="768" alt="Gemini_Generated_Image_w5yljjw5yljjw5yl" src="https://github.com/user-attachments/assets/28c1ab6b-d5a1-453a-9083-252e1a45638e" />

A Claude skill that extracts invoices **and proves the extraction is correct.**

Most document-extraction tools return a confident JSON blob. You have no way to know
whether the model misread a column, lost a thousands separator, or transposed two
digits — and the model will report high confidence either way. Self-reported
confidence is the model grading its own homework.

Invoices happen to be checkable. An invoice line carries five numbers — quantity,
unit price, net, VAT rate, gross — of which only three are independent. The document
over-determines itself, so the arithmetic either closes or it does not, and finding
out requires no model at all.

This skill extracts with a model and then audits with code.

```
47 invoices   44 clean   2 flagged   1 unverifiable

FLAGGED
  inv-2291  line 3: quantity x unit price = 1,240.00 but stated net is 1,420.00
            (digit transposition; page 2, "Freight surcharge")
  inv-2310  net total + VAT does not equal gross total; delta 900.00
```

## Results

Measured on 76 real invoices with human ground truth. Full method and reproduction
in [EVALUATION.md](EVALUATION.md).

| | |
|---|---|
| False positives on real invoices | **0 / 76** |
| Planted arithmetic errors caught | **583 / 583** |
| Smallest error reliably caught | **5 cents** |
| Real annotation errors found in the public dataset | **2** |

That last row is the one worth dwelling on. Running the audit over the ground truth
of a public dataset used to train extraction models surfaced two mislabeled records
— one column shift, one stray digit — with no model in the loop.

## What it cannot do

Arithmetic validates only figures that participate in an identity:

- Vendor names, addresses, tax IDs, IBANs and descriptions are unverifiable this way
- If every amount is scaled by the same factor, every identity still closes
- Errors below one cent are invisible by design, so that ordinary rounding does not
  flag every legitimate invoice

A clean audit means the document is internally consistent. Not that the extraction is
right, and not that the charge is owed.

## Install

```bash
git clone https://github.com/Jessmatth/invoice-auditor ~/.claude/skills/invoice-auditor
```

Then hand Claude an invoice. Requires Python 3.9+; the verifier uses only the
standard library.

## Use directly

```bash
python3 scripts/verify.py extracted.json          # audit one extraction
python3 scripts/verify.py --dir out/ --json       # audit a batch
python3 scripts/evaluate.py --seed 7              # reproduce the evaluation
```

## Layout

```
SKILL.md                 the skill
scripts/verify.py        deterministic arithmetic audit, no model, stdlib only
scripts/evaluate.py      plants known corruptions, measures detection per class
references/schema.json   extraction schema
tests/corpus/            76 invoices + human ground truth
eval/results.json        latest evaluation run
EVALUATION.md            method, results, and the limitations
```

## Why the design is this way

The verifier has no model in it and makes no judgement calls, so its output does not
drift between runs or between model versions. That is the point: it is the fixed
reference the extraction is measured against. Any change to it is scored against the
corpus before and after, and both numbers go in `EVALUATION.md`. A change that
improves nothing measurable does not ship.

## Corpus and attribution

The evaluation corpus is 76 invoices from
[`katanaml-org/invoices-donut-data-v1`](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1),
MIT licensed. Ground truth JSON is vendored in `tests/corpus/truth/`. The page
images are 54MB and are not — fetch them with:

```bash
python3 scripts/fetch_corpus.py
```

The two annotation errors documented in [EVALUATION.md](EVALUATION.md) were found in
that dataset by this tool and are reported here for reproducibility, not as a
criticism of it; a 2.6% annotation error rate is unremarkable for hand-labeled
document data, which is rather the point.
