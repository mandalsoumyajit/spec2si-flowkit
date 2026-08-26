<!--docmeta
title: Routekit — one card-driven router for the four ports
genre: plan
status: active
area: top
owner: soumyajit
updated: 2026-08-26
summary: Consolidate the seventeen hand-built routers across spec2si-{tsmc65,tsmc28,xt011,sky130} onto ONE card-driven search core, vendored from this repo the way the IR solver already is. Decided on the survey's own scoreboard — every search-based router closed (glue_solver 136/136 signed, xt011's SKILL maze signed, the 28 nm tile's first run 48/71 through a byte-identical port behind a ten-symbol adapter) while every constructive router accumulated hand-tuning — and on the fact that all four are planar CMOS processes, so direction parity, enclosure schemes and riser disciplines are card DATA, not algorithms. Constraints ride as data too: EM floors as per-net width/cut attributes, R budgets driving route_widen inside the solver's own occupancy model, IR drop solved on the drawn supply by the vendored MNA solver, keepouts as typed claims in the one occupancy model, and net classes (differential, noisy/quiet, shields, matched-in-ohms legs) through the net_classes.json mechanism where an unmatched net is a refusal. Phase 0 is DONE 2026-08-26: the regression corpus is frozen in routekit/corpus.json — tsmc65 re-solves 136/136 with zero findings and is from-scratch deterministic (byte-identical twice), xt011's ring loops replay byte-identically at their signing commit and its 179 offline gates pass, tsmc28's digest tests pass. The from-scratch/snapshot divergence is now measured at 83/136 state records (was 17 on 2026-08-04), which fixes the policy: the snapshot is frozen by hash, and the core is gated on determinism + gates-green, never snapshot equality.
-->

# Routekit — one card-driven router for the four ports

**Status:** plan approved 2026-08-26; phase 0 complete; phases 1–6 open.
The rendered decision page (same content, with the survey behind it) is the
"Routekit" artifact; this file is the version of record.

## 1. The finding

A full survey (2026-08-26) of the five repos found **seventeen distinct
hand-built router codebases** (Innovus/NanoRoute and the OpenROAD digital
port aside): ten in `spec2si-tsmc65`, seven-plus in `spec2si-tsmc28`, four
in `spec2si-xt011`, none in `spec2si-sky130`, none here. None was copied
carelessly — each fork has a documented reason — and the result is still
that every routing job starts with a hand-tuned, single-purpose tool.

Five patterns make it unscalable:

1. **Forks at the wrong boundary.** The 65→28 fork of `routing.py` shares
   37 of 1,061 lines; `netlist_route.py` shares 23 lines and zero function
   names. The route-plan divergence was real; the duplicated occupancy
   models, via arithmetic and audits were not.
2. **Verbatim copies drift** — `rengine/` is 552 lines from its declared
   byte-identical parent; the via-name table is written four times in
   tsmc28 and three in xt011, where two via-card readers disagree and one
   is right by numeric coincidence.
3. **Rules leak into router source** (`MAX_THIN_W = 1.20` restating deck
   rule W3M4; `P_METAL_FAMILY` known-wrong 4× and worked around twice).
4. **Per-job hand-tuning is the interface** — `PIN_CURRENT_MA` fudge
   dicts, `NET_ORDER`, typed corridor tables, instance-name literals, the
   `CTRL_*` env-var knob farm.
5. **Each repo re-learns the same lessons** — four obstacle extractors,
   three pin-access solvers, four audit suites, the same stale-input and
   silent-pass bug classes, post-mortems that never travel.

**The existence proof is already in the tree.** tsmc28's `tile_solver.py`
is tsmc65's `glue_solver.py` byte-for-byte below its header, behind a
ten-symbol adapter (`tile_abstract.py`); the port surfaced exactly two
defects, both adapter numbers, both caught offline. On 2026-08-25 it routed
its first real nets on the 28 nm tile (48/71) through a driver that
subclasses `Allocator.seed` rather than editing the copy. xt011's chip-top
plan independently chose to port the same family rather than write a fifth
router.

## 2. The decision shape

**One algorithm, not a family.** All four are planar CMOS processes: the
routing problem is topologically identical at every node and every level,
and the per-node "algorithms" (65 nm lanes, 28 nm bands) are artifacts of
*constructive* routing, where the direction scheme is compiled into control
flow. A card-driven search has no plan for a direction flip to break. The
survey's scoreboard: search-based routers closed (glue 136/136 signed;
xt011's SKILL maze signed at MET1–MET3 including power; the tile 48/71
first try); constructive routers accumulated the hand-tuning.

