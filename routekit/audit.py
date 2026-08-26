#!/usr/bin/env python3
"""Tier-1 geometric + connectivity gate for a router. Node-agnostic engine.

Extracted from `spec2si-tsmc28` `analog/engine/layout/audit.py` (itself
forked from the 65 nm `netlist_route` audits) with ONE mechanical change:
every process fact arrives through a `rules` object a consumer hands in --
the same seam the IR solver set. Nothing here imports a tech module, and a
rules object that cannot answer raises, which is a refusal and not a pass.

WHY THIS EXISTS. It is pure python and runs in milliseconds, BEFORE
strmout and the signoff tool. A routing bug caught here costs seconds; the
same bug caught by LVS costs a 25-minute round trip, and some of them are
not caught at all:

  * a SPLIT NET passes every spacing and short check and surfaces only as
    an LVS phantom net. The 65 nm record has one (`net 5` on the LVDS
    tail) that survived thirteen DRC/short iterations before anyone
    looked for opens.
  * DRC spacing is NET-BLIND. Two same-net shapes 0.04 apart are a
    violation unless something merges them into one polygon, so the
    audit tracks connected components rather than just net names.

The two lessons that make it correct, both paid for at 65 nm and kept:

  1. same-net proximity is only a finding ACROSS connected components --
     two same-net rects that a third shape bridges are one legal polygon;
  2. a single-conductor island is NOT an open. A passive terminal (a MOM
     spine, a resistor head, a device terminal) reaches its net THROUGH
     the device, so it legitimately floats. Only >= 2 components each
     carrying >= 2 conductors is a real split.

## The `rules` protocol

The gates that measure against process rules take a `rules` object as
their FIRST argument. It must answer (each mirrors the accessor the
tsmc28 `tech/process.py` already exposes; a consumer binds its own):

    min_space(layer) -> um            line_end_space(layer) -> um
    wide_metal_tiers(layer) -> [..]   min_width(layer) -> um
    min_area(layer) -> um2            landing_pad(layer) -> um
    compact_edge() -> um              via_geometry(cut) -> (cut, e1, e2)
    via_enclosure_crowded() -> dict|falsy
    via_tier(cut) -> tier             via_redundancy_tiers(tier) -> (..,)
    via_pair_space(cut) -> um|None    via_rect_cut([cut]) -> (long, short)
    plate_proximity_rules() -> (..,)

`shorts`/`opens`/`run` take no rules object -- their one number, the
tolerated gap, is an explicit argument: the caller states the metal
spacing, this module never guesses one.

Layer names default to the M1..M9 / VIA1..VIA8 / CO-PO-OD vocabulary both
TSMC ports use; a process with different names (xt011's MET1..METCT) passes
its own tables through the keyword arguments.

Python floor: the cluster's 3.6 -- no dataclasses, no walrus, `.format`.
"""
try:
    from . import geom                                   # the vendored package
except ImportError:                                      # standalone/flat use
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import geom                                          # noqa: E402

METALS = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")
# Layers the SHORT check runs on. Poly belongs here: the router draws gate
# extensions on it, so two different nets' gates can merge through poly
# exactly as they can through metal. Leaving PO out is why a CLK/net1 poly
# short survived the audit and surfaced 25 minutes later as an LVS
# INCORRECT NETS -- the precise failure this gate exists to prevent.
SHORT_LAYERS = METALS + ("PO",)
VIA_MET = {"VIA1": ("M1", "M2"), "VIA2": ("M2", "M3"),
           "VIA3": ("M3", "M4"), "VIA4": ("M4", "M5"),
           "VIA5": ("M5", "M6"), "VIA6": ("M6", "M7"),
           "VIA7": ("M7", "M8"), "VIA8": ("M8", "M9")}
# CO bridges the device layers to M1; OD and PO are conductors for
# connectivity purposes even though nothing routes on them
CONTACT = {"CO": ("OD", "PO", "M1")}

ALL_CUTS = ("VIA1", "VIA2", "VIA3", "VIA4",
            "VIA5", "VIA6", "VIA7", "VIA8")

_union_find = geom.union_find
_subtract = geom.subtract
_uncovered = geom.uncovered
_union_area = geom.union_area
_boundary_edges = geom.boundary_edges


class TraceWorker(object):
    """Worker proxy that records every drawn rect against the net it was
    drawn for (set `.net` before drawing). `mark()` records conductors
    that exist without being drawn here -- PCell terminal columns, the
    tap straps -- so the audit sees the whole net, not just the part the
    router authored."""

    def __init__(self, w):
        self._w, self.rec, self.net = w, [], None
        # Conductors that EXIST but were not drawn here -- the pin metal
        # of a placed instance. They take part in the OPENS check and not
        # in the shorts check: a vendor cell's own pins sit 0.05 um apart
        # by design, so feeding them to a proximity check reports the
        # library rather than the route.
        self.ref = []
        # Placed instance outlines, for the renderer. A placed cell's
        # interior is never drawn through this worker, so without this the
        # picture shows routing floating in empty space.
        self.blocks = []

    def rect(self, lib, cell, layer, x1, y1, x2, y2, purpose="drawing"):
        self.rec.append((layer, min(x1, x2), min(y1, y2), max(x1, x2),
                         max(y1, y2), self.net))
        return self._w.rect(lib, cell, layer, x1, y1, x2, y2, purpose)

    def rects(self, lib, cell, specs):
        for s in specs:
            self.rec.append((s[0], min(s[2], s[4]), min(s[3], s[5]),
                             max(s[2], s[4]), max(s[3], s[5]), self.net))
        return self._w.rects(lib, cell, specs)

    def mark(self, layer, x1, y1, x2, y2, net):
        self.rec.append((layer, min(x1, x2), min(y1, y2), max(x1, x2),
                         max(y1, y2), net))

    def mark_pin(self, layer, x1, y1, x2, y2, net):
        """A placed instance's pin, in parent coordinates."""
        self.ref.append((layer, min(x1, x2), min(y1, y2), max(x1, x2),
                         max(y1, y2), net))

    def mark_block(self, name, x1, y1, x2, y2):
        """A placed instance's footprint, in parent coordinates."""
        self.blocks.append((name, min(x1, x2), min(y1, y2),
                            max(x1, x2), max(y1, y2)))

    @property
    def raw(self):
        """The wrapped worker, for drawing into a cell OTHER than the one
        under audit -- a marker added to a copied child, say.

        Geometry sent this way is deliberately NOT recorded, and that is the
        correct answer rather than a shortcut: `rec` describes ONE cell, and
        a foreign shape in it would be measured against nets it is not on
        and counted in the tag census that decides whether this audit proved
        anything at all.
        """
        return self._w

    def __getattr__(self, name):
        return getattr(self._w, name)


