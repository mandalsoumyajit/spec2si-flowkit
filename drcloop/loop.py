#!/usr/bin/env python3
"""The protocol: a control, a binding, and a ledger. This is the framework.

`resultsdb`, `markers` and `triage` are the instruments. This file is the
DISCIPLINE that makes their output mean something, and it is three rules:

  1. **A run without a control is a number, not a result.** The same cellview
     streamed BEFORE the change under test is the baseline; `Delta.added` is
     the only figure a change is judged by. A control that is a different
     object is not a control.
  2. **A reply is bound to the stream it replied to.** A patch set answers
     markers found in ONE stream and is stale the moment the stream changes.
     Re-route, re-DRC, re-patch: skipping the middle step is how a patch comes
     to sit one grid step from the shape it was meant to merge with.
  3. **Shrink the artefact, never the check.** When the number cannot be read
     -- 1098 results over 23 rules on a die, 53 of them pre-existing -- the
     answer is a smaller cell holding the thing under test, with the
     coordinates UNCHANGED so a marker here and a marker there are the same
     number. Not a looser deck and not a sampled run.

WHY A BINDING AND NOT A TIMESTAMP
---------------------------------
Both ports have shipped a stale derived artefact behind a plausible mtime, and
one flow's own file records a builder's refusal being a NOT-SAVING -- so the
next step streamed the PREVIOUS cellview under this run's filename and lost a
day. A digest is the cheap version of the fix: the reply carries the SHA-256
of the stream it was computed against, and loading it against a different
stream is a refusal with the remedy in the message.

⚠️ It is a binding, not a proof of correctness. It says the reply answers
THIS stream's markers. Whether the patch is right is what the next DRC run is
for -- which is the loop.

THE LOOP, WRITTEN OUT
---------------------
    stream(baseline)        -> the control, same cellview, change not applied
    deck(baseline)          -> Database  ------------------.
    apply(change); stream() -> the artefact under test      |
    deck(routed)            -> Database  --> Delta ---------'  added = ours
    close_all(added)        -> Reply, bound to THIS stream
    apply(reply); stream(); deck()  -> Database --> Delta   added should fall
    ... until Delta.clean, or a Refusal names what is left

`Ledger` records that as it happens so the trajectory -- 1063 -> 147 -> 21 ->
11 on one real cell -- is an artefact rather than a memory.
"""
import hashlib
import json
import os

from . import triage


class StaleReply(Exception):
    """A patch set is being used against a stream it did not answer."""


class NoControl(Exception):
    """A run is being called clean with no baseline to be clean against."""


