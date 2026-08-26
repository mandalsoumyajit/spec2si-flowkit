<!--docmeta
title: ADR-0002 — the routing core is vendored; the process stays home
genre: decision
status: accepted
area: top
owner: soumyajit
updated: 2026-08-26
summary: The "shared rule set, not shared engine" contract gains one clause — node-agnostic ROUTING code is vendored from flowkit exactly as the IR solver is, because the seam em_ir_alignment.md defined ("touches no PDK API, no deck, no PCell, only numbers a card hands it") has now been demonstrated to hold for a router, twice, in silicon-relevant use. Evidence, not preference — tsmc28's tile_solver is tsmc65's tapeout-proven glue_solver byte-for-byte behind a ten-symbol adapter, surfaced exactly two port defects (both adapter numbers, both caught offline), and routed the 28 nm tile's first 48 nets; xt011's chip-top plan independently chose to port the same family rather than write a fifth router. What vendors: geometry, the tier-1 audit engine (phase 1), the search core and its electrical/widen unit (phase 3), all rule access through a `rules`/card object where a missing value refuses. What never vendors: rule values, probes, OA/SKILL drawers, signoff drivers, per-node adapters. The gate on every phase is the frozen corpus in routekit/corpus.json — promotion never changes signed geometry.
-->

# ADR-0002 — the routing core is vendored; the process stays home

**Status:** accepted · 2026-08-26 · amends the sharing contract stated in
[`em_ir_alignment.md`](../em_ir_alignment.md) §6; supersedes nothing.

## Context

The 2026-08-26 survey ([`routekit_plan.md`](../routekit_plan.md) §1) found
seventeen hand-built router codebases across the four ports, forked at the
wrong boundary: the route-plan divergence between nodes is real, but the
occupancy models, via arithmetic, geometry sweeps and audit gates were
duplicated with it — and the copies drift (552 lines on `rengine/`, four
via tables in one repo, two via-card readers that disagree).

This repo's standing contract is **shared rule set, not shared engine**,
set on measured evidence that the *engines* genuinely diverge (Calibre vs
Pegasus, PyCell vs SKILL). That evidence still stands. What changed is
that a second measured fact now stands beside it.

## The fact

`spec2si-tsmc28/analog/engine/layout/tile_solver.py` is
`spec2si-tsmc65/hybrid_adc/floorplan/glue_solver.py` **byte-for-byte below
its header**, consuming the 28 nm process through a ten-symbol adapter
(`tile_abstract.py`). The port surfaced exactly two defects — both wrong
numbers in the adapter, both caught by an offline test — and on 2026-08-25
the ported copy routed the 28 nm tile's first 48 nets, driven through a
subclass that overrides only `seed()`. The router core sits on the
shareable side of the seam `em_ir_alignment.md` drew: it touches no PDK
API, no deck, no PCell — only numbers a card hands it.

## Decision

1. **`routekit/` lives in this repo and vendors through `sync.py`**, file
   by hash-gated file, exactly as `irdrop/` does. Phase 1 vendors the
   geometry (`routekit/geom.py`) and the tier-1 audit engine
   (`routekit/audit.py`, extracted from tsmc28's `audit.py` — itself the
   65 nm audits made a module). Phase 3 vendors the search core and its
   electrical/widen unit. Tests ship beside the code, as the solver's do.
2. **Every process fact crosses one seam.** Engine functions take a
   `rules` object (phase 2 formalizes the card that populates it); a rules
   object that cannot answer raises, which is a refusal and not a pass.
   Layer vocabularies are parameters with M1..M9 defaults.
3. **What never vendors:** rule values and their probes, EM/RC cards,
   OA/SKILL drawers (`oa_worker`, `route_cml.il`), signoff drivers
   (Calibre / PVS / Pegasus), and each node's adapter. A consumer's shim
   binds its own `tech/process.py`-class accessors and keeps its public
   API; behaviour under the shim must be identical, witnessed by that
   repo's own test suite.
4. **The corpus gates every phase.** `routekit/corpus.json` freezes the
   signed artifacts by hash with their replay commands; promotion of
   shared code never changes signed geometry, and the tsmc65 core is
   gated on from-scratch determinism + gates-green, never on snapshot
   equality (the 83/136 divergence is measured and recorded there).
5. **Signed cells are never re-routed.** Constructive routers freeze for
   what they signed and are deprecated for new work; the array pattern
   generators and supply synthesis stay constructive by design.

## Consequences

* A fifth router does not get written: tsmc65's v2 re-route, tsmc28's
  tile completion and xt011's `gen_core_route.py` all consume the
  vendored core through adapters (plan §5, phase 4).
* `sync.py --check-all` now checks 23 files per consumer; a drifted
  routekit copy fails the same gate a drifted policy core does.
* The audit engine's lessons — the ones paid for in cluster round trips —
  travel: xt011 and sky130 receive the same shorts/opens/spacing/via
  gates the two TSMC ports converged on, parameterized by their own
  cards when those exist.
* The known risk is named in the plan (§7): the M1-regime legality model
  is the long pole for taking the SEARCH core down the stack; if it
  stalls, the engine holds at M2-and-up and the frozen constructive
  routers persist at M1 only.
