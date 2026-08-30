#!/usr/bin/env python3
"""Gates for drcloop.triage -- each with a control that must FIRE."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from drcloop import triage                                  # noqa: E402


def _rec(rule, cx, cy, w=0.1):
    return {"rule": rule, "kind": "p",
            "pts": [(cx - w, cy - w), (cx + w, cy - w),
                    (cx + w, cy + w), (cx - w, cy + w)]}


def _table():
    return (triage.RuleTable()
            .add("area", r"^A1M", "extend the bar along its long axis", True)
            .add("metal-space", r"^S1M", "different-net: fix the plan; "
                 "same-net: bridge the gap", False))


# ---------------------------------------------------------------------------
# the rule table
# ---------------------------------------------------------------------------

def test_classify_and_meta():
    t = _table()
    assert t.classify("A1M2") == "area"
    assert t.classify("S1M1") == "metal-space"
    assert t.automatable("A1M2") and not t.automatable("S1M1")
    assert t.meta("A1M2")["group"] == "A"


def test_an_unknown_rule_is_UNCLASSIFIED_not_bucketed():
    """Poison twin: a table that folds the unknown into 'other' stops
    reporting the day the deck gains a rule."""
    t = _table()
    assert t.classify("W1V1") is None
    m = t.meta("W1V1")
    assert m["cls"] is None and "UNCLASSIFIED" in m["response"]
    assert not m["auto"]
    recs = [_rec("A1M2", 1, 1), _rec("W1V1", 2, 2), _rec("W1V1", 3, 3)]
    assert t.unclassified(recs) == {"W1V1": 2}


# ---------------------------------------------------------------------------
# geometric attribution
# ---------------------------------------------------------------------------

def _zones():
    #  the ring's box CONTAINS the block it wraps -- the real nesting
    return triage.Zones([("ring", (0.0, 0.0, 100.0, 100.0)),
                         ("block", (10.0, 10.0, 90.0, 90.0)),
                         ("big_analog", (-50.0, -50.0, 500.0, 500.0))])


def test_smallest_zone_wins_the_nested_case():
    z = _zones()
    assert z.owner(_rec("A1M2", 50, 50)["pts"]) == "block"
    assert z.owner(_rec("A1M2", 5, 5)["pts"]) == "ring"
    assert z.owner(_rec("A1M2", 200, 200)["pts"]) == "big_analog"


def test_a_marker_in_no_zone_is_the_ASSEMBLY_not_silently_binned():
    """Poison: an unattributed marker is a finding about the floorplan, and
    a triage that drops it reports a die as fully accounted for."""
    z = _zones()
    assert z.owner(_rec("A1M2", 9999, 9999)["pts"]) == triage.UNATTRIBUTED


def test_attribute_counts_per_zone():
    z = _zones()
    recs = [_rec("A1M2", 50, 50), _rec("A1M2", 50, 51), _rec("S1M1", 5, 5)]
    got = triage.attribute(recs, z)
    assert got["block"] == {"A1M2": 2}
    assert got["ring"] == {"S1M1": 1}


# ---------------------------------------------------------------------------
# the diff
# ---------------------------------------------------------------------------

def test_added_is_what_the_change_is_judged_by():
    d = triage.diff({"R1M1": 11}, {"R1M1": 11, "W1M2": 806, "A1M2": 96})
    assert d.added == {"W1M2": 806, "A1M2": 96}
    assert not d.removed
    assert d.net == 902
    assert not d.clean


def test_clean_is_ADDED_NOTHING_not_returned_zero():
    """A density-only baseline is clean AT its baseline. A flow that waits
    for zero waits forever; one that quotes a total hides what it added."""
    d = triage.diff({"R1M1": 11}, {"R1M1": 11})
    assert d.clean and d.net == 0
    assert sum(d.run.values()) == 11        # not zero, and still clean
    # poison twin: one more result and it must stop being clean
    assert not triage.diff({"R1M1": 11}, {"R1M1": 12}).clean


def test_removals_are_reported_separately_from_additions():
    """A step that removes two of its own and adds three is not progress."""
    d = triage.diff({"A1M2": 96, "S1M1": 10}, {"A1M2": 0, "S1M1": 13})
    assert d.removed == {"A1M2": 96}
    assert d.added == {"S1M1": 3}
    assert d.net == -93          # and the NET number would have said 'better'
    assert not d.clean


def test_report_names_every_rule_on_either_side():
    d = triage.diff({"A1M2": 1}, {"S1M1": 2})
    txt = d.report()
    assert "A1M2" in txt and "S1M1" in txt and "TOTAL" in txt


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("triage: %d check(s) passed" % n)
