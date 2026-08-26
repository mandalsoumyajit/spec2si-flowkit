#!/usr/bin/env python3
"""Gates for routekit.card -- the contract, exercised on a mini-card.

MINI_CARD below is the schema's worked example: two metal families with
membership lists, one via tier, the annotated and the bare value shapes,
and both flavours of "no" -- a MISSING fact (refusal) and a MEASURED
ABSENT one (an answered empty).
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import card                                  # noqa: E402

MINI_CARD = {
    "metal": {
        "M1f": {"layers": ["M1"],
                "min_width_um": {"value": 0.05, "rule": "M1.W.1"},
                "min_space_um": 0.05,
                "line_end_space_um": 0.06,
                "wide_metal_space_tiers": [],
                "min_area_um2": 0.0115,
                "landing_pad_um": 0.11},
        "Mxf": {"layers": ["M2", "M3"],
                "min_width_um": 0.05,
                "min_space_um": 0.05,
                "line_end_space_um": 0.07,
                "wide_metal_space_tiers": [
                    {"width_gt_um": 1.5, "parallel_run_gt_um": 1.5,
                     "space_um": 0.5}],
                "landing_pad_um": 0.12},
    },
    "min_area_um2": {"compact_edge_um": 0.13, "Mxf": 0.014},
    "via": {
        "VIAx": {"cut_layers": ["VIA1", "VIA2"],
                 "cut_um": 0.05,
                 "enclosure": {"along_um": 0.05, "across_um": 0.0},
                 "min_space_pair_um": 0.1,
                 "redundancy_tiers": [
                     {"rule": "VIAx.R.2", "width_and_length_gt_um": 0.18,
                      "max_space_um": 0.1}],
                 "plate_proximity_rules": []},
    },
}

R = card.CardRules(MINI_CARD)


def test_both_value_shapes_resolve():
    assert R.min_width("M1") == 0.05          # annotated
    assert R.min_width("M2") == 0.05          # bare


def test_family_is_resolved_by_the_layers_list():
    assert R.min_space("M3") == 0.05
    assert R.line_end_space("M3") == 0.07
    assert R.wide_metal_tiers("M2")[0]["space_um"] == 0.5


def test_a_layer_in_no_list_is_a_refusal_naming_the_failure_shape():
    try:
        R.min_width("M7")
    except card.CardError as e:
        assert "membership lists are the ONE authority" in str(e)
    else:
        raise AssertionError("an unlisted layer did not refuse")


def test_min_area_family_fallback_and_entry_override():
    assert R.min_area("M1") == 0.0115         # in the family entry
    assert R.min_area("M2") == 0.014          # via the min_area section


def test_compact_edge_and_landing_pad():
    assert R.compact_edge() == 0.13
    assert R.landing_pad("M3") == 0.12


def test_via_tier_and_geometry_by_cut_layers_list():
    assert R.via_tier("VIA2") == "VIAx"
    assert R.via_geometry("VIA1") == (0.05, 0.05, 0.0)
    assert R.via_pair_space("VIA2") == 0.1


def test_measured_absent_is_an_answer():
    assert R.plate_proximity_rules() == ()
    assert R.via_redundancy_tiers("VIAx")[0]["rule"] == "VIAx.R.2"


def test_missing_is_a_refusal():
    c = copy.deepcopy(MINI_CARD)
    del c["metal"]["Mxf"]["min_space_um"]
    try:
        card.CardRules(c).min_space("M2")
    except card.CardError as e:
        assert "min_space_um" in str(e) and "Mxf" in str(e)
    else:
        raise AssertionError("a missing fact did not refuse")


def test_no_rect_cut_recorded_is_a_refusal_saying_measured_absent():
    try:
        R.via_rect_cut("VIA1")
    except card.CardError:
        pass
    else:
        raise AssertionError("an unrecorded rect cut did not refuse")


def test_load_split_survives_a_missing_values_file(tmp_path):
    p = tmp_path / "structure.json"
    p.write_text('{"metal": {"M1f": {"layers": ["M1"]}}}',
                 encoding="utf-8")
    c = card.load_split(str(p), str(tmp_path / "absent_values.json"))
    assert c["metal"]["M1f"]["layers"] == ["M1"]
    try:
        card.CardRules(c).min_width("M1")
    except card.CardError:
        pass                        # per-fact refusal, not a load crash
    else:
        raise AssertionError("missing values did not refuse per-fact")


def test_load_split_values_win_key_by_key(tmp_path):
    s = tmp_path / "s.json"
    v = tmp_path / "v.json"
    s.write_text('{"metal": {"M1f": {"layers": ["M1"], '
                 '"min_width_um": null}}}', encoding="utf-8")
    v.write_text('{"metal": {"M1f": {"min_width_um": 0.06}}}',
                 encoding="utf-8")
    c = card.load_split(str(s), str(v))
    assert card.CardRules(c).min_width("M1") == 0.06
    assert c["metal"]["M1f"]["layers"] == ["M1"]      # structure kept


def test_validate_clean_on_the_mini_card():
    assert card.validate(MINI_CARD) == []


def test_validate_poison_duplicate_layer_claim():
    c = copy.deepcopy(MINI_CARD)
    c["metal"]["M1f"]["layers"] = ["M1", "M2"]
    out = card.validate(c)
    assert any("claimed by families" in ln for ln in out)


def test_validate_poison_family_without_layers():
    c = copy.deepcopy(MINI_CARD)
    del c["metal"]["Mxf"]["layers"]
    out = card.validate(c)
    assert any("P_METAL_FAMILY" in ln for ln in out)


def test_validate_poison_unrecorded_redundancy():
    c = copy.deepcopy(MINI_CARD)
    del c["via"]["VIAx"]["redundancy_tiers"]
    out = card.validate(c)
    assert any("redundancy_tiers not recorded" in ln for ln in out)


PER_LAYER_CARD = {
    "schema": 1,
    "routing_layers": {"met1": {"min_width_um": {"value": 0.14}},
                       "met2": {"min_width_um": {"value": 0.14}}},
    "vias": {"mcon": {"cut_um": {"value": 0.17}}},
    "global_absences": {"redundancy_tiers": {"value": [],
                                             "note": "measured absent"}},
}


def test_validate_accepts_the_per_layer_profile():
    assert card.validate(PER_LAYER_CARD) == []


def test_validate_per_layer_poison_no_redundancy_answer():
    c = copy.deepcopy(PER_LAYER_CARD)
    del c["global_absences"]
    out = card.validate(c)
    assert any("no redundancy answer" in ln for ln in out)


def test_validate_per_layer_poison_empty_sections():
    out = card.validate({"routing_layers": {}, "vias": {}})
    assert len(out) == 2


def test_validate_names_a_wrong_kind_instead_of_judging_it():
    out = card.validate({"em": {"met1": {}}, "provenance": {}})
    assert len(out) == 1 and out[0].startswith("NOT-A-ROUTING-CARD")
