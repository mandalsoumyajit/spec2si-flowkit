<!--docmeta
title: RESUME — the routekit workstream, session handoff
genre: overview
status: active
area: top
owner: soumyajit
updated: 2026-08-26
summary: Where routekit stands after the 2026-08-26 sessions and the exact next actions. Phases 0-3 are done or done-with-named-tails, all on this repo's `routekit` branch (pushed, NOT merged to main): the corpus is frozen and every promotion gated on it; geom/audit/card/ruleprobe/solve/elec/gdsw are vendored to all four ports at 33 files / 132 checks; both TSMC ports route through the vendored search core (tsmc65 136/136 from-scratch deterministic, tsmc28 tile 48/71 first run); sky130's cards passed all four gates including its Pegasus golden probe; tsmc28's Calibre golden probe countersigned the engine 5/5 on M2. Next actions in order: merge decisions (this branch; the consumers' unpushed commits), the four named phase-2/3 tails (tsmc65 rules binding then its probe arm; the M7 deck-option investigation; the extract_dr round for My line-end + M7 min-area; route_widen with phase 4), then phase 4's three live consumers, all unblocked. Read the plan (docs/routekit_plan.md) for the full record; this file is only where to START.
-->

# RESUME — the routekit workstream

Last worked **2026-08-26**, across five repos in one push. **Start by
reading [`docs/routekit_plan.md`](docs/routekit_plan.md)** — it is the
plan of record with every phase's gates and measurements; this file is
the handoff: what state each repo is in, what is safe to touch, and the
exact next actions. The rendered decision page is the "Routekit"
artifact (claude.ai/code/artifact/4e69cf73-1698-4a7e-b670-191f5b3e53dd).

## The state, measured 2026-08-26 (not remembered — re-run the sweep)

```
for r in flowkit tsmc65 tsmc28 xt011 sky130; do cd /c/dev/spec2si-$r; \
  echo "$r: $(git branch --show-current) $(git log -1 --format=%h) \
  unpushed=$(git rev-list --count @{upstream}..HEAD 2>/dev/null)"; done
```

| repo | branch | HEAD | unpushed | notes |
|---|---|---|---|---|
| flowkit | `routekit` | f9a8911 | 0 (pushed) | **NOT merged to main** — the merge is the owner's call |
| tsmc65 | main | 6d959db | **8** | + the binding/arm commit; dirty: `analog/specs/runlog_stats.json` (auto-stats, theirs) |
| tsmc28 | main | 1419d44 | **9** | + the vendored refresh |
| xt011 | **`ring-rev3`** | 788d9f9 | no upstream | vendored refresh sits UNCOMMITTED in-tree again — a live ring session was mid-edit both times; commit `routekit/` there once it lands |
| sky130 | main | dbae638 | **8** | + the vendored refresh |

⚠️ **Nothing here pushes a consumer.** Every consumer's unpushed commits
are deliberate: their owners push/PR on their own flow. The flowkit
`routekit` branch is pushed but unmerged for the same reason.

## What is DONE (gates in the plan, hashes in `routekit/corpus.json`)

- **Phases 0–1–2–3**: corpus frozen (tsmc65 136/136 from-scratch
  deterministic; snapshot-vs-scratch policy fixed at 83/136 measured);
  geom + audit extracted, tsmc28 re-pointed suite-green; the card
  contract + rule probes + per-layer via-enclosure override; the search
  core promoted behind `bind()` with both TSMC ports on it and the
  byte-copy deleted; `elec.py` (EM floors with band edges, ohm pricing,
  R_max, the fixpoint contract) and the round-trip-gated GDS writer.
- **sky130 cards**: all four gates including the Pegasus golden probe
  on asic9 and UNCHANGED_GEOMETRY by semantic digest; roadmap item 10
  DONE. Its per-layer card profile is validated by `card.validate`.
- **tsmc28 golden probe (Calibre, asic7)**: M2 countersigned **5/5**
  (M2.S.1/2/3/7/13, A.2+A.3, G.4:M2i×4). Drivers:
  `chip/floorplan/ruleprobe_stream.py` + `ruleprobe_run.py`
  (`--score-only` re-scores without licences).
- **tsmc65 binding + golden probe (Calibre, asic7, 2026-08-26 second
  session): RKP_PASS, all four rule families** — `rules65.py` +
  `routecard65.py` + ported drivers; thick-tier DATATYPE gating and
  G.4-stops-at-M7i measured and carded; clean twin density-only. The
  10 named skips in `rkprobe_expected.json` are the tsmc65 extract
  round's worklist.
- **tsmc28 arm completed (third session): RKP_PASS 11/11** — M7/My
  datatype-resolved and countersigned, via probes streaming on the
  deck-read via numbers, the line-end family modelled
  (`line_end_pair_space`), extract round done for the routing card,
  and the wide-landing pair-construction flow finding measured and
  flagged (task_6675958d).
