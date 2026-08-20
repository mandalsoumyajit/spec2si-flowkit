#!/usr/bin/env python3
"""The web-manual backend: a static HTML site, from the same model.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/htmlbackend.py`,
hash-gated by that repo's `sync.py --check`. Edit it THERE, never here.

THE SECOND OF THREE BACKENDS. It renders what `DocModel` parsed and
`mdrender` marked up; it parses nothing of its own. That is the whole reason
the model was split out: a manual generated from the same parse as the
in-repo Markdown cannot drift from the repo, and a hand-written one goes
stale silently -- which is precisely the failure class the policy's
`negative-control` rule exists to catch.

⚠ STDLIB ONLY, AND NO NETWORK. The pages carry their own CSS inline in one
`site.css`; there is no CDN link, no web font and no build step. A manual you
cannot open from a file:// URL on a machine with no internet is not a manual
these audiences can use -- and half of them are reading it precisely because
they cannot run the code.

⚠ THE FULL DOCSTRING IS PUBLISHED HERE, unlike the Markdown backend. That
asymmetry is the point of `module_api` returning bodies whole: the API
reference is eight Markdown pages and `full` would put ~400 K in one of them,
past where GitHub renders at all -- but a paginated web page has no such
limit, and the narrative in these docstrings is most of their value.
"""
import os
import re

import docmodel
import mdrender

CSS = """/* Spec-to-Silicon manual. Light and dark from one palette; the
   idiom -- system fonts, alpha-hex neutrals that work on either ground --
   is browse/'s, so the manual and the live browser read as one system. */
:root{color-scheme:light dark;--ink:#1a1a1f;--bg:#fff;--soft:#f6f6f8;
 --line:#8884;--dim:#6b6b76;--accent:#3b82f6;--warn:#a15c07}
@media(prefers-color-scheme:dark){:root{--ink:#e8e8ef;--bg:#14141a;
 --soft:#1c1c24;--dim:#9a9aa8;--accent:#7aa7f8;--warn:#fbbf24}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{display:flex;align-items:flex-start;max-width:1180px;margin:0 auto}
nav{flex:0 0 250px;position:sticky;top:0;max-height:100vh;overflow-y:auto;
 padding:1.4rem 1rem 3rem;border-right:1px solid var(--line);font-size:13px}
nav h2{font-size:11px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--dim);margin:1.3rem 0 .4rem}
nav a{display:block;padding:.13rem 0;color:inherit;text-decoration:none}
nav a:hover{color:var(--accent);text-decoration:underline}
nav a.here{color:var(--accent);font-weight:600}
main{flex:1 1 auto;min-width:0;padding:1.4rem 2rem 5rem}
h1,h2,h3,h4,h5,h6{line-height:1.25;margin:1.8em 0 .5em;text-wrap:balance}
h1{font-size:1.9rem;margin-top:.3em}h2{font-size:1.35rem;
 border-bottom:1px solid var(--line);padding-bottom:.25rem}
h3{font-size:1.1rem}h4,h5,h6{font-size:1rem}
p,li{overflow-wrap:break-word}
a{color:var(--accent)}
code{font:.87em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 background:var(--soft);border:1px solid var(--line);border-radius:3px;
 padding:.06em .3em}
pre{background:var(--soft);border:1px solid var(--line);border-radius:5px;
 padding:.7rem .9rem;overflow-x:auto}
pre code{background:none;border:0;padding:0;font-size:.85em;line-height:1.5}
blockquote{margin:1em 0;padding:.1rem 1rem;border-left:3px solid var(--line);
 color:var(--dim)}
blockquote strong,blockquote code{color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:.93em;margin:1em 0}
th,td{border:1px solid var(--line);padding:.35rem .55rem;
 text-align:left;vertical-align:top}
th{background:var(--soft);font-size:.85em;letter-spacing:.03em}
.scroll{overflow-x:auto}
hr{border:0;border-top:1px solid var(--line);margin:2em 0}
img{max-width:100%;height:auto}
.meta{font-size:12px;color:var(--dim);margin:.2rem 0 1.4rem;
 padding-bottom:.9rem;border-bottom:1px solid var(--line)}
.meta b{color:var(--ink);font-weight:600}
.pill{display:inline-block;font-size:10.5px;letter-spacing:.06em;
 text-transform:uppercase;border:1px solid var(--line);border-radius:3px;
 padding:.05rem .35rem;margin-right:.35rem}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);
 font-size:12px;color:var(--dim)}
.toc{font-size:13px;background:var(--soft);border:1px solid var(--line);
 border-radius:5px;padding:.6rem .9rem;margin:1.2rem 0}
.toc a{display:block;padding:.08rem 0;color:inherit;text-decoration:none}
.toc a:hover{color:var(--accent)}
.toc .l3{padding-left:1rem}.toc .l4{padding-left:2rem}
.api h3{font-family:ui-monospace,monospace;font-size:.95rem;
 background:var(--soft);border:1px solid var(--line);border-radius:4px;
 padding:.3rem .5rem}
.api .sig{font-family:ui-monospace,monospace;font-size:.87rem}
@media(max-width:820px){.wrap{display:block}nav{position:static;flex:none;
 max-height:none;border-right:0;border-bottom:1px solid var(--line)}
 main{padding:1rem 1.1rem 4rem}}
"""


