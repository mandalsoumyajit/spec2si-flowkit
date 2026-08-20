#!/usr/bin/env python3
"""LaTeX emitter for the shared Markdown parser: backend three.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/texrender.py`,
hash-gated by that repo's `sync.py --check`. Edit it THERE, never here.

This brings NO parser of its own. It plugs into `mdrender.render(..., emit=)`
and implements the same handful of methods `HtmlEmitter` does, so the PDF and
the web manual are two renderings of ONE parse. A second Markdown grammar
here would diverge from the other the first time either learned something --
which is the whole argument that put the model in the flowkit to begin with.

⚠ XeLaTeX, NOT pdfLaTeX. The docstrings use ⛔, ⚠ and ⭐ as STRUCTURAL
markers -- they are how a warning is distinguished from a note -- and the
prose carries µ, Ω, →, ≈, ×, ° throughout. pdfLaTeX cannot set them at all.
XeLaTeX can, given a font with coverage, and `test_pdf.py` reads the build
log for `Missing character` so that a glyph the font lacks FAILS rather than
vanishing silently. A dropped ⛔ turns a prohibition into a statement.

⚠ ONLY BASE AND STANDARD PACKAGES. No fvextra, no listings, no minted: code
blocks are hard-wrapped here and set in plain `verbatim`, and tables are
`longtable` with computed `p{}` columns. A manual whose build needs a
package the machine has to fetch is a manual that does not build.
"""
import re

import mdrender

#: LaTeX's own specials. Backslash must go first or it re-escapes the others.
_ESC_MAP = {chr(92): r"\textbackslash{}", "{": r"\{",
            "}": r"\}", "&": r"\&", "%": r"\%",
            "$": r"\$", "#": r"\#", "_": r"\_",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}"}
_ESC_RE = re.compile("[" + re.escape("".join(_ESC_MAP)) + "]")

#: ⭐ The three structural markers get MACROS rather than raw glyphs, so the
#: manual keeps their meaning even in a font that renders them poorly. The
#: macros are defined in the preamble the backend emits.
#: The structural markers, mapped rather than set as glyphs. The first
#: three because their MEANING must survive any font; the last five
#: because DejaVu Sans -- measured, the best coverage of the 114
#: non-ASCII characters this corpus uses -- lacks exactly these, and a
#: dropped tick mark silently turns a PASS into nothing at all.
_MARKS = {"⛔": r"\stopmark{}", "⚠": r"\warnmark{}",
          "⭐": r"\starmark{}",
          "✅": r"\okmark{}", "❌": r"\failmark{}",
          "⏸": r"\pausemark{}", "⏭": r"\nextmark{}",
          "📊": r"\chartmark{}",
          "️": "", "\ufe0f": ""}

_CODE_WRAP = 88          # hard wrap for verbatim, so no package is needed


#: ⛔ CHARACTERS THE *MONO* FACE LACKS. Probing the main font was not
#: enough: code spans are set in DejaVu Sans Mono, which has no ∥,
#: ≪, ≫, ① or ② -- and `≫` inside backticks is ordinary
#: prose here. XeLaTeX drops a missing glyph SILENTLY, so `test_pdf.py`
#: caught this only because it reads the log. These map to math-mode or
#: base-LaTeX constructs, which do not depend on either face.
_FALLBACKS = {
    "∥": r"\ensuremath{\\parallel}",
    "≪": r"\ensuremath{\\ll}",
    "≫": r"\ensuremath{\\gg}",
    "①": r"\textcircled{\\scriptsize 1}",
    "②": r"\textcircled{\\scriptsize 2}",
}


def esc(s):
    """Text -> LaTeX, specials escaped and structural marks mapped.

    ⛔ ONE PASS, NOT A CHAIN OF REPLACES. Substituting sequentially means a
    later rule rewrites what an earlier one just inserted: backslash has to
    go first, and then the brace rule escaped the braces of the
    `\\textbackslash{}` it had produced, yielding `\\textbackslash\\{\\}` --
    literal junk in the page. Mapping each character exactly once is the
    only ordering that has no such interaction.
    """
    s = _ESC_RE.sub(lambda m: _ESC_MAP[m.group(0)], s)
    for a, b in _MARKS.items():
        s = s.replace(a, b)
    for a, b in _FALLBACKS.items():
        s = s.replace(a, b)
    return s


