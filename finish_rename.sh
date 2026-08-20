#!/usr/bin/env bash
# Finish ADR-0001: AIML_ASIC -> spec2si-tsmc65, the last of the four renames.
#
# ⛔ RUN THIS FROM A SHELL THAT IS NOT INSIDE C:\dev\AIML_ASIC, WITH EVERY
#    AGENT SESSION IN THAT REPO CLOSED. That is the whole reason this file
#    exists: Windows refuses to rename a directory that is any live process's
#    current directory, and an agent session rooted there holds exactly such a
#    handle. Measured 2026-08-20 -- `mv`, `cmd ren`, `[IO.Directory]::Move`,
#    PowerShell `Move-Item -Force` AND a WSL `mv` through /mnt/c were all
#    refused while a session was rooted inside.
#
# ⚠ MUST RUN UNDER GIT-BASH, NOT WSL. From a PowerShell prompt, plain `bash`
#   resolves to WSL, which mounts the drive at /mnt/c and has a Linux python
#   that cannot open `C:\dev\...` -- so the embedded python steps would fail
#   halfway through, after the directory had already moved. Invoke it as:
#
#     & "C:\Program Files\Git\bin\bash.exe" /c/dev/spec2si-flowkit/finish_rename.sh
#
# Delete this script once it has run; it is a one-shot, not a tool.
set -euo pipefail

# Fail loudly on the wrong shell rather than plausibly at step 4.
if [ ! -d /c/dev ] && [ -d /mnt/c/dev ]; then
  echo "⛔ This is WSL. The script needs git-bash (it uses /c/... paths and the"
  echo "   Windows python). Re-run from PowerShell as:"
  echo '   & "C:\Program Files\Git\bin\bash.exe" /c/dev/spec2si-flowkit/finish_rename.sh'
  exit 1
fi
[ -d /c/dev ] || { echo "⛔ /c/dev not found -- is this git-bash?"; exit 1; }
python -c "import sys; sys.exit(0 if sys.platform=='win32' else 1)" 2>/dev/null || {
  echo "⛔ \`python\` here is not the Windows interpreter; the path rewrite in"
  echo "   step 4 opens C:\\dev\\... and would fail after the move. Use git-bash."
  exit 1
}

OLD=/c/dev/AIML_ASIC
NEW=/c/dev/spec2si-tsmc65
PROJ=/c/Users/super/.claude/projects
FLOWKIT=/c/dev/spec2si-flowkit

say() { printf '\n=== %s\n' "$1"; }

say "0. preflight"
[ -d "$OLD" ] || { echo "   $OLD is gone -- already renamed?"; exit 1; }
[ -e "$NEW" ] && { echo "   $NEW already exists; refusing to overwrite"; exit 1; }
if [ -n "$(git -C "$OLD" status --porcelain | grep -v 'runlog_stats.json' || true)" ]; then
  echo "   ⚠ uncommitted work in $OLD:"; git -C "$OLD" status --short
  echo "   commit or stash it first, then re-run."; exit 1
fi
echo "   clean, and $NEW is free"

say "0b. who holds the directory open?"
# ⛔ THE ONLY REASON THIS RENAME EVER FAILS. Windows refuses to move a
# directory that is any live process's CURRENT DIRECTORY, and every layer
# reports it uselessly: mv says "Device or resource busy", Move-Item says
# "Access is denied", and Restart Manager says there is no holder at all.
# Name them here, before the move, rather than making the caller guess.
if ! powershell -NoProfile -ExecutionPolicy Bypass \
        -File "$(cygpath -w "$FLOWKIT/holders.ps1")" "C:\\dev\\AIML_ASIC"; then
  echo
  echo "   Refusing to continue: the move would fail and this script would"
  echo "   abort halfway. Close the sessions listed above and re-run."
  exit 1
fi

say "1. rename the repo directory"
mv "$OLD" "$NEW"
echo "   AIML_ASIC -> spec2si-tsmc65"

say "2. rename the Claude project dirs (32 memory files -- keyed by repo path)"
for d in "$PROJ"/C--dev-AIML-ASIC*; do
  [ -e "$d" ] || continue
  b=$(basename "$d")
  mv "$d" "$PROJ/${b/C--dev-AIML-ASIC/C--dev-spec2si-tsmc65}"
  echo "   $b -> ${b/C--dev-AIML-ASIC/C--dev-spec2si-tsmc65}"
done