def _rel(frm, to):
    """A site-relative href from one output page to another."""
    r = os.path.relpath(to, os.path.dirname(frm)).replace(os.sep, "/")
    return r


class HtmlBackend(object):
    """Render one repo's docs as a static site.

    `outdir` is written under the repo (gitignored by convention -- it is a
    build product, and the freshness gate covers the Markdown, not this).
    """

    def __init__(self, model, docsdir, areas, outdir, title,
                 subtitle="", notice="", header=None):
        self.model = model
        self.docsdir = docsdir
        self.areas = list(areas)
        self.outdir = outdir
        self.title = title
        self.subtitle = subtitle
        self.notice = notice

    # -- page shell ----------------------------------------------------

    def _page(self, path, title, body, nav, toc=""):
        css = _rel(path, os.path.join(self.outdir, "site.css"))
        home = _rel(path, os.path.join(self.outdir, "index.html"))
        html = (
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,'
            'initial-scale=1">\n<title>%s — %s</title>\n'
            '<link rel="stylesheet" href="%s">\n</head><body>\n'
            '<div class="wrap"><nav><a href="%s"><b>%s</b></a>'
            '<div style="color:var(--dim);font-size:12px">%s</div>%s</nav>\n'
            '<main>%s%s\n<footer>%s</footer></main></div>\n'
            '</body></html>\n'
            % (mdrender.escape(title), mdrender.escape(self.title), css,
               home, mdrender.escape(self.title),
               mdrender.escape(self.subtitle), nav, toc, body,
               mdrender.escape(self.notice)))
        self.model.write_if_changed(path, html)

    def _nav(self, here, pages):
        """Sidebar: areas in reading order, then everything else."""
        by_area = {}
        for rec in pages:
            by_area.setdefault(rec["area"], []).append(rec)
        order = [a for a, _d, _g in self.areas if a in by_area]
        order += sorted(a for a in by_area if a not in order)
        out = []
        for area in order:
            out.append("<h2>%s</h2>" % mdrender.escape(area))
            for rec in sorted(by_area[area],
                              key=lambda r: (r["genre"], r["title"].lower())):
                cls = ' class="here"' if rec["out"] == here else ""
                out.append('<a href="%s"%s>%s</a>'
                           % (_rel(here, rec["out"]), cls,
                              mdrender.escape(rec["title"])))
        return "".join(out)

    @staticmethod
    def _toc(heads):
        if len(heads) < 3:
            return ""
        out = ['<div class="toc">']
        for lvl, txt, anchor in heads:
            if lvl < 2 or lvl > 4:
                continue
            out.append('<a class="l%d" href="#%s">%s</a>'
                       % (lvl, anchor, mdrender.escape(txt)))
        out.append("</div>")
        return "".join(out) if len(out) > 2 else ""

    # -- build ---------------------------------------------------------

    def _doc_pages(self):
        """One record per hand-authored doc."""
        recs = []
        for p, meta, body in self.model.iter_docs():
            rel = self.model.rel(p)
            out = os.path.join(self.outdir, "doc",
                               rel[:-3].replace("/", os.sep) + ".html")
            recs.append({"src": p, "rel": rel, "meta": meta, "body": body,
                         "out": out,
                         "area": meta.get("area", "misc"),
                         "genre": self.model.canon_genre(
                             meta.get("genre")) or "?",
                         "title": meta.get("title") or os.path.basename(rel)})
        return recs

    def _linkmap(self, recs):
        """repo-relative .md path -> output page, for rewriting links."""
        return dict((r["rel"], r["out"]) for r in recs)

    _A = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)

    def _fix_links(self, html, page, srcdir, linkmap):
        """Point intra-repo `.md` links at the generated pages.

        ⚠ A LINK THAT RESOLVES NOWHERE BECOMES TEXT, not a dead anchor. Most
        of these point at SOURCE files -- `analog/engine/sync/push.sh`, a
        docstring citing a sibling `.md` -- which are real, tracked, and
        correct links inside the repository; they are simply not pages of
        this site. Left as hrefs they were 341 dead links; rewritten to
        somewhere plausible they would be worse, because a link that
        silently goes to the wrong page cannot be noticed. As `<code>` the
        reader still gets the path, which is the useful part.
        """
        def sub(m):
            href, text = m.group(1), m.group(2)
            if href.startswith(("http://", "https://", "mailto:", "#")):
                return m.group(0)
            frag = ""
            if "#" in href:
                href, frag = href.split("#", 1)
                frag = "#" + frag
            if href.endswith(".md"):
                tgt = os.path.relpath(
                    os.path.normpath(os.path.join(srcdir, href)),
                    self.model.root).replace(os.sep, "/")
                if tgt in linkmap:
                    return '<a href="%s%s">%s</a>' % (
                        _rel(page, linkmap[tgt]), frag, text)
            return "<code>%s</code>" % text

        return self._A.sub(sub, html)

    def build(self):
        """Write the whole site. -> (pages, api_pages)."""
        recs = self._doc_pages()
        linkmap = self._linkmap(recs)
        self.model.write_if_changed(
            os.path.join(self.outdir, "site.css"), CSS)

        for r in recs:
            body, heads = mdrender.render(r["body"], heading_shift=0)
            body = self._fix_links(body, r["out"],
                                   os.path.dirname(r["src"]), linkmap)
            m = r["meta"]
            meta = ('<div class="meta">'
                    '<span class="pill">%s</span>'
                    '<span class="pill">%s</span>'
                    'updated <b>%s</b> &middot; <code>%s</code></div>'
                    % (mdrender.escape(r["genre"]),
                       mdrender.escape(m.get("status", "?")),
                       mdrender.escape(m.get("updated", "?")),
                       mdrender.escape(r["rel"])))
            head = "<h1>%s</h1>" % mdrender.escape(r["title"])
            self._page(r["out"], r["title"], head + meta + body,
                       self._nav(r["out"], recs), self._toc(heads))

        api = self._api_pages(recs, linkmap)
        self._index(recs, api)
        return len(recs), len(api)

    def _api_pages(self, recs, linkmap=None):
        """One page per area, with the FULL docstring for every symbol."""
        made = []
        for area, desc, globs in self.areas:
            out = os.path.join(self.outdir, "api", area + ".html")
            files = self.model.iter_py(globs)
            B = ['<h1>API — <code>%s</code></h1>' % mdrender.escape(area),
                 '<div class="meta">%s &middot; extracted statically from '
                 '<b>%d</b> module(s), never imported</div>'
                 % (mdrender.escape(desc), len(files))]
            heads = []
            for path in files:
                got = docmodel.module_api(path)
                if got is None:
                    continue
                mdoc, funcs, classes = got
                if not funcs and not classes:
                    continue
                rel = self.model.rel(path)
                a = mdrender.slug(rel)
                heads.append((2, rel, a))
                B.append('<h2 id="%s"><code>%s</code></h2>' % (a, rel))
                fix = (lambda h: self._fix_links(
                    h, out, os.path.dirname(path), linkmap or {}))
                if mdoc:
                    B.append(fix(mdrender.render(mdoc, heading_shift=3)[0]))
                B.append('<div class="api">')
                for sig, doc in funcs:
                    B.append('<h3>%s</h3>' % mdrender.escape(sig))
                    if doc:
                        B.append(fix(mdrender.render(doc, heading_shift=3)[0]))
                for name, cdoc, meths in classes:
                    B.append('<h3>class %s</h3>' % mdrender.escape(name))
                    if cdoc:
                        B.append(fix(mdrender.render(cdoc, heading_shift=3)[0]))
                    for sig, doc in meths:
                        B.append('<p class="sig">&nbsp;&nbsp;%s</p>'
                                 % mdrender.escape(sig))
                        if doc:
                            B.append(fix(
                                mdrender.render(doc, heading_shift=4)[0]))
                B.append('</div>')
            self._page(out, "API — " + area, "".join(B),
                       self._nav(out, recs), self._toc(heads))
            made.append((area, out))
        return made

    def _index(self, recs, api):
        out = os.path.join(self.outdir, "index.html")
        by_area = {}
        for r in recs:
            by_area.setdefault(r["area"], []).append(r)
        order = [a for a, _d, _g in self.areas if a in by_area]
        order += sorted(a for a in by_area if a not in order)
        B = ["<h1>%s</h1>" % mdrender.escape(self.title)]
        if self.subtitle:
            B.append("<p>%s</p>" % mdrender.escape(self.subtitle))
        B.append("<h2>API reference</h2><p>")
        B.append(" &middot; ".join(
            '<a href="%s">%s</a>' % (_rel(out, p), mdrender.escape(a))
            for a, p in api))
        B.append("</p>")
        for area in order:
            B.append('<h2>%s</h2><div class="scroll"><table><thead><tr>'
                     '<th>Doc</th><th>Genre</th><th>Status</th>'
                     '<th>Updated</th><th>Summary</th></tr></thead><tbody>'
                     % mdrender.escape(area))
            for r in sorted(by_area[area],
                            key=lambda x: (x["genre"], x["title"].lower())):
                B.append('<tr><td><a href="%s">%s</a></td><td>%s</td>'
                         '<td>%s</td><td>%s</td><td>%s</td></tr>'
                         % (_rel(out, r["out"]), mdrender.escape(r["title"]),
                            mdrender.escape(r["genre"]),
                            mdrender.escape(r["meta"].get("status", "?")),
                            mdrender.escape(r["meta"].get("updated", "?")),
                            mdrender.escape(r["meta"].get("summary", "")[:220])))
            B.append("</tbody></table></div>")
        self._page(out, "index", "".join(B), self._nav(out, recs))
