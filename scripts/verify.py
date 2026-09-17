#!/usr/bin/env python3
"""
verify.py - deterministic arithmetic audit of an extracted invoice.

The extraction step (a model, or a human annotator, reading the document) is
not trusted. This module re-derives every number that can be re-derived from
the others and reports where the document fails to close. There is no model in
here and it makes no judgement calls.

An invoice line carries five numbers - quantity, unit price, net amount, VAT
rate and gross amount - of which only three are independent. That redundancy is
the whole basis of the audit: when a value is missing it can usually be
recovered, and when two independent derivations of the same value disagree,
something upstream is wrong and we can say precisely which field it is.

Usage:
    python3 verify.py extracted.json
    python3 verify.py --dir path/ [--json]
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys
from dataclasses import dataclass, asdict, field
from decimal import Decimal, InvalidOperation

__version__ = "4.2"

# ---------------------------------------------------------------- numbers --

_CURRENCY = re.compile(r"[^\d,.\-]")

def parse_amount(raw):
    """Parse a money or quantity token into Decimal, handling both the US
    (1,234.56) and European (1.234,56) conventions, plus space-grouped
    (16 800,00) which this corpus uses heavily."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    s = _CURRENCY.sub("", str(raw)).strip()
    # A currency abbreviation can leave its own punctuation behind ("Rp. 111,000"
    # strips to ".111,000", which then reads as a European decimal). Keep only
    # the numeric core: an optional sign, then digits and separators, ending in
    # a digit.
    m = re.search(r"-?\d[\d.,]*\d|-?\d", s)
    if not m:
        return None
    s = m.group(0)
    has_dot, has_com = "." in s, "," in s
    if has_dot and has_com:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif has_com:
        frag = s.split(",")
        s = s.replace(",", ".") if (len(frag) == 2 and len(frag[1]) in (1, 2)) else s.replace(",", "")
    elif has_dot:
        frag = s.split(".")
        if len(frag) > 2 or (len(frag) == 2 and len(frag[1]) == 3 and len(frag[0]) <= 3):
            s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None

def parse_rate(raw):
    """'10%' -> 0.10 ; 10 -> 0.10 ; '0,1' -> 0.10"""
    if raw is None:
        return None
    v = parse_amount(str(raw))
    if v is None:
        return None
    return v / Decimal(100) if ("%" in str(raw) or v > 1) else v

# ------------------------------------------------------------ rate table --

_RATES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "references", "us_sales_tax_rates.json")
_RATES = None

def us_rates():
    """US state sales-tax brackets, loaded lazily. Returns None if unavailable."""
    global _RATES
    if _RATES is None:
        try:
            _RATES = json.load(open(_RATES_PATH))
        except Exception:
            _RATES = {}
    return _RATES or None

# ---------------------------------------------------------------- results --

@dataclass
class Finding:
    rule: str
    severity: str                 # error | warning | info
    field: str | None
    message: str
    expected: str | None = None
    found: str | None = None
    delta: str | None = None
    line: int | None = None

@dataclass
class Audit:
    doc_id: str | None
    status: str = "clean"         # clean | flagged | unverifiable
    checks_run: int = 0
    checks_passed: int = 0
    findings: list = field(default_factory=list)
    recovered: list = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    tax: dict = field(default_factory=dict)
    verifier_version: str = __version__

    def to_dict(self):
        d = asdict(self)
        d["findings"] = [asdict(f) if isinstance(f, Finding) else f for f in self.findings]
        return d

CENT = Decimal("0.01")
def tol(terms=1):
    """Each independently rounded term can be off by half a cent; allow a full
    cent per term so legitimate rounding never trips a flag."""
    return CENT * Decimal(max(1, terms))
def close(a, b, t):  return abs(a - b) <= t
def fmt(d):          return None if d is None else f"{d:,.2f}"

