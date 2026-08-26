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
| 2 ✅ | RoutingCard schema + probe kit; dense-layer rule kinds and EM/RC cards from day one; fix known-wrong values through the card (`P_METAL_FAMILY`, VIAGEO, `M9_VIA8`) | per-repo golden rule-probe DRC run; deliberate violations must fire (satisfies sky130 roadmap item 10) — DONE 2026-08-26: arms RKP_PASS on sky130 (Pegasus), tsmc28 (Calibre 11/11 incl. via probes and M7/My) and tsmc65 (Calibre 24/24, all four families + all three via tiers); the value-fix rounds landed and BOTH extract rounds are done (deckroute65.py / the deck-header reads). Open tails: a schema slot for rule APPLICABILITY (the consumer-side `min_edge_rule` key), and the wide-landing pair-construction flow finding (task_6675958d, running). xt011's card arrives with its phase-4 import |
| 3 ✅ | Promote the solver + the widen/elec unit; delete the tsmc28 byte-copy | tsmc65 replays the frozen corpus; tsmc28 digests green; inter-repo diff = adapters only — solver promoted + both repos re-pointed 2026-08-26 (see §6); widen/elec unit DONE 2026-08-26 (fifth session): the router is width-aware (Appendix F retired the translation pass), so the unit is PRODUCER-side — `elec.solve_width` promoted from `route_budget.width_for` with every §10 guard as its regression suite; tsmc65 re-pointed with a byte-identical `--json` replay and the 136/136 corpus replay green |
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

**Phase 2 core (2026-08-26).** `routekit/card.py` — the RoutingCard
contract: load/validate/bind, families and via tiers resolved by
membership lists ONLY (a shiftable side-map can no longer exist),
missing-is-a-refusal vs measured-absent-is-an-answer kept apart
structurally, the tracked/untracked NDA split supported
(`load_split`), both value shapes via `card_num`. `routekit/ruleprobe.py`
— card-driven violation/clean geometry pairs per rule kind,
self-checked against the audit engine: the offline half of the golden
rule-probe gate; skipped probes carry their reason. Schema written
field-by-field against the two real instances
([`routekit_card_schema.md`](routekit_card_schema.md)), including the
per-layer via-enclosure `overrides` that is the designed home for the
`M9_VIA8` fix, the EM/RC sections, and the current-map scope. 58
upstream gates green. What remains of phase 2:

