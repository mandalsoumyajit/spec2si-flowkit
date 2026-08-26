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


def _assert_on_grid(out, grid):
    """Refuse any probe whose geometry is off the manufacturing grid --
    the deck fires G.1 FIRST, in the violation cell AND the clean twin,
    and the run then scores the stream instead of the rule. Measured on
    the tsmc65 arm (G.1:M1i x6 from a 0.162 stub) after one licence was
    already spent; this guard makes the class an offline refusal."""
    for p in out:
        if "skipped" in p:
            continue
        for kind in ("violation", "clean"):
            for r in p[kind]:
                for v in r[1:5]:
                    n = round(v / grid)
                    if abs(n * grid - v) > 1e-9:
                        raise ValueError(
                            "probe {} draws off-grid coordinate {} on {}"
                            " (grid {}) -- an off-grid probe tests the "
                            "stream, not the rule".format(
                                p["name"], v, r[0], grid))


def probes(rules, layer="M2", cut=None, grid=0.005):
    """Build the probe set for one metal layer (and optionally one cut).

    Returns a list of dicts:
        {name, expect, layer, violation: [rec..], clean: [rec..]}
    or, where the card cannot support the probe:
        {name, skipped: <reason>}

    Every emitted coordinate is asserted onto `grid` before return --
    see `_assert_on_grid`.
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
        # ⚠️ THE CLEAN TWIN IS AN END-TO-END PAIR, so it must clear the
        # whole line-end FAMILY: tsmc28's clean pair at S.7's 0.07 drew
        # exactly one M2.S.12 ("space OF two line-ends" >= 0.08) on the
        # deck. The governing clean gap is the pair value where the
        # card records one; the violation stays under le and fires the
        # family either way.
        pv = None
        if getattr(rules, "line_end_pair_space", None) is not None:
            try:
                pv = rules.line_end_pair_space(layer)
            except Exception:                               # noqa: BLE001
                # a refused pair value skips the layer in the gate, so
                # selfcheck goes loud on its own -- no silent weaker gap
                pv = None
        clean_gap = _ceil_g(le if pv is None else max(le, pv), grid)
        out.append(dict(
            name="line_end", expect="line_end {} < {}".format(gap, le),
            layer=layer,
            violation=[_rec(layer, 0, 0, L, w, "a"),
                       _rec(layer, L + gap, 0, 2 * L + gap, w, "b")],
            clean=[_rec(layer, 0, 0, L, w, "a"),
                   _rec(layer, L + clean_gap, 0,
                        2 * L + clean_gap, w, "b")]))
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
    # ⚠️ THE BARS MUST BE LONGER THAN THE BRIDGE IS WIDE, or the "U"
    # DEGENERATES into a solid block and the probe tests nothing: at
    # w=0.4 (tsmc65 M8) L = 4w = bar, the bridge spanned the full
    # width, and the island was silently solid -- masked on the deck
    # runs because the SPACING island shares the M8.S. family pattern,
    # and caught offline the moment the extract round turned the
    # spacing gate on for the thick tiers.
    Ln = max(L, 2 * bar)
    notch_gap = s
    try:
        for tier in rules.wide_metal_tiers(layer):
            if bar > tier["width_gt_um"] + 1e-9 and                     Ln > tier["parallel_run_gt_um"] + 1e-9:
                notch_gap = max(notch_gap, tier["space_um"])
    except Exception:                                       # noqa: BLE001
        pass
    out.append(dict(
        name="notch", expect="notch {} < {}".format(bad_gap, s),
        layer=layer, offline_unjudged=_unj,
        violation=[_rec(layer, 0, 0, Ln, bar, "a"),
                   _rec(layer, 0, bar + bad_gap, Ln,
                        2 * bar + bad_gap, "a"),
                   _rec(layer, Ln - bar, 0, Ln, 2 * bar + bad_gap, "a")],
        clean=[_rec(layer, 0, 0, Ln, bar, "a"),
               _rec(layer, 0, bar + notch_gap, Ln,
                    2 * bar + notch_gap, "a"),
               _rec(layer, Ln - bar, 0, Ln, 2 * bar + notch_gap, "a")]))

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
    # ⚠️ THE STUB WIDTH IS SNAPPED, LIKE THE AREA SIDES ABOVE. 1.8*w is
    # off-grid whenever w is an odd multiple of the grid -- 1.8 * 0.090
    # (tsmc65 M1) = 0.162, and the deck answered G.1 in BOTH cells, the
    # clean twin included. tsmc28 never saw it because 1.8 * 0.100 lands
    # on-grid by luck. An off-grid probe tests the stream, not the rule.
    step = 2 * grid
    if step < w - 1e-9:
        stub_w, stub_h = _ceil_g(1.8 * w, grid), L
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
        _assert_on_grid(out, grid)
        return out

    # -- via enclosure -----------------------------------------------
    try:
        cw, e_along, e_across = rules.via_geometry(cut)
    except Exception as e:                                  # noqa: BLE001
        # BOTH via probes need this geometry -- name both skips, or the
        # wide-landing probe vanishes without a trace (the exact silent
        # shrink this module's contract forbids; caught by the tsmc65
        # arm, whose card refuses the enclosure ACROSS minimum)
        out.append(dict(name="via_enclosure", skipped=str(e)))
        out.append(dict(name="wide_landing", skipped=str(e)))
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

        # ⚠️ A CLEAN PAD MUST BE LEGAL METAL IN ITS OWN RIGHT: clear of
        # its metal's MIN-AREA (the tsmc28 deck answered the first via
        # clean twin with M2.A.2+A.3 -- probing the pad's area, not the
        # enclosure) and no narrower than its metal's MIN-WIDTH (a
        # cut-width M9 strap over VIA8 is 5x under M9.W.1 -- the tsmc65
        # thick tiers made this class real). Width grows ACROSS by
        # symmetric grid-snapped offsets, length ALONG until the area
        # clears; a card refusing either answer keeps the smaller pad.
        def _pad(metal):
            try:
                mw = rules.min_width(metal)
            except Exception:                               # noqa: BLE001
                mw = cw
            # the ACROSS margin covers the tier's across enclosure too
            # -- VIAx's 0 hid this until VIAz's 0.02 fired the offline
            # gate on its own clean twin (selfcheck, no licence spent)
            off = _ceil_g(max(e_across, (max(mw, cw) - cw) / 2.0), grid)
            width = cw + 2 * off
            ext = max(e_along, e_across)
            try:
                need = (rules.min_area(metal) / width - cw) / 2.0
                if need > ext:
                    ext = _ceil_g(need, grid)
            except Exception:                               # noqa: BLE001
                pass
            return off, ext

        lo_off, e_ext = _pad(lo)
        # ⚠️ AN UNGATED REDUNDANCY TIER MAKES A LONE CUT ILLEGAL
        # EVERYWHERE -- tsmc65's VIA8.R.8 is "at least two VIA8 ... to
        # connect M9 and M8", no width predicate, so a single-cut clean
        # twin can never be quiet on that tier. The clean connection
        # draws the ungated option's cut count at one grid inside its
        # ceiling; the violation stays a lone flush cut (EN fires, and
        # the R noise is the same family).
        need_cuts, ugap = 1, None
        try:
            for t in rules.via_redundancy_tiers(rules.via_tier(cut)):
                if t.get("width_and_length_gt_um") is None:
                    for o in (t.get("options") or []):
                        if o.get("shape", "square") == "square" and                                 isinstance(o.get("count"), int):
                            if o["count"] >= need_cuts:
                                need_cuts = o["count"]
                                ms = o.get("max_space_um")
                                if isinstance(ms, (int, float)):
                                    ugap = ms
        except Exception:                                   # noqa: BLE001
            pass
        cgap = None
        if need_cuts > 1:
            # at the option's own ceiling exactly: the SIZE-merge
            # closes on abutment (viapair_probe, 2026-08-26)
            cgap = _floor_g(ugap if ugap is not None else
                            rules.via_pair_space(cut), grid)
        # ⚠️ AND THE UPPER METAL IS A NARROW STRAP, NOT A PLATE. An
        # 8-cut-wide cap is WIDE metal, and redundancy needs only ONE
        # wide side -- (M3Wide AND M2i) in the deck's own body -- so a
        # big cap turns the lone clean cut into a redundancy case:
        # the tsmc28 clean twin drew VIA2.R.2 from exactly this. The
        # strap runs PERPENDICULAR to the lower pad like a real route
        # and stays at its own minimum width.
        hi_off, he = _pad(hi)
        span = cw if cgap is None else (
            need_cuts * cw + (need_cuts - 1) * cgap)
        hi_v = _rec(hi, -he, -hi_off, cw + he, cw + hi_off, "a")
        hi_c = _rec(hi, -he, -hi_off, cw + he, span + hi_off, "a")
        clean_cuts = [_rec(cut, 0, i * (cw + (cgap or 0)),
                           cw, i * (cw + (cgap or 0)) + cw, "a")
                      for i in range(need_cuts)]
        out.append(dict(
            name="via_enclosure",
            expect="{} cut flush on {} -- needs {} along one axis".format(
                cut, lo, e_along),
            layer=lo,
            violation=[_rec(cut, 0, 0, cw, cw, "a"),
                       _rec(lo, 0, 0, cw, cw, "a"), hi_v],
            clean=clean_cuts + [
                _rec(lo, -lo_off, -e_ext, cw + lo_off,
                     span + e_ext, "a"), hi_c]))

        # -- wide landing (lone cut) ---------------------------------
        try:
            tiers = rules.via_redundancy_tiers(rules.via_tier(cut))
        except Exception as e:                              # noqa: BLE001
            tiers = None
            out.append(dict(name="wide_landing", skipped=str(e)))
        if tiers is not None:
            thr, gov = None, None
            for t in tiers:
                v = t.get("width_and_length_gt_um")
                if isinstance(v, (int, float)) and (thr is None or
                                                    v < thr):
                    thr, gov = v, t
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
                side = _ceil_g(2 * thr, grid)
                # the plate itself must be LEGAL metal: no narrower
                # than min-width, no smaller than min-area -- in BOTH
                # cells, so the violation island's only defect is the
                # lone cut (tsmc65's thick tiers: M8 min area 0.565
                # exceeds a 2x-threshold plate)
                try:
                    side = max(side, _ceil_g(rules.min_width(lo), grid))
                except Exception:                           # noqa: BLE001
                    pass
                try:
                    side = max(side, _ceil_g(
                        rules.min_area(lo) ** 0.5, grid))
                except Exception:                           # noqa: BLE001
                    pass
                pair = rules.via_pair_space(cut)
                # centred-cut arithmetic goes off-grid whenever side and
                # cut disagree in grid parity -- snap, same class as the
                # stub width above
                c0 = _floor_g(side / 2.0 - cw / 2.0, grid)
                # ⚠️ THE SITE'S TIER IS SET BY EITHER CONDUCTOR, so the
                # UPPER metal here is a NARROW STRAP: a big cap promotes
                # the site into the next tier and the island stops
                # testing the tier it names -- the rkpair experiment's
                # 1.16 um cap turned every island into an R.3 site and
                # its "2-square pairs fail at every gap" conclusion was
                # that tier behaving as written (refuted by the 31-island
                # viapair_probe, one variable per island, 2026-08-26).
                # The clean cluster is the governing tier's SMALLEST
                # square option -- the construction the flow itself
                # builds -- at its own ceiling EXACTLY: measured legal
                # at 0.100 (the SIZE-merge closes on abutment) and
                # firing at 0.105.
                n_sq, ospace = 2, pair
                sq_opts = [o for o in ((gov.get("options") or [])
                                       if gov else [])
                           if o.get("shape", "square") == "square" and
                           isinstance(o.get("count"), int)]
                if sq_opts:
                    o = min(sq_opts, key=lambda o: o["count"])
                    n_sq = o["count"]
                    if isinstance(o.get("max_space_um"), (int, float)):
                        ospace = o["max_space_um"]
                pgap = _floor_g(min(ospace, side - 2 * cw), grid)
                import math
                k = int(math.ceil(math.sqrt(n_sq)))
                # cuts at pgap; grow the landing if the cluster cannot
                # fit the wide plate
                span = k * cw + (k - 1) * pgap
                cside = max(side, _ceil_g(span + 2 * grid, grid))
                cc0 = _floor_g((cside - span) / 2.0, grid)
                cluster = []
                placed = 0
                for iy in range(k):
                    for ix in range(k):
                        if placed >= n_sq:
                            break
                        x0 = cc0 + ix * (cw + pgap)
                        y0 = cc0 + iy * (cw + pgap)
                        cluster.append(_rec(cut, x0, y0,
                                            x0 + cw, y0 + cw, "a"))
                        placed += 1
                span_x = max(r[3] for r in cluster) - cc0
                span_y = max(r[4] for r in cluster) - cc0
                # ⚠️ BOTH CELLS CARRY THE UPPER METAL -- a via with no
                # metal above it is malformed, not clean (the first
                # twin without it drew M3.EN.1) -- but as a strap at
                # its own legal width, never a plate (see above).
                cap = [_rec(hi, c0 - he, c0 - hi_off,
                            c0 + cw + he, c0 + cw + hi_off, "a")]
                ccap = [_rec(hi, cc0 - he, cc0 - hi_off,
                             cc0 + span_x + he,
                             cc0 + span_y + hi_off, "a")]
                out.append(dict(
                    name="wide_landing",
                    expect="lone {} cut on {} x {} {}".format(
                        cut, side, side, lo),
                    layer=lo,
                    violation=[
                        _rec(lo, 0, 0, side, side, "a"),
                        _rec(cut, c0, c0, c0 + cw, c0 + cw, "a")] + cap,
                    clean=[
                        _rec(lo, 0, 0, cside, cside, "a")] +
                    cluster + ccap))
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