class NullSink(object):
    """Drawing sink for a planning pass: geometry discarded, only the
    call sequence matters. The routing code is deterministic, so a plan
    pass and the drawing pass see identical requests."""

    def __init__(self):
        self.net = None

    def rect(self, *a, **k):
        pass

    def rects(self, *a, **k):
        return 0

    def mark(self, *a, **k):
        pass

    def mark_pin(self, *a, **k):
        pass

    def mark_block(self, *a, **k):
        pass

    def place(self, lib, cell, name, mlib, master, params, x, y,
              orient="R0"):
        """A planning sink places nothing and measures nothing. Returning
        an empty bbox is what tells an assembler's landed-check that there
        is no independent measurement to compare against, rather than
        failing every instance."""
        return None, []

    def label(self, *a, **k):
        pass


def shorts(rec, gap, short_layers=None, via_met=None):
    """Different-net shapes on one layer must not touch (SHORT); all
    unmerged pairs -- same net or not -- must clear `gap` (NEAR); via
    cuts must not overlap foreign metal on their adjacent layers
    (VIASHORT). Returns (shorts, nears) as printable strings, deduped by
    (layer, net pair) with counts and an example location.

    `gap` is the tolerated proximity -- the caller states its process's
    metal spacing; this module never guesses one."""
    short_layers = SHORT_LAYERS if short_layers is None else short_layers
    via_met = VIA_MET if via_met is None else via_met
    by = {}
    for ly, x1, y1, x2, y2, net in rec:
        by.setdefault(ly, []).append((x1, y1, x2, y2, net))
    sh, nr = {}, {}
    for ly in short_layers:
        shp = by.get(ly, [])
        find, union = _union_find(len(shp))
        for i, a in enumerate(shp):
            for j in range(i + 1, len(shp)):
                b = shp[j]
                if a[4] != b[4]:
                    continue
                if (max(a[0] - b[2], b[0] - a[2]) <= 1e-6
                        and max(a[1] - b[3], b[1] - a[3]) <= 1e-6):
                    union(i, j)
        for i, a in enumerate(shp):
            for j in range(i + 1, len(shp)):
                b = shp[j]
                dx = max(a[0] - b[2], b[0] - a[2])
                dy = max(a[1] - b[3], b[1] - a[3])
                if dx > gap - 1e-6 or dy > gap - 1e-6:
                    continue
                touch = dx <= 1e-6 and dy <= 1e-6
                key = (ly,) + tuple(sorted((str(a[4]), str(b[4]))))
                if a[4] == b[4]:
                    if not touch and find(i) != find(j):
                        nr.setdefault(key, []).append((a, b))
                elif touch:
                    sh.setdefault(key, []).append((a, b))
                else:
                    nr.setdefault(key, []).append((a, b))
    for vly, mls in via_met.items():
        for c in by.get(vly, ()):
            for ml in mls:
                for m in by.get(ml, ()):
                    if m[4] == c[4]:
                        continue
                    if (m[0] < c[2] - 1e-6 and c[0] < m[2] - 1e-6
                            and m[1] < c[3] - 1e-6 and c[1] < m[3] - 1e-6):
                        key = (vly + ">" + ml,) + tuple(
                            sorted((str(c[4]), str(m[4]))))
                        sh.setdefault(key, []).append((c, m))

    def fmt(tag, d):
        out = []
        for key, pairs in sorted(d.items()):
            a, b = pairs[0]
            out.append("{} {} {}: x{} @ ({:.3f},{:.3f})".format(
                tag, key[0], "/".join(key[1:]), len(pairs),
                (max(a[0], b[0]) + min(a[2], b[2])) / 2,
                (max(a[1], b[1]) + min(a[3], b[3])) / 2))
        return out
    return fmt("SHORT", sh), fmt("NEAR", nr)


def opens(rec, metals=None, via_met=None, contact=None):
    """Every net's conductors must form ONE connected component: metal
    connects by touch on a layer, a via cut bridges its two adjacent
    metals, a contact bridges its declared layers. Returns one string per
    split net."""
    metals = METALS if metals is None else metals
    via_met = VIA_MET if via_met is None else via_met
    contact = CONTACT if contact is None else contact
    extra = set()
    for lys in contact.values():
        extra.update(lys)
    conductors = set(metals) | set(via_met) | set(contact) | extra
    by_net = {}
    for ly, x1, y1, x2, y2, net in rec:
        if ly in conductors:
            by_net.setdefault(net, []).append((ly, x1, y1, x2, y2))
    out = []
    for net, shp in sorted(by_net.items(), key=lambda kv: str(kv[0])):
        if net is None:
            continue        # untagged geometry is not a net: dummy poly,
                            # implant bands and wells are floating by
                            # construction and have no connectivity to check

        find, union = _union_find(len(shp))
        for i, a in enumerate(shp):
            for j in range(i + 1, len(shp)):
                b = shp[j]
                dx = max(a[1] - b[3], b[1] - a[3])
                dy = max(a[2] - b[4], b[2] - a[4])
                touch = dx <= 1e-6 and dy <= 1e-6
                overlap = dx < -1e-6 and dy < -1e-6
                la, lb = a[0], b[0]
                conn = False
                if la == lb and la in conductors:
                    conn = touch
                elif la in via_met and lb in via_met.get(la, ()):
                    conn = overlap
                elif lb in via_met and la in via_met.get(lb, ()):
                    conn = overlap
                elif la in contact and lb in contact[la]:
                    conn = overlap
                elif lb in contact and la in contact[lb]:
                    conn = overlap
                if conn:
                    union(i, j)
        comps = {}
        for i in range(len(shp)):
            comps.setdefault(find(i), []).append(i)
        big = [c for c in comps.values() if len(c) >= 2]
        if len(big) > 1:
            pieces = sorted(big, key=len)
            small = pieces[0]
            bb = (min(shp[i][1] for i in small),
                  min(shp[i][2] for i in small),
                  max(shp[i][3] for i in small),
                  max(shp[i][4] for i in small))
            out.append(
                "OPEN {}: {} routed pieces (sizes {}), smallest at "
                "({:.3f},{:.3f})-({:.3f},{:.3f})".format(
                    net, len(big), "/".join(str(len(p)) for p in pieces),
                    *bb))
    return out


