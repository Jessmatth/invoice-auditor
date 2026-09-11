#!/usr/bin/env python3
"""
test_parsing.py - number parsing regression tests.

Real corpora disagree about separators. This dataset writes 444,60 for four
hundred and forty four point six; CORD writes 28.182 and 11,000 for twenty eight
thousand and eleven thousand, using '.' and ',' as thousands separators in the
same corpus. Getting this wrong silently changes amounts by a factor of 1000,
which is exactly the class of error the audit exists to catch, so the parser
itself needs tests.

    python3 scripts/test_parsing.py
"""
import os, sys
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import parse_amount, parse_rate

AMOUNTS = [
    # European decimal comma (katanaml corpus)
    ("444,60",        "444.60",   "European decimal comma"),
    ("2,00",          "2",        "European decimal comma, whole number"),
    ("$ 889,20",      "889.20",   "currency symbol and space"),
    ("16 800,00",     "16800.00", "space-grouped thousands"),
    ("$25 329,96",    "25329.96", "symbol, space grouping, decimal comma"),
    # US convention
    ("1,234.56",      "1234.56",  "US thousands comma, decimal point"),
    ("$1,234.56",     "1234.56",  "US with symbol"),
    ("208.97",        "208.97",   "plain decimal point"),
    # Indonesian / CORD: both separators used as thousands
    ("11,000",        "11000",    "comma as thousands (CORD)"),
    ("28.182",        "28182",    "dot as thousands (CORD)"),
    ("194,000",       "194000",   "comma as thousands, six figures"),
    ("Rp. 111,000",   "111000",   "currency abbreviation with its own period"),
    # European thousands dot with decimal comma
    ("1.234,56",      "1234.56",  "European thousands dot"),
    # signs and edge cases
    ("-200.00",       "-200.00",  "negative"),
    ("-$200.00",      "-200.00",  "negative with symbol"),
    ("0",             "0",        "zero"),
    ("5",             "5",        "single digit"),
    (None,            None,       "None"),
    ("",              None,       "empty string"),
    ("n/a",           None,       "non-numeric"),
    ("$",             None,       "symbol only"),
    ("-",             None,       "sign only"),
    (1234.5,          "1234.5",   "float passthrough"),
]

RATES = [
    ("10%",   "0.10",  "percent sign"),
    ("0%",    "0",     "zero percent"),
    ("20%",   "0.20",  "percent sign"),
    ("8.25%", "0.0825","fractional percent"),
    (10,      "0.10",  "bare number over 1"),
    ("0,1",   "0.10",  "European decimal fraction"),
    (None,    None,    "None"),
]

def run(name, cases, fn):
    print(f"\n{name}")
    print(f"  {'input':<18}{'expected':<12}{'actual':<12}result")
    fails = 0
    for raw, exp, desc in cases:
        got = fn(raw)
        ok = (got is None and exp is None) or (got is not None and exp is not None and got == Decimal(exp))
        fails += not ok
        print(f"  {repr(raw)[:17]:<18}{str(exp):<12}{str(got):<12}{'PASS' if ok else 'FAIL'}   {desc}")
    return fails

if __name__ == "__main__":
    f = run("amounts", AMOUNTS, parse_amount) + run("rates", RATES, parse_rate)
    total = len(AMOUNTS) + len(RATES)
    print(f"\n{total-f} passed, {f} failed")
    sys.exit(1 if f else 0)