FIELDS = {
    "qty":   ("item_qty", "quantity", "qty"),
    "price": ("item_net_price", "unit_price", "price"),
    "net":   ("item_net_worth", "amount", "net", "line_total"),
    "gross": ("item_gross_worth", "gross", "gross_amount"),
    "rate":  ("item_vat", "tax_rate", "vat", "vat_rate"),
}

def pick(d, key):
    for k in FIELDS[key]:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

# ------------------------------------------------------------------ audit --

def audit_line(it, i, a):
    """Reconcile one line. Returns (net, gross) using recovered values where
    the source was silent but the value is unambiguously derivable."""
    qty   = parse_amount(pick(it, "qty"))
    price = parse_amount(pick(it, "price"))
    net   = parse_amount(pick(it, "net"))
    gross = parse_amount(pick(it, "gross"))
    rate  = parse_rate(pick(it, "rate"))

    def check(ok, f):
        a.checks_run += 1
        if ok: a.checks_passed += 1
        else:  a.findings.append(f)

    # Two independent routes to the net amount.
    routes = {}
    if qty is not None and price is not None:
        routes["quantity x unit price"] = qty * price
    if gross is not None and rate is not None and (Decimal(1) + rate) != 0:
        routes["gross / (1 + VAT)"] = gross / (Decimal(1) + rate)

    if net is not None:
        # Stated. Check every available route against it.
        for label, derived in routes.items():
            check(close(derived, net, tol(2)), Finding(
                "L1_line_closes", "error", "net",
                f"line {i}: {label} does not equal the stated net amount",
                fmt(derived), fmt(net), fmt(net - derived), i))
    elif len(routes) >= 2:
        # Not stated, two routes available - they must agree with each other.
        (la, va), (lb, vb) = list(routes.items())[:2]
        if close(va, vb, tol(3)):
            net = va
            a.recovered.append({"line": i, "field": "net", "value": fmt(net),
                                "method": la, "corroborated_by": lb})
            a.checks_run += 1; a.checks_passed += 1
        else:
            a.checks_run += 1
            a.findings.append(Finding(
                "L2_route_conflict", "error", "net",
                f"line {i}: net amount is absent and the two ways of deriving it disagree "
                f"({la} = {fmt(va)}, {lb} = {fmt(vb)}); at least one input field on this line is wrong",
                fmt(va), fmt(vb), fmt(vb - va), i))
    elif len(routes) == 1:
        label, val = next(iter(routes.items()))
        net = val
        a.recovered.append({"line": i, "field": "net", "value": fmt(net),
                            "method": label, "corroborated_by": None})
        a.findings.append(Finding(
            "L3_recovered_uncorroborated", "warning", "net",
            f"line {i}: net amount was absent and was recovered from {label}; no second "
            f"route available to corroborate it", fmt(net), None, None, i))

    # Gross, given a net and a rate.
    if net is not None and rate is not None:
        exp = net * (Decimal(1) + rate)
        if gross is not None:
            check(close(exp, gross, tol(2)), Finding(
                "L4_line_vat", "error", "gross",
                f"line {i}: net plus VAT does not equal the stated gross amount",
                fmt(exp), fmt(gross), fmt(gross - exp), i))
        else:
            gross = exp
            a.recovered.append({"line": i, "field": "gross", "value": fmt(gross),
                                "method": "net x (1 + VAT)", "corroborated_by": None})

    if qty is not None and qty <= 0:
        a.findings.append(Finding("S1_nonpositive_qty", "warning", "qty",
                                  f"line {i}: quantity is {fmt(qty)}", line=i))
    if price is not None and price < 0:
        a.findings.append(Finding("S2_negative_price", "warning", "price",
                                  f"line {i}: unit price is negative", line=i))
    return net, gross


