#!/usr/bin/env python3
"""Tests for the LaTeX emitter.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's
`docs/test_texrender.py`, hash-gated by that repo's `sync.py --check`.

Every case is a shape that actually broke, or would break, a XeLaTeX build
of this corpus. LaTeX fails LOUDLY on a malformed group and SILENTLY on a
missing glyph, so both halves are covered here: the shapes that stop the
build, and the marks that must never reach the font at all.

  python3 test_texrender.py      # or: pytest test_texrender.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import texrender                                           # noqa: E402

BS = chr(92)
NL = chr(10)
R = lambda s: texrender.render(s)[0]                       # noqa: E731


def latex_specials_are_escaped():
    """The invariant is that no special is left UNESCAPED -- checking that
    the raw character is absent is wrong, since the escape contains it."""
    out = texrender.esc("100% & $5 #1 a_b {x}")
    for ch in ("%", "&", "$", "#", "_", "{", "}"):
        for k, c in enumerate(out):
            if c == ch:
                assert k and out[k - 1] == BS, (ch, k, out)


def a_backslash_does_not_re_escape_the_rest():
    """Backslash must be substituted FIRST or it mangles every escape that
    follows it."""
    out = texrender.esc(BS + "n")
    assert out == BS + "textbackslash{}n", out


def the_structural_marks_become_macros():
    """⛔ These must never reach the font. DejaVu Sans lacks ✅ ❌ ⏸ ⏭ 📊
    outright, and a font that merely renders ⛔ poorly still costs the
    document its meaning -- a dropped prohibition reads as a statement."""
    for glyph, macro in (("⛔", "stopmark"), ("⚠", "warnmark"),
                         ("⭐", "starmark"), ("✅", "okmark"),
                         ("❌", "failmark"), ("⏸", "pausemark"),
                         ("⏭", "nextmark"), ("📊", "chartmark")):
        out = texrender.esc(glyph + " x")
        assert BS + macro in out, (glyph, out)
        assert glyph not in out, (glyph, out)


def a_cell_starting_with_a_bracket_is_protected():
    """⛔ THE ONE THAT FAILED THE FIRST BUILD. In LaTeX a `[` straight after
    `\\\\` is read as the optional argument of the line break, so a row whose
    first cell was `[14,-9,7,-5]` -- an ordinary vector here -- produced
    'Illegal unit of measure' and stopped the run."""
    out = R("| a | b |" + NL + "|---|---|" + NL + "| [14,-9,7,-5] | 7.29 |" + NL)
    assert "{}[14" in out, out


def an_item_starting_with_a_bracket_is_protected():
    out = R("- [a,b] is a pair" + NL)
    assert BS + "item {}[a,b]" in out or "{}[a,b]" in out, out


def code_spans_survive_and_are_escaped_once():
    out = R("use `flow_policy.json` here")
    assert BS + "texttt" in out
    assert BS + "_" in out                     # the underscore is escaped
    assert "__" not in out                     # and not twice


def emphasis_does_not_break_a_group():
    """A stray pair of asterisks either side of a command must not take one
    brace and leave its partner: XeLaTeX fails the build on that."""
    out = R("see *[the doc](http://x/y) and* more")
    assert out.count("{") == out.count("}"), out


def every_rendered_document_has_balanced_braces():
    """The invariant XeLaTeX actually enforces.

    \u26a0 Verbatim is excluded on purpose: inside it a brace is a literal
    character with no grouping meaning, and these docs paste plenty of
    unbalanced fragments into fenced blocks. Counting them would make the
    test fail on correct output -- and a test that cries wolf gets muted."""
    import re
    for src in ("**a** and *b*",
                "| x | y |" + NL + "|---|---|" + NL + "| `a_b` | 1 |",
                "> quoted **bold** text",
                "```" + NL + "raw { unbalanced" + NL + "```",
                "- one" + NL + "- two"):
        out = R(src)
        outside = re.sub(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", "",
                         out, flags=re.DOTALL)
        assert outside.count("{") == outside.count("}"), (src, outside)


def a_fence_becomes_verbatim_and_wraps():
    long = "x" * 200
    out = R("```" + NL + long + NL + "```" + NL)
    assert "verbatim" in out
    assert max(len(l) for l in out.split(NL)) < 120, "verbatim did not wrap"


def marks_inside_a_fence_become_ascii():
    """⛔ VERBATIM IS LITERAL, SO A MACRO CANNOT RENDER THERE. Fenced code
    bypasses esc() by design, so a ✅ or a ≫ inside a fence reached the font
    raw and XeLaTeX dropped it silently. The log gate caught it in another
    port after this emitter had already been called finished here."""
    out = R("```" + NL + "✅ done  ≫ 3  ⛔ stop" + NL + "```" + NL)
    for glyph in ("✅", "≫", "⛔"):
        assert glyph not in out, (glyph, out)
    assert "[OK]" in out and ">>" in out and "[STOP]" in out, out


def a_fallback_emits_one_backslash_not_two():
    """`\\parallel` is a LaTeX line break followed by the word; the
    generator that wrote this table over-escaped it and XeLaTeX answered
    with \"Missing $ inserted\"."""
    out = texrender.esc("a ∥ b")
    assert BS + "ensuremath{" + BS + "parallel}" in out, out
    assert BS + BS not in out, out


def a_table_renders_as_longtable():
    out = R("| a | b |" + NL + "|---|---|" + NL + "| 1 | 2 |" + NL)
    assert BS + "begin{longtable}" in out and BS + "end{longtable}" in out


def headings_map_to_sections():
    out = R("# Top" + NL + NL + "## Sub" + NL)
    assert BS + "section{Top}" in out
    assert BS + "subsection{Sub}" in out


def raw_html_keeps_its_text_and_drops_its_tags():
    out = R('<p align="center">caption here</p>' + NL)
    assert "caption here" in out
    assert "<p" not in out and "align=" not in out


def main():
    tests = [v for k, v in sorted(globals().items())
             if callable(v) and not k.startswith("_") and k != "main"
             and getattr(v, "__module__", None) == "__main__"
             and k != "R"]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