say "3. repair the worktree -- EXPLICIT new path"
# `git worktree repair` with NO arguments does NOT fix a worktree that moved:
# it reports it `prunable` and changes nothing. Measured on spec2si-tsmc28.
for w in "$NEW"/.claude/worktrees/*/; do
  [ -d "$w" ] || continue
  git -C "$NEW" worktree repair "$(cygpath -m "$w" 2>/dev/null || echo "$w")"
done
git -C "$NEW" worktree list

say "4. rewrite dev-path references (NOT the git remote)"
python - <<'PY'
import os, re, subprocess
REPOS = {"spec2si-tsmc65": r"C:\dev\spec2si-tsmc65",
         "spec2si-tsmc28": r"C:\dev\spec2si-tsmc28",
         "spec2si-xt011":  r"C:\dev\spec2si-xt011",
         "spec2si-flowkit": r"C:\dev\spec2si-flowkit"}
# Anchored on a `dev` path segment so that `mandalsoumyajit/AIML_ASIC.git`
# -- the GitHub remote, which is NOT renamed -- cannot match.
PAT = re.compile(r"(dev[/\\\\]{1,2})AIML_ASIC")
SKIP = {"docs/decisions/0001-process-scoped-repos.md"}   # dated record
for name, root in REPOS.items():
    for r, url in [(root, subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=root, text=True).strip())]:
        assert not PAT.findall(url), "REMOTE WOULD MATCH: " + url
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    n = 0
    for rel in [x for x in raw.decode("utf-8", "replace").split("\0")
                if x and ".claude/worktrees" not in x and x not in SKIP]:
        p = os.path.join(root, rel.replace("/", os.sep))
        try:
            t = open(p, encoding="utf-8", newline="").read()
        except (OSError, UnicodeDecodeError):
            continue
        new = PAT.sub(lambda m: m.group(1) + "spec2si-tsmc65", t)
        if new != t:
            open(p, "w", encoding="utf-8", newline="").write(new)
            n += 1
    print("   %-18s %d file(s)" % (name, n))
PY

say "5. regenerate the API reference (browse/*.py docstrings carry the path)"
(cd "$NEW" && python docs/gen.py build | head -2)

say "6. point the registry at the NEW path -- now that it exists"
python - <<'PY'
import json, io
p = r"C:\dev\spec2si-flowkit\consumers.json"
d = json.load(open(p, encoding="utf-8"))
for c in d["consumers"]:
    if c["path"].endswith("AIML_ASIC"):
        c["path"] = "C:\\dev\\spec2si-tsmc65"
        c["name"] = "spec2si-tsmc65"
d.pop("rename_in_progress", None)
d["renamed"] = ("ADR-0001: all three process ports moved to spec2si-<process> on "
                "2026-08-20, alongside SPEC2SI_FLOWKIT -> spec2si-flowkit. These are "
                "LOCAL paths only; the GitHub repos still carry the old names, so "
                "`git remote -v` disagreeing with this file is EXPECTED, not drift. "
                "Standing rule: record where a repo IS, never where it is going -- an "
                "intended path makes --check-all report MISSING on a healthy repo.")
open(p, "w", encoding="utf-8", newline="\n").write(
    json.dumps(d, indent=1, ensure_ascii=False) + "\n")
print("   consumers.json -> spec2si-tsmc65")
PY

say "7. gates"
(cd "$FLOWKIT" && python sync.py --check-all | tail -2)
(cd "$NEW" && python docs/gen.py check | tail -1)
for p in "$NEW" /c/dev/spec2si-tsmc28 /c/dev/spec2si-xt011; do
  printf '   conformance %-16s ' "$(basename "$p")"
  (cd "$p" && python -B policy/test_policy_conformance.py | tail -1)
done

say "8. commit"
MSG='rename: this repo is spec2si-tsmc65 -- local paths follow

Per ADR-0001 in the flowkit: repos are scoped to the PROCESS and named for
it. Last of the four. LOCAL PATHS ONLY -- the GitHub repo is still AIML_ASIC
and the remote is untouched; the rewrite anchors on a `dev` path segment so
the remote cannot match, asserted before applying.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'
(cd "$NEW" && git add -A && git commit -m "$MSG")
for p in /c/dev/spec2si-tsmc28 /c/dev/spec2si-xt011; do
  (cd "$p" && git add -A && git diff --cached --quiet || \
     git -C "$p" commit -m "docs: follow AIML_ASIC to its new path, spec2si-tsmc65

Local paths only -- the GitHub repo is unchanged. Per ADR-0001.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
done
(cd "$FLOWKIT" && git add -A && git commit -m "consumers: all four repos renamed -- the registry is spec2si-* throughout

Last of the ADR-0001 renames. AIML_ASIC -> spec2si-tsmc65, and this lands
AFTER the directory actually moved, which is the ordering the first attempt
got wrong.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")

say "DONE -- all four repos are spec2si-*"
ls -d /c/dev/spec2si-*
