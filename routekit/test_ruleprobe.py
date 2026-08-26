#!/usr/bin/env python3
"""Gates for routekit.ruleprobe -- the loop closed: card -> CardRules ->
probes -> the audit engine, with a poison that proves selfcheck can say
no."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import audit, card, ruleprobe                # noqa: E402
from routekit.test_card import MINI_CARD                   # noqa: E402

R = card.CardRules(MINI_CARD)


def test_selfcheck_clean_on_M2_with_VIA2():
    assert ruleprobe.selfcheck(R, layer="M2", cut="VIA2") == []


def test_selfcheck_clean_on_M1_metal_only():
    assert ruleprobe.selfcheck(R, layer="M1") == []


def test_every_metal_probe_is_constructible_on_M2():
    ps = ruleprobe.probes(R, layer="M2", cut="VIA2")
    built = [p["name"] for p in ps if "skipped" not in p]
    for name in ("spacing", "line_end", "notch", "min_area", "min_edge",
                 "via_enclosure", "wide_landing"):
        assert name in built, (name, ps)


def test_a_skipped_probe_states_its_reason():
    class NoLineEnd(card.CardRules):
        def line_end_space(self, layer):
            return self.min_space(layer)      # rule folds into flat
    ps = ruleprobe.probes(NoLineEnd(MINI_CARD), layer="M2")
    sk = [p for p in ps if p["name"] == "line_end"]
    assert sk and "skipped" in sk[0]


def test_every_probe_coordinate_is_on_the_grid():
    """The tsmc65 arm's G.1 finding: 1.8 * 0.090 = 0.162 is off the
    0.005 grid, and the deck fired G.1 in BOTH cells -- after a licence
    was spent. A width that is an odd grid multiple must still emit
    on-grid geometry, and the builder's own guard must refuse anything
    that is not."""
    import copy
    c = copy.deepcopy(MINI_CARD)
    for fam in c["metal"].values():
        fam["min_width_um"] = 0.045          # 1.8*w = 0.081: off-grid raw
        fam["min_space_um"] = 0.065
    ps = ruleprobe.probes(card.CardRules(c), layer="M2", grid=0.005)
    for p in ps:
        for kind in ("violation", "clean"):
            for r in p.get(kind, ()):
                for v in r[1:5]:
                    assert abs(round(v / 0.005) * 0.005 - v) < 1e-9, \
                        (p["name"], r)


def test_poison_an_off_grid_probe_is_refused_by_the_guard():
    """Negative control for the grid guard itself."""
    out = [dict(name="x", violation=[("M2", 0, 0, 0.162, 1.0, "a")],
                clean=[])]
    try:
        ruleprobe._assert_on_grid(out, 0.005)
    except ValueError as e:
        assert "off-grid" in str(e)
    else:
        raise AssertionError("an off-grid probe was not refused")


def test_a_refused_via_geometry_names_both_via_skips():
    """When the card refuses via_geometry, BOTH via probes must appear
    as named skips -- the first version dropped wide_landing without a
    trace (found by the tsmc65 arm, whose enclosure ACROSS minimum is an
    annotated null)."""
    import copy
    c = copy.deepcopy(MINI_CARD)
    c["via"]["VIAx"]["enclosure"]["across_um"] = None
    ps = ruleprobe.probes(card.CardRules(c), layer="M2", cut="VIA2")
    sk = dict((p["name"], p.get("skipped")) for p in ps
              if p["name"] in ("via_enclosure", "wide_landing"))
    assert set(sk) == {"via_enclosure", "wide_landing"}, ps
    assert all("across_um" in (v or "") for v in sk.values()), sk


def test_poison_a_silenced_gate_is_caught():
    orig = audit.spacing
    audit.spacing = lambda *a, **k: []
    try:
        out = ruleprobe.selfcheck(R, layer="M2")
        assert any("did not fire" in ln for ln in out)
    finally:
        audit.spacing = orig


def test_poison_a_trigger_happy_gate_is_caught():
    orig = audit.min_area
    audit.min_area = lambda *a, **k: ["FAKE finding"]
    try:
        out = ruleprobe.selfcheck(R, layer="M2")
        assert any("clean twin fired" in ln for ln in out)
    finally:
        audit.min_area = orig
