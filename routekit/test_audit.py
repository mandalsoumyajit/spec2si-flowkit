#!/usr/bin/env python3
"""Gates for routekit.audit -- every check paired with a poison control.

The stub rules object below is the WHOLE process interface the engine may
touch; a new `rules.` access in audit.py fails here first, which is the
point -- the seam is load-bearing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import audit                                 # noqa: E402

GAP = 0.05


class StubRules(object):
    """A minimal, self-consistent fictional process."""

    def min_space(self, layer):
        return 0.05

    def line_end_space(self, layer):
        return 0.07

    def wide_metal_tiers(self, layer):
        return [{"width_gt_um": 1.5, "parallel_run_gt_um": 1.5,
                 "space_um": 0.5}]

    def min_width(self, layer):
        return 0.05

    def min_area(self, layer):
        return 0.014

    def landing_pad(self, layer):
        return 0.12

    def compact_edge(self):
        return 0.13

    def via_geometry(self, cut):
        return (0.05, 0.05, 0.0)

    def via_enclosure_crowded(self):
        return None

    def via_tier(self, cut):
        return "VIAx"

    def via_redundancy_tiers(self, tier):
        return ({"rule": "VIAx.R.2", "width_and_length_gt_um": 0.18,
                 "max_space_um": 0.1},)

    def via_pair_space(self, cut):
        return 0.1

    def via_rect_cut(self, cut=None):
        raise KeyError("no rectangular cut in the stub kit")

    def plate_proximity_rules(self):
        return ({"rule": "VIA1.R.4", "plate_min_width_um": 0.18,
                 "plate_min_length_um": 0.18, "max_distance_um": 0.5},)


R = StubRules()


def _r(layer, x1, y1, x2, y2, net):
    return (layer, x1, y1, x2, y2, net)


# ---- shorts / opens / run ----------------------------------------------

def test_shorts_fires_on_touching_foreign_nets():
    rec = [_r("M2", 0, 0, 1, 0.1, "a"), _r("M2", 1, 0, 2, 0.1, "b")]
    sh, nr = audit.shorts(rec, GAP)
    assert len(sh) == 1 and "SHORT" in sh[0]


def test_shorts_clean_when_separated():
    rec = [_r("M2", 0, 0, 1, 0.1, "a"), _r("M2", 1.2, 0, 2, 0.1, "b")]
    sh, nr = audit.shorts(rec, GAP)
    assert sh == [] and nr == []


def test_near_fires_on_unbridged_same_net_pair():
    rec = [_r("M2", 0, 0, 1, 0.1, "a"), _r("M2", 1.02, 0, 2, 0.1, "a")]
    sh, nr = audit.shorts(rec, GAP)
    assert sh == [] and len(nr) == 1 and "NEAR" in nr[0]


def test_near_silent_when_a_third_shape_bridges():
    rec = [_r("M2", 0, 0, 1, 0.1, "a"), _r("M2", 1.02, 0, 2, 0.1, "a"),
           _r("M2", 0.9, 0.1, 1.1, 0.3, "a"),
           _r("M2", 0.9, 0.05, 1.1, 0.15, "a")]
    # the two bridge shapes touch both halves: one component, no finding
    sh, nr = audit.shorts(rec, GAP)
    assert sh == []
    assert all("NEAR M2 a/a" not in ln or "x0" in ln for ln in nr) or nr == []


def test_via_short_fires_on_foreign_metal_over_cut():
    rec = [_r("VIA1", 0, 0, 0.05, 0.05, "a"),
           _r("M2", -0.1, -0.1, 0.1, 0.1, "b")]
    sh, _nr = audit.shorts(rec, GAP)
    assert any("VIA1>M2" in ln for ln in sh)


def test_opens_fires_on_a_split_net():
    rec = [_r("M1", 0, 0, 1, 0.1, "a"), _r("VIA1", 0.4, 0, 0.5, 0.1, "a"),
           _r("M1", 2, 0, 3, 0.1, "a"), _r("VIA1", 2.4, 0, 2.5, 0.1, "a")]
    out = audit.opens(rec)
    assert len(out) == 1 and out[0].startswith("OPEN a")


def test_opens_ignores_single_conductor_island():
    # a lone terminal reaches its net THROUGH the device: not an open
    rec = [_r("M1", 0, 0, 1, 0.1, "a"), _r("VIA1", 0.4, 0, 0.5, 0.1, "a"),
           _r("M1", 2, 0, 3, 0.1, "a")]
    assert audit.opens(rec) == []


def test_opens_connected_through_via_overlap():
    rec = [_r("M1", 0, 0, 1, 0.1, "a"), _r("VIA1", 0.4, 0.02, 0.5, 0.08, "a"),
           _r("M2", 0.3, -0.5, 0.6, 0.5, "a"),
           _r("M2", 0.3, 0.5, 0.6, 1.5, "a"),
           _r("VIA2", 0.4, 0.6, 0.5, 0.7, "a"),
           _r("M3", 0.3, 0.55, 0.6, 0.75, "a")]
    assert audit.opens(rec) == []


def test_run_reports_an_untagged_block():
    rec = [_r("M1", 0, 0, 1, 0.1, None), _r("M2", 0, 0.3, 1, 0.4, None)]
    n, lines = audit.run(rec, GAP, verbose=False)
    assert n == 1 and lines and lines[0].startswith("UNTAGGED")


def test_run_clean_on_a_tagged_clean_layout():
    rec = [_r("M1", 0, 0, 1, 0.1, "a"), _r("M1", 0, 0.3, 1, 0.4, "b")]
    n, lines = audit.run(rec, GAP, verbose=False)
    assert n == 0


# ---- spacing ------------------------------------------------------------

def test_spacing_fires_under_the_rule():
    rec = [_r("M2", 0, 0, 1, 0.2, "a"), _r("M2", 0, 0.24, 1, 0.5, "b")]
    out = audit.spacing(R, rec, layers=("M2",))
    assert len(out) == 1 and "SPACE M2" in out[0]


def test_spacing_clean_at_the_rule():
    rec = [_r("M2", 0, 0, 1, 0.2, "a"), _r("M2", 0, 0.26, 1, 0.5, "b")]
    assert audit.spacing(R, rec, layers=("M2",)) == []


def test_spacing_diagonal_pair_is_not_exempt():
    # 0.03 apart in BOTH axes is 0.042 apart -- and it drew a real M2.S.1
    rec = [_r("M2", 0, 0, 1, 1, "a"), _r("M2", 1.03, 1.03, 2, 2, "b")]
    out = audit.spacing(R, rec, layers=("M2",))
    assert len(out) == 1


def test_spacing_line_end_takes_the_larger_value():
    # 0.06 clears the 0.05 flat rule; a 0.05-tall line end wants 0.07
    rec = [_r("M2", 0, 0, 1, 0.05, "a"), _r("M2", 1.06, 0, 2, 0.05, "b")]
    out = audit.spacing(R, rec, layers=("M2",))
    assert len(out) == 1 and "line-end" in out[0]


def test_spacing_two_line_ends_take_the_pair_value():
    """tsmc28's M2.S.12 class: BOTH facing edges are line-ends -> a
    third, stricter number. 0.075 clears the flat 0.05 AND the 0.07
    either-edge value; with a 0.08 pair value recorded it must fire --
    and stay quiet at 0.08, and stay an either-edge case when only ONE
    facing edge is a line-end."""
    import copy as _copy
    from routekit.test_card import MINI_CARD
    from routekit import card as _card
    c = _copy.deepcopy(MINI_CARD)
    c["metal"]["Mxf"]["line_end_pair_space_um"] = {"value": 0.08,
                                                  "rule": "Mx.S.12"}
    Rp = _card.CardRules(c)
    end_end = [_r("M2", 0, 0, 1, 0.05, "a"),
               _r("M2", 1.075, 0, 2, 0.05, "b")]
    assert len(audit.spacing(Rp, end_end, layers=("M2",))) == 1
    clean = [_r("M2", 0, 0, 1, 0.05, "a"),
             _r("M2", 1.08, 0, 2, 0.05, "b")]
    assert audit.spacing(Rp, clean, layers=("M2",)) == []
    end_side = [_r("M2", 0, 0, 1, 0.05, "a"),
                _r("M2", 1.075, -1, 1.2, 1, "b")]
    assert audit.spacing(Rp, end_side, layers=("M2",)) == []
    # and WITHOUT the pair value the same end-end gap is legal -- the
    # negative control that proves the new number is doing the work
    assert audit.spacing(R, end_end, layers=("M2",)) == []


def test_spacing_ref_vs_ref_is_not_ours():
    ref = [_r("M2", 0, 0, 1, 0.2, "a"), _r("M2", 0, 0.22, 1, 0.5, "b")]
    assert audit.spacing(R, [], ref=ref, layers=("M2",)) == []


def test_spacing_same_polygon_notch_is_reported():
    # two arms of one net joined further east: the 0.04 slot between them
    # is a violation even though they are one component
    rec = [_r("M2", 0, 0.0, 1.0, 0.2, "a"),
           _r("M2", 0, 0.24, 1.0, 0.44, "a"),
           _r("M2", 0.9, 0.0, 1.0, 0.44, "a")]
    out = audit.spacing(R, rec, layers=("M2",))
    assert len(out) == 1 and "notch" in out[0]


# ---- min_area / min_edge ------------------------------------------------

def test_min_area_fires_on_a_small_island():
    rec = [_r("M2", 0, 0, 0.11, 0.05, "a"),
           _r("M2", 5, 5, 6, 6, "b")]
    out = audit.min_area(R, rec, layers=("M2",))
    assert any("A.2" in ln for ln in out)


def test_min_area_compact_island_fails_at_any_area():
    # 0.12 x 0.12 = 0.0144 um2 clears A.2's 0.014 and still fails A.3
    rec = [_r("M2", 0, 0, 0.12, 0.12, "a")]
    out = audit.min_area(R, rec, layers=("M2",))
    assert len(out) == 1 and "A.3" in out[0]


def test_min_area_island_merged_with_ref_is_clean():
    rec = [_r("M2", 0, 0, 0.11, 0.05, "a")]
    ref = [_r("M2", 0.05, -0.5, 0.5, 0.5, "a")]
    assert audit.min_area(R, rec, ref=ref, layers=("M2",)) == []


def test_min_edge_fires_where_both_edges_are_short():
    # a 0.11 foot proud of a 0.09 stub by 0.01, with the stub ending
    # 0.03 past the foot: the 0.01 step edge meets the 0.03 remnant of
    # the stub end at one vertex -- both under min width
    rec = [_r("M2", 0, 0, 0.09, 0.60, "a"),
           _r("M2", -0.01, 0.46, 0.10, 0.57, "a")]
    out = audit.min_edge(R, rec, layers=("M2",))
    assert out and all("G.4" in ln for ln in out)


def test_min_edge_clean_on_a_plain_wire():
    rec = [_r("M2", 0, 0, 0.09, 5.0, "a")]
    assert audit.min_edge(R, rec, layers=("M2",)) == []


# ---- via gates ----------------------------------------------------------

def test_via_enclosure_fires_on_an_uncovered_cut():
    rec = [_r("VIA1", 0, 0, 0.05, 0.05, "a"),
           _r("M1", 0, 0, 0.05, 0.05, "a"),          # flush: no e_along
           _r("M2", -0.2, -0.2, 0.3, 0.3, "a")]
    out = audit.via_enclosure(R, rec)
    assert len(out) == 1 and "ENC VIA1:M1" in out[0]


def test_via_enclosure_either_orientation_passes():
    # enclosure along y only -- the disjunction accepts it
    rec = [_r("VIA1", 0, 0, 0.05, 0.05, "a"),
           _r("M1", 0, -0.05, 0.05, 0.10, "a"),
           _r("M2", 0, -0.05, 0.05, 0.10, "a")]
    assert audit.via_enclosure(R, rec) == []


def test_via_enclosure_skips_an_undeclared_landing():
    rec = [_r("VIA1", 0, 0, 0.05, 0.05, "a"),
           _r("M2", -0.2, -0.2, 0.3, 0.3, "a")]
    assert audit.via_enclosure(R, rec) == []     # no M1 at all: not ours


def test_wide_landing_fires_on_a_lone_cut():
    rec = [_r("VIA1", 0.5, 0.5, 0.55, 0.55, "a"),
           _r("M1", 0, 0, 1, 1, "a")]
    out = audit.via_wide_landing(R, rec)
    assert len(out) == 1 and "WIDE VIAx.R.2" in out[0]


def test_wide_landing_pair_within_space_is_clean():
    rec = [_r("VIA1", 0.5, 0.5, 0.55, 0.55, "a"),
           _r("VIA1", 0.5, 0.62, 0.55, 0.67, "a"),
           _r("M1", 0, 0, 1, 1, "a")]
    assert audit.via_wide_landing(R, rec) == []


def test_via_plates_fires_on_a_branch_cut_near_a_plate():
    rec = [_r("M2", 0, 0, 1, 1, "p"),                    # the plate
           _r("M2", 1, 0.45, 1.4, 0.55, "p"),            # the branch
           _r("VIA1", 1.3, 0.47, 1.35, 0.52, "p")]       # lone square cut
    out = audit.via_plates(R, rec)
    assert len(out) == 1 and "PLATE VIA1.R.4" in out[0]


def test_via_plates_cut_on_the_plate_is_not_this_rule():
    rec = [_r("M2", 0, 0, 1, 1, "p"),
           _r("VIA1", 0.5, 0.5, 0.55, 0.55, "p")]
    assert audit.via_plates(R, rec) == []


def test_via_enclosure_per_layer_override_governs_that_metal_only():
    class OverrideRules(StubRules):
        def via_enclosure_for(self, cut, metal):
            return (0.3, 0.3) if metal == "M2" else None
    # covered to the TIER's enclosure on both metals: clean without the
    # override, and the M2 side alone fails once M2 wants 0.3
    rec = [_r("VIA1", 0, 0, 0.05, 0.05, "a"),
           _r("M1", 0, -0.05, 0.05, 0.10, "a"),
           _r("M2", 0, -0.05, 0.05, 0.10, "a")]
    assert audit.via_enclosure(R, rec) == []
    out = audit.via_enclosure(OverrideRules(), rec)
    assert len(out) == 1 and "VIA1:M2" in out[0]


# ---- via_wide_landing: the SITE has two conductors (viapair_probe) ------

def _r3_rules():
    """A two-tier card: R.2 above 0.18, R.3 above 0.44 wanting FOUR
    squares -- the shape the 28 nm deck measured over 31 islands."""
    import copy as _copy
    from routekit.test_card import MINI_CARD
    from routekit import card as _card
    c = _copy.deepcopy(MINI_CARD)
    c["via"]["VIAx"]["redundancy_tiers"] = [
        {"rule": "VIAx.R.2", "width_and_length_gt_um": 0.18,
         "options": [{"count": 2, "shape": "square",
                      "max_space_um": 0.1}]},
        {"rule": "VIAx.R.3", "width_and_length_gt_um": 0.44,
         "options": [{"count": 4, "shape": "square",
                      "max_space_um": 0.1}]},
    ]
    return _card.CardRules(c)


def _stub_bus(cuts):
    """A 0.05 um M1 stub landing on a 1.0 um M2 bus -- the R.3 site
    that hid on the tile's own geometry: the stub's width, the only
    number its caller declared, is 0.05."""
    return ([_r("M1", 0, 0, 0.05, 2.0, "a"),
             _r("M2", -0.5, 0, 0.5, 2.0, "a")] + cuts)


def test_wide_landing_tier_is_the_sites_not_one_conductors():
    """The pair this gate used to PASS on an R.3 site: the tier comes
    from the WIDEST conductor over the cut, and two squares are not in
    R.3's table at any spacing."""
    R = _r3_rules()
    pair = [_r("VIA1", 0, 0.2, 0.05, 0.25, "a"),
            _r("VIA1", 0, 0.345, 0.05, 0.395, "a")]
    out = audit.via_wide_landing(R, _stub_bus(pair))
    assert len(out) == 2 and "VIAx.R.3" in out[0]
    quad = [_r("VIA1", x, y, x + 0.05, y + 0.05, "a")
            for x in (0.0, 0.145) for y in (0.2, 0.345)]
    # the stub is 0.05 wide; the 2x2 needs a wider one -- widen it and
    # the site tier STAYS R.3 (the bus's), which is the point
    rec = [_r("M1", 0, 0, 0.195, 2.0, "a"),
           _r("M2", -0.5, 0, 0.5, 2.0, "a")] + quad
    assert audit.via_wide_landing(R, rec) == []