def audit(doc, doc_id=None, expect_rate=None, state=None):
    doc = doc.get("gt_parse", doc)
    a = Audit(doc_id=doc_id)
    items   = doc.get("items") or doc.get("line_items") or []
    summary = doc.get("summary") or doc.get("totals") or doc

    def check(ok, f):
        a.checks_run += 1
        if ok: a.checks_passed += 1
        else:  a.findings.append(f)

    nets, grosses = [], []
    for i, it in enumerate(items, 1):
        n, g = audit_line(it, i, a)
        if n is not None: nets.append(n)
        if g is not None: grosses.append(g)

    t_net   = parse_amount(summary.get("total_net_worth")   or summary.get("subtotal"))
    t_vat   = parse_amount(summary.get("total_vat")         or summary.get("tax_amount"))
    t_gross = parse_amount(summary.get("total_gross_worth") or summary.get("total"))
    n_terms = max(1, len(items)) + 1
    complete = len(nets) == len(items) and len(items) > 0

    # Line prices may be quoted before tax (lines sum to the subtotal) or after
    # it (lines sum to the grand total). Retail in much of Asia and Europe does
    # the latter. Assuming one convention reports a false mismatch on the other,
    # so accept whichever reconciles and record which it was.
    pricing = None
    if complete and (t_net is not None or t_gross is not None):
        exp = sum(nets)
        fits_sub = t_net   is not None and close(exp, t_net,   tol(n_terms))
        fits_tot = t_gross is not None and close(exp, t_gross, tol(n_terms))
        if fits_sub:
            pricing = "tax_exclusive"
            a.checks_run += 1; a.checks_passed += 1
        elif fits_tot:
            pricing = "tax_inclusive"
            a.checks_run += 1; a.checks_passed += 1
        else:
            target, label = ((t_net, "net total") if t_net is not None
                             else (t_gross, "gross total"))
            check(False, Finding(
                "D1_net_total", "error", "total_net_worth",
                f"line amounts sum to neither the stated {label} nor the grand total",
                fmt(exp), fmt(target), fmt(target - exp)))
    elif t_net is not None and items:
        a.findings.append(Finding(
            "D4_total_unverifiable", "warning", "total_net_worth",
            f"net total could not be checked: {len(items)-len(nets)} of {len(items)} lines "
            f"have no net amount and none could be recovered"))

    if len(grosses) == len(items) and items and t_gross is not None:
        exp = sum(grosses)
        check(close(exp, t_gross, tol(n_terms)), Finding(
            "D2_gross_total", "error", "total_gross_worth",
            "line gross amounts do not sum to the stated gross total",
            fmt(exp), fmt(t_gross), fmt(t_gross - exp)))

    # A real receipt rarely goes straight from subtotal to total. Discounts and
    # service charges sit in between, and a checker that ignores them reports a
    # false mismatch on every discounted document.
    t_disc = parse_amount(summary.get("discount_price") or summary.get("discount")
                          or summary.get("total_discount"))
    t_svc  = parse_amount(summary.get("service_price") or summary.get("service_charge")
                          or summary.get("etc"))

    if t_net is not None and t_gross is not None:
        # A discount may be written as a positive magnitude to subtract or as a
        # negative adjustment. Both mean the same thing, so normalise.
        parts, names = [], []
        if t_disc is not None: parts.append(-abs(t_disc));  names.append("less discount")
        if t_svc  is not None: parts.append(t_svc);         names.append("plus service charge")
        if t_vat  is not None: parts.append(t_vat);         names.append("plus tax")
        exp = t_net + sum(parts)

        if parts or t_net == t_gross:
            desc = " ".join(["net total"] + names) if names else "net total"
            check(close(exp, t_gross, tol(2 + len(parts))), Finding(
                "D3_total_identity", "error", "total_gross_worth",
                f"{desc} does not equal the gross total",
                fmt(exp), fmt(t_gross), fmt(t_gross - exp)))
        else:
            a.findings.append(Finding(
                "D5_unexplained_gap", "warning", "total_gross_worth",
                f"net total and gross total differ by {fmt(t_gross - t_net)} and no tax, "
                f"discount or service charge was captured to account for it"))

    # ---- tax model ------------------------------------------------------
    # VAT puts a rate on every line, which gives a second independent route to
    # each net amount and makes the tax figure itself cross-checkable. US sales
    # tax is a single document-level number with no redundancy behind it. The
    # audit is materially weaker in that case and has to say so rather than
    # reporting a quiet "clean".
    line_rates = [parse_rate(pick(it, "rate")) for it in items]
    rated = [r for r in line_rates if r is not None]
    doc_rate = parse_rate(summary.get("vat_rate") or summary.get("tax_rate")
                          or summary.get("rate"))
    eff = None
    taxable_base = None
    if t_net is not None:
        taxable_base = t_net - (abs(t_disc) if t_disc is not None else Decimal(0))
    if taxable_base not in (None, 0) and t_vat is not None:
        eff = (t_vat / taxable_base)

    if items and len(rated) == len(items):
        model, checked = "per_line_rate", True
    elif doc_rate is not None:
        model, checked = "document_rate", True
        exp = taxable_base * (Decimal(1) + doc_rate) if taxable_base is not None else None
        if exp is not None and t_gross is not None:
            check(close(exp, t_gross, tol(2)), Finding(
                "T1_document_rate", "error", "total_gross_worth",
                f"stated tax rate of {doc_rate*100:.3g}% applied to the net total "
                f"does not produce the stated gross total",
                fmt(exp), fmt(t_gross), fmt(t_gross - exp)))
    elif t_vat is not None:
        model, checked = "document_amount", False
    else:
        model, checked = "none", False

    if model == "document_amount":
        if expect_rate is not None:
            er = parse_rate(expect_rate)
            exp = (taxable_base * er) if taxable_base is not None else None
            if exp is not None:
                checked = True
                check(close(exp, t_vat, tol(2)), Finding(
                    "T2_expected_rate", "error", "tax_amount",
                    f"tax does not match the expected rate of {er*100:.4g}%",
                    fmt(exp), fmt(t_vat), fmt(t_vat - exp)))
        elif state is not None and eff is not None:
            tbl = us_rates()
            info = (tbl or {}).get("states", {}).get(str(state).upper())
            if info is None:
                a.findings.append(Finding(
                    "T5_unknown_state", "warning", "tax_amount",
                    f"no sales-tax bracket on file for state {state!r}"))
            else:
                pct = eff * Decimal(100)
                ceiling = Decimal(str(info["max_combined"]))
                floor   = Decimal(str(info["min_expected"]))
                checked = True
                # The ceiling is a hard bound: no address in the state can
                # legally exceed state rate plus the highest local rate.
                check(pct <= ceiling + Decimal("0.01"), Finding(
                    "T4_above_state_ceiling", "error", "tax_amount",
                    f"effective tax rate of {pct:.4g}% exceeds the maximum possible "
                    f"combined rate in {info['name']} ({ceiling}% = {info['state_rate']}% state "
                    f"plus up to {info['max_local_rate']}% local)",
                    f"<= {ceiling}%", f"{pct:.4g}%", None))
                # The floor is not a bound: exempt lines legitimately drag the
                # effective rate down, so this can only ever be a warning.
                if pct < floor - Decimal("0.01"):
                    a.findings.append(Finding(
                        "T6_below_state_floor", "warning", "tax_amount",
                        f"effective tax rate of {pct:.4g}% is below the {info['name']} state "
                        f"rate of {floor}%. Legitimate if some lines are exempt, worth a look "
                        f"if they are not"))
        else:
            a.findings.append(Finding(
                "T3_tax_uncorroborated", "warning", "tax_amount",
                "tax is stated only as a document-level amount, so the arithmetic "
                "confirms it is consistent with the totals but cannot confirm the "
                "rate is correct"
                + (f"; the effective rate is {eff*100:.4g}%" if eff is not None else "")
                + ". Pass --expect-rate to check it."))

    a.tax = {
        "line_pricing": pricing,
        "model": model,
        "rate_verified": checked,
        "effective_rate": (f"{eff*100:.4g}%" if eff is not None else None),
        "line_rates": sorted({f"{r*100:.4g}%" for r in rated}) or None,
    }

    a.coverage = {
        "n_items": len(items),
        "lines_fully_reconciled": len(nets),
        "values_recovered": len(a.recovered),
        "has_net_total": t_net is not None,
        "has_vat_total": t_vat is not None,
        "has_gross_total": t_gross is not None,
    }
    errs = [f for f in a.findings if f.severity == "error"]
    a.status = "unverifiable" if a.checks_run == 0 else ("flagged" if errs else "clean")
    return a