def run(rec, gap, verbose=True, ref=()):
    """Both gates. Returns (n_blocking, lines).

    `gap` is the tolerated proximity for `shorts` -- the caller's metal
    spacing, stated explicitly.

    `ref` is conductors that exist without being drawn here -- at the
    assembly level, the pin metal of placed instances. It joins the OPENS
    check only. That is what turns "the via landed 0.26 um from the pin"
    from a signoff round trip into a split net reported in milliseconds:
    without it the audit sees the escape and the track, both on the same
    net, connected to each other and to nothing else, and calls it fine.
    It stays out of the SHORTS check because a vendor cell's pins are
    legitimately 0.05 um apart and reporting that describes the library,
    not the route.

    AN UNTAGGED BLOCK IS REPORTED, NOT PASSED. Both checks here are
    net-relative: SHORT means "different nets touch" and OPEN means "one
    net in pieces", so a caller that never sets `TraceWorker.net` gets
    every shape on the same net None -- and both checks come back empty
    for the same reason a question nobody asked has no answer. That is
    not hypothetical: `loop_filter_1` drew 6533 shapes without a single
    tag, passed here at "0 blocking, 0 findings", and went to Calibre
    with IN, OUT and VSS merged into one net and its five supply buses
    floating. Fewer than two distinct nets is now a finding of its own,
    in the same NOT-EVALUATED spirit a via-redundancy predicate answers
    with."""
    sh, nr = shorts(rec, gap)
    op = opens(list(rec) + list(ref))
    tags = set(r[5] for r in list(rec) + list(ref) if r[5] is not None)
    untagged = []
    if len(tags) < 2 and rec:
        untagged = ["UNTAGGED: {} shapes carry {} net name(s) -- both "
                    "checks below are net-relative, so this run proves "
                    "nothing. Set TraceWorker.net as the route draws."
                    .format(len(rec), len(tags))]
    lines = untagged + sh + op + nr
    if verbose:
        for ln in untagged + sh + op:
            print("    " + ln)
        for ln in nr:
            print("    " + ln)
    return len(untagged) + len(sh) + len(op), lines


# ---- tier-1 SPACING -----------------------------------------------------
#
# `shorts` and `opens` answer connectivity: is every net whole, and do two
# nets TOUCH. They are blind BY DESIGN to two shapes that come close
# without touching -- which is a DRC violation and not a connectivity one,
# and which no check in this engine could see until lock_detector_1's
# first routed builds returned M2.S.1, M2.S.13 and Mx.S.7 markers that
# every offline gate had passed.
#
# THREE THINGS A NAIVE PAIRWISE SWEEP GETS WRONG, and each cost a marker:
#
#   1. IT MUST INCLUDE INSTANCE PIN METAL. A vendor cell's own pins are
#      metal this engine did not draw and the signoff deck sees no
#      differently. A sweep over `rec` alone checked half the layout and
#      reported clean while a bus sat 0.030 um from `INVD4`'s ZN.
#
#   2. SAME-NET IS NOT EXEMPT. Spacing is a rule between POLYGONS, not
#      between nets. Two pieces of one net that do not merge are two
#      polygons, and 0.045 um apart they are a violation exactly as two
#      nets would be. Skipping same-net pairs -- the obvious optimisation,
#      since merging is normally the point -- is what hid net1's M2.S.1.
#
#   3. MERGE FIRST, THEN MEASURE. Shapes that overlap or touch become ONE
#      polygon and have no spacing to each other, and connectivity is
#      TRANSITIVE: a wire that overlaps two pads makes all three one
#      polygon even where the pads are 0.03 apart. Measuring raw
#      rectangles pairwise reports that as a violation and it is not.
#
# The line-end family is modelled too, because it is a DIFFERENT RULE with
# a LARGER value -- `Mx.S.7` is 0.07 against `Mx.S.1`'s 0.05, and M1's is
# 0.06 and not the same rule again. An edge shorter than the card's
# `line_end_def` facing a gap is a line end and takes the larger spacing.


def _merge_components(shapes):
    """Union-find over shapes that OVERLAP OR TOUCH, per layer.

    `shapes` are rec-tuples `(layer, x1, y1, x2, y2, net)`. Returns a list
    of component ids parallel to `shapes`. This is the polygon merge the
    signoff tool does before it measures anything."""
    n = len(shapes)
    find, union = _union_find(n)
    for i in range(n):
        ax1, ay1, ax2, ay2 = shapes[i][1:5]
        for j in range(i + 1, n):
            bx1, by1, bx2, by2 = shapes[j][1:5]
            # touching counts: a shared edge merges two rectangles
            if (ax1 <= bx2 + 1e-9 and bx1 <= ax2 + 1e-9 and
                    ay1 <= by2 + 1e-9 and by1 <= ay2 + 1e-9):
                union(i, j)
    return [find(i) for i in range(n)]


def via_enclosure(rules, rec, ref=(), cut_layers=ALL_CUTS, via_met=None):
    """`VIAx.EN.1`/`EN.2` offline -- IS EVERY CUT ACTUALLY COVERED?

    The most basic via question there is, and until 2026-08-03 nothing in
    the 28 nm engine asked it. Every other via gate models a CONDITIONAL
    enclosure -- a crowded line (`EN.11`), a wide landing (`R.2`/`R.3`), a
    nearby plate (`R.4`) -- and all three assume the plain one holds. It
    does not hold by construction: a drawing layer's `via` draws a pad only
    for the layers a caller NAMES, and omitting one is legitimate whenever
    existing metal covers the cut. Whether it does is the caller's claim,
    and this is what checks it.

    ⚠️ **THE REQUIREMENT IS A DISJUNCTION AND MODELLING IT AS A CONJUNCTION
    REPORTS FIVE SIGNED-OFF BLOCKS.** `EN.1`+`EN.2` is "the along enclosure
    on ONE opposing pair of sides and ~zero on the other", and WHICH pair is
    not fixed by the layer -- a pad extends a wire along its own direction,
    but a landing that is a vendor pin rect or a wide strap runs whichever
    way the library drew it. Checked in the preferred direction only, this
    reported four blocks, all of them DRC-clean on the cluster. So both
    orientations are tried and either one passing is a pass.

    ⚠️ **AND A CUT WITH NO SAME-NET METAL AT ALL ON A LAYER IS SKIPPED, NOT
    REPORTED.** That is the signature of a landing this flow cannot see --
    a placed instance's own pin that nothing declared through `mark_pin`,
    which is the blind spot every offline check here shares. Reporting it
    would describe the declaration and not the geometry, and a cut that
    genuinely touches nothing is already an island to `opens`.

    Coverage is measured against the UNION of that net's shapes on the
    layer, so a pad plus the wire it sits on count together -- which is how
    a legitimately pad-less via passes.
    """
    via_met = VIA_MET if via_met is None else via_met
    allsh = list(rec) + list(ref)
    out = []
    for cut_layer in cut_layers:
        pair = via_met.get(cut_layer)
        if not pair:
            continue
        cuts = [q for q in allsh if q[0] == cut_layer]
        if not cuts:
            continue
        _cut, e_along, e_across = rules.via_geometry(cut_layer)
        for metal in pair:
            # ⚠️ A LAYER'S ENCLOSURE CAN DIFFER FROM ITS TIER'S. tsmc28
            # measured M9-over-VIA8 needing 0.300 where the tier says
            # 0.080 (2 blocking M9.EN.1 on the tile's first build). A
            # rules object MAY expose `via_enclosure_for(cut, metal)`
            # returning a per-layer (along, across) override or None;
            # absent accessor or None means the tier's own pair -- the
            # exact previous behaviour.
            _ov = getattr(rules, "via_enclosure_for", None)
            _pair_enc = _ov(cut_layer, metal) if _ov is not None else None
            if _pair_enc is not None:
                m_along, m_across = _pair_enc
            else:
                m_along, m_across = e_along, e_across
            sh = [q for q in allsh if q[0] == metal]
            for c in cuts:
                cover = [(q[1], q[2], q[3], q[4]) for q in sh
                         if (q[5] == c[5] or q[5] is None or c[5] is None)
                         and q[1] < c[3] - 1e-9 and c[1] < q[3] - 1e-9
                         and q[2] < c[4] - 1e-9 and c[2] < q[4] - 1e-9]
                if not cover:
                    continue                  # undeclared instance metal
                worst = None
                for ex, ey in ((m_along, m_across), (m_across, m_along)):
                    need = (c[1] - ex, c[2] - ey, c[3] + ex, c[4] + ey)
                    left = _uncovered(need, cover)
                    if not left:
                        worst = None
                        break
                    gap = max(max(q[2] - q[0], q[3] - q[1]) for q in left)
                    if worst is None or gap < worst[0]:
                        worst = (gap, need)
                if worst is None:
                    continue
                gap, need = worst
                out.append(
                    "ENC {}:{} cut @ ({:.3f},{:.3f}) net {} is not enclosed "
                    "-- {:.3f} um of the {:.3f} x {:.3f} it needs has no {} "
                    "on that net under it".format(
                        cut_layer, metal, (c[1] + c[3]) / 2.0,
                        (c[2] + c[4]) / 2.0, c[5], gap,
                        need[2] - need[0], need[3] - need[1], metal))
    return sorted(set(out))


