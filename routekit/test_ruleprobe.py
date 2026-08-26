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
