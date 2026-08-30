#!/usr/bin/env python3
"""Whose result is it, and did this change ADD one?

    zones = triage.Zones([("ancBrain_top", box), ("SLDO_5", box), ...])
    owned = triage.attribute(db.records, zones)
    delta = triage.diff(baseline.counts(), run.counts())

Two questions a raw count cannot answer, and a full-die run answers neither.

⛔ **ATTRIBUTE BY GEOMETRY, NOT BY THE TOOL'S CELL NAMES.** The obvious
attribution is the verification tool's own hierarchical report, and on one
real die run it put 4336 of 4742 results into three cells called `MASCO__P1`,
`MASCO__P2` and `MASCO__P3` -- while listing the block that actually holds
4492 of them at **twenty-two**. `MASCO` is in none of the stream's 2101
structures, in no rule file, nowhere in the results database, and IS the
engine's own partitioning binary. Read as design cells the table is not merely
uninformative, it is inverted. The database's coordinates, on the other hand,
are in the top cell's frame and the placement says where every block is, so a
result is inside a block or it is not, and no name is consulted.

⚠️ **THE ZONES NEST, SO "INSIDE" NEEDS AN ORDER.** A ring's box CONTAINS the
block it wraps; a large analogue block's box contains most of a cluster.
Smallest-area-first is what makes "inside the inner block" beat "inside the
ring", and a result inside nothing is reported as the ASSEMBLY's rather than
silently binned -- an unattributed marker is a finding about the floorplan.

⚠️ **AND A ZONE IS A BOUNDING BOX, WHICH IS EVIDENCE AND NOT PROOF.** What
settles ownership is re-running the deck **on the identical stream bytes**
with the suspect block as the top cell. That is cheap -- a block inside a die
stream is already a valid top cell, and one measured pair was 51 s against the
die's 255 -- and it needs no rebuild, no new GDS and no block owner. This
module localises; the control run proves. `loop.Ledger` is where the control
gets recorded.

THE RULE TABLE IS THE PORT'S, AND ONLY THE PORT'S
-------------------------------------------------
A rule NAME is a process fact. `M3.S.2.1`, `S1M3` and `met3.spacing.2` are
three vocabularies for one idea, and the mechanical response to each is
measured judgement about a specific deck. So `RuleTable` is a container the
consumer fills; nothing here ships a table. What IS shared is the shape of an
entry -- a class, a response, and whether a mechanical repair exists -- and
the discipline that an unclassified rule is REPORTED as unclassified rather
than folded into a default bucket.
"""
import collections
import re

from . import resultsdb


class RuleTable(object):
    """The port's DRC semantics: one source, consulted by every consumer.

    Entries are `(cls, pattern, response, auto)`, tried in order:

        cls       a short class name, the key everything else groups by
        pattern   a regex (or a compiled one) matched against the rule name
        response  the MECHANICAL response, in prose -- what a person or a
                  responder should do about a marker of this class
        auto      True when a responder exists that closes it unattended

    ⚠️ An unmatched rule comes back class `None`, and callers must print that
    count. A table that silently buckets the unknown into "other" is a table
    that stops reporting the day the deck gains a rule -- which is the same
    failure as a predicate that goes from sometimes-true to never-true.
    """

    def __init__(self, entries=()):
        self.entries = []
        for e in entries:
            self.add(*e)

    def add(self, cls, pattern, response, auto=False):
        rx = pattern if hasattr(pattern, "match") else re.compile(pattern)
        self.entries.append((cls, rx, response, bool(auto)))
        return self

    def classify(self, rule):
        for cls, rx, _resp, _auto in self.entries:
            if rx.match(rule):
                return cls
        return None

    def meta(self, rule):
        """{cls, response, auto, rule, group} -- the full record for a rule."""
        for cls, rx, resp, auto in self.entries:
            if rx.match(rule):
                return {"rule": rule, "cls": cls, "response": resp,
                        "auto": auto, "group": resultsdb.group_of(rule)}
        return {"rule": rule, "cls": None,
                "response": "UNCLASSIFIED -- no entry in this port's rule "
                            "table. Read the deck's own rule body: the "
                            "caption describes the drawing and only the rule "
                            "says what it checks.",
                "auto": False, "group": resultsdb.group_of(rule)}

    def automatable(self, rule):
        return self.meta(rule)["auto"]

    def unclassified(self, records):
        """{rule: n} for every rule this table does not know."""
        out = collections.Counter()
        for r in records:
            if self.classify(r["rule"]) is None:
                out[r["rule"]] += 1
        return out


# ---------------------------------------------------------------------------
# geometric attribution
# ---------------------------------------------------------------------------

UNATTRIBUTED = "<assembly>"


class Zones(object):
    """Named boxes, searched smallest-area-first.

    `zones` is `[(name, (x0, y0, x1, y1)), ...]` in the SAME frame as the
    results database -- which is the top cell's. A caller that mixes frames
    gets confident nonsense, so state the frame where the zones are built.
    """

    def __init__(self, zones):
        self.zones = sorted(
            [(n, tuple(float(v) for v in b)) for n, b in zones],
            key=lambda nb: (nb[1][2] - nb[1][0]) * (nb[1][3] - nb[1][1]))

    def owner(self, pts):
        """The smallest zone whose box contains the marker's CENTRE.

        The centre rather than the whole polygon: a spacing marker at a seam
        legitimately straddles two blocks, and "in neither" would be the one
        answer that is certainly wrong.
        """
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        for name, b in self.zones:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                return name
        return UNATTRIBUTED


def attribute(records, zones):
    """{zone: {rule: n}} -- who owns what, by geometry only."""
    out = collections.OrderedDict()
    for r in records:
        who = zones.owner(r["pts"])
        out.setdefault(who, collections.Counter())[r["rule"]] += 1
    return out


# ---------------------------------------------------------------------------
# the diff -- judge a change by what it ADDED
# ---------------------------------------------------------------------------

class Delta(object):
    """baseline -> run, per rule. `added` is the number that means anything."""

    def __init__(self, baseline, run):
        self.baseline = collections.Counter(baseline)
        self.run = collections.Counter(run)
        self.added = collections.Counter()
        self.removed = collections.Counter()
        for rule in set(self.baseline) | set(self.run):
            d = self.run[rule] - self.baseline[rule]
            if d > 0:
                self.added[rule] = d
            elif d < 0:
                self.removed[rule] = -d

    @property
    def net(self):
        return sum(self.run.values()) - sum(self.baseline.values())

    @property
    def clean(self):
        """True when the run added nothing.

        ⚠️ NOT "the run returned zero". A cell with a density-only baseline is
        clean at its baseline, and a flow that waits for zero waits forever --
        while a flow that quotes a total hides the one result it added.
        """
        return not self.added

    def report(self, width=10):
        L = ["%-*s %8s %8s %8s" % (width, "rule", "base", "run", "added")]
        for rule in sorted(set(self.baseline) | set(self.run)):
            L.append("%-*s %8d %8d %8s"
                     % (width, rule, self.baseline[rule], self.run[rule],
                        ("+%d" % self.added[rule]) if self.added[rule]
                        else ("-%d" % self.removed[rule])
                        if self.removed[rule] else "."))
        L.append("%-*s %8d %8d %8s"
                 % (width, "TOTAL", sum(self.baseline.values()),
                    sum(self.run.values()),
                    "+%d" % self.net if self.net > 0 else str(self.net)))
        return "\n".join(L)


def diff(baseline, run):
    """`Delta` between two `{rule: n}` counters (or two `Database.counts()`)."""
    return Delta(baseline, run)