def _wrap(line, width=_CODE_WRAP):
    """Hard-wrap one verbatim line; `verbatim` will not do it for us."""
    out = []
    while len(line) > width:
        cut = line.rfind(" ", 0, width)
        if cut < width // 2:
            cut = width
        out.append(line[:cut])
        line = line[cut:].lstrip() if line[cut:cut + 1] == " " else line[cut:]
    out.append(line)
    return out


class LatexEmitter(mdrender.HtmlEmitter):
    """Emit LaTeX for `mdrender.render`.

    `top` is the sectioning level a level-1 heading maps to: 0 chapter,
    1 section, 2 subsection. The backend sets it per document so a doc
    embedded as a chapter does not open a second part.
    """

    LEVELS = ["chapter", "section", "subsection", "subsubsection",
              "paragraph", "subparagraph", "subparagraph"]

    def __init__(self, top=1, label_prefix=""):
        self.top = top
        self.prefix = label_prefix
        self.in_quote = 0

    # -- blocks --------------------------------------------------------

    def heading(self, level, text, anchor):
        cmd = self.LEVELS[min(len(self.LEVELS) - 1, self.top + level - 1)]
        body = self.inline(text)
        star = "*" if cmd in ("paragraph", "subparagraph") else ""
        lab = ""
        if anchor and not star:
            lab = r"\label{%s%s}" % (self.prefix, anchor)
        return "%s\\%s%s{%s}%s%s" % (chr(10), cmd, star, body, lab, chr(10))

    def para(self, text):
        return chr(10) + self.inline(text) + chr(10)

    def code(self, body, lang):
        lines = []
        for ln in body.split(chr(10)):
            lines.extend(_wrap(ln.replace(chr(9), "    ")))
        # `verbatim` ends at the first \end{verbatim}; nothing else can
        # close it, so the only unsafe content is that literal string.
        safe = [l.replace(r"\end{verbatim}", r"\end {verbatim}")
                for l in lines]
        return ("%s{\\footnotesize\\begin{verbatim}%s%s%s\\end{verbatim}}%s"
                % (chr(10), chr(10), chr(10).join(safe), chr(10), chr(10)))

    def rule(self):
        return chr(10) + r"\vspace{2pt}\hrule\vspace{6pt}" + chr(10)

    def table(self, head, rows, aligns):
        """Markdown table -> longtable, so it wraps AND paginates.

        ⚠ Column widths are computed from the measured content, not split
        evenly: these tables run to five and six columns where one holds a
        sentence and the others hold a number, and an even split makes the
        prose column unreadable while the numbers float in white space.
        """
        n = max([len(head)] + [len(r) for r in rows]) or 1
        head = head + [""] * (n - len(head))
        width = []
        for k in range(n):
            cells = [head[k]] + [r[k] for r in rows if k < len(r)]
            width.append(max(4, sum(len(c) for c in cells)
                             / float(max(1, len(cells)))))
        total = sum(width) or 1.0
        # keep every column at least 6% of the line so nothing collapses
        frac = [max(0.06, w / total) for w in width]
        scale = 0.94 / sum(frac)
        spec = "".join(">{\\raggedright\\arraybackslash}p{%.3f\\linewidth}"
                       % (f * scale) for f in frac)
        L = [chr(10), r"{\small\begin{longtable}{%s}" % spec, chr(10),
             r"\hline" + chr(10)]
        L.append(" & ".join(r"\textbf{%s}" % self.inline(c)
                            for c in head))
        L.append(r" \\ \hline" + chr(10) + r"\endhead" + chr(10))
        for r in rows:
            r = r + [""] * (n - len(r))
            cells = [self.inline(c) for c in r]
            cells[0] = _nobracket(cells[0])
            L.append(" & ".join(cells))
            L.append(r" \\" + chr(10))
        L.append(r"\hline" + chr(10) + r"\end{longtable}}" + chr(10))
        return "".join(L)

    def quote(self, inner):
        # A longtable cannot live inside `quote`; when the quoted block
        # carries one, indent with a plain list instead of an environment
        # that would break the table's page handling.
        if r"\begin{longtable}" in inner:
            return (chr(10) + r"\begingroup\leftskip=1.2em\relax" + chr(10)
                    + inner + chr(10) + r"\endgroup" + chr(10))
        return chr(10) + r"\begin{quote}" + inner + r"\end{quote}" + chr(10)

    def raw(self, line):
        """Raw HTML has no meaning in print. Keep any TEXT it wraps."""
        txt = re.sub(r"<[^>]+>", "", line).strip()
        return (chr(10) + self.inline(txt) + chr(10)) if txt else ""

    def list_open(self, ordered):
        return (chr(10) + r"\begin{%s}[leftmargin=1.4em,itemsep=1pt,"
                r"topsep=3pt,parsep=0pt]" % ("enumerate" if ordered
                                             else "itemize") + chr(10))

    def list_close(self, ordered):
        return (chr(10) + r"\end{%s}" % ("enumerate" if ordered else "itemize")
                + chr(10))

    def item_open(self, text):
        return r"\item " + _nobracket(self.inline(text))

    def item_more(self, text):
        return " " + self.inline(text)

    def item_close(self):
        return chr(10)

    def join(self, parts):
        return "".join(parts)

    # -- inline --------------------------------------------------------

    def inline(self, s):
        """⚠ SAME ORDERING RULE AS THE HTML EMITTER, for the same reason:
        code spans come out FIRST and go back LAST, so `**kwargs` and
        `a_b` inside backticks are never seen by the emphasis rules -- and
        so their LaTeX specials are escaped exactly once."""
        spans = []

        def stash(m):
            spans.append(m.group(2))
            return "\x00%d\x00" % (len(spans) - 1)

        s = re.sub(r"(`+)(.+?)\1", stash, s, flags=re.DOTALL)
        s = esc(s)
        s = mdrender._LINK.sub(
            lambda m: "" if m.group(1) else
            r"\href{%s}{%s}" % (m.group(3).replace("%", r"\%"), m.group(2))
            if m.group(3).startswith(("http://", "https://"))
            else m.group(2), s)
        s = mdrender._BOLD.sub(
            lambda m: m.group(0) if _unbalanced(m.group(1))
            else r"\textbf{%s}" % m.group(1), s)
        s = mdrender._ITAL.sub(
            lambda m: m.group(0) if _unbalanced(m.group(1))
            else r"\emph{%s}" % m.group(1), s)
        for i, code in enumerate(spans):
            s = s.replace("\x00%d\x00" % i,
                          r"\texttt{\small %s}" % _tt(code))
        return s


