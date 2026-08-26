#!/usr/bin/env python3
"""Extract per-run-dir FEATURES for the staleness classifier. Read-only.

    python3 run_features.py > features.json          # on the cluster

Sweeping by age is a classifier with one feature and an unvalidated
threshold, and measured against the real tree it errs in both directions
(2026-08-26: 88 of 319 "stale" dirs hold signoff artifacts, while
`drc_v1`..`drc_v16` all read "fresh" although fifteen were superseded the
moment the next one was written). This dumps the features a real decision
needs, so the classifier can be evaluated instead of asserted.

⚠️ THIS FILE COMPUTES FEATURES AND NOTHING ELSE. It does not decide, and it
never moves a file. Keeping extraction separate from the decision is what
makes a labelled evaluation possible at all: the same feature rows get
scored by any candidate rule, and the rows are cheap to re-score offline
without re-walking NFS.

Python floor is the cluster's 3.6 -- no dataclasses, no f-strings.
"""
import json
import os
import re
import sys
import time

# artifacts that mean "a real result was produced here"
SIGNOFF = re.compile(r"(^DRC\.rep$|^lvs\.rep$|\.gds$|^DRC_RES\.db$|\.sp$"
                     r"|\.oa$|^DRC\.sum$|\.lib$|\.lef$)")
# leftovers that mean "a run died here"
WRECKAGE = re.compile(r"(\.cdslck$|^core\.\d+|^\.nfs[0-9a-f]{8}|\.lck$"
                      r"|^panic.*\.log$)")
# ⚠️ COMPLETION IS TOOL-SPECIFIC, AND KNOWING ONLY ONE TOOL UNDER-DETECTS IT
# BADLY. The first version tested for Calibre's `DRC.rep` alone and scored 97
# of 468 dirs complete while 272 held a real result -- so `superseded_by`,
# which requires a COMPLETED successor, found 13 where `drc_v1`..`drc_v16`
# alone should give fifteen. Measured on this tree, the terminal files are:
#   Calibre  DRC.rep / lvs.rep / DRC_RES.db      (61 dirs)
#   Pegasus  <cell>_drc.sum + *.rdb              (xt011)
#   strmout  strmout.log / strmout.out           (60)
#   Virtuoso worker.raw.txt (a build area, 99)
# A terminal file is written at the END of a run, so its PRESENCE is the
# signal; the content marker is a second confirmation where one exists.
TERMINAL = re.compile(r"(^DRC\.rep$|^lvs\.rep$|\.sum$|^strmout\.log$"
                      r"|^worker\.raw\.txt$|\.lib$)")
DONE_MARK = (("DRC.rep", "TOTAL Result Count"),
             ("lvs.rep", "CORRECT"),
             ("lvs.rep", "INCORRECT"))

MAX_DEPTH = 3           # NFS: a full walk of 468 dirs is minutes
MAX_FILES = 4000        # per dir; only counts and flags need the tail


def walk_limited(root):
    """(files, truncated). Depth- and count-limited: the features below are
    flags and counts, and a dir with 40k files answers all of them in the
    first few thousand."""
    out = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - root_depth >= MAX_DEPTH:
            dirnames[:] = []
        for fn in filenames:
            out.append((dirpath, fn))
            if len(out) >= MAX_FILES:
                return out, True
    return out, False


def base_name(name):
    """The run's identity with its version suffix removed, so siblings of
    one campaign group together.

    `drc_v1`..`drc_v16`, `drc_pwr`..`drc_pwr7` and `chk_LVT_TT` are the
    shapes actually on disk. This is the SUPERSESSION key, and it is the
    feature age cannot see: fifteen of sixteen `drc_v*` were garbage the
    moment the next completed, and every one of them looked fresh."""
    n = re.sub(r"[_-]?v?\d+$", "", name)
    return n or name


def features(path, now):
    name = os.path.basename(path.rstrip(os.sep))
    files, truncated = walk_limited(path)
    newest = 0.0
    total = 0
    has_signoff = False
    has_wreckage = False
    completed = False
    confirmed = False
    for dirpath, fn in files:
        full = os.path.join(dirpath, fn)
        try:
            st = os.lstat(full)
        except OSError:
            continue
        total += st.st_size
        if st.st_mtime > newest:
            newest = st.st_mtime
        if SIGNOFF.search(fn):
            has_signoff = True
        if WRECKAGE.search(fn):
            has_wreckage = True
        if TERMINAL.search(fn):
            completed = True
            for want_fn, mark in DONE_MARK:
                if fn == want_fn:
                    try:
                        with open(full, "rb") as fh:
                            # the terminal marker is near the end
                            fh.seek(max(0, st.st_size - 200000))
                            confirmed = confirmed or mark.encode() in fh.read()
                    except (OSError, IOError):
                        pass
    return {
        "name": name,
        "path": path,
        "base": base_name(name),
        "n_files": len(files),
        "truncated": truncated,
        "size_mb": round(total / 1048576.0, 2),
        "age_days": round((now - newest) / 86400.0, 1) if newest else None,
        "mtime": newest,
        "has_signoff": has_signoff,
        "has_wreckage": has_wreckage,
        "completed": completed,
        "confirmed": confirmed,
        "has_keep": os.path.exists(os.path.join(path, ".keep")),
        "empty": len(files) == 0,
    }


def main():
    now = time.time()
    roots = []
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    if os.path.isdir(docs):
        for proj in sorted(os.listdir(docs)):
            for sub in ("analog/work", "work"):
                w = os.path.join(docs, proj, sub)
                if os.path.isdir(w):
                    roots.append(w)
    rows = []
    for w in roots:
        for d in sorted(os.listdir(w)):
            p = os.path.join(w, d)
            if os.path.isdir(p):
                try:
                    rows.append(features(p, now))
                except OSError as e:
                    sys.stderr.write("skip %s: %s\n" % (p, e))

    # ── supersession: a LATER COMPLETED sibling with the same base ───────
    # Computed across the whole set rather than per dir, because it is a
    # relationship: "is there a newer completed run of the same thing".
    # This is the feature that separates 'old' from 'obsolete', and no
    # amount of mtime gives it.
    by_key = {}
    for r in rows:
        by_key.setdefault((os.path.dirname(r["path"]), r["base"]), []).append(r)
    for group in by_key.values():
        newest_done = None
        for r in group:
            if r["completed"] and (newest_done is None or
                                   r["mtime"] > newest_done["mtime"]):
                newest_done = r
        for r in group:
            r["siblings"] = len(group)
            if (newest_done is not None and r is not newest_done and
                    r["mtime"] < newest_done["mtime"]):
                r["superseded_by"] = newest_done["name"]
            else:
                r["superseded_by"] = None

    json.dump({"generated": now, "host": os.uname()[1], "rows": rows},
              sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    sys.stderr.write("%d run dirs, %d roots\n" % (len(rows), len(roots)))


if __name__ == "__main__":
    main()
