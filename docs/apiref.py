#!/usr/bin/env python3
"""The reference MODEL: commands, symbols, and an index to look them up in.

⛔ VENDORED. Byte-identical copy of spec2si-flowkit's `docs/apiref.py`,
hash-gated by that repo's `sync.py --check`. Edit it THERE, never here.

⭐ WHY THIS EXISTS, AND WHAT WAS WRONG BEFORE. The first PDF bound 123
existing documents and called itself a manual. It was a TRANSCRIPT: those
documents are decisions, findings and session records -- written for the
author, narrating how things came to be -- and no amount of binding turns
narration into instruction. The repo's own genre contract already said so:
`guide` is "hand-written and meant to be stable; POINTS AT GENERATED
REFERENCE rather than copying it", and `reference` is "GENERATED, never
hand-edited". A manual is those two and nothing else.

So this module builds the half a reader looks THINGS UP in. Measured on the
65 nm port: 374 modules, 2,049 public functions, 82 classes, and **156
runnable entry points** -- this flow is a toolbox, and a toolbox needs a
parts list, not a memoir.

⚠ AND IT REPORTS ITS OWN GAPS. Only 12 of those 156 entry points carry a
usage line in their module docstring -- 83 of the undocumented ones are in
`hybrid_adc` and 42 in `analog`. That number is printed in the manual rather
than hidden, for the same reason the policy adoption gap is: an undocumented
command and a documented one look identical from the outside until you
count. It is also the honest measure of how much how-to layer is missing.
"""
import ast
import io
import os
import re

import docmodel

#: A `Usage:` / `Run as:` line in a module docstring -- the house convention
#: for saying how a script is invoked.
_USAGE = re.compile(r"^[ \t]*(?:usage|run as|run|invoke)[ \t]*:[ \t]*(.*)$",
                    re.I | re.M)


def _usage_block(doc):
    """The usage lines of a module docstring, verbatim, or ''. """
    m = _USAGE.search(doc or "")
    if not m:
        return ""
    lines = (doc[m.start():].split(chr(10)))
    out = [lines[0].strip()]
    for ln in lines[1:]:
        s = ln.strip()
        if not s:
            break
        if s.lower().startswith(("usage", "run ", "invoke")) or s.startswith(
                ("python", "$", "#", "-", "wsl", "ssh", "bash", "tclsh")):
            out.append(s)
            continue
        break
    return chr(10).join(out)


def is_entry_point(src):
    """Is this module something a person RUNS, as opposed to imports?"""
    return "__main__" in src and ("sys.argv" in src or "argparse" in src)


def commands(model, areas):
    """[{area, module, summary, usage}] for every runnable entry point.

    Sorted by module path, which is how someone hunting for a command
    actually scans: they know roughly where in the tree it lives.
    """
    out = []
    for area, _desc, globs in areas:
        for p in model.iter_py(globs):
            try:
                src = io.open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            if not is_entry_point(src):
                continue
            try:
                doc = ast.get_docstring(ast.parse(src, p)) or ""
            except SyntaxError:
                doc = ""
            out.append({"area": area, "module": model.rel(p),
                        "summary": docmodel.first_line(doc),
                        "usage": _usage_block(doc)})
    out.sort(key=lambda c: c["module"])
    return out


def symbols(model, areas):
    """[{area, module, kind, name, sig, doc, parent}] for every public symbol.

    `parent` is the class for a method, else ''. This is the flat list the
    index is built from; the per-module view is a grouping of the same rows,
    so the two can never disagree about what exists.
    """
    out = []
    for area, _desc, globs in areas:
        for p in model.iter_py(globs):
            got = docmodel.module_api(p)
            if got is None:
                continue
            mdoc, funcs, classes = got
            rel = model.rel(p)
            for sig, doc in funcs:
                out.append({"area": area, "module": rel, "kind": "function",
                            "name": sig.split("(")[0], "sig": sig,
                            "doc": doc, "parent": ""})
            for name, cdoc, meths in classes:
                out.append({"area": area, "module": rel, "kind": "class",
                            "name": name, "sig": "class " + name,
                            "doc": cdoc, "parent": ""})
                for sig, doc in meths:
                    out.append({"area": area, "module": rel, "kind": "method",
                                "name": sig.split("(")[0], "sig": sig,
                                "doc": doc, "parent": name})
    return out


def modules(model, areas):
    """[{area, module, doc, funcs, classes}] -- the per-module view."""
    out = []
    for area, _desc, globs in areas:
        for p in model.iter_py(globs):
            got = docmodel.module_api(p)
            if got is None:
                continue
            mdoc, funcs, classes = got
            if not funcs and not classes:
                continue
            out.append({"area": area, "module": model.rel(p), "doc": mdoc,
                        "funcs": funcs, "classes": classes})
    return out


def index(syms):
    """Alphabetical (name, [(module, kind, parent)]) for lookup.

    ⚠ Case-insensitive on the NAME but stable on the module, so a symbol
    defined in several places lists them in one entry instead of scattering
    -- which is the question the index is actually asked: 'where is `build`
    defined, and which one do I want?'
    """
    by = {}
    for s in syms:
        # ⚠ Dunders are not lookup targets. `__init__` is a method of
        # nearly every class here, so indexing it puts one useless entry at
        # the head of the alphabet pointing at eighty modules. It stays in
        # the per-module API, where the constructor signature is the point.
        if s["name"].startswith("__"):
            continue
        by.setdefault(s["name"], []).append(
            (s["module"], s["kind"], s["parent"]))
    return sorted(((n, sorted(set(v))) for n, v in by.items()),
                  key=lambda kv: (kv[0].lower(), kv[0]))


def coverage(cmds):
    """(documented, total) entry points -- the gap, as a number."""
    return sum(1 for c in cmds if c["usage"]), len(cmds)