def via_crowded_enclosure(rules, rec, ref=(),
                          cut_layers=("VIA1", "VIA2", "VIA3")):
    """`Mx.EN.11` offline -- a via on a narrow line with a close neighbour.

    ⚠️ A HELD ENCLOSURE SCHEME CAN PUT 0.0 ON TWO OPPOSITE SIDES, AND THIS
    IS THE RULE THAT TAKES IT BACK. On a metal line between the card's two
    width bounds, with other metal nearer than its neighbour threshold
    running parallel for more than its run threshold, the deck wants
    enclosure on the side facing that neighbour. A flush edge -- which
    every other enclosure rule here accepts -- is a violation.

    That is not an exotic case. It is the NORMAL case for an escape jog
    threading a congested band, which is exactly where `lock_detector_1`
    hit it: a 0.11 um jog 0.08 um from a supply bus, one `M2.EN.11`, on
    geometry that satisfied `VIAx.EN.1` and `EN.2` both.

    Approximate in the same way its siblings are: widths and runs are
    measured per RECTANGLE rather than over merged polygons, and the
    same-via-group exemption is applied by net rather than by the deck's
    full construction.
    """
    cr = rules.via_enclosure_crowded()
    if not cr:
        return []
    lo, hi = cr["metal_width_gt_um"], cr["metal_width_le_um"]
    d1, prl, need = (cr["neighbour_space_lt_um"],
                     cr["parallel_run_gt_um"], cr["value_um"])
    allsh = list(rec) + list(ref)
    out = []
    for cut in cut_layers:
        try:
            n = int(cut[3:])
        except ValueError:
            continue
        for c in [q for q in allsh if q[0] == cut]:
            cx, cy = (c[1] + c[3]) / 2.0, (c[2] + c[4]) / 2.0
            for metal in ("M%d" % n, "M%d" % (n + 1)):
                sh = [q for q in allsh if q[0] == metal]
                host = [q for q in sh
                        if q[1] - 1e-9 <= cx <= q[3] + 1e-9 and
                        q[2] - 1e-9 <= cy <= q[4] + 1e-9]
                if not host:
                    continue
                h = max(host, key=lambda q: (q[3] - q[1]) * (q[4] - q[2]))
                wid = min(h[3] - h[1], h[4] - h[2])
                if not (lo + 1e-9 < wid <= hi + 1e-9):
                    continue
                for o in sh:
                    if o is h or o[5] == h[5]:
                        continue
                    dx = max(o[1] - h[3], h[1] - o[3])
                    dy = max(o[2] - h[4], h[2] - o[4])
                    if max(dx, dy) >= d1 - 1e-9 or max(dx, dy) < 0:
                        continue
                    if dx >= dy:        # gap in x; run is the y overlap
                        run = min(h[4], o[4]) - max(h[2], o[2])
                        got = (h[3] - c[3]) if o[1] > h[3] else (c[1] - h[1])
                    else:
                        run = min(h[3], o[3]) - max(h[1], o[1])
                        got = (h[4] - c[4]) if o[2] > h[4] else (c[2] - h[2])
                    if run <= prl + 1e-9 or got >= need - 1e-9:
                        continue
                    out.append(
                        "ENC {} {}:{} cut @ ({:.3f},{:.3f}) net {} is "
                        "enclosed {:.3f} facing net {} {:.3f} away on a "
                        "{:.2f} um line -- needs {}"
                        .format(cr["rule"], cut, metal, cx, cy, c[5],
                                got, o[5], max(dx, dy), wid, need))
                    break
    return out


