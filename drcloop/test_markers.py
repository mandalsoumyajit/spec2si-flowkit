#!/usr/bin/env python3
"""Gates for drcloop.markers -- each with a control that must FIRE.

The stepped-polygon fixture is the real one: the deck's marker for a via pad
measured 0.290 x 0.195 across its bounding box and 0.0561 um2 in fact. A test
built on a plain rectangle cannot tell the shoelace from the bbox, which is
exactly the mistake it exists to catch.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from drcloop import markers                                 # noqa: E402


class Rules(object):
    """The seam, filled in with one node's measured numbers."""

    def __init__(self, area=0.0800, space=0.1400, grid=0.005):
        self._a, self._s, self._g = area, space, grid

    def min_area(self, layer):
        return self._a

    def min_space(self, layer):
        return self._s

    def grid(self):
        return self._g


#: 0.290 x 0.190 bar with a 0.190 x 0.005 step on its high-y side.
#: bbox 0.290 x 0.195 = 0.056550 um2;  shoelace = 0.056050 um2.
STEPPED = [(0.000, 0.000), (0.290, 0.000), (0.290, 0.190),
           (0.190, 0.190), (0.190, 0.195), (0.000, 0.195)]


def _marker(pts=None, rule="A1M2"):
    return {"rule": rule, "kind": "p", "pts": pts or STEPPED}


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def test_area_is_the_shoelace_not_the_bbox():
    a = markers.area(STEPPED)
    b = markers.bbox(STEPPED)
    boxarea = (b[2] - b[0]) * (b[3] - b[1])
    assert abs(a - 0.056050) < 1e-9, a
    assert abs(boxarea - 0.056550) < 1e-9
    # the whole point: they differ, and the bbox is the OPTIMISTIC one
    assert boxarea > a


def test_long_axis_is_the_direction_the_bar_runs():
    assert markers.long_axis(STEPPED) == "x"
    tall = [(0, 0), (0.19, 0), (0.19, 0.5), (0, 0.5)]
    assert markers.long_axis(tall) == "y"


def test_edge_span_is_the_metal_at_the_edge_not_the_bbox():
    """Poison: the low-x edge spans the FULL 0.195 (the step is there);
    the high-x edge spans only 0.190. A patcher using the bbox on the high
    side draws 0.005 um of metal beside nothing -- a notch."""
    ext, lo, hi = markers.edge_span(STEPPED, "x", hi=True)
    assert (ext, lo, hi) == (0.290, 0.000, 0.190)
    ext, lo, hi = markers.edge_span(STEPPED, "x", hi=False)
    assert (ext, lo, hi) == (0.000, 0.000, 0.195)


def test_snap_up_never_rounds_down():
    assert markers.snap_up(0.0101, 0.005) == 0.015
    assert markers.snap_up(0.0100, 0.005) == 0.010     # already on grid
    assert markers.snap_up(0.0001, 0.005) == 0.005


def test_gap_and_touch():
    a = (0.0, 0.0, 1.0, 1.0)
    assert markers.gap(a, (1.0, 0.0, 2.0, 1.0)) == 0.0
    assert markers.touches(a, (1.0, 0.0, 2.0, 1.0))
    assert abs(markers.gap(a, (1.5, 0.0, 2.0, 1.0)) - 0.5) < 1e-9
    assert not markers.touches(a, (1.5, 0.0, 2.0, 1.0))


# ---------------------------------------------------------------------------
# the patch
# ---------------------------------------------------------------------------

def test_patch_closes_the_deficit_and_abuts_the_shape():
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED)]})
    p = markers.close_area(_marker(), "MET2", cond, Rules())
    assert isinstance(p, markers.Patch), p
    # deficit 0.0800 - 0.05605 = 0.02395 over a 0.190 wide edge -> 0.1261 ->
    # snapped up to 0.130
    assert p.axis == "x" and p.way == "+"
    assert p.box == (0.290, 0.000, 0.420, 0.190), p.box
    assert markers.touches(p.box, markers.bbox(STEPPED))
    # and it really is enough metal
    added = (p.box[2] - p.box[0]) * (p.box[3] - p.box[1])
    assert p.was + added >= p.need