- **the cluster arm** — sky130 DONE (Pegasus, asic9: 7 poison families
  fired, clean twin density-only). **tsmc28 DONE for the Mx family**
  (Calibre, asic7, 2026-08-26): `ruleprobe_stream.py`/`ruleprobe_run.py`
  streamed routekit's card-driven probes and every M2 probe drew its
  exact deck family — M2.S.1/2/3/7/13, BOTH min-area predicates
  (A.2+A.3), `G.4:M2i` ×4 with the vertex-count shape — the deck
  countersigning the offline engine. Four named findings: the clean
  twin's one stray `M2.S.12` (attribute by coordinate); the **M7/My
  regime is gated behind deck options** (`USER_GUIDE.M7` ×4, zero M7
  rule evaluations on bare metal — investigate before trusting an
  M7-regime offline verdict); My `line_end_space_um` and M7
  `min_area_um2` missing from the values card (extract_dr round); via
  GDS numbers still unmeasured. The four offline refusals it took to
  get there (wide-tier notch gap, named line-end skip, off-grid
  sqrt(area), layer-qualified G.4) each fired before a licence was
  spent. **ALL FOUR FINDINGS RESOLVED 2026-08-26 (second session) and
  the full arm is RKP_PASS — 11/11 probes on M2 (six spacing-family
  rules incl. S.12/S.13, A.2+A.3, G.4:M2i, and BOTH via probes) and
  M7/My (S.1/S.2, A.1, G.4:M7i), clean twin density-only.** What each
  finding turned out to be: (1) the "M7 deck options" were the SAME
  thick-tier DATATYPE gating tsmc65 measured — `M7i = (37;20)`, dt 0
  is NOUSEM7; the gridcard's `gds_layers` now records `{layer,
  datatype}` entries (M7/M8/M9 = dt 20/40/60, VIA6/7/8 = 20/40/60,
  read off the deck's LAYER MAP lines) and the streamer streams them;
  (2) `M2.S.12` attributed by marker coordinate to the line_end CLEAN
  island: the deck's line-end is a FAMILY — S.7 "space TO a line-end"
  vs S.12 "space OF two line-ends" 0.01 stricter — modelled upstream
  as the optional `line_end_pair_space` accessor (audit gate applies
  it only when BOTH facing edges are line-ends; absent accessor/None =
  prior behaviour; tsmc28's binding answers it, the PLL pin-site
  consumer keeps the S.7 semantics it depends on); (3) My line-end:
  the deck has NO plain line-end rule for My — recorded as
  min_space-governs (the sky130 precedent), which turns the offline
  spacing gate ON for M7; M7 min-area filled (A.1 header). The via
  probes then found THREE upstream clean-twin construction defects
  (pad under its own min-area; a cap plate WIDE enough to make the
  lone clean cut a redundancy case; cluster options taken from the
  wrong tier) — each fixed in `ruleprobe.py` — and one measured FLOW
  finding: **the deck's R.2 implementation rejects 2-square pairs on
  wide landings at EVERY gap in [0.08, 0.10] (its own prose ceiling),
  accepts the 0.07-floor pair only at the price of VIA2.S.5, fires on
  the single-rectangular option, and is quiet only on the 2x2
  cluster** (the `rkpair` experiment GDS, marker-attributed, one
  licence). `routing.via` builds `space = max_space` pairs, i.e. the
  rejected construction — flagged to the owner (chip task_6675958d);
  the probe's clean twin now draws the governing tier's most-redundant
  square option. The tsmc28 extract round is thereby DONE for the
  routing card.
  ⛔ **THE FLOW FINDING ABOVE WAS MISATTRIBUTED, AND task_6675958d's
  session REFUTED it (2026-08-26, its 31-island `viapair_probe`, one
  variable per island, every verdict pinned in
  `test_via_redundancy_tiers.py`).** The rkpair experiment's M3 cap
  (8·cut of margin, 1.16 µm) made every island an **R.3 site — the
  deck picks the redundancy tier from EITHER conductor**
  (`(M2Wide AND M3i) OR (M3Wide AND M2i)`), so "2-square pairs fail
  at every gap" was R.3 requiring four squares, exactly as written.
  Measured truth: **R.2 pairs are LEGAL at 0.080/0.095/0.100 — the
  ceiling merges on abutment — and fire at 0.105**; a lone slot is
  legal in either orientation on R.2; on R.3 it is the COUNT not the
  shape (4 squares as a 2×2 or a row, two slots at 0.13, or slot+2
  squares); `WITH WIDTH` reads the narrow dimension. The flow's
  `space = max_space` construction was fine all along; the REAL
  defect was model and gate asking about ONE conductor (a 0.10 µm
  stub on a 1.0 µm bus is an R.3 site the gate passed). Their fix —
  `partner_um` through `via_redundancy`/`routing.via`, the tier's
  whole option table, and the site-tier gate in `audit.py` — is now
  UPSTREAMED with three site-tier poisons, and the probe kit
  corrected (narrow strap caps so an island tests the tier it names;
  the clean twin is the governing tier's smallest square option at
  its exact ceiling). Both arms re-ran RKP_PASS on the corrected
  constructions. Lesson, permanent: **a probe's upper-metal cap sets
  the site's tier — one variable per island, and never conclude
  about a tier the island's own conductors did not select.** **tsmc65 DONE — binding, card and arm in one pass, RKP_PASS
  (Calibre, asic7, 2026-08-26): all FOUR rule families** (M1, Mx, Mz,
  Mu — this stack's ladders genuinely differ, measured). The binding is
  the OTHER designed path: no `tech/process` module exists there, so
  `rules65.py` binds `CardRules` over a card ASSEMBLED from in-repo
  measurements (`routecard65.py`: the deck-transcribed spacing
  ladder card becomes `min_space`+wide tiers with a family-identity
  refusal; §1b widths; the bisected min-areas; the deck-read via
  redundancy) — tracked template derived by scrubbing, values card
  gitignored under the repo's own `*_card.json` catch-all. 12/12
  streamed probes drew their exact per-layer families
  (M1.S.1/S.2+A.1+G.4:M1i, the M2 twins, M8.S.1, M9.S.1), clean twin
  density-only. Three rounds, three findings, each now load-bearing:
  (1) `1.8*w` stub off-grid at w=0.09 → G.4/G.1 strays both cells →
  upstream grid-snap + an on-grid guard in `ruleprobe.probes` (the
  class is now an offline refusal); (2) **the thick tiers are
  datatype-gated**: with `MIXED_SCHEME` commented out the deck reads M8
  only at (38;40), M9 at (39;60), VIA7/8 at 40 — dt-0 shapes land in
  NOUSEM8/9, draw only `USER_GUIDE.M8/M9`, and evaluate NOTHING (the
  65 nm twin of the M7/My finding; the signed chip stream already
  carries the NEW datatypes, so signoff was never exposed — the card's
  `gds_layers` now records layer AND datatype); (3) **G.4 stops at
  M7i** — no vertex rule on Mz/Mu, recorded as a measured-absent
  `min_edge_rule` in the family entries (consumer-side key; a schema
  slot for rule APPLICABILITY is a named follow-up). **The tsmc65
  extract round is DONE and deck-countersigned (2026-08-26, fourth
  session): RKP_PASS 24/24.** `deckroute65.py` (deckspace.py's
  sibling: every numeric deck VARIABLE, live conditional branch,
  tracked-no-values) feeds a `_apply_extract` overlay in
  `routecard65.py` where every value that replaces a measured bound is
  asserted INSIDE it — both min-area bisection brackets CONFIRMED by
  the deck, M1's signed-practice 0.09 width deck-exact, every prior
  deck-read constant re-confirmed. The answers: NO plain line-end
  class on this node either (S.5 is the dense corner form, S.6 the
  45° bend — flat spacing governs all four families, no pair rule,
  spacing gate ON everywhere); the via-enclosure ACROSS is a
  deck-READ zero for VIAx ("Enclosure by M2 >= 0", the EN.2 body's
  `GOOD 0 ... OPPOSITE`); VIAz/VIAu fully carded
  (cut/enclosure/redundancy/plate) with **VIA8.R.8 UNGATED** — a lone
  VIA8 is never legal, the audit gate's documented case now real;
  M8/M9 min-areas carded. Streaming all three via tiers surfaced
  three MORE probe-construction classes, each caught OFFLINE by
  selfcheck before a licence (a clean pad's across margin must cover
  the tier's nonzero across enclosure — VIAx's zero had hidden it;
  pads must respect the metal's own min-width/min-area — an M9 strap
  at cut width is 5× under M9.W.1; an ungated tier needs the clean
  twin to draw the legal cluster), plus one the deck had silently
  absorbed: **the notch probe DEGENERATES to a solid block when
  L = 4w = bar** (tsmc65 M8/M9) — masked because the spacing island
  shares the `Mn.S.` family pattern, so the earlier thick-tier notch
  OKs were vacuous; bars now outrun the bridge and the real notches
  fired M8.S.1/S.2. Via probes are cut-qualified in the scorer (three
  via islands per cell; a bare "VIA" pattern would cross-satisfy);
- **the `P_METAL_FAMILY` round, measured and deferred.** The one-line
  fix (`P_METAL_FAMILY = dict(GRIDCARD["metal_stack"]["rule_family"])`)
  was applied and the suite measured its blast radius: **10 failures in
  4 files** — seven `test_cap_dac_8bit_1_core_plan` tests, one each in
  `test_cap_dac_8bit_1_plan` and `test_cap_dac_vref_dummy_1_plan`
  (the CDAC family derives real M5/M6 geometry from the shifted
  values: `cap_dac_8bit_1_core_bp.py:724` returns
  `P.min_width("M5")`, `_def.py:836` and `_gt.py` lean on
  `space_between("M6", ...)`), plus the deliberate sentinel
  `test_adc_tile_route.py:261`. Reverted. The recipe: freeze each
  CDAC derivation at its signed value with a provenance note, one
  file at a time, each gated on its own plan test; then apply the
  one-line fix; then flip the sentinel to assert 0.1. Belongs in a
  round with the CDAC owner's attention — the signed generators are
  the tile campaign's live dependency;
- **`M9_VIA8`** — schema home exists (`enclosure.overrides`); move the
  def-file constant into the tsmc28 values card on the cluster;
- **xt011 VIAGEO** — with xt011's other deferred work, once its live
  session lands.

**Phase 3, solver (2026-08-26).** `routekit/solve.py` is the search core
promoted: the tile campaign's generalization of `glue_solver` (per-tier
via pads, phase-agnostic arrivals, per-terminal access tiers — each
documented in place to reduce exactly), behind ONE seam,
`bind(adapter, via_table, route_tiers, base, pad_via, pad_along_um,
here)`. Both TSMC ports are re-pointed through thin binding shims
(`tile_solver.py`, `glue_solver.py` — public surfaces unchanged), and
the diff between the repos is now adapters only. Gates, measured:

- **tsmc65**: from scratch through the vendored core the chip routes
  **136/136, 0 unrouted, 0 gate findings, byte-deterministic** (two
  runs, throwaway worktree); in-repo, the signed snapshot re-verifies
  PASS through the shim. The new core's from-scratch answer differs
  from the old core's on **82/136** state records — the fixed per-tier
  pad semantics (a run end claims the pad's own along extent) change
  claim classes even where the one-via-class values are flat. Both
  answers pass every gate; **the signed snapshot stays frozen** and the
  v2 re-route starts from this core.
- **tsmc28**: tracks digest 7/7 on the shim; full suite **712 / 1
  skipped / 1 pre-existing** with the shim and the `P_METAL_FAMILY`
  fix together. The byte-copy is deleted — what remains in
  `tile_solver.py` is the binding.
- Upstream: 66 routekit gates green (the bind seam has its own:
  refuse-without-route_tiers, node constants computed exactly,
  `via_cost` reducing to the flat scalar).

- **The offline self-test, controlled.** `test_glue_solver.py` (never
  run in phases 0-2; direct-run, routes the die) fails 6 under the new
  core -- measured against the OLD core at the prior commit: **3
  pre-date the promotion** (stale against the tree: the dn11
  access-stack count, the s_lvl/dn0 M6-jog nears) and **3 are pinned to
  old-core geometry**, two of them because the new core is *stronger*
  (raw maze 133 -> 136; the no-rip-up control routes all 136, so
  "displacement is load-bearing" stopped being true on this board). The
  one to chase: the bundles scenario drops one net (135/136, likely
  `dac/dn11` -- unverified). A re-pin round is chipped
  (task: re-pin test_glue_solver to the vendored core).

**Phase 3, widen/elec unit (2026-08-26, fifth session) — DONE, and
smaller than the plan feared.** The 700-line `route_widen` translation
pass was never the unit: ROUTE_BUDGET Appendix F retired it when the
router became width-aware (`solve.Tracks` takes `widths={net: um}` and
prices the whole band — machinery that rode into `routekit/solve.py`
with the phase-3 promotion and is exercised by the 136/136 corpus
replay). What remained was PRODUCER-side: **`elec.solve_width`**, the
budget→width inversion promoted verbatim from `route_budget.width_for`
with every guard the 65 nm campaign paid for as its regression suite —
the via floor as a refusal (not "w = 12 um"), the via-rule dead band
where the NARROWEST segment decides (topn's five VIAn.R.* through a
PASS), keep-what-passes idempotence (the loop-self-destruction class),
the never-below-drawn floor (§10.4's vcm 505→775 from a green gate),
and the headroom that covers the runs the price model leaves at drawn
width. Pricing selectivity (only-what-widens) stays in the consumer's
`price` callable — the seam takes callables and numbers, nothing
node-shaped. Gates, measured: seven new upstream poisons (95 routekit
gates); tsmc65's `width_for` re-pointed as a thin binding with a
**byte-identical `--json` replay** (widths AND why-prose) and the
corpus replay green (136/136, 0 findings, audits 0/0/0). One
informational drift recorded: the frozen `route_widths.json`'s `topp`
`R_drawn_ohm` reads 47.82 where today's tree prices 48.34 — pre-dating
this change (pre/post identical), a report field only, every width
decision unchanged; the snapshot-freeze policy covers it. Phase 4's
three live consumers are now the open work.

**Phase 4, first consumer (2026-08-26, sixth session) — the tile at
63/71, from 48.** The 23 "no path within the search box" failures
split by a `--solo` diagnosis mode (each net alone on a fresh,
fully-seeded board): 22 of 23 failed SOLO — a systematic defect, not
congestion — and the defect was THREE MORE MEMBERS of the same
BASE-era assumption family the driver had already named twice
("start is (x, y) on BASE"): (1) the maze start honours `start_tier`
but not the terminal's certified RUNWAY, so a decode-bus pin inside
its neighbours' tagged halos got a POINT window (one expansion, no
turn possible — a perpendicular track centre would have to sit
exactly on the off-grid pin); (2) `legal()`'s anchored exception read
`t == BASE`, so an on-tier terminal's landing run was judged
strictly against the map containing its own pin's surroundings (the
CDAC's unpublished decode-bus lines 0.16 µm off the pin line); (3)
the pin-goal arrival re-asked `bounds` without the span the goal
itself carries. Each fix is a None-default seam beside `start_tier`
(`start_span`, `legal(spans=)`, the `gl.pin` union), the 65 nm corpus
replayed green after each (136/136, 0 findings), and the consumer's
`net_probe` gained a nearest-conductor tie-break for halo frames
contested by two pins' grown boxes (untagged = a hard wall for BOTH
runways). Result, measured: **63 routed / 8 failed / 0 disconnected,
174 s wall (was 48/23, 372 s)**. The remaining eight each carry a
named diagnosis in the artifact: `Dout[1]/[7]`/`Vrefp` (M8 port-goal
legs), `HP[7]`/`LP[7]` (the bit-7 pair), `SAMP` (an anchored-claim co
0.015 off its terminal — match tolerance), `VDACn` (the array
keep-out aperture has no corridor OUT of the box; routes with the
keep-out lifted), `net31` (real contention: evicted CLK_C cannot be
re-placed). Owed upstream: maze-level unit fixtures — the gates for
these three seams are the corpus replay and the tile itself.

**Meanwhile, consumer-side (same day):** the sky130 card build-out
completed ALL FOUR of its gates (cards on asic6, PCell probe on asic8,
**Pegasus golden rule-probe on asic9** — 7 poison families fired, clean
twin density-only — and the ota6 layouts reproduced UNCHANGED by
semantic GDS digest; roadmap item 10 → DONE, three policy rules
advanced). And the `P_METAL_FAMILY` round executed the freeze-first
recipe to completion on tsmc28 main: per-cell `_SIGNED_METAL_FAMILY`
frozen maps, the sentinel flipped, suite at exact baseline.

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
