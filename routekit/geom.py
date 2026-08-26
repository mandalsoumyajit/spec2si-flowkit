#!/usr/bin/env python3
"""Pure rectangle geometry for the routing core. No process facts anywhere.

Extracted verbatim from `spec2si-tsmc28` `analog/engine/layout/audit.py`
(itself forked from the 65 nm `netlist_route` audits) so that the sweeps the
audits and the router share live once. Every function here takes plain
axis-aligned rectangles `(x1, y1, x2, y2)` with `x1 <= x2`, `y1 <= y2`;
nothing knows about layers, nets or rules.

Python floor: the cluster's 3.6 -- no dataclasses, no walrus, `.format`.
"""


def union_find(n):
    """A tiny union-find over `range(n)`. Returns `(find, union)`."""
    parent = list(range(n))

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return find, union


def subtract(r, o):
    """`r` minus `o`, as a list of rectangles."""
    rx1, ry1, rx2, ry2 = r
    ox1, oy1, ox2, oy2 = o
    if ox2 <= rx1 or ox1 >= rx2 or oy2 <= ry1 or oy1 >= ry2:
        return [r]
    out = []
    if ox1 > rx1:
        out.append((rx1, ry1, ox1, ry2))
    if ox2 < rx2:
        out.append((ox2, ry1, rx2, ry2))
    mx1, mx2 = max(rx1, ox1), min(rx2, ox2)
    if oy1 > ry1:
        out.append((mx1, ry1, mx2, oy1))
    if oy2 < ry2:
        out.append((mx1, oy2, mx2, ry2))
    return [q for q in out
            if q[2] - q[0] > 1e-9 and q[3] - q[1] > 1e-9]


def uncovered(rect, others):
    """The parts of `rect` no shape in `others` covers."""
    pending = [rect]
    for o in others:
        nxt = []
        for q in pending:
            nxt.extend(subtract(q, o))
        pending = nxt
        if not pending:
            return []
    return pending


def union_area(rects):
    """Exact area of a union of axis-aligned rectangles, by x-slab sweep.

    Calibre measures the MERGED polygon, so summing the rectangles a caller
    drew double-counts every overlap -- and a landing pad is two or three
    overlapping pads by construction, which is precisely the shape the
    min-area gate exists to measure."""
    xs = sorted(set([r[0] for r in rects] + [r[2] for r in rects]))
    total = 0.0
    for i in range(len(xs) - 1):
        x1, x2 = xs[i], xs[i + 1]
        if x2 - x1 <= 1e-12:
            continue
        spans = sorted((r[1], r[3]) for r in rects
                       if r[0] <= x1 + 1e-12 and r[2] >= x2 - 1e-12)
        cov, lo, hi = 0.0, None, None
        for a, b in spans:
            if lo is None:
                lo, hi = a, b
            elif a > hi + 1e-12:
                cov += hi - lo
                lo, hi = a, b
            else:
                hi = max(hi, b)
        if lo is not None:
            cov += hi - lo
        total += (x2 - x1) * cov
    return total


def boundary_edges(rects):
    """Every boundary edge of a union of axis-aligned rects.

    Coordinate-compress, rasterise, keep the cell edges with nothing on the
    far side, then merge collinear runs THAT FACE THE SAME WAY. The side
    matters: two rects touching at a corner put a top edge and a bottom
    edge on the same line, and merging those describes a polygon that is
    not there.

    Returns [(orient, const, a, b)] -- "H" runs in x at y `const`, "V" runs
    in y at x `const`.
    """
    rects = [tuple(round(v, 6) for v in r) for r in rects]
    xs = sorted(set([r[0] for r in rects] + [r[2] for r in rects]))
    ys = sorted(set([r[1] for r in rects] + [r[3] for r in rects]))
    ix = dict((v, i) for i, v in enumerate(xs))
    iy = dict((v, i) for i, v in enumerate(ys))
    filled = set()
    for x1, y1, x2, y2 in rects:
        for i in range(ix[x1], ix[x2]):
            for j in range(iy[y1], iy[y2]):
                filled.add((i, j))
    by = {}
    for (i, j) in filled:
        if (i, j - 1) not in filled:
            by.setdefault(("H", ys[j], 1), []).append((xs[i], xs[i + 1]))
        if (i, j + 1) not in filled:
            by.setdefault(("H", ys[j + 1], -1), []).append((xs[i], xs[i + 1]))
        if (i - 1, j) not in filled:
            by.setdefault(("V", xs[i], 1), []).append((ys[j], ys[j + 1]))
        if (i + 1, j) not in filled:
            by.setdefault(("V", xs[i + 1], -1), []).append((ys[j], ys[j + 1]))
    out = []
    for (o, c, _sd), lst in by.items():
        lst.sort()
        cur = list(lst[0])
        for a, b in lst[1:]:
            if a <= cur[1] + 1e-9:
                cur[1] = max(cur[1], b)
            else:
                out.append((o, c, cur[0], cur[1]))
                cur = [a, b]
        out.append((o, c, cur[0], cur[1]))
    return out
