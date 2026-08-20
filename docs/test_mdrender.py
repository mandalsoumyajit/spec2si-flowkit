#!/usr/bin/env python3
"""Tests for the Markdown subset renderer.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's
`docs/test_mdrender.py`, hash-gated by that repo's `sync.py --check`.

Every case here is a shape that actually occurs in these repos, not a
CommonMark conformance item -- and several are shapes that a naive renderer
gets wrong in a way you would not notice until a page was already published:
`**kwargs` inside backticks, a pipe inside a code span in a table cell, a
`-` bullet that looks like a horizontal rule.

  python3 test_mdrender.py       # or: pytest test_mdrender.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdrender                                            # noqa: E402

R = lambda s: mdrender.render(s)[0]                        # noqa: E731


def code_spans_are_not_emphasis():
    """⭐ THE ONE THAT MATTERS. These docs are full of `**kwargs`, `*.gds`
    and `a * b` inside backticks; a renderer that runs emphasis before code
    turns them into bold and eats the asterisks."""
    assert R("`**kwargs`") == "<p><code>**kwargs</code></p>"
    assert R("`*.gds`") == "<p><code>*.gds</code></p>"
    assert "<strong>" not in R("use `a ** b` here")
    assert R("**real** and `**not**`") == (
        "<p><strong>real</strong> and <code>**not**</code></p>")


def code_spans_are_escaped_not_interpreted():
    assert R("`<lef>`") == "<p><code>&lt;lef&gt;</code></p>"
    assert R("`a && b`") == "<p><code>a &amp;&amp; b</code></p>"


def html_is_escaped_outside_code():
    assert "&lt;script&gt;" in R("a <script> tag")


def headings_get_stable_anchors():
    html, heads = mdrender.render("# The Flow\n\n## The Flow\n")
    assert 'id="the-flow"' in html
    assert 'id="the-flow-1"' in html, "duplicate anchors must not collide"
    assert [h[1] for h in heads] == ["The Flow", "The Flow"]


def heading_shift_demotes():
    html, _ = mdrender.render("# Title\n", heading_shift=1)
    assert html.startswith("<h2 ")


def tables_render_with_alignment():
    html = R("| a | b |\n|---|--:|\n| 1 | 2 |\n")
    assert "<table>" in html and "<th>a</th>" in html
    assert 'text-align:right' in html
    assert "<td>1</td>" in html


def a_pipe_inside_a_code_span_is_not_a_cell_break():
    """`a \\| b` in a cell -- an escaped pipe is data, not a separator."""
    html = R("| x | y |\n|---|---|\n| `a \\| b` | z |\n")
    assert html.count("<td") == 2, html


def bullets_are_not_horizontal_rules():
    """`- item` starts with a dash; `---` alone is a rule. A rule test that
    runs first, or is too loose, deletes the list."""
    assert "<ul>" in R("- one\n- two\n")
    assert "<hr>" in R("text\n\n---\n\ntext\n")


def nested_lists_nest():
    html = R("- a\n  - b\n- c\n")
    assert html.count("<ul>") == 2, html
    assert html.count("</ul>") == 2, html


def ordered_lists_render():
    assert "<ol>" in R("1. one\n2. two\n")


def fenced_code_is_verbatim():
    html = R("```bash\npython3 sync.py --check-all\n```\n")
    assert 'class="language-bash"' in html
    assert "python3 sync.py --check-all" in html
    assert "<em>" not in R("```\na * b * c\n```\n")


def text_after_a_fence_survives():
    """⛔ THE ONE A CONTENT-BLIND CHECK CANNOT SEE. The first version built
    its closing-fence pattern as `fmt % c * n`, which binds as `(fmt % c)
    * n` -- so no closing fence ever matched and every fenced block ate the
    REST OF THE DOCUMENT. The HTML stayed perfectly well-formed (one big
    <pre>), so tag-balance and link checks both passed on truncated pages.
    Assert the content after the fence, not the fence itself."""
    out = R("intro" + chr(10)*2 + "```" + chr(10) + "code" + chr(10)
            + "```" + chr(10)*2 + "AFTERWARDS" + chr(10))
    assert "<p>AFTERWARDS</p>" in out, out
    assert out.count("<pre>") == 1, out


def a_longer_closing_fence_still_closes():
    out = R("```" + chr(10) + "x" + chr(10) + "````" + chr(10)*2 + "AFTER" + chr(10))
    assert "<p>AFTER</p>" in out, out


def blockquotes_render_and_keep_their_markup():
    html = R("> **note** and `code`\n")
    assert "<blockquote>" in html and "<strong>note</strong>" in html


def underscores_are_never_emphasis():
    """⛔ MEASURED, NOT PREFERRED: 14,332 `*italic*` vs 23 `_italic_` in the
    corpus, and the 23 were almost all false positives. The LaTeX in these
    docs made underscore emphasis open a span in one place and close it in
    another -- interleaving with a <strong> and producing invalid HTML."""
    assert "<em>" not in R("$D_\text{max}$ sizes the buffers")
    assert "<em>" not in R("the _pycache_ directory")
    assert "<em>" not in R("window_len and D_max")
    assert "<em>real</em>" in R("this is *real* emphasis")


def links_and_images():
    assert R("[a](b.md)") == '<p><a href="b.md">a</a></p>'
    assert '<img src="x.svg" alt="d">' in R("![d](x.svg)")


def a_placeholder_is_not_an_html_tag():
    """⭐ These docstrings are full of `<cell>`, `<flowdir>`, `<asic_tools>`
    at the start of a line. Passing any `<word` through as raw markup left
    six API pages with unclosed elements -- broken structure that no gate on
    the Markdown side can see, because the Markdown itself is fine."""
    for ph in ("<cell>", "<flowdir>", "<asic_tools>", "<repo>"):
        out = R(ph + " is a placeholder")
        assert ph.replace("<", "&lt;").replace(">", "&gt;") in out, out
        assert ph not in out, out


def raw_html_passes_through():
    assert '<p align="center">' in R('<p align="center">\n')


def the_house_glyphs_survive():
    """⛔ ⚠ ⭐ are STRUCTURAL markers in these docs. If the renderer or its
    IO mangles them the pages lose their emphasis system entirely."""
    for g in ("⛔", "⚠", "⭐"):
        assert g in R("%s a warning\n" % g)


def strip_markup_is_plain_text():
    assert mdrender.strip_markup("**a** `b` [c](d)") == "a b c"


def unknown_syntax_degrades_to_text():
    """Anything outside the grammar must come out as escaped text, never as
    half-applied markup."""
    out = R("a ~~strike~~ b\n")
    assert "~~strike~~" in out and "<del>" not in out


def main():
    tests = [v for k, v in sorted(globals().items())
             if callable(v) and not k.startswith("_") and k != "main"
             and getattr(v, "__module__", None) == "__main__"
             and k not in ("R",)]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
