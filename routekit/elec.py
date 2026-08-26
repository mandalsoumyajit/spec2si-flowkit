#!/usr/bin/env python3
"""Electrical primitives for the routing core: EM floors, ohm pricing,
the R_max budget, and the widen fixpoint's contract.

Extracted from the three implementations the ports converged on --
tsmc65's `route_budget`/`routing.r_width` family (signed with the 136-net
chip), tsmc28's `adc_tile_route` ohm pricing (foundry QRC sourced) and
xt011's `tech/em.py` (whose banded-step lesson is encoded here) -- with
the same seam as everything else in routekit: numbers come from a card
accessor the caller binds, nothing is typed here, and a question the
inputs cannot answer is a refusal.

The `route_widen` translation pass (corridor moves, owner-tagged
reservations, stem carries) is deliberately NOT here -- and never will
be: ROUTE_BUDGET Appendix F retired it. The router itself is
width-aware (`solve.Tracks` takes `widths={net: um}` and prices the
whole band), so the unit that closes the loop is PRODUCER-side:
`solve_width` below inverts a net's R budget to the width the next
solve routes to, `widths_settled` is the fixpoint exit, and the drawn
rectangles never get rewritten -- "the width the maze routed to is the
width in the GDS, and nothing in between translates anything."

Two measured rules every consumer inherits:

  * **widening is not monotone in routability** -- a net that routes at
    15-17.5 ohm and >= 28 ohm can starve the lanes everywhere between
    (tsmc65, `vref`). So `widths_settled` is a fixpoint test on the
    WHOLE width plan, and a caller iterates solve -> price -> widen
    until it holds, rather than editing one net's width in place.
  * **a banded limit has a step in it, and a step solves no equation**
    (xt011, MET3's 1.40*w below 1.0 um vs 1.77*w at it): a current in
    the gap inverts to a width each band's own condition excludes, while
    a band EDGE plainly carries it. So `min_em_width` checks candidate
    widths against `imax(w)` directly -- band edges included by the
    caller -- and refuses, naming the current, when none suffices.

Python floor: the cluster's 3.6.
"""
import math


class ElecError(ValueError):
    """An electrical question the inputs cannot answer. The message names
    the missing measurement or the current no candidate width carries."""


# ---- EM floors ----------------------------------------------------------

def min_em_width(i_ma, imax_of_width, candidates):
    """The narrowest candidate width whose own limit carries `i_ma`.

    `imax_of_width(w) -> mA` is the card's (already derated) limit AT
    width `w` -- a callable, because banded rules make the limit a step
    function of the width itself. `candidates` is an ascending iterable
    of drawable widths and MUST include the band edges: the xt011 case
    is a 5.036 mA current whose inversion lands in the 4.368->5.522 mA
    step, where no in-band solution exists and the 1.000 um edge plainly
    carries it. Nothing is averaged and nothing is assumed sufficient:
    every candidate is checked against `imax` itself.

    Refuses (naming the current and the best candidate) when none
    suffices -- a minimum is not a size, and a caller then adds strands
    or layers rather than silently drawing the biggest width anyway."""
    best_w, best_i = None, None
    for w in candidates:
        i = imax_of_width(w)
        if best_i is None or i > best_i:
            best_w, best_i = w, i
        if i >= i_ma - 1e-12:
            return w
    raise ElecError(
        "no candidate width carries {} mA -- the best is {} at {} mA. "
        "Add strands or layers; do not draw the widest and hope.".format(
            i_ma, best_w, best_i))


def min_cuts(i_ma, imax_per_cut_ma):
    """The fewest via cuts that carry `i_ma`, from the card's per-cut
    limit. At least one; refuses on a non-positive limit rather than
    dividing by it."""
    if imax_per_cut_ma <= 0:
        raise ElecError(
            "per-cut EM limit is {} mA -- an unmeasured via limit is a "
            "refusal, not a divisor".format(imax_per_cut_ma))
    return max(1, int(math.ceil(i_ma / imax_per_cut_ma - 1e-12)))


# ---- ohm pricing --------------------------------------------------------

def route_resistance(segments, vias, rs_of_layer, via_r_of_cut):
    """Price a route in ohms, the `adc_tile_route` way (foundry-table
    sourced), never from typed sheet values.

    `segments` -- [(layer, length_um, width_um)]; each contributes
    `rs_of_layer(layer) * length / width` (sheet resistance in
    ohm/square from the RC card / QRC table).
    `vias` -- [(cut_layer, n_cuts)]; each contributes
    `via_r_of_cut(cut_layer) / n_cuts` (per-cut resistance in ohm).

    Returns (r_wire_ohm, r_via_ohm). A zero-width segment or a
    non-positive cut count is a refusal: the measured failure mode is a
    pessimistic floor silently inflating one net's answer."""
    r_wire = 0.0
    for layer, length, width in segments:
        if width <= 0:
            raise ElecError(
                "segment on {} has width {} -- an unmeasured width is a "
                "refusal".format(layer, width))
        r_wire += rs_of_layer(layer) * (float(length) / float(width))
    r_via = 0.0
    for cut, n in vias:
        if n <= 0:
            raise ElecError(
                "via {} has {} cuts -- a stack with no cuts prices as "
                "infinity, not zero".format(cut, n))
        r_via += via_r_of_cut(cut) / float(n)
    return (r_wire, r_via)


# ---- the R_max budget ---------------------------------------------------

