#!/usr/bin/env python3
"""Negative controls and closed-form checks for the vendored IR solver.

Offline, no PDK, milliseconds -- so it actually gets run:

    python3 irdrop/test_solver.py

Every case here is one whose right answer is known WITHOUT the solver, by
hand or by Ohm's law. A test that only asserts the solver agrees with
itself would pass against a sign error in the injection convention, which
is the bug most likely to survive review.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solver import Grid, SolverError, series          # noqa: E402


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def t_single_resistor():
    """One load at the end of one resistor: V = I R, by Ohm's law."""
    g = Grid().pin("pad", 1.2).resistor("pad", "load", 2.0).inject_mA(
        "load", 10.0)
    v = g.solve()
    assert close(v["load"], 1.2 - 0.010 * 2.0), v
    r = g.report()
    assert close(r["worst_load"]["drop_mV"], 20.0), r["worst_load"]
    print("  ok  single resistor: 10 mA x 2 ohm = 20.000 mV")


def t_series_shares_current():
    """Two taps on one trunk. The near segment carries BOTH currents --
    the property an EM check on the far segment alone would miss."""
    g = Grid().pin("pad", 1.0)
    series(g, ["pad", "t1", "t2"], [1.0, 1.0], "trunk")
    g.inject_mA("t1", 10.0).inject_mA("t2", 10.0)
    v = g.solve()
    # near segment: 20 mA x 1 ohm = 20 mV; far: 10 mA x 1 ohm = 10 mV
    assert close(v["t1"], 1.0 - 0.020), v
    assert close(v["t2"], 1.0 - 0.030), v
    b = dict((x["label"], x) for x in g.report()["branches"])
    assert close(b["trunk[0]"]["mA"], 20.0), b["trunk[0]"]
    assert close(b["trunk[1]"]["mA"], 10.0), b["trunk[1]"]
    print("  ok  series: near segment carries 20 mA, far 10 mA")


def t_parallel_halves():
    """Two equal paths from pad to load: R/2, so half the drop."""
    g = Grid().pin("pad", 1.0)
    g.resistor("pad", "load", 4.0, "a").resistor("pad", "load", 4.0, "b")
    g.inject_mA("load", 10.0)
    v = g.solve()
    assert close(v["load"], 1.0 - 0.010 * 2.0), v
    print("  ok  parallel: two 4 ohm paths behave as 2 ohm")


def t_sign_convention():
    """A LOAD LOWERS THE VOLTAGE. This is the negative control for the
    injection sign -- a flipped sign gives a load that pushes the rail
    UP, which looks like a fine number and is physically backwards."""
    g = Grid().pin("pad", 1.0).resistor("pad", "n", 1.0).inject_mA("n", 1.0)
    assert g.solve()["n"] < 1.0, "a load must lower the node it draws from"
    print("  ok  sign: a load lowers its node")


def t_ground_grid_rise():
    """Pinned at 0, the same maths gives the ground BOUNCE."""
    g = Grid().pin("gnd", 0.0).resistor("gnd", "n", 2.0).inject_mA("n", -5.0)
    # -5 mA injected = 5 mA flowing INTO the ground node from the block
    assert close(g.solve()["n"], 0.010), g.solve()
    print("  ok  ground grid: 5 mA into 2 ohm rises 10.000 mV")


def t_floating_node_raises():
    """A node with no path to a pin is an OPEN, not a small voltage."""
    g = Grid().pin("pad", 1.0).resistor("pad", "a", 1.0)
    g.resistor("island1", "island2", 1.0).inject_mA("island1", 1.0)
    try:
        g.solve()
    except SolverError as e:
        assert "island1" in str(e) and "island2" in str(e), str(e)
        print("  ok  floating node raises and names it")
        return
    raise AssertionError("a floating island must raise, not solve")


def t_no_pin_raises():
    g = Grid().resistor("a", "b", 1.0).inject_mA("a", 1.0)
    try:
        g.solve()
    except SolverError as e:
        assert "pin" in str(e).lower(), str(e)
        print("  ok  no pin raises")
        return
    raise AssertionError("a network with no reference must raise")


def t_zero_ohm_raises():
    try:
        Grid().resistor("a", "b", 0.0, "merge-me")
    except SolverError as e:
        assert "merge" in str(e), str(e)
        print("  ok  zero-ohm branch raises")
        return
    raise AssertionError("a zero-ohm branch must raise")


def t_mA_conversion():
    """inject_mA must be exactly 1e-3 of inject -- the 1000x error is the
    one guaranteed to produce a believable wrong answer."""
    a = Grid().pin("p").resistor("p", "n", 1.0).inject_mA("n", 1.0).solve()
    b = Grid().pin("p").resistor("p", "n", 1.0).inject("n", 0.001).solve()
    assert close(a["n"], b["n"]), (a, b)
    print("  ok  inject_mA == inject x 1e-3")


def t_scale_invariance():
    """Doubling every resistance doubles every drop, exactly. Catches a
    factoring bug that a single-case test would not."""
    def build(k):
        g = Grid().pin("pad", 1.0)
        series(g, ["pad", "a", "b", "c"], [k * 1.0, k * 2.0, k * 3.0])
        return g.inject_mA("a", 1.0).inject_mA("b", 2.0).inject_mA("c", 3.0)
    v1, v2 = build(1.0).solve(), build(2.0).solve()
    for n in ("a", "b", "c"):
        assert close(1.0 - v2[n], 2.0 * (1.0 - v1[n])), (n, v1, v2)
    print("  ok  drops scale linearly with resistance")


def main():
    print("[irdrop] solver checks")
    for fn in (t_single_resistor, t_series_shares_current, t_parallel_halves,
               t_sign_convention, t_ground_grid_rise, t_floating_node_raises,
               t_no_pin_raises, t_zero_ohm_raises, t_mA_conversion,
               t_scale_invariance):
        fn()
    print("[irdrop] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
