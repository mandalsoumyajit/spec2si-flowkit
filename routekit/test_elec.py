#!/usr/bin/env python3
"""Gates for routekit.elec -- the banded-step case is the load-bearing
one, taken from xt011's measured MET3 failure."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import elec                                  # noqa: E402


# xt011 MET3: coefficient 1.40 below 1.0 um and 1.77 at or above, on a
# 3.12 mA/um base -- the limit JUMPS from 4.368 mA just under 1.000 um
# (3.12*1.40*0.999) to 5.522 at it (3.12*1.77*1.000).
def _met3_imax(w):
    return 3.12 * (1.40 * w if w < 1.0 else 1.77 * w)


def test_banded_step_solves_at_the_edge():
    # 5.036 mA inverts into the 4.368->5.522 gap: no in-band width works,
    # and the 1.000 um band edge plainly carries it. The candidate list
    # includes the edge, as the contract requires.
    cands = [0.9, 0.95, 0.99, 1.0, 1.1]
    assert elec.min_em_width(5.036, _met3_imax, cands) == 1.0


def test_below_the_step_the_narrow_band_answers():
    # 3.0 mA wants 3.12*1.40*w >= 3.0 -> w >= 0.687
    assert elec.min_em_width(3.0, _met3_imax, [0.5, 0.72, 0.8]) == 0.72


def test_no_candidate_refuses_naming_the_current():
    try:
        elec.min_em_width(50.0, _met3_imax, [0.5, 1.0, 1.2])
    except elec.ElecError as e:
        assert "50.0" in str(e) and "strands or layers" in str(e)
    else:
        raise AssertionError("an uncarriable current did not refuse")


def test_min_cuts_ceils_and_refuses_zero_limit():
    assert elec.min_cuts(0.26, 0.015) == 18       # the 0.26 mA tap case
    assert elec.min_cuts(0.001, 0.015) == 1
    try:
        elec.min_cuts(1.0, 0.0)
    except elec.ElecError:
        pass
    else:
        raise AssertionError("a zero per-cut limit did not refuse")


def test_route_resistance_prices_wire_and_vias_separately():
    rs = {"M7": 0.062, "M8": 0.021}.__getitem__
    vr = {"VIA7": 5.0}.__getitem__
    rw, rv = elec.route_resistance(
        [("M7", 100.0, 0.1), ("M8", 50.0, 0.4)], [("VIA7", 2)], rs, vr)
    assert abs(rw - (0.062 * 1000.0 + 0.021 * 125.0)) < 1e-9
    assert abs(rv - 2.5) < 1e-12


def test_route_resistance_refuses_unmeasured_shapes():
    rs = lambda ly: 0.1                                    # noqa: E731
    vr = lambda c: 5.0                                     # noqa: E731
    for bad_seg, bad_via in ((("M1", 1.0, 0.0), None),
                             (None, ("VIA1", 0))):
        try:
            elec.route_resistance(
                [bad_seg] if bad_seg else [], [bad_via] if bad_via else [],
                rs, vr)
        except elec.ElecError:
            pass
        else:
            raise AssertionError("an unmeasured shape did not refuse")


def test_r_max_matches_route_budget_arithmetic():
    # topp's quote: share 1.0 of 132 ps at 8 bits into 375 fF
    import math
    want = 1000.0 * 132.0 / (math.log(2.0 ** 9) * 375.0)
    assert abs(elec.r_max_ohm(1.0, 132.0, 8, 375.0) - want) < 1e-9
    try:
        elec.r_max_ohm(1.0, 132.0, 8, 0.0)
    except elec.ElecError:
        pass
    else:
        raise AssertionError("an unmeasured load did not refuse")


def test_widths_settled_is_a_whole_plan_test():
    assert elec.widths_settled({"a": 0.1, "b": 0.2}, {"a": 0.1, "b": 0.2})
    assert not elec.widths_settled({"a": 0.1}, {"a": 0.1, "b": 0.2})
    assert not elec.widths_settled({"a": 0.1, "b": 0.2}, {"a": 0.1})
    assert not elec.widths_settled({"a": 0.1}, {"a": 0.15})
    assert elec.widths_settled({"a": 0.1}, {"a": 0.1004}, tol_um=0.001)


# ---- solve_width: ROUTE_BUDGET's paid-for guards, each with its poison --

def _price(via_ohm, k_ohm_um):
    """A synthetic route: R = via + k/w (metal inversely to width);
    price(None) prices as drawn at 0.14 um."""
    def price(w):
        use = 0.14 if w is None else w
        return via_ohm + k_ohm_um / use, via_ohm
    return price


def test_solve_width_via_floor_is_a_refusal_not_a_number():
    w, why = elec.solve_width(_price(80.0, 10.0), 60.0, 0.14, 0.14)
    assert w is None and "via floor" in why and "add cuts" in why


def test_solve_width_never_shrinks_a_passing_net():
    """The vcm defect: a net the contract widened, inside budget, must
    KEEP its width -- the old bisection floor returned the tier
    minimum and made the chip worse from a green gate (505 -> 775)."""
    def price(w):
        use = 0.5 if w is None else w      # drawn wide by a prior plan
        return 5.0 + 20.0 / use, 5.0
    w, why = elec.solve_width(price, 60.0, 0.5, 0.14)
    assert w == 0.5 and "idempotent" in why


def test_solve_width_passing_at_base_width_changes_nothing():
    w, why = elec.solve_width(_price(5.0, 5.0), 60.0, 0.14, 0.14)
    assert w is None and "buy nothing" in why


def test_solve_width_bisection_honours_headroom_and_drawn_floor():
    price = _price(5.0, 30.0)              # drawn: 5 + 214 = over 60
    w, why = elec.solve_width(price, 60.0, 0.14, 0.14)
    assert w is not None and w >= 0.14
    r, _ = price(w)
    # the solved width lands at the HEADROOM, not the budget (the
    # round(hi, 3) can give back half a thousandth of it -- the
    # headroom is what absorbs exactly such slop)
    assert r <= 0.90 * 60.0 + 0.1
    assert r < 60.0                        # and well inside the budget
    assert "metal at" in why


def test_solve_width_no_width_means_a_tier_not_a_guess():
    w, why = elec.solve_width(_price(5.0, 5000.0), 60.0, 0.14, 0.14)
    assert w is None and "thick tier" in why


def test_solve_width_dead_band_narrowest_segment_decides():
    """topn: the WIDEST leg at 0.370 read compliant while one 0.358
    leg sat inside the band -- five VIAn.R.* results through a PASS."""
    w, why = elec.solve_width(
        _price(5.0, 5.0), 60.0, 0.37, 0.14,
        dead_band=(0.30, 0.37), segment_widths=(0.37, 0.358))
    assert w == 0.37 and "NOT for the budget" in why


def test_solve_width_dead_band_raises_the_solved_width():
    price = _price(5.0, 18.0)              # solves into the band
    w, why = elec.solve_width(price, 60.0, 0.14, 0.14,
                              dead_band=(0.30, 0.37))
    assert w == 0.37 and "raised from" in why