`routekit/` lives in this repo and vendors through `sync.py` like the IR
solver — the `em_ir_alignment.md` seam ("touches no PDK API, no deck, no
PCell, only numbers a card hands it"), which the tile_solver port proved
the router core satisfies:

| module | contents |
|---|---|
| `solve` | the promoted `glue_solver` core (Tracks, A* Maze, Allocator with bounded displacement, bundle router, MST+L global, single-tier Dijkstra) + two track-graph builders: uniform lattice over an obstacle map (glue), placement-seeded graph (device level: S/D columns, OD gaps, poly pitch) |
| `geom` | rects, intervals, lattices, transforms (reflection-conjugation fix), ONE occupancy model |
| `audit` | offline tier-1 gates (shorts/opens/enclosure/min-area/spacing/landings/connectivity) + the negative-control harness |
| `card` | the RoutingCard schema — layers, directions, width/space incl. width-pair wide-metal, via geometry and redundancy predicates, dense-layer rule kinds (line-end, enclosure schemes, min-area, riser adjacency), EM/RC cards. Values stay per-repo with provenance (probe, date, deck line); a missing value is a refusal, never a default |
| `io` | the `.route` text grammar (xt011's), plan JSON, abstract/obstacle-map schemas, GDS/DEF readers |
| `elec` | EM width/cut floors, R/τ budgets + `route_widen`-class widening inside the solver's occupancy model, ohm pricing, the current map, IR hooks to the vendored MNA solver |

**Local per repo:** card values and probes, OA/SKILL drawers
(`route_cml.il`, `oa_worker`), signoff drivers (Calibre / PVS / Pegasus),
and the per-node adapter (the `tile_abstract` pattern). **Reclassified:**
constructive routers are frozen for signed cells (a signed cell is never
re-routed) and deprecated for new work. **Out of scope:** array pattern
generators (DAC buses, MOM meshes, decap straps — the geometry *is* the
design) and supply synthesis (a mesh/comb is a designed structure,
verified electrically, not searched).

## 3. Constraints are data, not algorithms

- **EM floors, before search.** Net class + current → per-layer minimum
  width and per-tier minimum cuts (EM card, temperature-derated). The
  occupancy model already carries per-net widths; width-pair spacing is
  already a card function.
- **R/τ budgets, around search.** tsmc65 built and signed this:
  `route_budget` derives per-net R_max and prices off the measured RC
  card; `route_widen` widens / re-corridors / reserves-and-evicts *inside
  the solver's own `Tracks`*; iterate to a `route_widths.json` fixpoint;
  PEX closes the loop. Ported beside the solver as one unit, with
  ROUTE_BUDGET §10's silent-pass defects as its regression suite. One
  measured rule carries over: **widening is not monotone in routability**
  (15–17.5 Ω and ≥28 Ω route; between starves the lanes) — a width change
  is a re-solve trigger, never a local edit. tsmc28 contributes the better
  resistance *source* (foundry QRC tables).
- **IR drop, after drawing.** The drawn supply is solved with the MNA
  solver this repo already vendors (`supply-drop-is-computed`); over
  budget is a refusal.
- **Keepouts are typed claims in the one occupancy model** — hard
  obstacle, owner-tagged reservation (`route_widen --reserve`), declared
  slab (the `dac_core` pattern), per-tier abstract keepouts
  (`m4/m6/m8_keepouts`), LEF `OBS`. Schema-level, so no consumer can skip
  one: the recorded tsmc28 gap ("the array keep-out is not enforced for
  signal ROUTES") becomes structurally impossible.
- **Net classes through the `net_classes.json` mechanism** (ported as a
  mechanism; content re-authored per chip; an unmatched net is a refusal,
  never a default). Class attributes: width floor, spacing class —
  noisy/quiet separation as class-pair clearance in the card's
  `space(layer, a, b)` form — shield rule, allowed tiers, routing
  priority, bundle membership, and matched groups with tolerance in µm
  AND ohms (the 28 nm tile's differential legs matched to 0.61 % in ohms
  is the precedent; a matched pair is legs, not nets).
- **The current map is the real gap.** Currents are declared today
  (`PIN_CURRENT_MA` tuned to game via counts; 148 of xt011's 216 taps on
  assumptions that can be 25× off). Extend `ir_grid.py`: operating-point
  currents at block ports, propagated per-branch down the net tree, so EM
  floors trace to provenance-carrying numbers. Until it lands, declared
  values carry provenance and an explicit margin.

## 4. Open source, assessed

**OpenROAD/TritonRoute** — right for the digital lane (the tsmc28 port
continues there); wrong core for analog/glue: LEF58-bound (the port
*measured* 33 dropped LEF58 statements), DEF-out not OA, no first-class
EM/R widths or matched legs, and the glue problems are 10–170 nets whose
hard part is exotic top-metal rules the in-house core already encodes.
Kept as an optional bounded benchmark arm. **Qrouter** — rejected: legacy
digital maze with a weaker rule model than `glue_solver`, same LEF burden.
**ALIGN/MAGICAL** — constraint-schema ideas only.

## 5. Phases

| # | what | gate |
|---|---|---|
| 0 ✅ | Freeze + characterize: corpus in `routekit/corpus.json`; snapshot-vs-scratch policy fixed | every signed artifact replays / verifies — DONE 2026-08-26, see §6 |
| 1 ✅ | Extract `geom` + `audit` (tsmc28's `audit.py` the base) into routekit; consumers re-point through shims; ADR-0002 records the seam extension | existing route tests green on vendored copies; `sync.py --check-all` clean — DONE 2026-08-26, see §6 |
| 2 | RoutingCard schema + probe kit; dense-layer rule kinds and EM/RC cards from day one; fix known-wrong values through the card (`P_METAL_FAMILY`, VIAGEO, `M9_VIA8`) | per-repo golden rule-probe DRC run; deliberate violations must fire (satisfies sky130 roadmap item 10) |
| 3 | Promote the solver + the widen/elec unit; delete the tsmc28 byte-copy | tsmc65 replays the frozen corpus; tsmc28 digests green; inter-repo diff = adapters only |
| 4 | Three live consumers: tsmc65 v2 glue re-route; finish the tsmc28 tile (48/71 → all, then the 11 escapes when ports exist); xt011 `gen_core_route.py` as an import | each routes on the vendored core, audits green, signoff diff clean vs frozen baseline; no new solver file anywhere |
| 5 | Down the stack: legality M3→M1 one regime at a time (rule-probe negative controls); block-level pilot — one NEW cell per node, zero hand route tables; current map lands; retire duplicates (freeze `rengine/`, collapse xt011's via tables onto the card) | a new cell routes DRC/LVS-clean per node; EM floors trace to computed currents; one via-map definition per repo |
| 6 | Optional: OpenROAD benchmark arm (DEF model of the tile glue, cluster `drt`, comparison memo) | memo written; no flow depends on it |

## 6. Phases 0–1 — done, and what they measured (2026-08-26)

**Phase 1.** `routekit/geom.py` (union-find, subtract/uncovered, exact
union area, boundary edges) and `routekit/audit.py` (the full tier-1
gate family) extracted from tsmc28's `audit.py` with one mechanical
change: every process fact arrives through a `rules` object, and a rules
object that cannot answer raises. 37 upstream gates beside them, every
check paired with a poison control. `sync.py` carries five new FILES
entries (18 → 23; 92 checks per `--check-all`, run clean); ADR-0002
records the seam extension. Consumers:

- **tsmc28 re-pointed**: `analog/engine/layout/audit.py` is now the
  28 nm *binding* (rule accessors + `shorts`' one default), public API
  unchanged for its 21 importers. Witnessed by the full suite — 683
  passed / 1 skipped / 1 failed both sides of the re-point, the failure
  being the pre-existing CDAC mirroring plan test.
- **tsmc65 / sky130**: vendored and committed; nothing imports the
  engine there yet (tsmc65 re-points with the solver in phase 3;
  sky130 after its cards). tsmc65's 136/136 glue replay re-verified
  green after vendoring.
- **xt011**: vendored into the working tree, commit DEFERRED — a live
  session is mid-rework on ring revision 3 (uncommitted
  `ancbrain_ring.*` edits; its power gates read 17/43 mid-refactor,
  which is that session's state, not vendoring fallout). Commit the
  `routekit/` directory there once that session lands its work.

## 6a. Phase 0 — done, and what it measured (2026-08-26)

- **tsmc65 @ 552ead53:** the signed snapshot re-solves **136/136, 0 gate
  findings** (audits all zero). From-scratch is **deterministic** — two
  clean-slate `--json` runs byte-identical (run in a throwaway worktree;
  the tracked snapshot was never touched). From-scratch vs the grown
  snapshot now differs on **83/136 state records** (was 17 on
  2026-08-04): the snapshot is the product of its own history, exactly as
  its own docstring says. **Policy fixed:** the snapshot is frozen by
  hash; the core is gated on determinism + gates-green, never snapshot
  equality.
- **xt011 @ 97faf4b (routes signed at 8e238ce):**
  `gen_ring_power_geom.py` replays `ancbrain_ring_power.route`
  **byte-identically** at the signing commit. All four offline gate
  suites pass: 44/44, 26/26, 93/93, 16/16 — with `PYTHONUTF8=1` on
  Windows (41 gates fail under cp1252; the scripts open files without
  `encoding="utf-8"` — small upstream fix candidate). The taps replay
  (`gen_ring_taps.py`) needs the streamed GDS and stays a cluster item.
  Note: ring **revision 3** landed 2026-08-26 (`ancbrain_ring.json`
  moved), so any replay must pin 8e238ce.
- **tsmc28 @ 5cec672:** `test_tile_tracks.py` + `test_netlist_route.py`
  — 7/7 (the DFF shape digest included).
- **The tile's first signal route is committed** (was cluster-only when
  first surveyed): the driver landed via tsmc28 PR #17 with the 47/71
  run's JSON, and commit `2718228` pulled the later 48/71 run back from
  asic7.
- Hashes, commits, replay commands and per-entry results:
  [`routekit/corpus.json`](../routekit/corpus.json).

## 7. Decisions

Taken (2026-08-26, with the owner): adopt the plan; **one search core for
all levels** (supersedes the earlier two-product split); constraints as
data per §3 including keepouts and net classes; snapshot-freeze /
determinism-gate policy per §6.

Open: ADR-0002 text (phase 1 entry); whether the phase-6 OpenROAD arm is
wanted; where the cluster-side tile driver lands (suggest
`chip/floorplan/`, committed with its JSON).
