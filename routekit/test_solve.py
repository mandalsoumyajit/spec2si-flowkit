#!/usr/bin/env python3
"""Gates for routekit.solve's bind seam. The real gates are consumer-side
(the tracks digest, the corpus replays); what is judged here is the seam:
unbound use refuses, bind computes the node constants exactly, and the
reductions the tile port documented hold arithmetically."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import solve                                 # noqa: E402


class StubCA(object):
    ROUTING_TIERS = (35, 36, 37, 38)
    BASE_LY = 31
    TIER_RULE = {35: (0.1, 0.1), 36: (0.1, 0.1), 37: (0.1, 0.1),
                 38: (0.4, 0.4)}
    TIER_AXIS = {35: "V", 36: "H", 37: "V", 38: "H"}

    def via_pad(self, t):
        return {35: (0.14, 0.11), 36: (0.14, 0.18), 37: (0.52, 0.52),
                38: (0.52, 1.22)}[t]


class StubBD(object):
    VIA = {"VIA5": (0, 0.1, 0.02, 0.25, 0),
           "VIA7": (0, 0.36, 0.08, 0.9, 40)}


def test_bind_requires_the_tier_list():
    try:
        solve.bind(StubCA(), StubBD())
    except ValueError as e:
        assert "route_tiers" in str(e)
    else:
        raise AssertionError("bind without route_tiers did not refuse")


def test_bind_computes_the_node_constants():
    solve.bind(StubCA(), StubBD(), route_tiers=(35, 36, 37, 38),
               pad_via="VIA5")
    assert solve.BASE == 35
    assert solve.PAD == 0.14 and solve.CUT == 0.1
    assert solve.LAND_TAPER == round(0.8 + 0.05 + 0.19, 4)
    assert solve.VIA_COST == round(6 * 0.14, 4)
    assert solve.ROUTE_TIERS == (35, 36, 37, 38)


def test_per_tier_pads_answer_through_the_adapter():
    solve.bind(StubCA(), StubBD(), route_tiers=(35, 36, 37, 38),
               pad_via="VIA5")
    assert solve.wire_w(38) == 0.52          # max(rule 0.4, via_pad 0.52)
    assert solve.pad_along(36) == 0.18


def test_via_cost_reduces_to_the_flat_scalar_when_pads_are_flat():
    class FlatCA(StubCA):
        def via_pad(self, t):
            return (0.14, 0.14)
    solve.bind(FlatCA(), StubBD(), route_tiers=(35, 36, 37),
               pad_via="VIA5")
    # the 65 nm cost was VIA_COST * |dt| with VIA_COST = 6 * PAD; the
    # generalized via_cost must reduce to it exactly when every pad is flat
    for dt in (1, 2, 3):
        assert abs(solve.via_cost(35, 35 + dt)
                   - solve.VIA_COST * dt) < 1e-12