def r_max_ohm(share, t_avail_ps, bits, c_load_ff):
    """Per-net resistance budget from a settling share of the available
    time -- `route_budget`'s own derivation, kept as the one formula:

        R_max = share * t_avail / (ln(2^(bits+1)) * C_load)

    Units: ps and fF give kilo-ohms natively (1 ps/fF = 1 kOhm); the
    return is in OHMS. The (bits+1) is the half-LSB settling criterion.
    Refuses on a non-positive load: a net with no documented C gets no
    verdict, never a default (`adc_tile_route` reports such nets as
    ohms-without-verdict instead)."""
    if c_load_ff <= 0:
        raise ElecError(
            "C_load is {} fF -- a budget against an unmeasured load is "
            "not a budget".format(c_load_ff))
    tau_ln = math.log(2.0 ** (bits + 1))
    return 1000.0 * share * t_avail_ps / (tau_ln * c_load_ff)


# ---- the budget -> width solver -----------------------------------------

def solve_width(price, target_ohm, drawn_w_um, base_w_um,
                headroom=0.90, hi_um=12.0, dead_band=None,
                segment_widths=()):
    """Invert a net's R budget to the width the NEXT solve routes to.
    -> (width_um | None, why). None means "change nothing" or "no width
    answers" -- the `why` says which.

    Promoted from tsmc65's `route_budget.width_for`, signed with the
    136-net chip; every branch below is a defect the campaign paid for
    (ROUTE_BUDGET §10 and appendices), kept in its own words:

    `price(w) -> (total_ohm, via_ohm)` prices the route at uniform
    width `w`; `price(None)` prices it AS DRAWN. Selectivity -- which
    segments actually widen (terminal legs never do) -- lives inside
    the caller's `price`, because a bisection that pretends everything
    widens under-asks (topp: solved 0.589 "meeting" 54.5 ohm, landed
    at 70.8). `drawn_w_um` is the widest drawn segment; `base_w_um`
    the width the router draws unwidened nets at (a pad width, not
    the tier minimum). `dead_band = (multi_cut_gt_um, min_array_um)`
    is the via rule's gap: a wire wider than the first forces a
    second cut, and only from the second can the cuts stand.
    `segment_widths` are the drawn per-segment widths, for the
    band pre-check.

    * ⛔ the via floor is a FLOOR and widening does not move it: when
      it alone exceeds the budget the answer is cuts or a tier, and
      "w = 12 um" would be a number that looks like an answer;
    * ⛔ the dead band is a RULE, not a budget, and the NARROWEST
      qualifying segment decides -- testing max(widths) reported topn
      compliant through five VIAn.R.* results;
    * ⭐ a passing net KEEPS the width it was routed at (idempotence on
      a solved board) -- returning None for a net the contract widened
      makes the loop self-destroying;
    * ⛔ NEVER below what is drawn: the old bisection floor was the
      tier minimum and it made vcm NARROWER from a green gate,
      505 -> 775 ohm;
    * ⚠ the target is not the budget: `headroom` covers the short
      runs the price model leaves at their drawn width (without it
      topp failed its gate by 1.5 % for a reason in a different file).
    """
    tot, via = price(None)
    if via >= target_ohm:
        return None, ("via floor %.1f ohm already exceeds the %.1f ohm "
                      "budget -- widen nothing, add cuts or drop a tier"
                      % (via, target_ohm))
    if dead_band is not None:
        lo_b, hi_b = dead_band
        band = sorted(w for w in segment_widths
                      if w > lo_b + 1e-9 and w < hi_b - 1e-9)
        if band:
            return hi_b, ("metal at %.3f um -- NOT for the budget (this "
                          "net passes at %.1f ohm) but for the via rule: "
                          "%d segment(s) from %.3f um are inside the band "
                          "that forces a second cut and cannot hold one"
                          % (hi_b, tot, len(band), band[0]))
    if tot <= target_ohm:
        if drawn_w_um > base_w_um + 1e-6:
            return round(drawn_w_um, 3), (
                "keep %.3f um -- inside budget at the width the last "
                "plan asked for; the plan is idempotent on a solved "
                "board" % drawn_w_um)
        return None, ("already inside budget at the drawn width -- "
                      "widening would take tracks and buy nothing")
    lo, hi = drawn_w_um, hi_um
    for _ in range(60):
        mid = (lo + hi) / 2.0
        r, _v = price(mid)
        if r > headroom * target_ohm:
            lo = mid
        else:
            hi = mid
    if hi >= hi_um - 1e-6:
        return None, ("no drawable width meets %.1f ohm -- this route "
                      "needs a thick tier" % target_ohm)
    w = round(hi, 3)
    if dead_band is not None and w > dead_band[0] + 1e-9 and             w < dead_band[1]:
        return dead_band[1], (
            "metal at %.3f um -- raised from %.3f, the narrowest wire "
            "that can carry the two cuts this width makes the deck ask "
            "for" % (dead_band[1], w))
    return w, "metal at %.3f um" % w


# ---- the widen fixpoint -------------------------------------------------

def widths_settled(prev, cur, tol_um=0.0):
    """True when a width plan has stopped moving -- the loop's exit test.

    `prev`/`cur` are {net: width_um}. A net appearing or vanishing is
    movement; so is any width change beyond `tol_um`. The contract this
    encodes (job_route.sh's loop, which replaced the forced six-step
    widening): the width is computed from the LAST solve's geometry, so
    a net that moves tier or length asks for a different width next
    turn, and the plan has settled only when a whole turn changes
    nothing. TURN 1 ALWAYS ROUTES -- comparing against a stale plan file
    says nothing about whether the router consumed it."""
    if set(prev) != set(cur):
        return False
    for net in cur:
        if abs(cur[net] - prev[net]) > tol_um + 1e-12:
            return False
    return True
