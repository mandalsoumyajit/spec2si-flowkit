#!/usr/bin/env python3
"""Card-driven rule probes: violation/clean geometry pairs, self-checked.

The phase-2 gate says a card is validated by a golden rule-probe DRC run
where DELIBERATE violations fire (a negative control) and a clean twin
passes. This module generates that geometry FROM the card, per rule
kind, and self-checks the offline half: `routekit.audit`'s own gate must
fire on every violation and stay silent on every clean twin, or the
probe (or the card, or the gate) is wrong -- found in milliseconds, not
in a cluster round trip.

The cluster half is consumer-side: stream each probe's `violation` and
`clean` rec-tuples to GDS cells with the repo's own writer, run the
signoff deck, and diff its answers against the `expect` field. A probe
the deck does not confirm is a finding about the card, and it is exactly
the finding this exists to surface.

A probe that CANNOT be built from the card -- the kit records no
redundancy rule, line-end equals flat spacing -- is returned with
`skipped` set and the reason, never silently dropped: a probe set that
shrinks without saying so reads as "covered" when it is not.

Python floor: the cluster's 3.6.
"""
try:
    from . import audit                                  # the vendored package
except ImportError:                                      # standalone/flat use
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import audit                                         # noqa: E402


def _rec(layer, x1, y1, x2, y2, net):
    return (layer, x1, y1, x2, y2, net)


def _floor_g(v, grid):
    return round(int(v / grid + 1e-9) * grid, 6)


def _ceil_g(v, grid):
    n = int(v / grid + 1e-9)
    if n * grid < v - 1e-9:
        n += 1
    return round(n * grid, 6)


