#!/usr/bin/env python3
"""Markdown -> HTML for the documentation subset these repos actually use.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/mdrender.py`,
hash-gated by that repo's `sync.py --check`. Edit it THERE, never here.

⭐ WHY THIS EXISTS RATHER THAN A DEPENDENCY. The freshness gate is
stdlib-only on purpose: it runs in CI with no PDK, no vendor licence and no
dependency install, and the cluster runs raw system python at a 3.6.8 floor
with no pip at all. A Markdown library would either break that or split the
toolchain in two. So this renders the SUBSET, measured rather than guessed --
across the 176 tracked docs of the reference port:

    inline code 17,003   bold 13,432   table rows 5,971   blockquote 5,561
    ul 2,444   headings 2,441   italic 1,550   links 1,097   ol 1,087
    fences 707   hr 254   raw HTML 26   images 2

That is a bounded grammar, and the house style keeps it bounded: these are
generated pages and hand docs written to one convention, not arbitrary
internet Markdown. It is NOT CommonMark and does not try to be. Anything
outside the grammar passes through escaped rather than being silently
mangled, which is the failure mode that matters -- a doc that renders wrong
is worse than one that renders plainly.

⚠ INLINE CODE IS TOKENISED FIRST, and that ordering is load-bearing. These
docs are full of things like `**kwargs`, `*.gds` and `a | b` INSIDE
backticks; emphasis or table parsing applied first would eat them. Spans are
lifted out, the rest is escaped and marked up, and the spans are put back
last -- so a backtick span is never interpreted as anything but text.
"""
import re

__all__ = ["render", "inline", "slug", "escape"]

_ESC = ((chr(38), "&amp;"), ("<", "&lt;"), (">", "&gt;"))
_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+-]*)\s*$")
_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_TROW = re.compile(r"^\s*\|.*$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
#: ⚠ A LINE STARTING WITH `<` IS USUALLY NOT HTML IN THESE DOCS. The
#: docstrings are full of placeholder tokens -- `<cell>`, `<flowdir>`,
#: `<asic_tools>`, `<repo>` -- written at the start of a line. Passing any
#: `<word` through as raw markup produced six pages with unclosed <cell> and
#: <asic_tools> elements, i.e. structurally broken HTML that no gate on the
#: Markdown side could ever see. So the passthrough is a WHITELIST of tags
#: that actually appear, and everything else is text.
_HTML_TAGS = frozenset((
    "p div span img br hr a b i em strong code pre blockquote center figure "
    "figcaption details summary sub sup small kbd table thead tbody tr td th "
    "ul ol li dl dt dd h1 h2 h3 h4 h5 h6 picture source video audio").split())
_HTML = re.compile(r"^\s*<(/?)([A-Za-z][A-Za-z0-9]*)")
_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BOLD = re.compile(r"\*\*(\S(?:[^*]*\S)?)\*\*")
#: ⛔ `_` IS NOT AN EMPHASIS DELIMITER HERE, and that is a measurement, not
#: a preference. Across the corpus: 14,332 `*italic*` against 23 `_italic_`,
#: and of those 23 all but a few were false positives -- `_pycache_`,
#: `<instance>/<device>`, `loop.log`. Worse, the LaTeX in these docs
#: (`$	ext{window\_len}$`, `$D_	ext{max}$`) made underscore emphasis open
#: a span in one place and close it in another, INTERLEAVING with a <strong>
#: and producing structurally invalid HTML. Underscore emphasis costs
#: correctness and buys nothing this corpus uses.
_ITAL = re.compile(r"(?<![*\w])\*(\S(?:[^*]*\S)?)\*(?!\*)")
_SLUG_BAD = re.compile(r"[^a-z0-9\s-]")


def escape(s):
    for a, b in _ESC:
        s = s.replace(a, b)
    return s


def slug(text):
    """A heading's anchor id: lowercase, punctuation dropped, spaces to '-'.

    Matches GitHub closely enough that intra-repo `#anchor` links written
    against GitHub's rendering keep working in the generated site."""
    t = _SLUG_BAD.sub("", strip_markup(text).lower()).strip()
    return re.sub(r"\s+", "-", t)


def strip_markup(s):
    """The plain text of an inline span -- for anchors, titles and the PDF."""
    s = _LINK.sub(lambda m: m.group(2), s)
    s = s.replace("`", "")
    s = _BOLD.sub(lambda m: m.group(1), s)
    s = _ITAL.sub(lambda m: m.group(1), s)
    return s


def inline(s):
    """Inline markup -> HTML.

    ⚠ Order is the whole correctness argument here: code spans come out
    FIRST and go back LAST, so `**kwargs` and `*.gds` inside backticks are
    never seen by the emphasis rules.
    """
    spans = []

    def _stash(m):
        spans.append(m.group(2))
        return "\x00%d\x00" % (len(spans) - 1)

    s = re.sub(r"(`+)(.+?)\1", _stash, s, flags=re.DOTALL)
    s = escape(s)
    s = _LINK.sub(
        lambda m: ('<img src="%s" alt="%s">' % (m.group(3), m.group(2)))
        if m.group(1) else
        ('<a href="%s">%s</a>' % (m.group(3), m.group(2))), s)
    s = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group(1), s)
    s = _ITAL.sub(lambda m: "<em>%s</em>" % m.group(1), s)
    for i, code in enumerate(spans):
        s = s.replace("\x00%d\x00" % i, "<code>%s</code>" % escape(code))
    return s


