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

What is DELIBERATELY NOT here (recorded, not forgotten): the
`route_widen` machinery -- corridor moves, owner-tagged reservations,
re-claiming widened tracks in the solver's own `Tracks`. It is one unit
with the solver's occupancy model and its regression suite is
ROUTE_BUDGET §10's silent-pass defects; porting it without a live
consumer exercising the loop risks an unvalidated 700-line translation.
Its natural gate is the tsmc65 v2 re-route (plan, phase 4), and it lands
there. Until then the fixpoint CONTRACT below is the shared piece: a
width change is a re-solve trigger, never a local edit.

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