def probes(rules, layer="M2", cut=None, grid=0.005):
    """Build the probe set for one metal layer (and optionally one cut).

    Returns a list of dicts:
        {name, expect, layer, violation: [rec..], clean: [rec..]}
    or, where the card cannot support the probe:
        {name, skipped: <reason>}
    """
    out = []
    w = rules.min_width(layer)
    s = rules.min_space(layer)
    # a card that cannot answer line-end REFUSES; here that refusal is a
    # named skip on the one probe that needs it, not a crash of the set
    # -- and the skip is itself a phase-2 finding (tsmc28's My family
    # carries no line_end_space_um yet).
    try:
        le = rules.line_end_space(layer)
    except Exception as _le_err:                            # noqa: BLE001
        le = None
        le_reason = str(_le_err)
    L = max(40 * grid, 4 * w, 1.0)          # long enough to dodge min_area

    # ⚠️ THE OFFLINE SPACING GATE CANNOT JUDGE A LAYER WITHOUT A
    # LINE-END VALUE -- its inherited try/except skips the whole layer
    # (the byte-faithful tsmc28 behaviour). The DECK can judge it, so
    # spacing/notch probes on such a layer still stream, marked
    # offline_unjudged with the card gap named; selfcheck skips them
    # rather than reporting a firing that the gate structurally cannot
    # produce. The card gap itself is the finding to fix.
    _unj = (None if le is not None else
            "offline spacing gate skips {}: {}".format(layer, le_reason))

    # -- flat spacing ------------------------------------------------
    bad_gap = max(grid, s - 2 * grid)
    out.append(dict(
        name="spacing", expect="min_space {} < {}".format(bad_gap, s),
        layer=layer, offline_unjudged=_unj,
        violation=[_rec(layer, 0, 0, L, w, "a"),
                   _rec(layer, 0, w + bad_gap, L, 2 * w + bad_gap, "b")],
        clean=[_rec(layer, 0, 0, L, w, "a"),
               _rec(layer, 0, w + s, L, 2 * w + s, "b")]))

    # -- line end ----------------------------------------------------
    if le is None:
        out.append(dict(name="line_end", skipped=le_reason))
    elif le > s + 1e-9:
        # legal flat, illegal line-end -- and ON the grid, between the
        # two rules (snap toward s so it stays under le)
        gap = min(_floor_g((s + le) / 2.0, grid), le - grid)
        gap = max(gap, s)
        out.append(dict(
            name="line_end", expect="line_end {} < {}".format(gap, le),
            layer=layer,
            violation=[_rec(layer, 0, 0, L, w, "a"),
                       _rec(layer, L + gap, 0, 2 * L + gap, w, "b")],
            clean=[_rec(layer, 0, 0, L, w, "a"),
                   _rec(layer, L + le, 0, 2 * L + le, w, "b")]))
    else:
        out.append(dict(name="line_end",
                        skipped="line_end_space <= min_space on {} -- no "
                                "gap distinguishes the rules".format(layer)))

    # -- same-polygon notch ------------------------------------------
    # ⚠️ THE CLEAN GAP IS THE GOVERNING RULE'S, NOT THE FLAT ONE. The
    # bars are 4*w wide with a full-length parallel run, which on a real
    # card can land in a wide-metal tier -- tsmc28's M2 wants 0.100
    # there against the flat 0.05, and the first clean twin fired on it.
    # Found by selfcheck refusing, which is the offline arm doing its
    # job before a licence was spent.
    bar = 4 * w
    notch_gap = s
    try:
        for tier in rules.wide_metal_tiers(layer):
            if bar > tier["width_gt_um"] + 1e-9 and                     L > tier["parallel_run_gt_um"] + 1e-9:
                notch_gap = max(notch_gap, tier["space_um"])
    except Exception:                                       # noqa: BLE001
        pass
    out.append(dict(
        name="notch", expect="notch {} < {}".format(bad_gap, s),
        layer=layer, offline_unjudged=_unj,
        violation=[_rec(layer, 0, 0, L, bar, "a"),
                   _rec(layer, 0, bar + bad_gap, L, 2 * bar + bad_gap, "a"),
                   _rec(layer, L - bar, 0, L, 2 * bar + bad_gap, "a")],
        clean=[_rec(layer, 0, 0, L, bar, "a"),
               _rec(layer, 0, bar + notch_gap, L,
                    2 * bar + notch_gap, "a"),
               _rec(layer, L - bar, 0, L, 2 * bar + notch_gap, "a")]))

    # -- min area ----------------------------------------------------
    try:
        a2 = rules.min_area(layer)
    except Exception as e:                                  # noqa: BLE001
        out.append(dict(name="min_area", skipped=str(e)))
        a2 = None
    if a2 is not None:
        # ⚠️ ON THE GRID, IN THE SAFE DIRECTION: sqrt(area) is
        # irrational, and an off-grid probe tests the stream, not the
        # rule (the deck fires offgrid_* first). Floor the violation
        # (stays under the area), ceil the clean (stays over).
        side_bad = max(2 * grid, _floor_g((a2 * 0.5) ** 0.5, grid))
        side_ok = _ceil_g((a2 * 4.0) ** 0.5, grid)
        out.append(dict(
            name="min_area", expect="area {:.5f} < {}".format(
                side_bad * side_bad, a2),
            layer=layer,
            violation=[_rec(layer, 0, 0, side_bad, side_bad, "a"),
                       _rec(layer, 10 * L, 0, 11 * L, bar, "b")],
            clean=[_rec(layer, 0, 0, side_ok, side_ok, "a"),
                   _rec(layer, 10 * L, 0, 11 * L, bar, "b")]))

    # -- min edge (G.4 vertex) ---------------------------------------
    step = 2 * grid
    if step < w - 1e-9:
        stub_w, stub_h = 1.8 * w, L
        foot_h = 2 * w
        remnant = max(2 * grid, w - grid)
        out.append(dict(
            name="min_edge",
            expect="adjacent edges {} and {} both < {}".format(
                step, remnant, w),
            layer=layer,
            violation=[
                _rec(layer, 0, 0, stub_w, stub_h + remnant, "a"),
                _rec(layer, -step, stub_h - foot_h,
                     stub_w + step, stub_h, "a")],
            clean=[_rec(layer, 0, 0, stub_w, stub_h + remnant, "a")]))
    else:
        out.append(dict(name="min_edge",
                        skipped="grid step {} not below min_width {} on "
                                "{}".format(step, w, layer)))

    if cut is None:
        return out

    # -- via enclosure -----------------------------------------------
    try:
        cw, e_along, e_across = rules.via_geometry(cut)
    except Exception as e:                                  # noqa: BLE001
        out.append(dict(name="via_enclosure", skipped=str(e)))
        return out
    lo = layer                       # treat `layer` as the lower metal
    n = int(cut[3:]) if cut[3:].isdigit() else None
    hi = ("M%d" % (n + 1)) if (lo == ("M%d" % n) if n else False) else None
    if hi is None:
        out.append(dict(
            name="via_enclosure",
            skipped="cannot name the upper metal for {} over {} -- pass "
                    "a matching layer/cut pair".format(cut, lo)))
    else:
        big = 8 * cw
        out.append(dict(
            name="via_enclosure",
            expect="{} cut flush on {} -- needs {} along one axis".format(
                cut, lo, e_along),
            layer=lo,
            violation=[_rec(cut, 0, 0, cw, cw, "a"),
                       _rec(lo, 0, 0, cw, cw, "a"),
                       _rec(hi, -big, -big, big, big, "a")],
            clean=[_rec(cut, 0, 0, cw, cw, "a"),
                   _rec(lo, 0, -e_along, cw, cw + e_along, "a"),
                   _rec(hi, -big, -big, big, big, "a")]))

        # -- wide landing (lone cut) ---------------------------------
        try:
            tiers = rules.via_redundancy_tiers(rules.via_tier(cut))
        except Exception as e:                              # noqa: BLE001
            tiers = None
            out.append(dict(name="wide_landing", skipped=str(e)))
        if tiers is not None:
            thr = None
            for t in tiers:
                v = t.get("width_and_length_gt_um")
                if isinstance(v, (int, float)):
                    thr = v if thr is None else min(thr, v)
            if not tiers:
                out.append(dict(
                    name="wide_landing",
                    skipped="redundancy_tiers is [] -- the kit records "
                            "no redundancy rule (measured absent)"))
            elif thr is None:
                out.append(dict(
                    name="wide_landing",
                    skipped="redundancy tiers carry no width threshold "
                            "-- ungated tier, probe not constructible"))
            else:
                side = 2 * thr
                pair = rules.via_pair_space(cut)
                c0 = side / 2.0 - cw / 2.0
                out.append(dict(
                    name="wide_landing",
                    expect="lone {} cut on {} x {} {}".format(
                        cut, side, side, lo),
                    layer=lo,
                    violation=[
                        _rec(lo, 0, 0, side, side, "a"),
                        _rec(cut, c0, c0, c0 + cw, c0 + cw, "a")],
                    clean=[
                        _rec(lo, 0, 0, side, side, "a"),
                        _rec(cut, c0, c0, c0 + cw, c0 + cw, "a"),
                        _rec(cut, c0, c0 + cw + min(pair, side - 2 * cw),
                             c0 + cw,
                             c0 + 2 * cw + min(pair, side - 2 * cw), "a")]))
    return out