def test_wide_landing_a_row_counts_like_a_square():
    """It is the COUNT, not the shape: four cuts in a ROW at the
    ceiling are one merged chain (`SIZE BY space/2` merges on
    abutment), and the deck accepts the row (stub_bus_4sq100)."""
    R = _r3_rules()
    row = [_r("VIA1", 0, 0.2 + i * 0.15, 0.05, 0.25 + i * 0.15, "a")
           for i in range(4)]
    assert audit.via_wide_landing(R, _stub_bus(row)) == []


def test_wide_landing_r2_site_pair_at_the_ceiling_is_legal():
    """Measured: the flow's own pair is legal at 0.080, 0.095 AND at
    0.100 -- the ceiling merges on abutment -- and a lone square
    fires."""
    R = _r3_rules()
    site = [_r("M1", 0, 0, 0.36, 0.36, "a"),
            _r("M2", 0.05, -0.5, 0.15, 0.5, "a")]
    pair = [_r("VIA1", 0.05, 0.05, 0.1, 0.1, "a"),
            _r("VIA1", 0.05, 0.2, 0.1, 0.25, "a")]     # gap exactly 0.10
    assert audit.via_wide_landing(R, site + pair) == []
    lone = [_r("VIA1", 0.05, 0.05, 0.1, 0.1, "a")]
    out = audit.via_wide_landing(R, site + lone)
    assert len(out) == 1 and "VIAx.R.2" in out[0]
