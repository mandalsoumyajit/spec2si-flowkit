#!/usr/bin/env python3
"""The ASCII physical-verification results database. ONE parser, two vendors.

    cell, unit, recs = resultsdb.parse_records("DRC_RES.db")
    db = resultsdb.Database.load("nvg_drc.db", expect_top="ancBrain_gap")

WHY THIS IS SHARED, AND THE EVIDENCE IS UNUSUALLY GOOD
------------------------------------------------------
This is the only file in the package whose portability was established by
accident rather than by argument. Two process ports wrote it independently:

  * `spec2si-tsmc65` reads **Calibre 2024.1** `DRC_RES.db`;
  * `spec2si-xt011` reads **PVS 23.1 / Pegasus** `results_db -drc -ascii`.

The xt011 port wrote down "whether Pegasus emits a Calibre-shaped database"
as the first question to ANSWER rather than assume, ran the 65 nm algorithm
unmodified against five real Pegasus databases, and read every one of them --
11, 12, 11, 12, 2183 and 191 records. The two implementations then turned out
to be the same algorithm to within a comment. That is a measurement, not a
hope, and it is what licenses one copy.

    header      "<top cell> <units-per-um>"
    per rule    a bare NAME line
                a counts line "<violations> <n> <deck-text-lines>"
                the braced deck text it sizes           <- skipped, see below
                records: "p <id> <nverts>" | "e <id> <nverts>"
                         then <nverts> lines of integer database units

THREE THINGS THIS FILE REFUSES TO DO, EACH PAID FOR
---------------------------------------------------
⛔ **It does not reduce a record to a bounding box.** A spacing violation is
an EDGE PAIR; a box drawn round both conductors points at the metal when the
error is the GAP. `bboxes()` exists for callers that want that reduction, and
it is theirs to ask for.

⛔ **It does not copy the deck text out.** The counts line sizes a block of
the rule deck's own source, which is skipped so it can never be mistaken for
a header or a record -- and it is the NDA-sensitive half of the file. A
results database can then travel with a report; the raw file cannot.

⛔ **It does not assume the marker frame.** Coordinates are in the TOP CELL's
own frame, so a marker from a die run and a marker from a block run are the
same number only when the top cells agree. `Database.load(expect_top=...)`
refuses on a disagreement instead of patching the wrong chip -- the failure
that motivates it (`DP_ERROR`) is silent otherwise, because a coordinate is a
perfectly good coordinate in the wrong frame.
"""
import collections
import re

#: A rule section header: a bare name on its own line.
_HDR = re.compile(r"^[A-Za-z][\w.\-:]*$")
#: The counts line under a header: <violations> <?> <deck lines>.
_COUNTS = re.compile(r"^(\d+)\s+\d+\s+(\d+)")
#: A violation record: kind ('p' polygon / 'e' edge), a number, vertex count.
_REC = re.compile(r"^([pe])\s+\d+\s+(\d+)\s*$")

DEFAULT_UNIT = 1000.0


class FrameError(Exception):
    """The database's top cell is not the one the caller is patching."""


def parse_records(dbpath):
    """(cell, unit, [{rule, kind, pts}, ...]) -- every violation, all vertices,
    in um.

    Record KIND is kept rather than reduced: see the module docstring.
    """
    with open(dbpath, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    if not lines:
        return "", DEFAULT_UNIT, []
    head = lines[0].split()
    cell = head[0] if head else ""
    unit = float(head[1]) if len(head) > 1 else DEFAULT_UNIT
    if unit <= 0:
        unit = DEFAULT_UNIT
    out, rule, i, n = [], None, 1, len(lines)
    while i < n:
        ln = lines[i].strip()
        m = _REC.match(ln)
        if m and rule:
            kind = m.group(1)
            nv = int(m.group(2))
            pts = []
            for k in range(1, nv + 1):
                if i + k >= n:
                    break
                parts = lines[i + k].split()
                try:
                    # Edges come in BOTH forms: two `x y` lines, and one
                    # packed `x1 y1 x2 y2`. Keep both endpoints or a real
                    # edge collapses to a zero-length point in the marker
                    # database -- which then renders as nothing at all.
                    pairs = 2 if kind == "e" and len(parts) >= 4 else 1
                    for j in range(pairs):
                        pts.append((float(parts[2 * j]) / unit,
                                    float(parts[2 * j + 1]) / unit))
                except (ValueError, IndexError):
                    break
            if pts:
                out.append({"rule": rule, "kind": kind, "pts": pts})
            i += nv + 1
            continue
        if _HDR.match(ln) and i + 1 < n:
            c = _COUNTS.match(lines[i + 1])
            if c:
                rule = ln
                nd = int(c.group(2))
                i += 2 + (nd if 0 <= nd < n else 0)
                continue
        i += 1
    return cell, unit, out


def counts(recs):
    """{rule: n} -- what the run returned, by rule."""
    return collections.Counter(r["rule"] for r in recs)


def bboxes(recs):
    """{rule: [(x0, y0, x1, y1), ...]} -- the reduction, when a caller asks.

    ⚠️ Lossy on purpose and only for the caller who wants it: an `e` record's
    box spans the two conductors and NOT the gap between them, which is the
    thing the rule is about.
    """
    out = {}
    for r in recs:
        xs = [p[0] for p in r["pts"]]
        ys = [p[1] for p in r["pts"]]
        out.setdefault(r["rule"], []).append(
            (min(xs), min(ys), max(xs), max(ys)))
    return out


def group_of(rule):
    """A SYNTACTIC grouping for a rule name -- NOT a severity judgement.

    The part before the first '.' when there is one (`floating.TUB` ->
    `floating`), else the leading run of letters (`W1M2` -> `W`, `M3.S.2` ->
    `M`). It groups so a couple of thousand markers stay navigable; it does
    not classify, because classification needs a rule table somebody has read
    out of the DRM. That is `triage.RuleTable`, and it belongs to the port.
    """
    if "." in rule:
        head = rule.split(".", 1)[0]
        return head or "other"
    m = re.match(r"^([A-Za-z]+)", rule)
    return m.group(1) if m else "other"


class Database(object):
    """A parsed results database, with its frame stated.

    `load()` is the one entry point that can refuse: a caller that names the
    top cell it believes it is patching gets a `FrameError` when the database
    is somebody else's run, rather than a set of perfectly-formed patches at
    coordinates that mean nothing here.
    """

    def __init__(self, cell, unit, records, path=None):
        self.cell = cell
        self.unit = unit
        self.records = records
        self.path = path

    @classmethod
    def load(cls, path, expect_top=None):
        cell, unit, recs = parse_records(path)
        db = cls(cell, unit, recs, path)
        if expect_top is not None and cell != expect_top:
            raise FrameError(
                "%s is a run on %r and the caller is patching %r -- a marker "
                "coordinate is only a coordinate in ITS OWN frame"
                % (path, cell, expect_top))
        return db

    def __len__(self):
        return len(self.records)

    def counts(self):
        return counts(self.records)

    def by_rule(self, pred):
        """Every record whose RULE satisfies `pred` (a callable or a set)."""
        if not callable(pred):
            want = set(pred)
            return [r for r in self.records if r["rule"] in want]
        return [r for r in self.records if pred(r["rule"])]

    def summary(self):
        """"<rule> <n>, ..." in rule order -- the one line worth printing."""
        c = self.counts()
        return ", ".join("%s %d" % (k, c[k]) for k in sorted(c))