def _findings(rules, probe, rec):
    """Run the gate a probe targets over `rec`; return its findings."""
    name, layer = probe["name"], probe.get("layer")
    if name in ("spacing", "line_end", "notch"):
        return audit.spacing(rules, rec, layers=(layer,))
    if name == "min_area":
        return audit.min_area(rules, rec, layers=(layer,))
    if name == "min_edge":
        return audit.min_edge(rules, rec, layers=(layer,))
    if name == "via_enclosure":
        return audit.via_enclosure(rules, rec)
    if name == "wide_landing":
        return audit.via_wide_landing(rules, rec)
    raise ValueError("no gate mapped for probe " + name)


def selfcheck(rules, layer="M2", cut=None, grid=0.005):
    """The offline negative control. Returns findings -- [] means every
    constructible violation FIRES and every clean twin is SILENT."""
    out = []
    for p in probes(rules, layer=layer, cut=cut, grid=grid):
        if "skipped" in p:
            continue
        if p.get("offline_unjudged"):
            continue            # streams for the deck arm; named there
        fired = _findings(rules, p, p["violation"])
        if not fired:
            out.append("PROBE {} on {}: the violation did not fire -- "
                       "the probe, the card or the gate is wrong"
                       .format(p["name"], layer))
        quiet = _findings(rules, p, p["clean"])
        if quiet:
            out.append("PROBE {} on {}: the clean twin fired: {}"
                       .format(p["name"], layer, quiet[0]))
    return out
