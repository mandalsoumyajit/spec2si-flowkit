#!/usr/bin/env python3
"""Gates for drcloop.loop -- each with a control that must FIRE.

The trajectory in `test_ledger_reproduces_a_real_run` is the measured one from
`spec2si-xt011`'s two-block gap cell, so the ledger is exercised against a
run that happened rather than against numbers chosen to make it pass.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from drcloop import loop                                    # noqa: E402


class _Refusal(object):
    def __init__(self):
        self.rule = "A1M2"
        self.layer = "MET2"
        self.marker_bbox = (1.0, 2.0, 1.3, 2.2)
        self.why = "0.0600 um from metal, against a 0.1400 rule"


def _tmp(data=b"stream-bytes"):
    fd, path = tempfile.mkstemp(suffix=".gds")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


# ---------------------------------------------------------------------------
# the binding
# ---------------------------------------------------------------------------

def test_a_reply_is_fresh_against_the_stream_it_answered():
    g = _tmp()
    try:
        r = loop.Reply.build("ancBrain_gap", "nvg_drc.db", g, patches=[1, 2])
        assert r.check_fresh(g) is True             # the control
    finally:
        os.remove(g)


def test_a_reply_REFUSES_a_stream_it_did_not_answer():
    """A patch is a reply to ONE stream. Re-route, re-DRC, re-patch --
    skipping the middle step is how a patch comes to sit one grid step from
    the shape it was meant to merge with."""
    g = _tmp()
    try:
        r = loop.Reply.build("ancBrain_gap", "nvg_drc.db", g)
    finally:
        os.remove(g)
    g2 = _tmp(b"stream-bytes-after-the-reroute")
    try:
        raised = False
        try:
            r.check_fresh(g2)
        except loop.StaleReply as exc:
            raised = True
            assert "re-run the deck" in str(exc)
        assert raised, "a stale reply was accepted against a changed stream"
    finally:
        os.remove(g2)


def test_the_header_carries_its_own_inputs_and_names_every_refusal():
    g = _tmp()
    try:
        r = loop.Reply.build("ancBrain_gap", "nvg_drc.db", g,
                             patches=[1], refusals=[_Refusal()])
        txt = "\n".join(r.header_lines())
        assert "ancBrain_gap" in txt
        assert "nvg_drc.db" in txt
        assert r.gds_digest in txt
        assert "REFUSED    A1M2 MET2" in txt          # named, not skipped
        assert "0.1400 rule" in txt
    finally:
        os.remove(g)


def test_sidecar_round_trips_the_binding():
    g = _tmp()
    side = None
    try:
        r = loop.Reply.build("gap", "db", g, patches=[1, 2, 3],
                             refusals=[_Refusal()])
        fd, side = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        r.write_sidecar(side)
        back = loop.Reply.read_sidecar(side)
        assert back.gds_digest == r.gds_digest
        assert back.top == "gap"
        assert back.meta["patches"] == 3
        assert back.check_fresh(g) is True
    finally:
        os.remove(g)
        if side:
            os.remove(side)


def test_a_foreign_sidecar_is_refused():
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('{"magic": "something-else"}')
    try:
        raised = False
        try:
            loop.Reply.read_sidecar(p)
        except loop.StaleReply:
            raised = True
        assert raised
    finally:
        os.remove(p)


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

def test_a_ledger_with_no_control_REFUSES_to_answer():
    """Poison twin of every 'clean' claim in the package: a DRC total is not
    a result, and a ledger that answers without a baseline is a total."""
    led = loop.Ledger("ancBrain_gap")
    led.step("routed", {"R1M1": 11, "W1M2": 806})
    raised = False
    try:
        led.clean
    except loop.NoControl as exc:
        raised = True
        assert "control that is a different object" in str(exc)
    assert raised, "a run was judged with no baseline to judge it against"


def test_ledger_reproduces_a_real_run():
    """The measured xt011 gap-cell trajectory, with its own baseline.

    Real: 11 baseline (R1DF + R1M1..M5 + R3M1..M5, every one a density
    rule), 1063 routed, 21 after the snap fix, 11 after the area patches.
    The routed step here carries the SIX families the commit named and not
    the eight results it elided, so this reads 1055 -- the shape is the
    measured one and the arithmetic is the fixture's, which is stated rather
    than rounded into agreement.
    """
    base = dict([("R1DF", 1)]
                + [("R1M%d" % i, 1) for i in range(1, 6)]
                + [("R3M%d" % i, 1) for i in range(1, 6)])
    led = loop.Ledger("ancBrain_gap")
    led.baseline(base, "same cellview, streamed before any route is drawn")
    led.step("routed", dict(base, W1M2=806, A1M2=96, S1M1=56, W1M3=55,
                            A1M3=19, S1M3=12))
    assert not led.clean
    assert led.delta.net == 1044
    led.step("patched", dict(base, S1M1=10))
    assert led.delta.added == {"S1M1": 10}
    led.step("resnapped", dict(base))
    assert led.clean, led.report()
    assert led.trajectory()[0] == ("baseline", 11)
    assert [t[1] for t in led.trajectory()] == [11, 1055, 21, 11]


def test_the_report_measures_every_step_against_the_BASELINE():
    """Poison: a rolling diff would call the middle step an improvement of
    -1034 and say nothing about the 10 it still owes."""
    led = loop.Ledger("c")
    led.baseline({"R": 11})
    led.step("a", {"R": 11, "X": 1000})
    led.step("b", {"R": 11, "X": 10})
    txt = led.report()
    assert "+1000" in txt and "+10" in txt      # both against the baseline
    assert "OPEN       10 added: X 10" in txt


def test_check_isolation_pairs_markers_by_position():
    """Rule 3: shrink the artefact with the coordinates UNCHANGED, so a
    marker here and a marker there are the same number."""
    a = [{"rule": "A1M2", "pts": [(13578.20, 420.4), (13578.40, 420.6)]}]
    same = [dict(a[0])]
    matched, moved = loop.check_isolation(a, same)
    assert (matched, moved) == (1, [])
    # poison twin: re-origin the small cell and the two runs stop comparing
    shifted = [{"rule": "A1M2", "pts": [(0.20, 0.4), (0.40, 0.6)]}]
    matched, moved = loop.check_isolation(a, shifted)
    assert matched == 0 and len(moved) == 1


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("loop: %d check(s) passed" % n)