def stream_digest(path, chunk=1 << 20):
    """SHA-256 of the stream BYTES. The identity of what the deck read."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# the reply
# ---------------------------------------------------------------------------

class Reply(object):
    """A patch set, bound to the (top cell, database, stream) it answers.

    It is a SEPARATE input, never an edit to the router's own output. The two
    answer different questions from different artefacts, so the base geometry
    can be regenerated without discarding the reply, and the reply can be
    regenerated without re-routing.
    """

    MAGIC = "drcloop-reply"
    VERSION = 1

    def __init__(self, top, db_path, gds_path, gds_digest,
                 patches=(), refusals=(), meta=None):
        self.top = top
        self.db_path = db_path
        self.gds_path = gds_path
        self.gds_digest = gds_digest
        self.patches = list(patches)
        self.refusals = list(refusals)
        self.meta = dict(meta or {})

    @classmethod
    def build(cls, top, db_path, gds_path, patches=(), refusals=(),
              meta=None):
        return cls(top, db_path, gds_path, stream_digest(gds_path),
                   patches, refusals, meta)

    # -- the binding ------------------------------------------------------

    def check_fresh(self, gds_path):
        """Raise unless `gds_path` is the stream this reply answered."""
        got = stream_digest(gds_path)
        if got != self.gds_digest:
            raise StaleReply(
                "this reply answers markers found in %s (sha256 %s...), and "
                "%s is a different stream (%s...). A patch is a reply to ONE "
                "stream: re-run the deck on the current stream and re-derive "
                "the reply. Do not apply this one."
                % (os.path.basename(self.gds_path), self.gds_digest[:12],
                   os.path.basename(gds_path), got[:12]))
        return True

    # -- serialisation ----------------------------------------------------

    def header_lines(self, comment="# "):
        """The provenance a port writes at the top of its own patch file.

        A generator that takes a declared input should write it into its
        OUTPUT, so the artefact carries its own inputs and a reader never has
        to find the command that made it.
        """
        L = ["%s%s v%d -- %d patch(es), %d refusal(s)."
             % (comment, self.MAGIC, self.VERSION,
                len(self.patches), len(self.refusals)),
             "%sTOP        %s" % (comment, self.top),
             "%sMARKERS    %s" % (comment, os.path.basename(self.db_path)),
             "%sSTREAM     %s" % (comment, os.path.basename(self.gds_path)),
             "%sSHA256     %s" % (comment, self.gds_digest),
             "%sThe POSITIONS are the deck's own; the clearances are measured"
             % comment,
             "%sagainst that stream, which is the one the deck read." % comment,
             "%sDo not hand-edit: re-run the deck and re-derive the reply."
             % comment]
        for r in self.refusals:
            L.append("%sREFUSED    %s %s at %.4f %.4f -- %s"
                     % (comment, r.rule, r.layer, r.marker_bbox[0],
                        r.marker_bbox[1], r.why))
        return L

    def sidecar(self):
        """The machine-readable binding, for a port that wants it separate."""
        return {"magic": self.MAGIC, "version": self.VERSION,
                "top": self.top,
                "db": os.path.basename(self.db_path),
                "gds": os.path.basename(self.gds_path),
                "sha256": self.gds_digest,
                "patches": len(self.patches),
                "refusals": [{"rule": r.rule, "layer": r.layer,
                              "at": list(r.marker_bbox), "why": r.why}
                             for r in self.refusals],
                "meta": self.meta}

    def write_sidecar(self, path):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            json.dump(self.sidecar(), fh, indent=1, sort_keys=True)
            fh.write("\n")
        return path

    @classmethod
    def read_sidecar(cls, path):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("magic") != cls.MAGIC:
            raise StaleReply("%s is not a %s sidecar" % (path, cls.MAGIC))
        r = cls(d["top"], d["db"], d["gds"], d["sha256"], meta=d.get("meta"))
        r.meta["patches"] = d.get("patches")
        return r

    def summary(self):
        return ("REPLY      %d patch(es), %d refusal(s) against %s (%s...)"
                % (len(self.patches), len(self.refusals),
                   os.path.basename(self.gds_path), self.gds_digest[:12]))


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

class Iteration(object):
    def __init__(self, label, counts, note=""):
        self.label = label
        self.counts = dict(counts)
        self.note = note

    @property
    def total(self):
        return sum(self.counts.values())


class Ledger(object):
    """The trajectory of one loop, recorded as it runs.

    A ledger opens on the CONTROL and refuses to answer `clean` without one:

        led = Ledger("ancBrain_gap")
        led.baseline(base_db.counts(), "same cellview, no routes drawn")
        led.step("routed", run_db.counts())
        led.step("patched", after_db.counts(), note="116 of 116 closed")
        print(led.report())

    `added` is always measured against the BASELINE, never against the
    previous step -- a step that removes two of its own results while adding
    three is not progress, and a rolling diff says it is.
    """

    def __init__(self, cell):
        self.cell = cell
        self.control = None
        self.steps = []

    def baseline(self, counts, note=""):
        self.control = Iteration("baseline", counts, note)
        return self

    def step(self, label, counts, note=""):
        self.steps.append(Iteration(label, counts, note))
        return self

    def _require(self):
        if self.control is None:
            raise NoControl(
                "%s has no baseline. A DRC total is not a result: the same "
                "cellview streamed before the change under test is the only "
                "thing the run can be judged against, and a control that is "
                "a different object is not a control." % self.cell)

    @property
    def delta(self):
        """`triage.Delta` for the LATEST step against the baseline."""
        self._require()
        if not self.steps:
            return triage.Delta(self.control.counts, self.control.counts)
        return triage.Delta(self.control.counts, self.steps[-1].counts)

    @property
    def clean(self):
        """True when the latest step has added nothing to the baseline."""
        return self.delta.clean

    def trajectory(self):
        self._require()
        return ([("baseline", self.control.total)]
                + [(s.label, s.total) for s in self.steps])

    def report(self):
        self._require()
        L = ["LOOP       %s" % self.cell]
        traj = self.trajectory()
        L.append("           " + " -> ".join("%s %d" % t for t in traj))
        base = self.control.total
        if self.control.note:
            L.append("BASELINE   %d -- %s" % (base, self.control.note))
        else:
            L.append("BASELINE   %d" % base)
        for s in self.steps:
            d = triage.Delta(self.control.counts, s.counts)
            L.append("STEP       %-12s %5d total, %+d over baseline%s"
                     % (s.label, s.total, d.net,
                        (" -- " + s.note) if s.note else ""))
        d = self.delta
        if d.clean:
            L.append("CLEAN      the run adds nothing to the baseline of %d"
                     % base)
        else:
            L.append("OPEN       %d added: %s"
                     % (sum(d.added.values()),
                        ", ".join("%s %d" % (k, d.added[k])
                                  for k in sorted(d.added))))
        return "\n".join(L)


# ---------------------------------------------------------------------------
# the isolation cell -- rule 3
# ---------------------------------------------------------------------------

def check_isolation(records_here, records_there, tol=0.0):
    """Do two runs' markers live in the SAME frame? -> (matched, moved).

    Rule 3 says to shrink the artefact with the coordinates UNCHANGED, so
    that a marker in the small cell and a marker in the big one are the same
    number and the two runs can be DIFFED rather than argued about. This is
    the check that the shrink kept that property: it pairs markers by rule
    and position and reports what did not pair.

    A non-empty `moved` does not mean the small cell is wrong -- the routes
    it holds may genuinely differ -- but it does mean the two runs are no
    longer comparable marker-for-marker, which is the property the shrink was
    performed to obtain.
    """
    def key(r):
        xs = [p[0] for p in r["pts"]]
        ys = [p[1] for p in r["pts"]]
        cx = round((min(xs) + max(xs)) / 2.0, 4)
        cy = round((min(ys) + max(ys)) / 2.0, 4)
        return (r["rule"], cx, cy)

    there = {}
    for r in records_there:
        there.setdefault(key(r), 0)
        there[key(r)] += 1
    matched, moved = 0, []
    for r in records_here:
        k = key(r)
        if there.get(k):
            there[k] -= 1
            matched += 1
        else:
            moved.append(r)
    return matched, moved