def via_wide_landing(rules, rec, ref=(), cut_layers=ALL_CUTS):
    """`VIAx.R.2/R.3` offline -- a lone cut on metal wide in BOTH axes.

    ▶ The finding it produces is the rule's own disjunction: `R.2` is
    `(Mx wide AND Mx+1i) OR (Mx+1 wide AND Mxi)`, so ONE wide side is
    enough. The landing a caller declares for the redundancy PREDICATE is
    the LARGER of the two; which way the cuts are LAID has to suit the
    smaller.

    The deck reads the MERGED metal, so a via dropped anywhere on a
    0.28 x 50 um guard-ring strap is a redundancy case however small the
    pad drawn at its centre.

    Satisfied by one RECTANGULAR cut, or by two square cuts close enough
    to count as one connection (`VIAx.R.2`'s own `max_space_um`, which is
    a CEILING -- unlike R.4, which has none).

    ⚠️⚠️ **EVERY NUMBER HERE IS THE CUT LAYER'S OWN TIER, AND ONE TIER FOR
    ALL EIGHT REPORTS A LEGAL PAIR AS A LONE CUT.** One tier wants two cuts
    within 0.100 um over a 0.180 um landing; another wants them within
    0.200 over 0.300. The card knows which tier a cut layer is in
    (`rules.via_tier`); nothing here may assume.

    ⚠️ **AND ONE TIER'S RULE IS NOT GATED ON A WIDTH AT ALL** -- "at least
    2 cuts are required to connect", with no width predicate. A `min()`
    over a key that tier does not carry is a `TypeError` two blocks later,
    and defaulting it to some number invents a threshold the deck does not
    have.

    ⚠️⚠️ **THE SITE'S TIER IS THE HIGHEST ANY ONE OF ITS TWO CONDUCTORS
    REACHES, AND CHECKING ONLY THE LOWEST PASSES A CONSTRUCTION THE DECK
    REJECTS.** This used to take the smallest threshold in the table, ask
    "is some metal here wider than that", and then accept any second cut
    within the two-square spacing. Where either metal is over the SECOND
    threshold that is wrong twice: the tier there wants FOUR squares, and
    two is not an option in it at any spacing.

    Measured 2026-08-26 over 31 islands (`chip/floorplan/viapair_probe.py`,
    every one as predicted): a 0.10 um M2 stub landing on a 1.0 um M3 bus
    draws two `VIA2.R.2__VIA2.R.3` markers for exactly the pair this gate
    was passing -- and the stub's own width, the only number its caller
    declared, is 0.10.

    So the tier comes from the WIDEST conductor over the cut, and the test
    is that tier's whole option table rather than a hard-coded pair: 4
    squares within 0.10, TWO SLOTS within 0.13, or one slot and two
    squares within 0.13. The slot options are not decoration -- on a stub
    too narrow to hold a 2x2 they are the only two-cut construction R.3
    admits.

    Two stated approximations:

    * Same as `via_plates`: the landing is judged per RECTANGLE, so metal
      that is only wide once several rectangles are unioned is not seen.
    * The deck grows each cut `INSIDE OF` the Mx AND Mx+1 OVERLAP, so a
      merge that would have to leave the overlap does not happen there and
      does here. That is the permissive direction, and only for cuts
      straddling the edge of one of their own conductors -- which is what
      `via_enclosure` is for.
    """
    allsh = list(rec) + list(ref)
    out = []
    for cut in cut_layers:
        try:
            n = int(cut[3:])
        except ValueError:
            continue
        cuts = [c for c in allsh if c[0] == cut]
        if not cuts:
            continue
        tier = rules.via_tier(cut)
        tiers = rules.via_redundancy_tiers(tier)
        if not tiers:
            continue
        want = [t.get("width_and_length_gt_um") for t in tiers]
        num = [v for v in want if isinstance(v, (int, float))]
        ungated = any(v is None for v in want)
        if not num and not ungated:
            continue
        try:
            rl, rs = rules.via_rect_cut(cut)
        except Exception:                                   # noqa: BLE001
            rl, rs = None, None

        def _is_slot(c, rl=rl, rs=rs):
            cw, ch = c[3] - c[1], c[4] - c[2]
            return (rl is not None and abs(max(cw, ch) - rl) < 1e-9 and
                    abs(min(cw, ch) - rs) < 1e-9)

        def _group(seed, space, cuts=cuts):
            """Every cut `seed` merges with at `space`, the way the deck's
            `SIZE ... BY space/2` does: a CHAIN, not a radius. Four cuts in
            a row at the ceiling are one merged region, and that row is a
            construction the deck accepts (measured, `stub_bus_4sq100`)."""
            grp, frontier = {id(seed): seed}, [seed]
            while frontier:
                a = frontier.pop()
                for o in cuts:
                    if id(o) in grp:
                        continue
                    if max(max(o[1] - a[3], a[1] - o[3]),
                           max(o[2] - a[4], a[2] - o[4])) <= space + 1e-9:
                        grp[id(o)] = o
                        frontier.append(o)
            return list(grp.values())

        for c in cuts:
            cx, cy = (c[1] + c[3]) / 2.0, (c[2] + c[4]) / 2.0
            # ⚠️⚠️ THE TIER IS THE SITE'S, AND THE SITE HAS TWO
            # CONDUCTORS: `(Mx wide AND Mx+1i) OR (Mx+1 wide AND Mxi)`.
            # The WIDEST metal over this cut chooses the rule -- by its
            # NARROW dimension, which is what the deck's `WITH WIDTH`
            # measures.
            site = None
            for metal in (VIA_MET.get(cut) or ("M%d" % n, "M%d" % (n + 1))):
                for s in allsh:
                    if s[0] != metal:
                        continue
                    if not (s[1] - 1e-9 <= cx <= s[3] + 1e-9 and
                            s[2] - 1e-9 <= cy <= s[4] + 1e-9):
                        continue
                    w, h = s[3] - s[1], s[4] - s[2]
                    if site is None or min(w, h) > min(site[1], site[2]):
                        site = (metal, w, h)
            # the HIGHEST tier any one conductor reaches -- stopping at the
            # lowest threshold is what passed a pair on an R.3 site
            gov, thr = None, None
            for t in tiers:
                v = t.get("width_and_length_gt_um")
                if v is None:                    # ungated: applies always
                    if gov is None:
                        gov, thr = t, None
                    continue
                if site is None or min(site[1], site[2]) <= v + 1e-9:
                    continue
                if thr is None or v > thr:
                    gov, thr = t, v
            if gov is None:
                continue
            # ⚠️ A TIER MAY STATE ITSELF WITHOUT AN OPTION TABLE. The
            # contract's flat form is `{rule, width_and_length_gt_um,
            # max_space_um}` -- one construction, two square cuts, which
            # is what `via_pair_space` is in the protocol for. Reading
            # only `options` turns such a tier into "nothing satisfies
            # this" and fires on every cut on it; a card that HAS the
            # table is the richer case, not the only one.
            opts = list(gov.get("options", ()))
            if not opts:
                opts = [{"count": 2, "shape": "square",
                         "max_space_um": gov.get("max_space_um") or
                         rules.via_pair_space(cut) or 0.1}]
            ok = None
            for o in opts:
                space, shape = o.get("max_space_um"), o.get("shape", "square")
                if space is None:
                    # the lone-slot option: one cut, no merge, no spacing
                    if shape == "rectangular" and o.get("count", 1) <= 1 \
                            and _is_slot(c):
                        ok = o
                        break
                    continue
                g = _group(c, space)
                sq = sum(1 for x in g if not _is_slot(x))
                rect = len(g) - sq
                if shape == "square" and sq >= o["count"]:
                    ok = o
                elif shape == "rectangular" and rect >= o["count"]:
                    ok = o
                elif shape == "mixed" and rect >= o.get("rect", 1) and \
                        sq >= o.get("square", 0):
                    ok = o
                if ok:
                    break
            if ok:
                continue
            widest = max([o.get("max_space_um") or 0.0
                          for o in opts] or [0.0])
            g = _group(c, widest)
            out.append(
                "WIDE {} {} @ ({:.3f},{:.3f}) net {} on a {:.2f} x {:.2f} "
                "{} site ({}) -- {} cut(s) merge here, and this tier "
                "accepts only {}"
                .format(gov["rule"], cut, cx, cy, c[5],
                        site[1] if site else 0.0, site[2] if site else 0.0,
                        site[0] if site else "?",
                        "ungated" if thr is None else "both > %s" % thr,
                        len(g),
                        " or ".join(
                            "{}{} {}{}".format(
                                o.get("count"),
                                ("(%d square + %d slot)" % (o.get("square", 0),
                                                            o.get("rect", 0)))
                                if o.get("shape") == "mixed" else "",
                                o.get("shape", "square"),
                                "" if o.get("max_space_um") is None
                                else " within %s" % o["max_space_um"])
                            for o in opts)))
    return out