- **P_METAL_FAMILY** fixed on tsmc28 main via the freeze-first recipe
  (its chip session, commit b8a79bb); **VIAGEO** reader fixed on xt011
  byte-replay-gated at 8e238ce; **M9/VIA8** through the card with the
  def constant cross-checked (`test_card_overrides.py`).
- **test_glue_solver re-pinned** to the vendored core (tsmc65
  676a8037): the bundles net is `code9_raw` (frozen code-bus
  contention), and the shim-rebinding hazard is test-side only
  (production code only MUTATES the shared dicts, which is safe).

## NEXT ACTIONS, in order

1. **Owner decisions**: merge flowkit `routekit` → main (or PR it);
   push/PR the consumers' unpushed commits. Until the flowkit merge,
   `sync.py --check-all` gates against the BRANCH's files.
2. ✅ **DONE 2026-08-26 (second session): tsmc65 rules binding + its
   probe arm — RKP_PASS on all four rule families** (plan §6 phase-2
   has the full record). `rules65.py` binds `CardRules` over the
   assembled `tsmc65_route_card` (builder `routecard65.py`, template
   tracked, values gitignored); drivers
   `analog/engine/layout/ruleprobe_{stream,run}.py` with `drc_gds` as
   the Calibre entry. Three findings, all landed: the off-grid
   `1.8*w` stub (upstream grid-snap + on-grid guard in `ruleprobe`);
   **thick tiers are DATATYPE-gated** (M8=(38;40), M9=(39;60),
   VIA7/8 dt 40 — dt-0 evaluates NOTHING; the signed chip already
   streams the NEW scheme; `gds_layers` now carries datatypes);
   **G.4 stops at M7i** (measured-absent `min_edge_rule` in the card).
   Upstream also hardened: an annotated `null` now REFUSES in every
   `CardRules` scalar accessor (a template merged through `load_split`
   used to answer None), and a refused `via_geometry` names BOTH via
   skips.
3. ✅ **DONE 2026-08-26 (third session): the M7/My mystery + the
   tsmc28 extract round — its arm is RKP_PASS, 11/11 probes incl.
   BOTH via probes** (plan §6 phase-2 has the full record). M7 was
   the tsmc65 datatype gating exactly (`M7i=(37;20)`; gridcard now
   carries `{layer, datatype}` entries for M7/M8/M9 + all vias);
   `M2.S.12` attributed by marker to the line_end clean island → the
   line-end FAMILY is modelled upstream as the optional
   `line_end_pair_space` accessor ("space OF two line-ends" vs S.7's
   "space TO"); My line-end folds into flat spacing (no plain rule —
   the sky130 precedent), M7 min-area filled. Three upstream
   clean-twin construction defects fixed in `ruleprobe.py`, and one
   measured FLOW finding flagged (chip task_6675958d): the deck
   rejects 2-square pairs on wide landings at every gap in its own
   [floor, ceiling] window except the floor (which draws VIA2.S.5);
   only the 2x2 cluster is quiet — `routing.via` builds the rejected
   construction (`rkpair` experiment, asic7 rkprobe/rkpair_run).
4. **tsmc65 extract round** (cluster; named by its card's own
   refusals, `rkprobe_expected.json` skip list): line-end `Mx.S.5/S.6`
   to/of split (fill BOTH `line_end_space_um` and
   `line_end_pair_space_um`, or drop the pair key if the deck has no
   distinct rule), the via-enclosure ACROSS minimum, VIAz/VIAu cut
   geometry, M8/M9 min-area; the deckspace.py transcription pattern is
   the recipe, and the 28 nm deck's headers-carry-values shortcut may
   apply to the 65 nm deck's rule bodies too.
5. **Phase 4 — three live consumers, all unblocked on the vendored
   core**: the tsmc65 v2 glue re-route (this is also `route_widen`'s
   port gate — the widen/corridor/reserve machinery deliberately waits
   for it), the tile's remaining 23 search-box failures + 11 deferred
   escapes (`adc_tile_signal_route.py`, cluster), and xt011's
   `gen_core_route.py` built by IMPORTING routekit
   (`docs/core_routing_plan.md`'s PORT column becomes an import list).

## Hazards the next session inherits (each measured this one)

- **`solve.bind()` is live module state.** A test or driver that binds
  a stub must restore (see `test_solve.py`'s fixture); rebinding a
  consumer shim's module attribute touches a dead copy — patch
  `sys.modules[Allocator.__module__]` instead (test_glue_solver does).
- **PYTHONUTF8=1 on Windows** for every gate/replay (cp1252 has cost 41
  green gates and a gridcard read).
- **Reuse `verify_layout`'s RULECHECK regex over `DRC.rep`** — a
  restated parser against `drc.out` reported "(none)" on a run that had
  results.
- **The shell's cwd does not survive parallel/backgrounded calls** —
  three commands this session ran in the wrong repo and printed
  "no tests ran"; `cd` explicitly in every compound command.
- **Signed cells are never re-routed**; the corpus
  (`routekit/corpus.json`) gates every phase, and `glue_route.json`
  stays frozen by hash.
