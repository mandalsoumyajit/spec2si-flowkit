#!/usr/bin/env python3
"""Gates for drcloop.resultsdb -- each with a control that must FIRE.

The fixture below is the ASCII layout both vendors write, hand-built so the
parser is tested against a stated format rather than against whichever real
database happened to be on disk. It carries every feature that has bitten:
braced deck text that looks like a header, an `e` record in the PACKED
four-number form, and a rule whose name holds a dot.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from drcloop import resultsdb                               # noqa: E402

# unit 1000 -> database units are nm.  Deck text is 2 lines under A1M2 and
# 1 under floating.TUB, and one of those lines is a bare word that would
# otherwise parse as a rule header.
DB = """\
ancBrain_gap 1000
A1M2
2 0 2
Rule File Pathname: /nowhere/xt011_DRC.rul
S1M1
p 1 4
100 200
390 200
390 390
100 390
p 2 4
1000 1000
1290 1000
1290 1195
1000 1195
floating.TUB
1 0 1
{ text }
e 3 2
5000 6000 5300 6000
"""


def _fixture(text=DB):
    fd, path = tempfile.mkstemp(suffix=".db")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def test_header_gives_cell_and_unit():
    p = _fixture()
    try:
        cell, unit, recs = resultsdb.parse_records(p)
        assert cell == "ancBrain_gap"
        assert unit == 1000.0
        assert len(recs) == 3
    finally:
        os.remove(p)


def test_deck_text_is_skipped_not_read_as_a_rule():
    """The braced line and the bare word `S1M1` are DECK TEXT.

    Poison: `S1M1` sits inside A1M2's deck block precisely because a parser
    that does not skip the block would open a rule section there and file
    A1M2's own markers under it.
    """
    p = _fixture()
    try:
        _c, _u, recs = resultsdb.parse_records(p)
        rules = [r["rule"] for r in recs]
        assert rules == ["A1M2", "A1M2", "floating.TUB"], rules
        assert "S1M1" not in rules
    finally:
        os.remove(p)


def test_packed_edge_keeps_both_endpoints():
    """An `e` record written as one four-number line is a real edge.

    Poison: a parser taking the first pair only returns a single point, the
    marker has zero length, and it renders as nothing at all.
    """
    p = _fixture()
    try:
        _c, _u, recs = resultsdb.parse_records(p)
        edge = [r for r in recs if r["kind"] == "e"][0]
        assert len(edge["pts"]) == 2, edge["pts"]
        assert edge["pts"] == [(5.0, 6.0), (5.3, 6.0)]
    finally:
        os.remove(p)


def test_units_are_applied():
    p = _fixture()
    try:
        _c, _u, recs = resultsdb.parse_records(p)
        assert recs[0]["pts"][0] == (0.1, 0.2)
    finally:
        os.remove(p)


def test_counts_and_summary():
    p = _fixture()
    try:
        db = resultsdb.Database.load(p)
        assert db.counts() == {"A1M2": 2, "floating.TUB": 1}
        assert db.summary() == "A1M2 2, floating.TUB 1"
        assert len(db) == 3
    finally:
        os.remove(p)


def test_frame_guard_refuses_the_wrong_top_cell():
    """A coordinate is a coordinate in the WRONG frame too.

    Poison twin: the matching name must NOT raise, or the guard is just an
    unconditional refusal wearing a check's clothes.
    """
    p = _fixture()
    try:
        resultsdb.Database.load(p, expect_top="ancBrain_gap")     # control
        raised = False
        try:
            resultsdb.Database.load(p, expect_top="AncASIC_P2_core_fp")
        except resultsdb.FrameError as exc:
            raised = True
            assert "ITS OWN frame" in str(exc)
        assert raised, "the frame guard did not fire on a foreign top cell"
    finally:
        os.remove(p)


def test_bboxes_reduce_but_the_records_do_not():
    p = _fixture()
    try:
        _c, _u, recs = resultsdb.parse_records(p)
        bb = resultsdb.bboxes(recs)
        assert bb["A1M2"][0] == (0.1, 0.2, 0.39, 0.39)
        # the reduction is the CALLER's; the records still carry 4 vertices
        assert len(recs[0]["pts"]) == 4
    finally:
        os.remove(p)


def test_group_of_is_syntactic():
    assert resultsdb.group_of("floating.TUB") == "floating"
    assert resultsdb.group_of("W1M2") == "W"
    assert resultsdb.group_of("M3.S.2.1") == "M3"
    assert resultsdb.group_of("1234") == "other"


def test_empty_database_is_empty_not_an_exception():
    p = _fixture("")
    try:
        cell, unit, recs = resultsdb.parse_records(p)
        assert (cell, unit, recs) == ("", 1000.0, [])
    finally:
        os.remove(p)


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("resultsdb: %d check(s) passed" % n)
