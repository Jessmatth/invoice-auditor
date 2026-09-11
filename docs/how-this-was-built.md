# How this was built, and what I got wrong

A decision trail. The interesting parts are the places where the work turned out
to be wrong and how that surfaced, so those are kept rather than tidied away.

## Why invoices

Not because invoice extraction is underserved. It is crowded. Invoices got picked
because of one property most document types lack: **the arithmetic closes.**

A line carries five numbers, quantity, unit price, net, VAT rate and gross, of which
only three are independent. The document over-determines itself. That means a wrong
extraction is provably wrong, with no human judgement and no labels, which in turn
means the tool can have a real accuracy number instead of a plausible-sounding one.

Everything else followed from that choice. The selection rule was: build only where
there is a deterministic check the model cannot fake.

## Testing the checker before trusting it

The first thing the verifier ran against was the corpus ground truth, not a model's
output. If a checker cannot agree with known-correct data, nothing it says later is
worth anything.

It flagged 4 documents out of 76. Each one was opened and read against the source
image. All four were real errors in the dataset's human annotations, not false
positives: two incomplete labels, one column shift where the net worth had been filed
in the price column, and one stray digit in a total.

That was the moment the approach justified itself. A public dataset that people train
extraction models on had bad labels, and arithmetic found them with no model in the
loop.

## The first version blamed the wrong thing

v1 reported those flags at the document level: *"line net amounts do not sum to the
stated net total."* True, and useless. It gave the user nowhere to look.

v2 reconciles each line through two independent routes, `quantity × unit price` and
`gross ÷ (1 + VAT)`. When a value is missing and both routes agree, it is recovered
and the document verifies. When they disagree, the finding names the field:

> line 1: net amount is absent and the two ways of deriving it disagree
> (quantity × unit price = 25,200.00, gross ÷ (1 + VAT) = 8,400.00);
> at least one input field on this line is wrong

Two false alarms removed, 228 additional checks enabled, 98.9% to 99.7%. Both numbers
are in `EVALUATION.md`, because an improvement claim without a before is a slogan.

## Publishing the floor instead of claiming 100%

Planted-error detection came out at 583 of 583, which is a suspiciously clean number.
It is clean because every corruption planted moves a figure that participates in an
identity by more than the tolerance, so the identity has to break. The number worth
trusting is the one underneath it.

So the tolerance floor got probed deliberately: a one-cent error is caught **0%** of
the time, a five-cent error 100%. Sub-cent discrepancies are invisible by design,
because without that allowance ordinary rounding would flag most legitimate invoices.

Three corruption classes were also added that arithmetic provably *cannot* catch, and
kept in the evaluation as a control: replacing a vendor name, replacing a description,
and scaling every amount by the same factor. All three pass verification while still
being wrong. Reporting a detection rate without that control would have been dishonest.

## Two questions that changed the work

Both came from review, and both found something real.

**"VAT is a British tax. Were all the invoices from the UK?"**

Checking rather than answering from memory turned up that the corpus is synthetic and
incoherent: 74 British IBANs, US addresses across 49 states, US SSN-shaped tax IDs,
dollar amounts written with European decimal commas, and 10% VAT on 300 of 300 line
items across 3 templates. No jurisdiction issues an invoice like that.

Calling those "76 real invoices" in the README had been wrong, and it was corrected.
The larger problem was underneath: **nothing in the corpus exercised a mixed-rate
invoice, a zero-rated line, or a US sales-tax invoice with no VAT column at all.**
Eight fixtures with hand-computed expected outcomes were added to cover those. All
eight passed, because the checks are structural identities rather than rate-specific
formulas, but that was assumption until it was measured.

**"So how do you account for sales tax?"**

Measuring instead of asserting showed a real asymmetry. A two-line VAT invoice runs
9 checks. The same invoice under US sales tax runs 4, because VAT states a rate on
every line and sales tax is a single document-level number with no redundancy behind
it. Inflating the tax and adjusting the total passes every identity.

The earlier "8 of 8 passed" claim had been true and shallow. Three things shipped in
response: the audit now reports the tax model and the effective rate and warns when
the tax is uncorroborated; `--state TX` checks the effective rate against that state's
maximum possible combined rate; and `--expect-rate` checks a known rate exactly. The
state ceiling is an error because it is a hard bound, while a rate below the state
floor is only a warning, because exempt lines legitimately lower it.

## The second corpus found two bugs in the tool

The synthetic corpus could not show what real documents do, so CORD was added: 100
real photographed Indonesian receipts, Rupiah, no VAT column, service charges,
discounts, and both `,` and `.` used as thousands separators.

It broke the tool twice.

`Rp. 111,000` parsed to `111.000`. The currency stripper removed `Rp` and the space
but left the period from the abbreviation, producing `.111,000`, which the separator
heuristic then read as a European decimal. **Silently dividing an amount by 1000 is
exactly the error class this tool exists to catch**, and it was in the tool. Fixed,
and 30 parser regression tests added, since there had been none.

Then: 30 of the 100 receipts price their lines *after* tax, so the items sum to the
grand total rather than the pre-tax subtotal. The verifier assumed tax-exclusive
pricing universally and reported a false mismatch on every one. It now accepts
whichever convention reconciles. CORD went from 67 clean to 83, and 18 documents
moved out of `unverifiable`.

Neither bug was visible in the synthetic corpus, because one generator producing one
layout cannot disagree with itself.

## What I would do differently

**Start with two corpora.** Every real defect in this tool was found by the second
one. The first corpus measured how well the checker agreed with itself.

**Write the parser tests first.** The parser was the highest-risk component from the
beginning, being the one place where a silent factor-of-1000 error could originate,
and it was the last thing to get tests.

**State the corpus composition up front.** The synthetic-monoculture problem was
knowable on day one by looking at the data, and it took an outside question to surface
it. A corpus section belongs at the top of an evaluation, not in an appendix.

## Honest note on how it was written

This was built in a working session with Claude Code, which wrote most of the code and
the first drafts of the documentation. The direction, the review questions that
changed the work, and the decisions about what to publish were mine. The commit
history records the co-authorship.

I would rather say that plainly than have it inferred. For roles in this space, how
someone directs and reviews AI-assisted work seems more interesting than whether they
typed the lines themselves.
