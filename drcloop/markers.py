#!/usr/bin/env python3
"""A marker's geometry, and the patch that closes it. Node-agnostic.

    cond  = markers.Conductors({"MET2": [(x0, y0, x1, y1), ...], ...})
    patch = markers.close_area(marker, "MET2", cond, rules)

THE MARKER **IS** THE SHAPE THAT IS WRONG. Everything here starts from the
polygon the deck wrote, never from the plan that drew it -- see the package
docstring for why. What a caller supplies is the two things the deck knows and
this package cannot:

  * the CONDUCTORS, flattened out of **the stream the deck read** (not the
    route file, which is the plan again). Each port has its own flattener;
    all this needs is `{layer: [(x0, y0, x1, y1), ...]}` of DRAWING purpose;
  * a `rules` object answering `min_area(layer)`, `min_space(layer)` and
    `grid()`. A fact it cannot answer is a refusal, never a default.

FIVE MEASURED FACTS THIS FILE ENCODES
-------------------------------------
1. ⚠️ **The area is a SHOELACE, not a bounding box.** The deck's marker for
   one via pad measured 0.290 x 0.195 across its bbox and **0.0561 um2** in
   fact -- a 0.290 x 0.190 bar with a 0.190 x 0.005 step. Sizing off the bbox
   understates the deficit by the step and leaves the result standing, which
   reads in the next run exactly like a patch that was never applied.
2. ⚠️ **The patch spans the polygon's cross-extent AT THE EDGE it joins**,
   not the bounding box's. On a stepped polygon the bbox reaches past the
   metal, and an extension that merely touches a corner is a NOTCH -- a rule
   family both ports have already paid for.
3. ⚠️ **A bar is extended along its LONG axis.** Widening it instead moves it
   into a neighbour's track, which trades an area rule for a spacing one.
4. ⚠️ **The clearance test carries NO NET NAMES, and that is correct.** Being
   one net excuses a SHORT and excuses nothing else -- not spacing, not notch,
   not width. Same-net metal a patch does not MERGE with still owes the space.
5. ⚠️ **Both directions are tried.** On a real run one marker of 116 needed
   the direction the other 115 did not, which is the entire reason to ask
   rather than to pick.

AND THE REFUSAL IS A RESULT. A marker that cannot be closed clear of its
neighbours is returned BY NAME with the clearance that beat it. A silent skip
and a fix look identical in the next DRC run, which is the whole failure mode
this package exists to remove.
"""
import collections

TOL = 1e-9


class RulesError(Exception):
    """The `rules` object could not answer a fact the patch needs."""


# ---------------------------------------------------------------------------
# polygon geometry
# ---------------------------------------------------------------------------

