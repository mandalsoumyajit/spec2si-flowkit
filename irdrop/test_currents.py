#!/usr/bin/env python3
"""Negative controls for the operating-point reader.

    python3 irdrop/test_currents.py

Every case is one where the WRONG behaviour produces a believable number
rather than an error. That is the whole point of this module: a missing
supply, a mis-scaled prefix and a flipped sign all give a grid that
solves cleanly and reports a drop that is too small.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from currents import (Currents, CurrentError, scale,          # noqa: E402
                      parse_oppoint_text)


def _close(a, b):
    """⚠️ Relative, not exact. `748.105 * 1e-18` and the literal
    `748.105e-18` are not bit-identical -- one is a multiplication and the
    other is parsed -- so an `==` here fails on the last mantissa bit and
    says nothing about whether the prefix was applied."""
    return abs(a - b) <= 1e-12 * max(abs(a), abs(b), 1e-300)


def t_si_prefix():
    """`27.8321 pA` is not 27.8321. The prefix is on the UNIT token."""
    assert _close(scale("27.8321", "pA"), 27.8321e-12)
    assert _close(scale("748.105", "aF"), 748.105e-18)
    assert _close(scale("284.9", "mV"), 284.9e-3)
    assert _close(scale("554.332e-21", "F"), 554.332e-21)  # already exponent
    assert scale("1.5", "A") == 1.5                      # single char: bare
    assert scale("50", "Ohm") == 50.0                    # multi-char, no prefix
    # the trap this exists for: dropping the prefix is 12 orders of
    # magnitude and still looks like a current
    assert scale("27.8321", "pA") < 1e-9
    print("  ok  SI prefixes read off the unit token, not guessed")


def t_missing_supply_raises():
    """The core rule: absent is not zero."""
    c = Currents("dc", "op1.dc").supply_load("vdd", 1e-3)
    try:
        c.amps("vss")
    except CurrentError as e:
        assert "absent" in str(e), str(e)
        print("  ok  a missing supply raises instead of reading 0")
        return
    raise AssertionError("a missing supply must raise")


def t_require_names_the_gap():
    c = Currents("dc", "op1.dc").supply_load("vdd", 1e-3)
    try:
        c.require(["vdd", "vss", "vref"])
    except CurrentError as e:
        assert "vss" in str(e) and "vref" in str(e), str(e)
        print("  ok  require() names every net with no simulated current")
        return
    raise AssertionError("require() must raise on an uncovered net")


def t_from_values_missing_raises():
    try:
        Currents.from_values({"Vdd:p": -1e-3}, "dc", "op1.dc",
                             want={"vdd": "Vdd:p", "vss": "Vss:p"})
    except CurrentError as e:
        assert "Vss:p" in str(e), str(e)
        print("  ok  a requested-but-unsaved terminal raises")
        return
    raise AssertionError("an unsaved terminal must raise")


def t_sign_magnitude_and_consistency():
    """A source's terminal sign is a bench fact, not a circuit fact --
    but a MIXTURE of signs is a bench fault and must be visible."""
    c = Currents.from_values({"Vdd:p": -1.5e-3, "Vss:p": -0.5e-3},
                             "dc", "op1.dc")
    assert c.amps("Vdd:p") == 1.5e-3, c.amps("Vdd:p")
    assert c.signs_consistent(), "all negative is consistent"
    d = Currents.from_values({"Vdd:p": -1.5e-3, "Vss:p": 0.5e-3},
                             "dc", "op1.dc")
    assert d.amps("Vss:p") == 0.5e-3
    assert not d.signs_consistent(), "a mixture must be reported"
    print("  ok  magnitude taken, sign mixture still reported")


def t_kind_cannot_be_mixed():
    a = Currents("avg", "tran").supply_load("vdd", 1e-3)
    p = Currents("peak", "tran").supply_load("vss", 2e-3)
    try:
        a.merged_with(p)
    except CurrentError as e:
        assert "peak" in str(e) and "avg" in str(e), str(e)
        print("  ok  avg and peak refuse to merge")
        return
    raise AssertionError("mixing kinds must raise")


def t_kind_must_be_named():
    try:
        Currents("whatever", "x")
    except CurrentError:
        print("  ok  an unnamed kind raises")
        return
    raise AssertionError("kind must be one of KINDS")


def t_merge_rejects_duplicates():
    a = Currents("dc", "A").supply_load("vdd", 1e-3)
    b = Currents("dc", "B").supply_load("vdd", 2e-3)
    try:
        a.merged_with(b)
    except CurrentError as e:
        assert "vdd" in str(e), str(e)
        print("  ok  two operating points defining one supply raise")
        return
    raise AssertionError("duplicate supply must raise")


def t_oppoint_text():
    txt = ("Instance: X1\n  id = 27.8321 pA\n  gm = 1.5 mS\n"
           "Instance: X2\n  id = 1.25 uA\n")
    d = parse_oppoint_text(txt)
    assert abs(d["X1"]["id"] - 27.8321e-12) < 1e-24, d
    assert abs(d["X2"]["id"] - 1.25e-6) < 1e-18, d
    assert abs(d["X1"]["gm"] - 1.5e-3) < 1e-15, d
    print("  ok  text operating point parsed with prefixes")


def t_provenance_travels():
    c = Currents.from_values({"Vdd:p": -1e-3}, "avg", "psf/tran.tran",
                             analysis="tran", corner="FF", temp_c=-40)
    p = c.provenance()
    assert p["kind"] == "avg" and p["corner"] == "FF" and p["temp_C"] == -40
    assert p["total_mA"] == 1.0 and p["signs_consistent"] is True
    print("  ok  provenance carries kind, corner, temperature and total")


def main():
    print("[irdrop] operating-point checks")
    for fn in (t_si_prefix, t_missing_supply_raises, t_require_names_the_gap,
               t_from_values_missing_raises, t_sign_magnitude_and_consistency,
               t_kind_cannot_be_mixed, t_kind_must_be_named,
               t_merge_rejects_duplicates, t_oppoint_text,
               t_provenance_travels):
        fn()
    print("[irdrop] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
