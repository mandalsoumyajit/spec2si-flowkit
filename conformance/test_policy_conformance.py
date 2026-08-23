#!/usr/bin/env python3
"""Policy conformance: does THIS repo carry every core rule, and say so?

Vendored into each consumer repo beside the core policy it checks. The
contract it enforces is deliberately narrow, because a wider one would be a
lie: three process ports cannot share an enforcement point (Calibre vs
PVS/Pegasus, PyCell vs SKILL, one substrate vs per-tub), so what is shared
is the RULE SET and its principle, and what stays local is the wording, the
enforcement path and the evidence.

  1. the vendored core has not drifted from upstream (content hash);
  2. the consumer's own policy file carries EVERY core rule id;
  3. each carries a status: enforced | partial | not-implemented | waived;
  4. a waived rule states why.

A young port declaring half the set `not-implemented` PASSES. That is the
point: the gap becomes a number printed on every run instead of an absence
nobody can see. Same argument as an unclassified runlog attempt, and the
opposite of a check that quietly has nothing to check.

  python3 test_policy_conformance.py            # from anywhere in the repo
  python3 test_policy_conformance.py --json     # machine-readable
"""
import hashlib
import json
import os
import sys

STATUSES = ("enforced", "partial", "not-implemented", "waived")

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(root, names):
    """First match for any of `names`, walking `root`.

    ⛔ `.claude` IS PRUNED, AND THAT IS NOT COSMETIC. A git worktree under
    `.claude/worktrees/<branch>/` is a COMPLETE SECOND CHECKOUT of this repo
    -- policy files and all -- and `.claude` sorts before `analog` and
    `policy`, so an unpruned walk finds the WORKTREE's copy first and
    silently conformance-checks a branch nobody asked about. Measured
    2026-08-20: the report named
    `.claude/worktrees/<branch>/policy/flow_policy.core.json` on two of
    three repos. It had always PASSED, for the worst possible reason -- the
    worktree happened to agree with main. The moment it did not, the gate
    would have graded the wrong tree without saying so.
    """
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", ".claude", "__pycache__", "work",
                                    "results", "node_modules", ".venv")]
        for n in names:
            if n in files:
                return os.path.join(dirpath, n)
    return None


def repo_root(start=None):
    """The checkout this file sits in.

    `.git` is EXISTS, not ISDIR: in a git worktree (and a submodule) it is a
    FILE holding a gitdir pointer, so an isdir test walks straight past the
    worktree and returns the main checkout -- the gate then grades a tree
    nobody is editing and PASSES, which is the same wrong-tree failure the
    `.claude` exclusion in `_find` was added for. Measured in spec2si-tsmc65
    2026-08-23: from .claude/worktrees/<name>/policy this returned the main
    checkout and reported ITS policy version against the worktree's change.
    """
    p = start or HERE
    while p != os.path.dirname(p):
        if os.path.exists(os.path.join(p, ".git")):
            return p
        p = os.path.dirname(p)
    return start or HERE


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check(root=None, upstream=None):
    root = root or repo_root()
    core_path = _find(root, ["flow_policy.core.json"])
    local_path = _find(root, ["flow_policy.json"])
    out = {"repo": os.path.basename(root), "errors": [], "warnings": [],
           "core": None, "local": None, "adoption": {}}
    if not core_path:
        out["errors"].append("no vendored flow_policy.core.json in this repo")
        return out
    if not local_path:
        out["errors"].append(
            "no flow_policy.json in this repo -- a consumer must carry its "
            "own policy file declaring a status for every core rule")
        return out
    core, local = load(core_path), load(local_path)
    out["core"] = {"version": core["version"], "sha256": sha256(core_path)[:16],
                   "path": os.path.relpath(core_path, root)}
    out["local"] = {"version": local.get("version"),
                    "path": os.path.relpath(local_path, root),
                    "conforms_to": local.get("conforms_to")}

    # 1. the vendored copy has not drifted from upstream
    if upstream and os.path.exists(upstream):
        if sha256(upstream) != sha256(core_path):
            out["errors"].append(
                "vendored core has DRIFTED from upstream {} -- re-vendor with "
                "sync.py, never hand-edit the copy".format(upstream))

    # 2/3. every core id present, with a legal status
    local_rules = {r["id"]: r for r in local.get("rules", [])}
    counts = dict.fromkeys(STATUSES, 0)
    for cr in core["rules"]:
        rid = cr["id"]
        lr = local_rules.get(rid)
        if lr is None:
            out["errors"].append(
                "core rule {!r} is absent from {} -- carry it, even as "
                "not-implemented".format(rid, out["local"]["path"]))
            continue
        st = lr.get("status")
        if st not in STATUSES:
            out["errors"].append(
                "core rule {!r} has status {!r}; one of {}".format(
                    rid, st, "|".join(STATUSES)))
            continue
        counts[st] += 1
        # 4. a waived rule owes a reason
        if st == "waived" and not lr.get("waived_because"):
            out["errors"].append(
                "core rule {!r} is waived without `waived_because`".format(rid))
    out["adoption"] = counts
    out["adoption"]["core_rules"] = len(core["rules"])

    # a consumer SHOULD pin which core version it conforms to
    if local.get("conforms_to") != core["version"]:
        out["warnings"].append(
            "local `conforms_to` is {!r}, vendored core is {!r}".format(
                local.get("conforms_to"), core["version"]))
    out["docs"] = doc_coverage(root)
    extra = [r for r in local_rules if r not in {c["id"] for c in core["rules"]}]
    if extra:
        out["warnings"].append(
            "{} local-only rule(s): {}".format(len(extra), ", ".join(sorted(extra))))
    return out