# ------------------------------------------------------------------- cli ---

def main():
    ap = argparse.ArgumentParser(description="Deterministic arithmetic audit of extracted invoices")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="summary line only")
    ap.add_argument("--state", metavar="XX",
                    help="two-letter US state code. Checks the effective tax rate against "
                         "that state's maximum possible combined rate.")
    ap.add_argument("--expect-rate", metavar="R",
                    help="known tax rate for this jurisdiction, e.g. 8.25%% or 0.0825. "
                         "Turns an unverifiable document-level tax amount into a real check.")
    args = ap.parse_args()

    paths = list(args.files)
    if args.dir:
        paths += sorted(glob.glob(f"{args.dir.rstrip('/')}/{args.glob}"))
    if not paths:
        ap.error("no input files")

    results = [audit(json.load(open(p)), p.split("/")[-1].rsplit(".", 1)[0],
                     expect_rate=args.expect_rate, state=args.state).to_dict() for p in paths]

    if args.json:
        print(json.dumps(results, indent=2)); return

    tally = {"clean": 0, "flagged": 0, "unverifiable": 0}
    for r in results:
        tally[r["status"]] += 1
        # a clean document can still carry warnings, and a warning the user
        # never sees is worthless; print anything with findings
        if args.quiet or (r["status"] == "clean" and not r["findings"]):
            continue
        print(f"\n{r['doc_id']}  [{r['status']}]  {r['checks_passed']}/{r['checks_run']} checks passed")
        for f in r["findings"]:
            loc = f" line {f['line']}" if f.get("line") else ""
            fld = f" .{f['field']}" if f.get("field") else ""
            print(f"   {f['severity'].upper():<8} {f['rule']}{loc}{fld}")
            print(f"            {f['message']}")
            if f.get("expected") and f.get("found"):
                print(f"            expected {f['expected']}  found {f['found']}  delta {f['delta']}")
        for rec in r["recovered"]:
            c = f", corroborated by {rec['corroborated_by']}" if rec["corroborated_by"] else ""
            print(f"   RECOVERED line {rec['line']} .{rec['field']} = {rec['value']} via {rec['method']}{c}")

    models = {}
    for r in results:
        models[r["tax"].get("model", "none")] = models.get(r["tax"].get("model", "none"), 0) + 1
    unver = sum(1 for r in results if not r["tax"].get("rate_verified")
                and r["tax"].get("model") in ("document_amount",))

    tot, checks = len(results), sum(r["checks_run"] for r in results)
    passed = sum(r["checks_passed"] for r in results)
    rec = sum(len(r["recovered"]) for r in results)
    print(f"\n{'='*66}")
    print(f"{tot} documents   {tally['clean']} clean   {tally['flagged']} flagged   {tally['unverifiable']} unverifiable")
    print(f"{checks} arithmetic checks   {passed} passed   {checks-passed} failed"
          + (f"   ({100*passed/checks:.1f}%)" if checks else ""))
    print(f"{rec} missing values recovered by derivation")
    print(f"tax model: " + ", ".join(f"{k} x{v}" for k, v in sorted(models.items())))
    if unver:
        print(f"{unver} document(s) with a tax amount the arithmetic cannot corroborate; "
              f"pass --expect-rate to check it")

if __name__ == "__main__":
    main()
