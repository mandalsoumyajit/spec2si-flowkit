#!/usr/bin/env python3
"""Gates for routekit.solve's bind seam. The real gates are consumer-side
(the tracks digest, the corpus replays); what is judged here is the seam:
unbound use refuses, bind computes the node constants exactly, and the
reductions the tile port documented hold arithmetically."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
import pytest                                              # noqa: E402

from routekit import solve                                 # noqa: E402

#: ⚠️⚠️ bind() SETS LIVE MODULE STATE, AND A TEST THAT LEAVES A STUB BOUND
#: POISONS EVERY LATER CONSUMER IN THE SAME PROCESS. Measured: with this
#: file collected before a consumer's tracks test, the stub's pitches
#: replaced the process's and four tracks assertions failed -- and the
#: reverse order passed, which is the worst kind of green. Every test here
#: restores the pre-test bind, so suite order cannot matter.
_BOUND = ("ca", "bd", "BASE", "_TILE_VIA", "PAD", "CUT", "PAD_ALONG",
          "LAND_TAPER", "VIA_COST", "ROUTE_TIERS", "HERE")


@pytest.fixture(autouse=True)
def _restore_bind():
    saved = dict((k, getattr(solve, k)) for k in _BOUND)
    yield
    for k, v in saved.items():
        setattr(solve, k, v)


class StubCA(object):
    ROUTING_TIERS = (35, 36, 37, 38)
    BASE_LY = 31
    TIER_RULE = {35: (0.1, 0.1), 36: (0.1, 0.1), 37: (0.1, 0.1),
                 38: (0.4, 0.4)}
    TIER_AXIS = {35: "V", 36: "H", 37: "V", 38: "H"}

    def via_pad(self, t):
        return {35: (0.14, 0.11), 36: (0.14, 0.18), 37: (0.52, 0.52),
                38: (0.52, 1.22)}[t]

    #: the rest of the ten-symbol seam a `Tracks` needs -- empty answers, so
    #: the grid it builds is a bare one and every query is about nothing
    WIDE_RULE = (1.0, 1.0, 0.4)

    def declared_boxes(self, *a, **k):
        return set()

    def rects(self, snap, t):
        return ()

    def num(self, n):
        return {"M5": 35, "M6": 36, "M7": 37, "M8": 38}[n]

    def _name(self, t):
        return "M%d" % (t - 30)

    def space_between(self, t, wa, wb=0.0, run_um=None):
        return self.TIER_RULE[t][1]

    def min_space(self, t):
        return self.TIER_RULE[t][1]

    def min_width(self, t):
        return self.TIER_RULE[t][0]


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


def test_every_occupancy_QUERY_is_callable_on_a_real_grid():
    """`free`, `blockers` and `bounds` answer, on a Tracks built here.

    ⚠️⚠️ **THIS EXISTS BECAUSE A BROKEN `free` PASSED EVERY GATE.** A patch
    meant for `blockers` landed in `free` instead -- the two share the line
    `w = self._ask_w(t, net, co)` and a first-occurrence replace took the
    wrong one -- leaving `w = ... if w is None else w` in a function with no
    `w` parameter. That is an `UnboundLocalError` on EVERY call, and it
    survived the 98 tests here AND the signed 136-net corpus replay, because
    neither of them ever calls `free`.

    ▶ So the gate is not "is the router right", which the corpus answers.
    It is "does each query still RUN" -- the cheapest possible check, and
    the one whose absence let an exception-on-every-call ship.
    """
    saved_tiers = solve.ROUTE_TIERS
    solve.bind(StubCA(), StubBD(), route_tiers=(35, 36, 37, 38))
    g = solve.Tracks({"tile": (10.0, 10.0), "rects": {}},
                     span=(0.0, 0.0, 10.0, 10.0), pg={})
    assert solve.ROUTE_TIERS == (35, 36, 37, 38) or saved_tiers is not None
    for t in (35, 36, 37, 38):
        k = g.index(t, 5.0)
        assert isinstance(g.free(t, k, 1.0, 2.0, "n"), bool)
        hard, nets = g.blockers(t, k, 1.0, 2.0, "n")
        assert isinstance(hard, bool)
        # the pad-width form: a caller stating the metal it is asking about
        hard2, _ = g.blockers(t, k, 1.0, 2.0, "n", w=solve.ca.via_pad(t)[0])
        assert isinstance(hard2, bool)
        w = g.bounds(t, (k,), 1.5, "n", False, 0.05)
        assert w is None or (isinstance(w, tuple) and len(w) == 2)