def doc_coverage(root):
    """(tagged, untagged, by_genre) for this repo's docs, or None.

    ⭐ WHY DOCUMENTATION IS IN A *POLICY* CONFORMANCE REPORT. The same
    reason the adoption gap above is printed rather than hidden behind a
    pass: a repo that quietly stops documenting looks identical to one that
    has nothing left to document. Printing the number means falling behind
    SHOWS, and the three repos stay comparable.

    ⚠ It NEVER contributes an error. Documentation adoption is incremental
    by design -- untagged docs only warn in the generator too -- and a gate
    that fails a chip commit over a missing `summary:` line is a gate people
    route around. Returns None (and the report simply omits the line) when
    the repo has not adopted the shared doc model yet, which is a real and
    allowed state, not a failure.
    """
    docsdir = os.path.join(root, "docs")
    if not os.path.isdir(docsdir):
        return None
    saved = list(sys.path)
    try:
        sys.path.insert(0, docsdir)
        for stale in ("gen", "docmodel", "mdbackend"):
            sys.modules.pop(stale, None)
        import gen                                        # the repo's own
        return gen.MODEL.coverage()
    except Exception:
        return None                 # not adopted, or not importable: quiet
    finally:
        sys.path[:] = saved
        for stale in ("gen", "docmodel", "mdbackend"):
            sys.modules.pop(stale, None)


def report(res):
    L = ["policy conformance: {}".format(res["repo"])]
    if res["core"]:
        L.append("  core  {} ({}) {}".format(
            res["core"]["version"], res["core"]["sha256"], res["core"]["path"]))
    if res["local"]:
        L.append("  local {} conforms_to={} {}".format(
            res["local"]["version"], res["local"]["conforms_to"],
            res["local"]["path"]))
    a = res["adoption"]
    if a:
        L.append("  adoption: {}/{} enforced, {} partial, {} not-implemented,"
                 " {} waived".format(a.get("enforced", 0), a.get("core_rules"),
                                     a.get("partial", 0),
                                     a.get("not-implemented", 0),
                                     a.get("waived", 0)))
    d = res.get("docs")
    if d:
        tagged, untagged, by_genre = d
        L.append("  docs:     {}/{} tagged ({} untagged); {}".format(
            tagged, tagged + untagged, untagged,
            ", ".join("{} {}".format(n, g)
                      for g, n in sorted(by_genre.items(),
                                         key=lambda kv: (-kv[1], kv[0])))))
    for w in res["warnings"]:
        L.append("  warn  " + w)
    for e in res["errors"]:
        L.append("  FAIL  " + e)
    L.append("  " + ("PASS" if not res["errors"] else "FAIL"))
    return "\n".join(L)


def main(argv):
    up = None
    if "--upstream" in argv:
        up = argv[argv.index("--upstream") + 1]
    res = check(upstream=up)
    if "--json" in argv:
        print(json.dumps(res, indent=1))
    else:
        print(report(res))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
