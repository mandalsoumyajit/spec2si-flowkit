"""routekit -- the node-agnostic routing core, vendored like the IR solver.

Everything in this package obeys the seam `docs/em_ir_alignment.md` set for
shared code: it touches no PDK API, no deck and no PCell -- only numbers a
card (or a caller's `rules` object) hands it. Per-node facts live in each
consumer repo; a missing fact is a refusal there, never a default here.

Vendored by `sync.py` into every consumer beside `irdrop/` and `policy/`.
Never hand-edit a vendored copy. Plan of record: `docs/routekit_plan.md`;
the regression corpus that gates every change: `routekit/corpus.json`
(upstream only, not vendored).
"""
