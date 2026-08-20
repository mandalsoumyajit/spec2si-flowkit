#!/usr/bin/env python3
"""Gate for the generated PDF manual: it built, nothing was dropped, nothing lost.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/test_pdf.py`,
hash-gated by that repo's `sync.py --check`.

⭐ THE MISSING-CHARACTER CHECK IS WHY THIS FILE EXISTS. XeLaTeX does not fail
when the font lacks a glyph -- it writes `Missing character: There is no X in
font ...` to the log and carries on, leaving a hole in the page. In this
corpus that is not cosmetic: ⛔ ⚠ ⭐ ✅ ❌ are STRUCTURAL, and a dropped ⛔
turns a prohibition into a plain statement. Measured over the 114 non-ASCII
characters the curated documents use, DejaVu Sans covers all but five, and
those five are mapped to macros -- so the correct number here is ZERO, and
anything else is a regression.

⚠ NEGATIVE CONTROL, because a gate that has never fired is a hypothesis:
`--self-test` builds a one-line document in a font known to lack a glyph and
asserts that this checker reports it. Cambria has no ⛔; if the probe comes
back clean, the detector is broken, not the manual.

  python3 test_pdf.py <manual-dir>
  python3 test_pdf.py --self-test
"""
import io
import os
import re
import shutil
import subprocess
import sys

MISSING = re.compile(r"Missing character: There is no (.) in font ([^!]*)")
ERROR = re.compile(r"^! (.*)$", re.M)


def read_log(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def audit(logtext):
    """-> (missing chars, hard errors)."""
    miss = {}
    for ch, font in MISSING.findall(logtext):
        miss.setdefault(ch, font.strip()[:40])
    errs = [e.strip() for e in ERROR.findall(logtext) if e.strip()]
    return miss, errs


def pages(logtext):
    """The page count XeLaTeX reports, or 0."""
    m = re.search(r"Output written on .*?\((\d+) pages?", logtext)
    return int(m.group(1)) if m else 0


def self_test():
    """Prove the detector fires. Cambria has no ⛔."""
    xelatex = shutil.which("xelatex")
    if not xelatex:
        print("self-test: xelatex not installed -- cannot run")
        return 2
    import tempfile
    d = tempfile.mkdtemp(prefix="pdfgate_")
    try:
        tex = os.path.join(d, "neg.tex")
        bs = chr(92)
        io.open(tex, "w", encoding="utf-8").write(chr(10).join([
            bs + "documentclass{article}",
            bs + "usepackage{fontspec}",
            bs + "setmainfont{Cambria}",
            bs + "begin{document}",
            "negative control ⛔",
            bs + "end{document}", ""]))
        subprocess.call([xelatex, "-interaction=nonstopmode", "neg.tex"],
                        cwd=d, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        log = os.path.join(d, "neg.log")
        if not os.path.exists(log):
            print("self-test: FAIL -- the probe did not build")
            return 1
        miss, _errs = audit(read_log(log))
        if "⛔" in miss:
            print("self-test: PASS -- the detector reports a dropped glyph")
            return 0
        print("self-test: FAIL -- Cambria has no U+26D4 and the checker "
              "did not notice. The gate is broken, not the manual.")
        return 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv):
    if "--self-test" in argv:
        return self_test()
    d = argv[0] if argv else "docs/manual"
    tex = os.path.join(d, "manual.tex")
    log = os.path.join(d, "manual.log")
    pdf = os.path.join(d, "manual.pdf")
    if not os.path.exists(log):
        print("no build log at %s -- run `python3 docs/gen.py pdf` first" % log)
        return 2
    text = read_log(log)
    miss, errs = audit(text)
    npages = pages(text)

    for ch, font in sorted(miss.items()):
        print("MISSING GLYPH  %r (U+%04X) has no glyph in %s"
              % (ch, ord(ch), font))
    for e in errs[:10]:
        print("LATEX ERROR    %s" % e)
    if not os.path.exists(pdf):
        print("NO PDF         the build produced no %s" % pdf)
    small = npages and npages < 20
    if small:
        print("SUSPICIOUS     only %d page(s) from %.1f MB of LaTeX"
              % (npages, os.path.getsize(tex) / 1e6
                 if os.path.exists(tex) else 0))
    ok = not (miss or errs or small) and os.path.exists(pdf)
    print("pdf check: %s — %d page(s), %d missing glyph(s), %d error(s)"
          % ("PASS" if ok else "FAIL", npages, len(miss), len(errs)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
