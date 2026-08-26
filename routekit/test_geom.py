#!/usr/bin/env python3
"""Gates for routekit.geom -- each with a control that must FIRE.

A geometry sweep that cannot return the failing answer proves nothing, so
every check here has a poison twin.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import geom                                  # noqa: E402


def test_union_find_is_transitive():
    find, union = geom.union_find(4)
    union(0, 1)
    union(1, 2)
    assert find(0) == find(2)
    assert find(3) != find(0)


def test_subtract_disjoint_returns_whole():
    assert geom.subtract((0, 0, 1, 1), (2, 2, 3, 3)) == [(0, 0, 1, 1)]


def test_subtract_covers_returns_nothing():
    assert geom.subtract((0, 0, 1, 1), (-1, -1, 2, 2)) == []


def test_subtract_partial_conserves_area():
    parts = geom.subtract((0.0, 0.0, 2.0, 2.0), (0.5, 0.5, 1.5, 1.5))
    got = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in parts)
    assert abs(got - (4.0 - 1.0)) < 1e-9


def test_uncovered_finds_the_gap():
    left = geom.uncovered((0, 0, 3, 1), [(0, 0, 1, 1), (2, 0, 3, 1)])
    assert len(left) == 1
    x1, y1, x2, y2 = left[0]
    assert abs(x1 - 1) < 1e-9 and abs(x2 - 2) < 1e-9


def test_union_area_does_not_double_count():
    # two 1x1 squares overlapping by 0.5x1: union is 1.5, sum is 2.0
    got = geom.union_area([(0, 0, 1, 1), (0.5, 0, 1.5, 1)])
    assert abs(got - 1.5) < 1e-9


def test_union_area_poison_sum_would_be_wrong():
    rects = [(0, 0, 1, 1), (0, 0, 1, 1)]        # the same square twice
    assert abs(geom.union_area(rects) - 1.0) < 1e-9


def test_boundary_edges_of_one_rect():
    es = geom.boundary_edges([(0, 0, 2, 1)])
    assert len(es) == 4
    lens = sorted(round(b - a, 6) for _o, _c, a, b in es)
    assert lens == [1.0, 1.0, 2.0, 2.0]


def test_boundary_edges_corner_touch_does_not_merge():
    # two rects meeting at one corner: the top edge of one and the bottom
    # edge of the other sit on the same line and MUST stay separate --
    # merging them describes a polygon that is not there.
    es = geom.boundary_edges([(0, 0, 1, 1), (1, 1, 2, 2)])
    assert len(es) == 8
    for _o, _c, a, b in es:
        assert abs((b - a) - 1.0) < 1e-9
