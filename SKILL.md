---
name: invoice-auditor
description: Extract invoices and receipts into structured data, then prove the extraction is correct by re-deriving every number that can be re-derived. Reports a flagged exception list instead of a confident guess. Use when the user provides invoices, receipts, bills, or accounts-payable documents, or mentions parse invoice, extract receipt, invoice to JSON, invoice to CSV, pull line items, AP processing, check invoice totals, verify an invoice, or reconcile a bill.
---

# Invoice Auditor

Extraction is the easy half. This skill exists for the hard half: knowing when the
extraction is wrong.

An invoice line carries five numbers — quantity, unit price, net amount, VAT rate,
gross amount — of which only three are independent. The document over-determines
itself, and that redundancy is checkable by arithmetic with no model in the loop.
Use it. Never report a figure as correct because it looked correct.

## The rule

**Never emit an extraction without running `scripts/verify.py` over it.** A number
that has not been cross-checked is a guess, and a guess reported with confidence is
the failure mode this skill exists to prevent. Self-reported confidence scores are
not evidence; the model that misread a total will also feel sure about it.

## Workflow

1. **Read the document.** PDF, image, or scan. Note the page count, whether the text
   layer is extractable, and the currency and decimal convention in use.

2. **Extract to the schema** in `references/schema.json`. Rules that matter:
   - Capture *every* numeric column present on each line, even when it looks
     redundant. The redundancy is what makes verification possible — dropping the
     net column because gross is present destroys a check.
   - Transcribe figures exactly as printed. Do not normalise, round, or "fix"
     anything. `16 800,00` is recorded as `16 800,00`; the verifier parses it.
   - Use `null` for a value that is genuinely absent. Never substitute a plausible
     one — the verifier can often recover a missing value and will say so, but it
     cannot recover from an invented one.
   - Record `page` and a bounding hint for each line so a flag is traceable back to
     the document.

3. **Run the verifier.**
   ```bash
   python3 scripts/verify.py extracted.json
   ```

4. **Act on the result.**
   - `clean` — every identity closed. Report the data.
   - `flagged` — report the data *with the findings attached*. Name the line and
     field. Do not quietly correct it; a mismatch means either the extraction is
     wrong or the invoice is wrong, and the user needs to know which.
   - `unverifiable` — too few numbers to cross-check anything. Say so plainly. This
     is not the same as correct.

5. **Re-read before re-guessing.** When a line is flagged, go back to that region of
   the document and look again. Most flags are a misread column or a lost thousands
   separator, and a second look resolves them. Only report a genuine invoice error
   once the extraction has been confirmed against the source.

## What the verifier checks

| Rule | Check |
|---|---|
| `L1_line_closes` | quantity × unit price, and gross ÷ (1 + VAT), both equal the stated net |
| `L2_route_conflict` | net is absent and the two derivations of it disagree — pinpoints the bad field |
| `L3_recovered_uncorroborated` | net was absent and recovered from a single route, with nothing to confirm it |
| `L4_line_vat` | net × (1 + VAT) equals the stated gross |
| `D1_net_total` | line net amounts sum to the stated net total |
| `D2_gross_total` | line gross amounts sum to the stated gross total |
| `D3_total_identity` | net total + VAT total = gross total |
| `D4_total_unverifiable` | a total could not be checked, and why |

Tolerance is one cent per independently rounded term, so legitimate rounding never
raises a flag.

## What it cannot check

Arithmetic validates only figures that participate in an identity. These pass
verification while still being wrong, and the skill must not imply otherwise:

- **Vendor, customer, addresses, tax IDs, IBANs, descriptions.** No arithmetic
  relationship exists. Verify these by re-reading, never by inference.
- **Uniformly scaled figures.** If every amount is wrong by the same factor, every
  identity still closes.
- **Errors under one cent.** Measured: a one-cent error is caught 0% of the time, a
  five-cent error 100%. This is the tolerance floor, by design.
- **Whether the invoice is legitimate.** Arithmetic that closes says the document is
  internally consistent, not that the charge is owed, correctly priced, or real.

State these limits when reporting results. A clean audit is a narrow claim.

## Output

Return the extraction and the audit together. The exception list is the deliverable —
for a batch, lead with the flagged documents and summarise the rest.

```
47 invoices   44 clean   2 flagged   1 unverifiable

FLAGGED
  inv-2291  line 3: quantity x unit price = 1,240.00 but stated net is 1,420.00
            (digit transposition; page 2, "Freight surcharge")
  inv-2310  net total + VAT does not equal gross total; delta 900.00

UNVERIFIABLE
  inv-2288  totals block only, no line items — nothing to cross-check
```

## Evaluating a change

`scripts/evaluate.py` plants known corruptions in a clean corpus and measures the
detection rate per class, against real invoices with human ground truth in
`tests/corpus/`. Run it before and after any change to the verifier and record both
numbers in `EVALUATION.md`. A change that improves nothing measurable does not ship.
