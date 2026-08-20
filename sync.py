#!/usr/bin/env python3
"""Vendor the shared policy layer into a consumer repo, and gate its drift.

Chosen over a submodule or a package install because it costs the consumers
NOTHING: a clone stays a clone, the cluster rsync push is unchanged, and the
cluster keeps running raw python3 through its activation wrapper. The price
is that real copies exist -- so the copies are hash-checked, which is the
same shape as every other derived artifact here (a staged value no script
reproduces survives only until it is re-spun).

  python3 sync.py --to C:\\dev\\XT011_ASIC        # vendor / update
  python3 sync.py --check C:\\dev\\XT011_ASIC     # gate: has the copy drifted?
  python3 sync.py --check-all                    # every registered consumer

Consumers are listed in consumers.json (paths are local to this machine and
that file is the only thing anyone needs to edit to add a fourth node).
"""
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONSUMERS = os.path.join(HERE, "consumers.json")

#: what gets vendored, and where it lands inside a consumer repo
FILES = [
    ("policy/flow_policy.core.json", "policy/flow_policy.core.json"),
    ("conformance/test_policy_conformance.py",
     "policy/test_policy_conformance.py"),
    # The docmeta genre vocabulary. Shared for the same reason as the policy
    # core and found the same way: all three repos adopted the `docmeta`
    # frontmatter convention independently, and by 2026-08-20 twenty-six
    # tracked docs carried a genre AIML_ASIC's generator rejects -- so a
    # documentation generator could not be shared across the three repos at
    # all, whatever else was in it. A genre is a STALENESS CONTRACT, and a
    # contract is exactly the kind of thing that must not diverge.
    ("policy/docmeta.core.json", "policy/docmeta.core.json"),
    # The IR solver. The FIRST non-policy thing shared here, and it earns
    # it by touching no PDK: ohms and amps in, volts out. Everything that
    # knows about a process -- the RC card, the Spectre reader, the rail
    # topology -- stays in the consumer's own adapter. See irdrop/solver.py.
    ("irdrop/solver.py", "irdrop/solver.py"),
    ("irdrop/test_solver.py", "irdrop/test_solver.py"),
    # The operating-point reader. Shared for the same reason as the
    # solver: a Spectre oppoint is a SIMULATOR format, not a PDK one --
    # `Vdd:p` means the same thing on all three nodes. How you GET the
    # numbers stays local (PSF vs text oppoint vs transient mean).
    ("irdrop/currents.py", "irdrop/currents.py"),
    ("irdrop/test_currents.py", "irdrop/test_currents.py"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def localize(path):
    """`C:\\dev\\X` -> `/mnt/c/dev/X` when running under WSL, which is where
    python actually lives on the Windows box. consumers.json records the
    canonical Windows paths; without this, --check-all silently reports every
    consumer MISSING, which is the worst possible failure for a drift gate."""
    if os.path.isdir("/mnt/c") and re.match(r"^[A-Za-z]:[\\/]", path):
        return "/mnt/{}/{}".format(path[0].lower(),
                                   path[3:].replace("\\", "/"))
    return path


def consumers():
    if not os.path.exists(CONSUMERS):
        return []
    with open(CONSUMERS, encoding="utf-8") as fh:
        out = json.load(fh).get("consumers", [])
    for c in out:
        c["path"] = localize(c["path"])
    return out


def vendor(dest):
    n = 0
    for src_rel, dst_rel in FILES:
        src = os.path.join(HERE, src_rel)
        dst = os.path.join(dest, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst) and sha256(dst) == sha256(src):
            print("  same  " + dst_rel)
            continue
        shutil.copyfile(src, dst)
        print("  wrote " + dst_rel)
        n += 1
    return n


def check(dest):
    """[(rel, status)] -- 'ok' | 'DRIFTED' | 'MISSING'."""
    out = []
    for src_rel, dst_rel in FILES:
        src = os.path.join(HERE, src_rel)
        dst = os.path.join(dest, dst_rel)
        if not os.path.exists(dst):
            out.append((dst_rel, "MISSING"))
        elif sha256(dst) != sha256(src):
            out.append((dst_rel, "DRIFTED"))
        else:
            out.append((dst_rel, "ok"))
    return out


def main(argv):
    if "--to" in argv:
        dest = argv[argv.index("--to") + 1]
        print("vendoring into " + dest)
        vendor(dest)
        return 0
    targets = []
    if "--check" in argv:
        targets = [argv[argv.index("--check") + 1]]
    elif "--check-all" in argv:
        targets = [c["path"] for c in consumers()]
    else:
        print(__doc__)
        return 2
    bad = 0
    for dest in targets:
        print(os.path.basename(dest.rstrip("/\\")) + ":")
        for rel, status in check(dest):
            print("  {:9s} {}".format(status, rel))
            bad += status != "ok"
    if bad:
        print("\n{} file(s) drifted or missing -- re-vendor with "
              "`sync.py --to <repo>`; never hand-edit a vendored copy."
              .format(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