def _nobracket(s):
    """Protect a cell or item that BEGINS with `[`.

    ⛔ In LaTeX a `[` straight after `\\\\` or `\\item` is read as an
    OPTIONAL ARGUMENT, not as text. A table row whose first cell was
    `[14,-9,7,-5]` -- a perfectly ordinary vector in these documents --
    made XeLaTeX try to parse it as a vertical skip and fail with
    "Illegal unit of measure". An empty group in front settles it.
    """
    return "{}" + s if s.lstrip().startswith("[") else s


def _unbalanced(body):
    """Would emphasising this span break a LaTeX group?

    ⛔ The LaTeX analogue of `mdrender.spans_markup`, and it needs a
    DIFFERENT invariant: there are no angle brackets here to look for,
    because `esc` has already turned every special into a command. What a
    stray pair of asterisks can do instead is straddle part of a
    `\\href{url}{text}` -- taking one brace and not its partner -- and hand
    XeLaTeX an unbalanced group, which fails the build rather than merely
    looking wrong. Emphasis that WHOLLY contains a command is fine and stays.
    """
    return body.count("{") != body.count("}")


def _tt(code):
    """A code span: escaped, and allowed to break inside a long identifier."""
    out = esc(code)
    # let a long path or signature break rather than run into the margin
    for ch in ("/", ".", "\\_", "-"):
        out = out.replace(ch, ch + r"\allowbreak{}")
    return out


def render(text, top=1, prefix=""):
    """Markdown -> (latex, headings), through the shared parser."""
    return mdrender.render(text, 0, LatexEmitter(top=top, label_prefix=prefix))
