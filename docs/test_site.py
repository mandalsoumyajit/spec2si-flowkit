#!/usr/bin/env python3
"""Gate for the generated web manual: structure, links, and content survival.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/test_site.py`,
hash-gated by that repo's `sync.py --check`.

⭐ WHY THIS EXISTS. Every defect found while building the first site was
INVISIBLE to the checks that already existed. The Markdown gate passed --
the Markdown was fine. The generated HTML was well-formed. The pages simply
said the wrong thing:

  * a precedence bug (`fmt % c * n` binds as `(fmt % c) * n`) meant no
    closing fence ever matched, so EVERY fenced block swallowed the rest of
    its document. The output was one big well-formed `<pre>`; tag-balance
    and link checks both passed on truncated pages. Only a CONTENT check
    could see it -- 0.5 MB of prose was missing across the site.
  * `<cell>` and `<asic_tools>`, placeholder tokens at the start of a line,
    were passed through as raw HTML and left six pages structurally broken.
  * underscore emphasis fired inside `$D_\\text{max}$` and interleaved an
    `<em>` across a `<strong>`.
  * 341 links pointed at repository files that are not pages of the site.

So this asserts three separate things, because each of the three failures
above was invisible to the other two:

  STRUCTURE  every page parses with a balanced tag stack
  LINKS      every internal href resolves to a file that exists
  CONTENT    the rendered text still contains what the source said

⚠ The CONTENT check is the one that matters most and is the easiest to
leave out. Run it against the corpus, not a fixture: a fixture proves the
renderer handles what you thought of.

  python3 test_site.py <site-dir> <repo-root>
"""
import io
import os
import sys
from html.parser import HTMLParser

VOID = frozenset(("area base br col embed hr img input link meta param "
                  "source track wbr").split())


class _Balance(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.stack = []
        self.bad = []
        self.hrefs = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)
        d = dict(attrs)
        if d.get("href"):
            self.hrefs.append(d["href"])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.bad.append("unclosed <%s>" % self.stack.pop())
            if self.stack:
                self.stack.pop()
        else:
            self.bad.append("stray </%s>" % tag)

    def handle_data(self, data):
        self.text.append(data)


def pages(site):
    for dp, _dns, fns in os.walk(site):
        for fn in sorted(fns):
            if fn.endswith(".html"):
                yield os.path.join(dp, fn)


def audit(site):
    """-> (n_pages, structure problems, dead links, sentinel leaks)."""
    bad, dead, sentinel, n, links = [], [], [], 0, 0
    for p in pages(site):
        n += 1
        src = io.open(p, encoding="utf-8").read()
        if "\x00" in src:
            sentinel.append(p)
        b = _Balance()
        b.feed(src)
        b.close()
        if b.stack:
            b.bad.append("unclosed at EOF: %s" % b.stack[:4])
        if b.bad:
            bad.append((os.path.relpath(p, site), b.bad[:4]))
        for h in b.hrefs:
            if h.startswith(("http://", "https://", "mailto:", "#")):
                continue
            links += 1
            tgt = os.path.normpath(
                os.path.join(os.path.dirname(p), h.split("#")[0]))
            if not os.path.exists(tgt):
                dead.append((os.path.relpath(p, site), h))
    return n, links, bad, dead, sentinel


def content_survives(site, model, sample=40):
    """⭐ THE CHECK THE OTHERS CANNOT SUBSTITUTE FOR.

    For a sample of docs, assert that the LAST substantial line of the
    source still appears in the rendered page. That is exactly what the
    unterminated-fence bug destroyed, and it is why a structure check alone
    is not enough: a truncated page is perfectly well-formed.

    ⚠ BOTH SIDES ARE NORMALISED, and the first version was not -- it kept
    the source's `3. ` list marker and its backticks, neither of which
    survives rendering, and reported 21 pages truncated that were entirely
    intact. A gate that cries wolf gets muted, so it compares plain words to
    plain words.
    """
    import re
    import mdrender
    missing = []
    docs = list(model.iter_docs())
    step = max(1, len(docs) // sample)
    for p, _meta, body in docs[::step]:
        rel = model.rel(p)
        out = os.path.join(site, "doc", rel[:-3].replace("/", os.sep) + ".html")
        if not os.path.exists(out):
            missing.append((rel, "no page"))
            continue
        b = _Balance()
        b.feed(io.open(out, encoding="utf-8").read())
        b.close()
        text = _bare("".join(b.text))
        cand = []
        for ln in body.split(chr(10)):
            s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln.strip())
            s = _words(mdrender.strip_markup(s))
            if len(s.split()) >= 7 and not s.startswith(("|", ">")):
                cand.append(s)
        if not cand:
            continue
        probe = _bare(" ".join(cand[-1].split()[-8:]))
        if probe not in text:
            missing.append((rel, probe[:60]))
    return missing


def _words(s):
    """Plain comparable text: markup gone, whitespace collapsed."""
    import re
    return re.sub(r"\s+", " ", s.replace(chr(160), " ")).strip()


def _bare(s):
    """Whitespace-FREE comparable text.

    ⚠ Whitespace cannot be compared across this boundary at all. `<code>`
    inside a sentence puts word breaks where the source has none, and block
    tags put none where the source has a line break -- comparing on spaces
    reported six intact pages as truncated. Dropping whitespace entirely
    compares the only thing that is actually invariant: the characters.
    """
    import re
    return re.sub(r"\s+", "", s.replace(chr(160), ""))


def main(argv):
    site = argv[0] if argv else "docs/site"
    root = argv[1] if len(argv) > 1 else os.getcwd()
    if not os.path.isdir(site):
        print("no site at %s -- run `python3 docs/gen.py html` first" % site)
        return 2
    n, links, bad, dead, sentinel = audit(site)

    sys.path.insert(0, os.path.join(root, "docs"))
    import gen                                             # the repo's own
    missing = content_survives(site, gen.MODEL)

    for rel, why in bad:
        print("STRUCTURE  %s: %s" % (rel, why))
    for rel, h in dead[:20]:
        print("DEAD LINK  %s -> %s" % (rel, h))
    for p in sentinel:
        print("SENTINEL   %s" % p)
    for rel, probe in missing:
        print("TRUNCATED  %s: tail missing from the page -- %r" % (rel, probe))
    ok = not (bad or dead or sentinel or missing)
    print("site check: %s — %d page(s), %d internal link(s), "
          "%d structure, %d dead, %d truncated"
          % ("PASS" if ok else "FAIL", n, links, len(bad), len(dead),
             len(missing)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