def via_plates(rules, rec, ref=(), cut_layers=("VIA1", "VIA2", "VIA3")):
    """`VIAx.R.4/R.5/R.6` offline -- a lone square via beside a big plate.

    ⚠️ THIS IS THE CHECK THAT DID NOT EXIST, and its absence is what made
    one marker cost three sessions. A redundancy predicate models the rule,
    but only for a caller that VOLUNTEERS a plate distance, and almost no
    caller can: the plate is usually a VENDOR PIN or a neighbouring net's
    metal that the code placing the via never looks at. `lock_detector_1`'s
    landing was 0.475 um from `INVD4BWP35P140`'s `ZN` -- 0.21 x 0.31 of M2,
    a plate by this rule's 0.18 -- and nothing in the block knew that.

    So this measures it from the GEOMETRY instead, which is the only place
    the answer actually lives. It reads the way the deck's own body does
    (`VIA1.R.4:M2`):

        plate   metal wider than the tier's threshold in BOTH axes
        branch  metal of the SAME polygon, narrower than that, TOUCHING
                the plate -- the deck subtracts the plate from its own
                sized region, so a via ON the plate is R.2's business,
                not this rule's
        bad     a branch holding exactly ONE SQUARE cut, within D of
                where the branch meets the plate

    A RECTANGULAR cut passes on its own, and so do two cuts on one branch
    -- with no spacing ceiling on the pair, which is a real difference
    from R.2 and the reason a pair that will not fit R.2's 0.10 can still
    be the fix.

    Two ways this is APPROXIMATE, both stated because a check that
    overstates itself is worse than none:

    * a plate assembled from several abutting rectangles is not seen as
      one plate, only each rectangle on its own. Every plate that has
      mattered so far is a single rect -- a vendor pin, a MOM's metal --
      but a hand-built one could hide here.
    * the distance is centre-to-plate Euclidean, where the deck walks the
      branch from the edge it attaches by. For a straight branch these
      agree; for an L they do not, and this reads SHORTER, so it errs
      towards reporting.
    """
    allsh = list(rec) + list(ref)
    tiers = rules.plate_proximity_rules()
    try:
        rl, rs = rules.via_rect_cut()
    except Exception:                                       # noqa: BLE001
        rl, rs = None, None
    out = []
    for cut in cut_layers:
        try:
            n = int(cut[3:])
        except ValueError:
            continue
        cuts = [r for r in allsh if r[0] == cut]
        if not cuts:
            continue
        for metal in ("M%d" % n, "M%d" % (n + 1)):
            sh = [r for r in allsh if r[0] == metal]
            if not sh:
                continue
            comp = _merge_components(sh)
            for tier in tiers:
                wthr = tier.get("plate_min_width_um")
                lthr = tier.get("plate_min_length_um")
                dmax = tier.get("max_distance_um")
                if wthr is None or dmax is None:
                    continue
                plates = [i for i in range(len(sh))
                          if min(sh[i][3] - sh[i][1],
                                 sh[i][4] - sh[i][2]) > wthr + 1e-9 and
                          max(sh[i][3] - sh[i][1],
                              sh[i][4] - sh[i][2]) > lthr + 1e-9]
                if not plates:
                    continue
                for c in cuts:
                    cx = (c[1] + c[3]) / 2.0
                    cy = (c[2] + c[4]) / 2.0
                    cw, ch = c[3] - c[1], c[4] - c[2]
                    # a rectangular cut is one connection by itself
                    if rl is not None and abs(
                            max(cw, ch) - rl) < 1e-9 and abs(
                            min(cw, ch) - rs) < 1e-9:
                        continue
                    # which polygon is this cut on, and is it ON a plate?
                    home, on_plate = None, False
                    for i in range(len(sh)):
                        if (sh[i][1] - 1e-9 <= cx <= sh[i][3] + 1e-9 and
                                sh[i][2] - 1e-9 <= cy <= sh[i][4] + 1e-9):
                            home = comp[i]
                            if i in plates:
                                on_plate = True
                    if home is None or on_plate:
                        continue
                    near = None
                    for i in plates:
                        if comp[i] != home:
                            continue
                        dx = max(sh[i][1] - cx, cx - sh[i][3], 0.0)
                        dy = max(sh[i][2] - cy, cy - sh[i][4], 0.0)
                        d = (dx * dx + dy * dy) ** 0.5
                        if near is None or d < near[0]:
                            near = (d, sh[i])
                    if near is None or near[0] > dmax + 1e-9:
                        continue
                    # two cuts on one branch also pass, at any spacing
                    sibs = sum(1 for o in cuts
                               if o is not c and
                               any(sh[i][1] - 1e-9 <= (o[1] + o[3]) / 2.0
                                   <= sh[i][3] + 1e-9 and
                                   sh[i][2] - 1e-9 <= (o[2] + o[4]) / 2.0
                                   <= sh[i][4] + 1e-9 and comp[i] == home
                                   for i in range(len(sh))))
                    if sibs:
                        continue
                    p = near[1]
                    out.append(
                        "PLATE {} {}:{} lone square cut @ ({:.3f},{:.3f}) "
                        "net {} is {:.3f} um from a {:.2f} x {:.2f} plate "
                        "(<= {}) -- needs 2 cuts or 1 rectangular"
                        .format(tier["rule"], cut, metal, cx, cy, c[5],
                                near[0], p[3] - p[1], p[4] - p[2], dmax))
                    break           # one tier is enough to report
    return out


