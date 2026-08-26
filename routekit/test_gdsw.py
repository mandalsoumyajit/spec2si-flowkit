#!/usr/bin/env python3
"""Round-trip gates for the minimal GDS writer: everything written is
re-parsed, values bit-exact, and off-grid input refuses."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir))
from routekit import gdsw                                  # noqa: E402


CELLS = {
    "probe_violation": [(31, 0, 0.0, 0.0, 1.0, 0.05),
                        (31, 0, 0.0, 0.09, 1.0, 0.14),
                        (51, 0, 0.4, 0.0, 0.5, 0.05)],
    "probe_clean": [(32, 0, -2.5, 0.0, 2.5, 0.1)],
}


def test_round_trip_is_exact(tmp_path):
    p = str(tmp_path / "probes.gds")
    gdsw.write(p, CELLS, dbu_um=0.001)
    back = gdsw.read_rects(p)
    assert sorted(back) == sorted(CELLS)
    for cell in CELLS:
        got = sorted(back[cell])
        want = sorted(CELLS[cell])
        assert len(got) == len(want)
        for g, w in zip(got, want):
            assert g[0] == w[0] and g[1] == w[1]
            for a, b in zip(g[2:], w[2:]):
                assert abs(a - b) < 1e-9, (cell, g, w)


def test_off_grid_coordinate_refuses(tmp_path):
    p = str(tmp_path / "bad.gds")
    try:
        gdsw.write(p, {"c": [(31, 0, 0.0, 0.0, 1.00000037, 0.1)]},
                   dbu_um=0.001)
    except ValueError as e:
        assert "dbu" in str(e)
    else:
        raise AssertionError("an off-grid coordinate did not refuse")


def test_reader_refuses_unknown_records(tmp_path):
    p = str(tmp_path / "alien.gds")
    gdsw.write(p, CELLS)
    data = open(p, "rb").read()
    # splice in a PATH record header (0x0900) the reader does not know
    alien = data[:4] + b"\x00\x04\x09\x00" + data[4:]
    open(p, "wb").write(alien)
    try:
        gdsw.read_rects(p)
    except ValueError as e:
        assert "half-read" in str(e)
    else:
        raise AssertionError("an unknown record did not refuse")


def test_real8_units_survive():
    for v in (0.001, 0.005, 1e-9, 0.25):
        enc = gdsw._gds_real8(v)
        b0 = enc[0]
        e = (b0 & 0x7F) - 64
        mant = int.from_bytes(enc[1:8], "big") / float(1 << 56)
        assert abs(mant * (16.0 ** e) - v) / v < 1e-12
