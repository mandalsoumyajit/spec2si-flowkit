"""drcloop -- put the signoff deck IN the debugging loop, node-agnostically.

Design owner, 2026-08-28, closing a routing session on XT011:

    "There is no need to compute these positions. The DRC already gives you
    the positions. Move DRC into the debugging loop."

and, in the same breath, the constraint that makes it safe:

    "The addition can be smart -- it can check local metal distances to
    ensure that new spacing errors are not introduced."

That is the whole method, and this package is the part of it that does not
depend on which deck ran. Two process ports arrived at it independently --
`spec2si-tsmc65`'s R3 report-driven repair (Calibre 2024.1) and
`spec2si-xt011`'s `drc_patch.py` (PVS 23.1 / Pegasus) -- and re-derived the
same parser, the same triage shape and the same patch geometry. Three copies
of a lesson is where lessons start diverging, so the third copy lives here.

THE ONE IDEA
------------
A geometry checker in the flow is a SECOND MODEL of a question the deck has
already answered, and the two disagree about which shapes merge, about what a
via def draws, and about what a block contributes. So do not re-derive the
violating shapes from the plan: **the results database carries every offending
polygon in the top cell's own coordinates.** Read it and answer THAT.

The corollary is what keeps the answer honest. A patch is new metal, so it
owes every rule the metal beside it owes -- and the only artefact that knows
what is really there (our routes, the blocks' internals, the vias' own pads)
is the STREAM the deck read. Never the route file, which is the plan again.

WHAT IS HERE, AND THE SEAM
--------------------------
  `resultsdb`  the ASCII results database -- one parser, two vendors
  `markers`    a marker's geometry, and the patch that closes it
  `triage`     whose result is it, and did this change ADD one
  `loop`       the protocol: a control, a binding, and a convergence ledger

Everything obeys the seam `docs/em_ir_alignment.md` set for shared code: no
PDK API, no deck, no PCell, no vendor tool -- only numbers a caller's `rules`
object or a card hands in. A fact this package was not given is a REFUSAL, not
a default: a patch sized from a guessed minimum area is a patch that looks like
a fix in the next run.

Python floor: the cluster's 3.6 -- no dataclasses, no walrus, `%`/`.format`.
Stdlib only. Vendored by `sync.py` beside `routekit/` and `irdrop/`; never
hand-edit a vendored copy.

Plan of record: `docs/drc_loop.md`. Decision: `docs/decisions/0003-drc-loop.md`.
"""

__all__ = ["resultsdb", "markers", "triage", "loop"]
