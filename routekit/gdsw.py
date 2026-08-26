#!/usr/bin/env python3
"""A minimal GDSII writer: rectangles into named cells, nothing else.

Exists for ONE job -- streaming `ruleprobe`'s violation/clean geometry to
the signoff deck -- and is deliberately no more than that job needs:
BOUNDARY records on (layer, datatype), one flat cell per call, 5 nm-class
grids as int32 database units. No paths, no refs, no text. A consumer
with real streams keeps using its own strmout; this is for geometry that
never lives in OA at all.

The round-trip gate in `test_gdsw.py` re-parses every record written --
a writer whose output is never parsed is untested, and the ports'
history with half-read GDS (PATHTYPE 4 extensions, purposes, mosaics) is
exactly why this writer refuses to write anything it cannot also read
back bit-exactly.

Python floor: the cluster's 3.6.
"""
import io
import struct

HEADER, BGNLIB, LIBNAME, UNITS = 0x0002, 0x0102, 0x0206, 0x0305
BGNSTR, STRNAME, ENDSTR, ENDLIB = 0x0502, 0x0606, 0x0700, 0x0400
BOUNDARY, LAYER, DATATYPE, XY, ENDEL = 0x0800, 0x0D02, 0x0E02, 0x1003, 0x1100

_TS = (2026, 1, 1, 0, 0, 0)          # fixed: a probe file diffs by content


def _rec(tag, payload=b""):
    return struct.pack(">HH", 4 + len(payload), tag) + payload


def _gds_real8(v):
    """GDS 8-byte real: sign, excess-64 base-16 exponent, 56-bit mantissa."""
    if v == 0:
        return b"\x00" * 8
    sign = 0
    if v < 0:
        sign, v = 0x80, -v
    e = 0
    while v >= 1.0:
        v /= 16.0
        e += 1
    while v < 0.0625:
        v *= 16.0
        e -= 1
    mant = int(round(v * (1 << 56)))
    if mant >= (1 << 56):
        mant >>= 4
        e += 1
    return struct.pack(">B", sign | (64 + e)) + \
        mant.to_bytes(7, "big")


def _name(s):
    b = s.encode("ascii")
    if len(b) % 2:
        b += b"\x00"
    return b


def write(path, cells, dbu_um=0.001):
    """`cells` is {cell_name: [(layer, datatype, x1, y1, x2, y2), ...]}
    in MICRONS; coordinates snap to `dbu_um` database units (default
    1 nm, which holds every 5 nm-grid value exactly). Refuses a
    coordinate the dbu cannot represent -- a probe drawn off its own
    grid tests the writer, not the rule."""
    scale = 1.0 / dbu_um
    out = [
        _rec(HEADER, struct.pack(">h", 600)),
        _rec(BGNLIB, struct.pack(">12h", *(_TS + _TS))),
        _rec(LIBNAME, _name("routekit_probes")),
        _rec(UNITS, _gds_real8(dbu_um) + _gds_real8(dbu_um * 1e-6)),
    ]
    for cell in sorted(cells):
        out.append(_rec(BGNSTR, struct.pack(">12h", *(_TS + _TS))))
        out.append(_rec(STRNAME, _name(cell)))
        for layer, dt, x1, y1, x2, y2 in cells[cell]:
            pts = []
            for (x, y) in ((x1, y1), (x2, y1), (x2, y2), (x1, y2),
                           (x1, y1)):
                for v in (x, y):
                    dv = v * scale
                    iv = int(round(dv))
                    if abs(dv - iv) > 1e-6:
                        raise ValueError(
                            "coordinate {} um is not on the {} um dbu "
                            "grid".format(v, dbu_um))
                    pts.append(iv)
            out.append(_rec(BOUNDARY))
            out.append(_rec(LAYER, struct.pack(">h", layer)))
            out.append(_rec(DATATYPE, struct.pack(">h", dt)))
            out.append(_rec(XY, struct.pack(">%di" % len(pts), *pts)))
            out.append(_rec(ENDEL))
        out.append(_rec(ENDSTR))
    out.append(_rec(ENDLIB))
    with io.open(path, "wb") as fh:
        fh.write(b"".join(out))


def read_rects(path):
    """The reader half of the round-trip gate: {cell: [(layer, dt, x1,
    y1, x2, y2), ...]} in microns, BOUNDARY records only, refusing any
    record type it does not know -- an unknown record silently skipped
    is how half-read GDS has lied to these flows before."""
    known = {HEADER, BGNLIB, LIBNAME, UNITS, BGNSTR, STRNAME, ENDSTR,
             ENDLIB, BOUNDARY, LAYER, DATATYPE, XY, ENDEL}
    cells, cell, cur, dbu = {}, None, None, None
    data = io.open(path, "rb").read()
    i = 0
    while i < len(data):
        (ln, tag) = struct.unpack(">HH", data[i:i + 4])
        body = data[i + 4:i + ln]
        i += ln
        if tag not in known:
            raise ValueError("unknown GDS record 0x%04X -- refusing a "
                             "half-read stream" % tag)
        if tag == UNITS:
            # decode the first real8: dbu in user units (um here)
            b0 = body[0]
            e = (b0 & 0x7F) - 64
            mant = int.from_bytes(body[1:8], "big") / float(1 << 56)
            dbu = mant * (16.0 ** e)
        elif tag == STRNAME:
            cell = body.rstrip(b"\x00").decode("ascii")
            cells[cell] = []
        elif tag == BOUNDARY:
            cur = {}
        elif tag == LAYER and cur is not None:
            cur["layer"] = struct.unpack(">h", body)[0]
        elif tag == DATATYPE and cur is not None:
            cur["dt"] = struct.unpack(">h", body)[0]
        elif tag == XY and cur is not None:
            n = len(body) // 4
            xy = struct.unpack(">%di" % n, body)
            xs = [v * dbu for v in xy[0::2]]
            ys = [v * dbu for v in xy[1::2]]
            cur["box"] = (min(xs), min(ys), max(xs), max(ys))
        elif tag == ENDEL and cur is not None:
            cells[cell].append((cur["layer"], cur["dt"]) + cur["box"])
            cur = None
    return cells
