# Worked example

A blind run of the full skill (extract, then audit) on `test-004`, a 7-line
invoice. The ground truth was held out until after the audit reported.

## 1. Extract

The model reads the page and transcribes every numeric column exactly as printed,
including the space-grouped thousands (`1 199,97`). No normalising, no rounding.
Result: [`worked-example-extraction.json`](worked-example-extraction.json).

## 2. Audit

```bash
$ python3 scripts/verify.py docs/worked-example-extraction.json

1 documents   1 clean   0 flagged   0 unverifiable
24 arithmetic checks   24 passed   0 failed   (100.0%)
```

Twenty-four independent checks: for each of the 7 lines, `quantity × unit price`
and `gross ÷ (1 + VAT)` both against the stated net, plus `net × (1 + VAT)` against
the stated gross; then at document level, line nets summing to the net total, line
grosses to the gross total, and `net total + VAT = gross total`.

## 3. Confirm

Only now compare against the held-out ground truth:

```
line-item count: mine=7 truth=7
numeric cells compared: 38   mismatches: 0   agreement: 100.0%
```

The audit said clean, and clean is what it was.

That is the whole point. The audit reached that verdict from the document's internal
consistency alone, with no access to ground truth, which is the situation you are
actually in when processing an invoice nobody has checked.