def area(pts):
    """Shoelace. -> um2, always positive. NOT the bounding box (fact 1)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def long_axis(pts):
    """'x' or 'y' -- the direction the shape already runs (fact 3).

    Ties go to 'x'. A square marker has no long axis, so the choice is
    arbitrary and both directions get tried anyway.
    """
    b = bbox(pts)
    return "x" if (b[2] - b[0]) >= (b[3] - b[1]) else "y"


def edge_span(pts, axis, hi):
    """(extreme, lo, hi) -- the polygon's extent ACROSS `axis` at one end.

    This is fact 2. `axis` names the direction the patch will grow in; the
    span returned is measured PERPENDICULAR to it, over only those vertices
    sitting on the extreme edge -- so the patch abuts the metal that is
    actually there rather than the bounding box's idea of it.
    """
    i, j = (0, 1) if axis == "x" else (1, 0)
    ext = max(p[i] for p in pts) if hi else min(p[i] for p in pts)
    at = [p[j] for p in pts if abs(p[i] - ext) < TOL]
    if not at:
        raise ValueError("no vertex on the %s %s extreme"
                         % (axis, "high" if hi else "low"))
    return ext, min(at), max(at)


def gap(a, b):
    """Clearance between two boxes, 0 when they overlap or touch.

    The larger of the two axis separations, which is how a deck measures a
    diagonal clearance between rectilinear shapes.
    """
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    if dx <= 0.0 and dy <= 0.0:
        return 0.0
    return max(dx, dy)


def touches(a, b, tol=TOL):
    return gap(a, b) <= tol


def snap_up(v, grid):
    """Round AWAY from zero to the manufacturing grid.

    Never to nearest: a length rounded down is a deficit that survives, and
    it survives looking exactly like a patch that was applied.
    """
    if grid <= 0:
        raise RulesError("grid() answered %r -- a patch cannot be snapped to "
                         "a grid nobody stated" % (grid,))
    return round((int(v / grid - TOL) + 1) * grid, 6)


# ---------------------------------------------------------------------------
# the conductors -- the stream the deck read
# ---------------------------------------------------------------------------

class Conductors(object):
    """A bucketed rectangle index, per layer. Built from the STREAM.

    The caller flattens; this only asks. `by_layer` is
    `{layer: iterable of (x0, y0, x1, y1)}` in um, drawing purpose only --
    a dummy-fill blockage marker streams to the same layer NUMBER as real
    metal on more than one node, and a census that unions the purposes
    reports a blockage as conductor.
    """

    CELL = 5.0

    def __init__(self, by_layer, cell=None):
        self.cell = float(cell or self.CELL)
        self.by = {}
        self.n = {}
        for lay, boxes in by_layer.items():
            grid = collections.defaultdict(list)
            count = 0
            for b in boxes:
                b = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                count += 1
                for cx in range(int(b[0] // self.cell),
                                int(b[2] // self.cell) + 1):
                    for cy in range(int(b[1] // self.cell),
                                    int(b[3] // self.cell) + 1):
                        grid[(cx, cy)].append(b)
            self.by[lay] = grid
            self.n[lay] = count

    def layers(self):
        return sorted(self.by)

    def near(self, layer, box, halo):
        """Every shape whose box comes within `halo` of `box`."""
        grid = self.by.get(layer)
        if grid is None:
            raise RulesError(
                "no conductors were supplied for %r -- 'nothing is near' and "
                "'nobody looked' are the same answer unless the map says which"
                % (layer,))
        q = (box[0] - halo, box[1] - halo, box[2] + halo, box[3] + halo)
        seen, out = set(), []
        for cx in range(int(q[0] // self.cell), int(q[2] // self.cell) + 1):
            for cy in range(int(q[1] // self.cell), int(q[3] // self.cell) + 1):
                for b in grid.get((cx, cy), ()):
                    if id(b) in seen:
                        continue
                    seen.add(id(b))
                    if gap(q, b) <= 0.0:
                        out.append(b)
        return out

    def touching(self, layer, box):
        """The shapes a patch at `box` would MERGE with."""
        return [b for b in self.near(layer, box, 0.0) if touches(b, box)]


# ---------------------------------------------------------------------------
# the patch
# ---------------------------------------------------------------------------

class Patch(object):
    """One rectangle answering one marker, with its own justification."""

    def __init__(self, rule, layer, box, marker_bbox, axis, way,
                 was, need):
        self.rule = rule
        self.layer = layer
        self.box = box
        self.marker_bbox = marker_bbox
        self.axis = axis
        self.way = way              # '+' grew toward high, '-' toward low
        self.was = was              # the marker's measured area, um2
        self.need = need            # the rule's minimum, um2
        self.net = None             # attribution, filled in by the caller

    @property
    def tag(self):
        return "%s_%s%s" % (self.rule, self.axis, self.way)

    def __repr__(self):
        return ("<Patch %s %s %.4f %.4f %.4f %.4f %s>"
                % ((self.rule, self.layer) + tuple(self.box) + (self.tag,)))


class Refusal(object):
    """A marker that could not be closed, named with what beat it."""

    def __init__(self, rule, layer, marker_bbox, why):
        self.rule = rule
        self.layer = layer
        self.marker_bbox = marker_bbox
        self.why = why

    def __repr__(self):
        return ("<Refusal %s %s at %.4f %.4f -- %s>"
                % (self.rule, self.layer, self.marker_bbox[0],
                   self.marker_bbox[1], self.why))


def _ask(rules, name, *args):
    fn = getattr(rules, name, None)
    if fn is None:
        raise RulesError(
            "the rules object cannot answer %s%s -- name the probe that "
            "settles it rather than defaulting one" % (name, args or ()))
    v = fn(*args)
    if v is None:
        raise RulesError("%s%s answered None -- an unmeasured value raises, "
                         "it does not default" % (name, args or ()))
    return v


def close_area(marker, layer, conductors, rules, axis=None):
    """Close ONE minimum-area marker. -> Patch or Refusal.

    `marker` is a record from `resultsdb` (`{rule, kind, pts}`) or anything
    with the same two keys. `axis` overrides the long-axis choice for a
    caller that knows better (a port whose deck reports a marker rotated).

    Returns a `Refusal` -- never None and never a silent skip -- when no
    direction clears, and `None` only when the marker is already big enough,
    which happens when a database is read after a patch it already answered.
    """
    pts = marker["pts"]
    rule = marker.get("rule", "?")
    have = area(pts)
    need = float(_ask(rules, "min_area", layer))
    if have + TOL >= need:
        return None                      # already legal: nothing owed
    space = float(_ask(rules, "min_space", layer))
    grid = float(_ask(rules, "grid"))

    bb = bbox(pts)
    ax = axis or long_axis(pts)
    own = conductors.touching(layer, bb)

    clash = "the marker presents no edge to grow from"
    for hi in (True, False):
        try:
            ext, c0, c1 = edge_span(pts, ax, hi)
        except ValueError as exc:
            clash = str(exc)
            continue
        w = c1 - c0
        if w <= 0.0:
            clash = ("the %s %s edge is a point, so no patch of finite "
                     "length can carry the deficit"
                     % (ax, "high" if hi else "low"))
            continue
        length = snap_up((need - have) / w, grid)
        if ax == "x":
            box = ((ext, c0, ext + length, c1) if hi
                   else (ext - length, c0, ext, c1))
        else:
            box = ((c0, ext, c1, ext + length) if hi
                   else (c0, ext - length, c1, ext))
        box = tuple(round(v, 6) for v in box)

        bad = None
        for b in conductors.near(layer, box, space):
            if any(b is o for o in own):
                continue                 # merges with the shape being fixed
            if touches(b, box):
                bad = ("would overlap other metal at %.4f %.4f %.4f %.4f" % b)
                break
            d = gap(b, box)
            if d + TOL < space:
                bad = ("%.4f um from metal at %.4f %.4f %.4f %.4f, against a "
                       "%.4f rule" % ((d,) + b + (space,)))
                break
        if bad is None:
            return Patch(rule, layer, box, bb, ax, "+" if hi else "-",
                         have, need)
        clash = bad
    return Refusal(rule, layer, bb, clash)


def close_all(records, layer_of, conductors, rules):
    """Close every marker a `layer_of(rule)` claims. -> (patches, refusals).

    `layer_of` is the port's own rule-name-to-layer map -- `A1M2` -> MET2 on
    one node, `M2.A.1` -> M2 on another -- and returning None means "not mine",
    which is how a caller runs the area responder over a mixed database.
    """
    patches, refusals = [], []
    for r in records:
        layer = layer_of(r["rule"])
        if layer is None:
            continue
        got = close_area(r, layer, conductors, rules)
        if got is None:
            continue
        (refusals if isinstance(got, Refusal) else patches).append(got)
    return patches, refusals