def min_area(rules, rec, ref=(), layers=("M2", "M3", "M4")):
    """`Mx.A.2` and `Mx.A.3` over merged same-net polygons.

    TWO PREDICATES, and the second is not the first with a bigger number:

      Mx.A.2   union area >= `rules.min_area(layer)`
      Mx.A.3   a shape whose edges are ALL under `compact_edge_um` must
               enclose a 0.05 x `compact_edge` rectangle -- which a
               component whose bounding box is under it in BOTH directions
               cannot do at any area. So no island may be small in both
               directions, however much area it has.

    ⚠️ **AN ISLAND IS ONLY AN ISLAND IF NOTHING ELSE COVERS IT.** A pad
    that merges with a vendor pin, a rail strap or a bus is part of that
    shape and the rule never sees it alone, so `ref` is merged in exactly as
    the spacing gate merges it -- and a component made only of `ref` is the
    LIBRARY's geometry and not ours to report.

    ⚠️⚠️ **WHICH IS WHY `M1` IS NOT IN THE DEFAULT LIST, AND THE REASON IS
    A MEASUREMENT AND NOT A PREFERENCE.** Run on M1 at 28 nm this gate
    reports SEVEN signed-off DRC-clean blocks -- 133 findings on
    `charge_pump_2` alone -- and every one is a riser onto a device's own
    source/drain column or gate pad: metal drawn INSIDE the PCell, which
    this flow never opens, so it is in neither `rec` nor `ref`. The riser
    is not an island; the gate simply cannot see what it merges with. It is
    the blind spot every offline check in this engine shares, stated once
    here rather than worked around. Pass `layers=("M1",)` deliberately if
    you have a block whose M1 really is all its own.
    """
    out = []
    allsh = [(r, False) for r in rec] + [(r, True) for r in ref]
    try:
        edge = rules.compact_edge()
    except Exception:                                       # noqa: BLE001
        return out
    for layer in layers:
        pairs = [(r, f) for r, f in allsh if r[0] == layer]
        if not pairs:
            continue
        try:
            need = rules.min_area(layer)
        except Exception:                                   # noqa: BLE001
            continue
        sh = [r for r, _ in pairs]
        isref = [f for _, f in pairs]
        # per NET as well as per layer: two nets that touch are a SHORT and
        # `shorts` is what reports that -- merging them here would hide a
        # small island inside someone else's polygon.
        keyed = {}
        for i, r in enumerate(sh):
            keyed.setdefault(r[5], []).append(i)
        for net, idx in sorted(keyed.items()):
            sub = [sh[i] for i in idx]
            comp = _merge_components(sub)
            groups = {}
            for k, c in enumerate(comp):
                groups.setdefault(c, []).append(k)
            for members in groups.values():
                if all(isref[idx[k]] for k in members):
                    continue                      # the library's own metal
                rects = [tuple(sub[k][1:5]) for k in members]
                area = _union_area(rects)
                bw = max(r[2] for r in rects) - min(r[0] for r in rects)
                bh = max(r[3] for r in rects) - min(r[1] for r in rects)
                at = (round(min(r[0] for r in rects), 3),
                      round(min(r[1] for r in rects), 3))
                if area < need - 1e-12:
                    out.append(
                        "{} {}.A.2 {} um2 < {} on net {} at {} ({:.3f} x "
                        "{:.3f}) -- a square pad of {} clears it".format(
                            layer, layer, round(area, 5), need, net, at,
                            bw, bh, rules.landing_pad(layer)))
                elif bw < edge - 1e-12 and bh < edge - 1e-12:
                    out.append(
                        "{} {}.A.3 {:.3f} x {:.3f} on net {} at {} -- every "
                        "edge is under {} and no {} x {} rectangle fits "
                        "inside it".format(layer, layer, bw, bh, net, at,
                                           edge, 0.05, edge))
    return out


def spacing(rules, rec, ref=(), layers=("M1", "M2", "M3"), min_space=None,
            line_end=None, line_end_def=None):
    """Same-layer spacing over merged polygons. Returns a list of lines.

    `min_space(layer)` and `line_end(layer)` default to the rules object's
    own accessors, so this reports against the process rather than against
    a constant someone typed here."""
    min_space = min_space or rules.min_space
    line_end = line_end or rules.line_end_space
    out = []

    # ⚠️ THE WIDE-METAL TIERS ARE PART OF THE SPACING RULE, and this gate
    # once did not model them. The flat minimum's own docstring says
    # "above a width AND a parallel-run threshold the wide-metal tiers
    # take over ... a caller separating two WIDE shapes with a long
    # parallel run has to consult those as well" -- and nothing consulted
    # them. So this reported clean on a 0.070 gap that the deck answered
    # with `M2.S.13`: a 0.11 um escape stub beside a 0.15 um supply bus,
    # 0.535 um of parallel run, where the governing number is 0.08 and not
    # the line-end rule's 0.07.
    #
    # The tiers are a CONJUNCTION of both thresholds and they apply if
    # EITHER shape is wide -- the deck says "at least one metal line
    # width > W1". The width that matters is the one ACROSS the gap, and
    # the parallel run is the overlap along it.
    def _tier_space(layer, wa, wb, run):
        try:
            tiers = rules.wide_metal_tiers(layer)
        except Exception:                                   # noqa: BLE001
            return 0.0
        need = 0.0
        for t in tiers:
            if max(wa, wb) > t["width_gt_um"] + 1e-9 and \
                    run > t["parallel_run_gt_um"] + 1e-9:
                need = max(need, t["space_um"])
        return need
    # ⚠️ REF-AGAINST-REF IS NOT OURS TO REPORT. A vendor cell's own pins
    # sit 0.05 um apart by construction and the cell is DRC-clean as
    # built; measuring one of its pins against another reports the
    # LIBRARY, not the route. Drawn-vs-drawn and drawn-vs-ref are the
    # pairs this engine can actually do something about.
    allsh = [(r, False) for r in rec] + [(r, True) for r in ref]
    for layer in layers:
        pairs = [(r, f) for r, f in allsh if r[0] == layer]
        sh = [r for r, _ in pairs]
        isref = [f for _, f in pairs]
        if len(sh) < 2:
            continue
        try:
            need = min_space(layer)
            need_le = line_end(layer)
            # ⚠️ TWO line-ends FACING EACH OTHER can carry a THIRD,
            # stricter number -- tsmc28's M2.S.12 wants 0.08 where S.7
            # ("space TO a line-end", either-edge) wants 0.07, and the
            # golden probe's clean twin at 0.07 drew exactly one S.12.
            # A rules object MAY expose `line_end_pair_space(layer)`
            # -> um|None for the both-ends case; None or an absent
            # accessor means no distinct pair rule (the previous
            # behaviour). A REFUSAL skips the layer exactly as a
            # refused line_end does -- an incomplete line-end model is
            # loud, never quietly weaker.
            _pair = getattr(rules, "line_end_pair_space", None)
            need_pair = _pair(layer) if _pair is not None else None
        except Exception:                                   # noqa: BLE001
            continue
        led = line_end_def if line_end_def is not None else need_le
        comp = _merge_components(sh)
        worst = {}
        for i in range(len(sh)):
            ax1, ay1, ax2, ay2 = sh[i][1:5]
            for j in range(i + 1, len(sh)):
                if isref[i] and isref[j]:
                    continue            # the library's own geometry
                same = comp[i] == comp[j]
                bx1, by1, bx2, by2 = sh[j][1:5]
                dx = max(bx1 - ax2, ax1 - bx2)
                dy = max(by1 - ay2, ay1 - by2)
                # ⚠️ A DIAGONAL PAIR IS NOT EXEMPT. Skipping it looks
                # right -- corner-to-corner is not edge-to-edge -- and
                # this deck measures it anyway: two landings 0.03 apart
                # in BOTH x and y are 0.042 apart and drew an M2.S.1.
                # So the corner distance is the measure when neither
                # axis overlaps.
                if dx > 0 and dy > 0:
                    gap = (dx * dx + dy * dy) ** 0.5
                else:
                    gap = max(dx, dy)
                if gap < 0:
                    continue
                # A LINE END is a short edge facing the gap, and it takes
                # the larger spacing. Which edge faces depends on which
                # axis the gap is on.
                if dx >= dy:
                    ea, eb = ay2 - ay1, by2 - by1
                else:
                    ea, eb = ax2 - ax1, bx2 - bx1
                want = need_le if min(ea, eb) < led - 1e-9 else need
                # ...the both-ends case (see the lookup above)
                if need_pair is not None and max(ea, eb) < led - 1e-9:
                    want = max(want, need_pair)
                # ...and the wide-metal tier, if either shape is wide and
                # they run parallel far enough. The run is the overlap
                # ALONG the gap -- a gap measured in x is spanned by a
                # run in y -- and the WIDTH is each shape's own narrow
                # dimension, which is NOT the edge facing the gap: two
                # 0.11 um wires 30 um long face each other with 30 um
                # edges and are 0.11 um wide. Reading the facing edge as
                # the width put every long parallel pair in the 1.5 um
                # tier and asked for 0.5 um of space.
                if dx >= dy:
                    run = min(ay2, by2) - max(ay1, by1)
                else:
                    run = min(ax2, bx2) - max(ax1, bx1)
                wa = min(ax2 - ax1, ay2 - ay1)
                wb = min(bx2 - bx1, by2 - by1)
                want = max(want, _tier_space(layer, wa, wb, run))
                if gap >= want - 1e-9:
                    continue
                # ⚠️ ONE POLYGON IS NOT A FREE PASS -- IT MAY HAVE A NOTCH.
                # Two shapes of the same merged polygon can still face each
                # other across a slot, if whatever joins them does so
                # SOMEWHERE ELSE. lock_detector_1's last M2.S.1 was exactly
                # that: `I4.ZN` below, a via pad above, and the bus that
                # connects them starting 0.055 um further east, leaving a
                # 0.045 um notch west of it. Skipping same-component pairs
                # -- which is right for spacing -- made it invisible.
                #
                # So the gap region is built and the rest of the polygon
                # SUBTRACTED from it. What survives is metal-free, and a
                # metal-free slot narrower than the rule is a violation
                # whether it is between two polygons or inside one.
                if same:
                    if dx >= dy:
                        gr = (min(ax2, bx2), max(ay1, by1),
                              max(ax1, bx1), min(ay2, by2))
                    else:
                        gr = (max(ax1, bx1), min(ay2, by2),
                              min(ax2, bx2), max(ay1, by1))
                    if gr[2] - gr[0] <= 1e-9 or gr[3] - gr[1] <= 1e-9:
                        continue
                    others = [sh[k][1:5] for k in range(len(sh))
                              if k != i and k != j and comp[k] == comp[i]]
                    if not _uncovered(gr, others):
                        continue        # the polygon fills its own gap
                key = (comp[i], comp[j], round(gap, 4))
                rule = ("notch" if same else
                        ("line-end" if want == need_le else "space"))
                if key not in worst or gap < worst[key][0]:
                    worst[key] = (gap, want, rule, sh[i], sh[j])
        for gap, want, rule, a, b in sorted(worst.values()):
            out.append(
                "SPACE {} {} {}/{}: {:.4f} < {:.3f} @ ({:.3f},{:.3f})"
                .format(layer, rule, a[5], b[5], gap, want, a[1], a[2]))
    return out