def _cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    # a `\|` is an escaped pipe inside a cell, not a separator
    parts, cur, esc = [], [], False
    for ch in row:
        if esc:
            cur.append(ch if ch == "|" else "\\" + ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _aligns(sep):
    out = []
    for c in _cells(sep):
        left, right = c.startswith(":"), c.endswith(":")
        out.append("center" if left and right else
                   "right" if right else "left" if left else "")
    return out


def _lazy_ok(ln):
    """May this unmarked line continue the blockquote above it?

    ⚠ ONLY IF IT STARTS NOTHING ELSE. The first version continued on any
    non-blank, non-heading line, which swallowed the `</details>` that closed
    a raw-HTML block begun before the quote -- the tag was re-emitted INSIDE
    the blockquote and the page came out with an unclosed <details> and a
    stray </details>. A lazy continuation is a paragraph line and nothing
    more, so every other block opener ends the quote.
    """
    s = ln.strip()
    if not s:
        return False
    if _ATX.match(ln) or _HR.match(ln) or _FENCE.match(ln):
        return False
    if _UL.match(ln) or _OL.match(ln) or _TROW.match(ln):
        return False
    m = _HTML.match(ln)
    if m and m.group(2).lower() in _HTML_TAGS:
        return False
    return True


class _Out(object):
    def __init__(self):
        self.parts = []
        self.heads = []            # (level, text, anchor) for a page TOC

    def __call__(self, s):
        self.parts.append(s)


def render(text, heading_shift=0):
    """Markdown -> (html, headings). `headings` is [(level, text, anchor)].

    `heading_shift` demotes every heading by N levels, so a document can be
    embedded under a page title without two `<h1>`s fighting.
    """
    o = _Out()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    para = []
    seen = {}

    def flush():
        if para:
            o("<p>%s</p>" % inline(" ".join(para).strip()))
            del para[:]

    while i < n:
        ln = lines[i]

        m = _FENCE.match(ln)
        if m:                                          # fenced code
            flush()
            close, lang = m.group(1), m.group(2)
            # ⛔ PARENTHESES ARE LOAD-BEARING. `"...%s..." % c * n` binds as
            # `("...%s..." % c) * n` -- % and * share precedence and go left
            # to right -- which built the pattern three times over instead of
            # a three-character fence, so NO closing fence ever matched and
            # every fenced block swallowed the rest of its document. The HTML
            # stayed well-formed (one big <pre>), so only a content check
            # could see it. A closing fence may be longer than the opener.
            closer = re.compile(r"^\s*%s{%d,}\s*$"
                                % (re.escape(close[0]), len(close)))
            body = []
            i += 1
            while i < n and not closer.match(lines[i]):
                body.append(lines[i]); i += 1
            i += 1
            cls = ' class="language-%s"' % lang if lang else ""
            o("<pre><code%s>%s</code></pre>" % (cls, escape("\n".join(body))))
            continue

        if not ln.strip():                             # blank
            flush(); i += 1; continue

        m = _ATX.match(ln)
        if m:                                          # heading
            flush()
            lvl = min(6, len(m.group(1)) + heading_shift)
            txt = m.group(2)
            a = slug(txt) or "section"
            if a in seen:                              # GitHub's -1, -2, ...
                seen[a] += 1; a = "%s-%d" % (a, seen[a])
            else:
                seen[a] = 0
            o('<h%d id="%s">%s</h%d>' % (lvl, a, inline(txt), lvl))
            o.heads.append((lvl, strip_markup(txt), a))
            i += 1; continue

        if _HR.match(ln) and not _UL.match(ln):        # rule
            flush(); o("<hr>"); i += 1; continue

        if _TROW.match(ln) and i + 1 < n and _TSEP.match(lines[i + 1]):
            flush()                                    # table
            head = _cells(ln)
            al = _aligns(lines[i + 1])
            i += 2
            o("<table><thead><tr>")
            for k, c in enumerate(head):
                st = ' style="text-align:%s"' % al[k] \
                    if k < len(al) and al[k] else ""
                o("<th%s>%s</th>" % (st, inline(c)))
            o("</tr></thead><tbody>")
            while i < n and _TROW.match(lines[i]):
                o("<tr>")
                for k, c in enumerate(_cells(lines[i])):
                    st = ' style="text-align:%s"' % al[k] \
                        if k < len(al) and al[k] else ""
                    o("<td%s>%s</td>" % (st, inline(c)))
                o("</tr>")
                i += 1
            o("</tbody></table>")
            continue

        if _QUOTE.match(ln):                           # blockquote
            flush()
            body = []
            while i < n and (_QUOTE.match(lines[i])
                             or (body and _lazy_ok(lines[i]))):
                mq = _QUOTE.match(lines[i])
                body.append(mq.group(1) if mq else lines[i])
                i += 1
            sub, subheads = render("\n".join(body), heading_shift)
            o.heads.extend(subheads)
            o("<blockquote>%s</blockquote>" % sub)
            continue

        if _UL.match(ln) or _OL.match(ln):             # list
            flush()
            i = _list(lines, i, o, heading_shift)
            continue

        mh = _HTML.match(ln)
        if mh and mh.group(2).lower() in _HTML_TAGS:   # raw HTML block
            flush()
            o(ln)
            i += 1; continue

        para.append(ln.strip())
        i += 1

    flush()
    return "".join(o.parts), o.heads


def _list(lines, i, o, shift):
    """One list, including nested ones. Returns the index after it."""
    n = len(lines)
    m = _UL.match(lines[i]) or _OL.match(lines[i])
    base = len(m.group(1))
    ordered = bool(_OL.match(lines[i]))
    o("<ol>" if ordered else "<ul>")
    while i < n:
        ln = lines[i]
        if not ln.strip():                             # blank: peek ahead
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_UL.match(lines[j]) or _OL.match(lines[j])) \
                    and len((_UL.match(lines[j]) or
                             _OL.match(lines[j])).group(1)) >= base:
                i = j; continue
            break
        mu, mo = _UL.match(ln), _OL.match(ln)
        if not (mu or mo):
            if len(ln) - len(ln.lstrip()) > base:      # lazy continuation
                o(" " + inline(ln.strip())); i += 1; continue
            break
        ind = len((mu or mo).group(1))
        if ind < base:
            break
        if ind > base:                                 # nested
            i = _list(lines, i, o, shift)
            continue
        o("<li>%s" % inline(mu.group(2) if mu else mo.group(3)))
        i += 1
        # a nested list belongs INSIDE this <li>
        if i < n:
            mn = _UL.match(lines[i]) or _OL.match(lines[i])
            if mn and len(mn.group(1)) > base:
                i = _list(lines, i, o, shift)
        o("</li>")
    o("</ol>" if ordered else "</ul>")
    return i
