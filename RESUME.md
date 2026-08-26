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
| flowkit | `routekit` | 996a78b | 0 (pushed) | **NOT merged to main** — the merge is the owner's call |
| tsmc65 | main | e8eb950 | **7** | dirty: `analog/specs/runlog_stats.json` (auto-stats, theirs) |
| tsmc28 | main | 190c282 | **8** | includes the tile 48/71 JSON, the audit/solve bindings, P_METAL_FAMILY, the probe arm |
| xt011 | **`ring-rev3`** | 788d9f9 | no upstream | the vendor + VIAGEO commits ride this branch; merges with the ring work |
| sky130 | main | ac740a1 | **7** | includes the card build-out (all four gates passed) |

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
2. **tsmc65 rules binding, then its probe arm.** `routing.py`'s helpers
   are not the fourteen-accessor protocol; write the binding on the
   tsmc28 `audit.RULES` pattern (its rules live in
   `tsmc65_gridcard.json` + the deck), then reuse the tsmc28 probe
   drivers with `drc_gds.py` as the Calibre entry (it takes any GDS).
3. **The M7/My deck-option investigation** (tsmc28): probes on M7 fire
   nothing while `USER_GUIDE.M7` ×4 fires — the deck gates the My
   regime behind options/markers a bare-metal stream lacks. Read the
   deck's USER_GUIDE.M7 body; do NOT trust an M7-regime offline verdict
   until settled. Also attribute the clean twin's one stray
   (`M2.S.12`=1) from `analog/work/rkprobe/rkprobe_clean/DRC_RES.db`
   coordinates and refine that probe.
4. **extract_dr round** (cluster): add My `line_end_space_um` and M7
   `min_area_um2` to the tsmc28 values card; measure the via GDS
   numbers (`gds_layers` "still to read") so the via probes can stream.
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