def test_a_legal_marker_is_not_patched():
    """Reading a database after the patch it already answered must be a
    no-op, not a second patch stacked on the first."""
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED)]})
    assert markers.close_area(_marker(), "MET2", cond,
                              Rules(area=0.010)) is None


def test_the_blocked_direction_is_abandoned_for_the_other_one():
    """One real marker of 116 needed the direction the other 115 did not."""
    blocker = (0.300, -1.0, 1.0, 1.0)          # 0.010 clear of the high edge
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED), blocker]})
    p = markers.close_area(_marker(), "MET2", cond, Rules())
    assert isinstance(p, markers.Patch), p
    assert p.way == "-", "it grew into the blocker instead of away from it"
    assert p.box[2] == 0.000 and p.box[0] < 0.0


def test_a_marker_boxed_in_on_both_sides_is_REFUSED_BY_NAME():
    """Poison twin of the two tests above: a silent skip and a fix look
    identical in the next DRC run, so the refusal must carry the number."""
    cond = markers.Conductors({"MET2": [
        markers.bbox(STEPPED),
        (0.300, -1.0, 1.0, 1.0),               # 0.010 east
        (-1.0, -1.0, -0.135, 1.0),             # 0.010 west of the patch
    ]})
    r = markers.close_area(_marker(), "MET2", cond, Rules())
    assert isinstance(r, markers.Refusal), r
    assert r.rule == "A1M2" and r.layer == "MET2"
    assert "against a 0.1400 rule" in r.why, r.why


def test_the_clearance_test_is_net_blind():
    """Being one net excuses a SHORT and excuses nothing else.

    There are no net names anywhere in `close_area`, and this is the check
    that keeps it that way: the blocker below is the SAME net as the marker
    in every sense a caller could mean, and it still blocks.
    """
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED),
                                        (0.300, -1.0, 1.0, 1.0)]})
    r = markers.close_area(_marker(), "MET2", cond, Rules())
    assert r.way == "-"          # it did not merge its way through


def test_metal_that_merges_with_the_marker_is_not_a_clash():
    """The shape being fixed is touching the patch by construction. Counting
    it as a clash would refuse every marker there is."""
    own = (-0.5, 0.0, 0.290, 0.190)            # a conductor the marker sits on
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED), own]})
    p = markers.close_area(_marker(), "MET2", cond, Rules())
    assert isinstance(p, markers.Patch), p


def test_an_unanswerable_rules_object_raises_rather_than_defaults():
    class Half(object):
        def min_area(self, layer):
            return 0.08
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED)]})
    raised = False
    try:
        markers.close_area(_marker(), "MET2", cond, Half())
    except markers.RulesError as exc:
        raised = True
        assert "min_space" in str(exc)
    assert raised, "a missing process fact was defaulted instead of refused"


def test_a_layer_with_no_conductors_supplied_raises():
    """'nothing is near' and 'nobody looked' are the same answer."""
    cond = markers.Conductors({"MET2": []})
    raised = False
    try:
        markers.close_area(_marker(), "MET3", cond, Rules())
    except markers.RulesError as exc:
        raised = True
        assert "MET3" in str(exc)
    assert raised


def test_close_all_skips_what_layer_of_disowns():
    cond = markers.Conductors({"MET2": [markers.bbox(STEPPED)]})
    recs = [_marker(rule="A1M2"), _marker(rule="S1M1"), _marker(rule="A1M2")]
    layer_of = lambda r: "MET2" if r.startswith("A1M") else None    # noqa: E731
    patches, refusals = markers.close_all(recs, layer_of, cond, Rules())
    assert len(patches) == 2 and not refusals


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("markers: %d check(s) passed" % n)