def min_edge(rules, rec, ref=(), layers=("M2", "M3", "M4"), min_w=None):
    """`G.4` offline -- *"adjacent edges with length less than min. width"*.

    ⚠️⚠️ **A SHORT EDGE IS NOT A VIOLATION AND COUNTING THEM IS NOT THE
    RULE.** One measured geometry has 164 boundary edges under `min_width`,
    and 118 of them fire nothing: a step whose two neighbours are both long
    is legal, and a pad that stands proud of its wire by 0.020 um is that.
    The rule wants a VERTEX where BOTH edges are short, and modelling it as
    "edges under min width" would send a router chasing legal metal.

    ▶ **The count reproduces Calibre digit for digit** on the block that
    taught it: 46 such vertices, 92 distinct edges taking part in one --
    and 92 is what the deck answered. Each participating edge is one
    result, so a line here is worth two markers when the two edges are
    counted separately.

    ⚠️ **AN INCOMPLETE VIEW OF A POLYGON CAN INVENT A NOTCH.** A rect this
    flow cannot see -- a PCell's own interior metal -- may be exactly what
    fills the step, so this reports metal that is legal in the layout. That
    is why `M1` is not in the default list, for the same measured reason
    `min_area` leaves it out: below M2 the engine does not see everything
    a shape merges with. Pass `layers=("M1",)` deliberately.

    Per NET and per LAYER, like every gate here -- two nets that touch are
    a SHORT and `shorts` is what reports that -- and a component made only
    of `ref` is the library's own geometry, not ours to report.
    """
    out = []
    allsh = [(r, False) for r in rec] + [(r, True) for r in ref]
    for layer in layers:
        pairs = [(r, f) for r, f in allsh if r[0] == layer]
        if not pairs:
            continue
        try:
            need = min_w if min_w is not None else rules.min_width(layer)
        except Exception:                                   # noqa: BLE001
            continue
        sh = [r for r, _ in pairs]
        isref = [f for _, f in pairs]
        keyed = {}
        for i, r in enumerate(sh):
            keyed.setdefault(r[5], []).append(i)
        for net, idx in sorted(keyed.items()):
            sub = [sh[i] for i in idx]
            comp = _merge_components(sub)
            groups = {}
            for k, c in enumerate(comp):
                groups.setdefault(c, []).append(k)
            for members in sorted(groups.values()):
                if all(isref[idx[k]] for k in members):
                    continue                      # the library's own metal
                rects = [tuple(sub[k][1:5]) for k in members]
                es = _boundary_edges(rects)
                at = {}
                for e in es:
                    ends = (((e[2], e[1]), (e[3], e[1])) if e[0] == "H"
                            else ((e[1], e[2]), (e[1], e[3])))
                    for p in ends:
                        at.setdefault((round(p[0], 6), round(p[1], 6)),
                                      []).append(e)
                for p, lst in sorted(at.items()):
                    short = [e for e in lst if (e[3] - e[2]) < need - 1e-9]
                    if len(short) < 2:
                        continue
                    a, b = short[0], short[1]
                    out.append(
                        "EDGE {} G.4 net {} @ ({:.3f},{:.3f}): adjacent "
                        "edges {:.3f} and {:.3f} are both under {:.3f}"
                        .format(layer, net, p[0], p[1], a[3] - a[2],
                                b[3] - b[2], need))
    return sorted(set(out))
