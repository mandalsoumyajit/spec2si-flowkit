<!--docmeta
title: The sky130 cards — what routekit needs measured, and how
genre: plan
status: active
area: top
owner: soumyajit
updated: 2026-08-26
summary: The complete card inventory spec2si-sky130 must produce before it can bind routekit — seven cards, of which six do not exist (only the stdcell inventory does). For each card, what it holds, where the value is measured from (the repo's own Cadence delivery — techfile probe, Pegasus rule-probe, Quantus qrcTech, PCell probe; NEVER quoted from open-source SKY130 forks without an identity proof, per SCOPE.md), what already exists to build on, and the definition of done. The consumer contract is frozen: routekit/audit.py's fourteen-accessor rules protocol plus the layer tables, so the card work and the upstream schema work can proceed in parallel and meet at that seam. Done = a tech/rules_sky130.py binding that answers all fourteen accessors from cards, a golden rule-probe DRC run on the cluster where every deliberate violation fires, the hv_plan/cc_plan/build_layout literals mapped 1:1 to card fields with the signed ota6 layouts reproduced unchanged, and roadmap item 10 ("placement/router facts read only through tech/") flipped to satisfied.
-->

# The sky130 cards — what routekit needs measured, and how

**For:** the agent building spec2si-sky130's process cards, in parallel
with routekit phase 2 (the shared card schema). **The seam between the
two workstreams is frozen** — `routekit/audit.py`'s `rules` protocol
(fourteen accessors, listed in §3) plus the layer tables — so neither
side waits on the other. Structure the cards to the shape of
`spec2si-tsmc28/tech/cards/tsmc28_gridcard.json` (the richest precedent);
if phase 2's schema renames fields, that migration is mechanical.

## 1. Ground rules (all from the repo's own policy, none new)

- **Measure from the Cadence delivery, never quote the open PDK.**
  `SCOPE.md` forbids importing rule values from open-source SKY130 forks
  without proving source identity with the Cadence delivery. The numbers
  come from the techfile, the Pegasus deck, the Quantus qrcTech and the
  PCells — via probes, on the cluster (`deployment/bnl/`).
- **Provenance per value:** every number carries
  `{value, unit, source, probe, date, host}` — where `source` is
  `techfile | pegasus-deck | qrctech | pcell-probe | engine-choice`.
  An *engine choice* (a track pitch, a preferred direction) is labelled
  as one, with its rationale, and is never presented as a process fact.
- **Refuse-on-missing, and "absent" is an answer.** A key the card does
  not carry is a refusal in the binding. A rule the process genuinely
  does not have (sky130 has no TSMC-style via plate-proximity family) is
  an **explicit empty value with provenance** ("measured absent,
  deck section X") — so the engine's gate returns clean by an answered
  question, not by a missing one.
- **No PDK files in git** (`.gitignore` already enforces it): the deck,
  LEF, techfile and qrcTech stay on the cluster; only measured values
  and probe scripts are committed. Measured *values* for sky130 are
  committable (the process is public); keep the provenance so that
  claim is checkable.

## 2. The card inventory

| # | card (suggested path) | exists today? | priority |
|---|---|---|---|
| 1 | `tech/cards/sky130_stack.json` — conductor graph | ❌ | **1** |
| 2 | `tech/cards/sky130_gridcard.json` — routing rules | ❌ | **1** |
| 3 | — via section of the gridcard (or its own file) | ❌ | **1** |
| 4 | `tech/cards/sky130_devcard.json` — PCell geometry | ❌ (probe exists) | 2 |
| 5 | `tech/cards/sky130_rc_card.json` — resistance/cap | ❌ | 3 |
| 6 | `tech/cards/sky130_em_card.json` — current limits | ❌ | 4 |
| 7 | density / fill card | ❌ (roadmap already tracks fill) | 5 |

The only card in the repo today is `tech/cards/sky130_scl_9t.json`
(stdcell inventory) — a formatting precedent, not a routing input.
`tech/pdk_manifest.json` records the delivery inventory.

### Card 1 — the stack / conductor graph

What `routekit.audit`'s layer tables are populated from. Holds:

- conductor list with GDS layer/purpose per name:
  `poly, diff, li1, met1..met5` (+ `prBoundary`, wells/taps for the
  placer);
- cut list and the graph — each cut names the pair it bridges:
  `licon1: (diff→li1, poly→li1)`, `mcon: (li1, met1)`,
  `via: (met1, met2)`, `via2: (met2, met3)`, `via3: (met3, met4)`,
  `via4: (met4, met5)`. Note `licon1` is a CONTACT-class entry (bridges
  more than one lower layer), exactly like the TSMC `CO`;
- the SHORT-check layer set (all metals + `li1` + `poly` — the poly
  lesson is already paid for at 28 nm and travels with the engine);
- each layer's **routing role**, as a recorded decision: `met1/met2`
  primary (the hv discipline), `met3..met5` upper, `li1` short
  gate-strap use only (the role `build_layout.il` already argues),
  `poly` gate extensions only.

Source: techfile probe (port `spec2si-xt011/tech/probes/tech_route_probe.il`
— it walks `viaDefs` and layer rules; adjust names) + the layermap.

### Card 2 — the routing grid card

Per routing conductor (`li1, met1..met5`), every value the fourteen
accessors need:

- manufacturing grid (`techGetMfgGridResolution`);
- min width; min spacing; **line-end spacing + the line-end defining
  width** (if the deck has the rule — measure; record absent if absent);
- **wide-metal spacing tiers** as `{width_gt_um, parallel_run_gt_um,
  space_um}` lists (sky130 has these — the >3 µm class on met1/met2 is
  the known example; take the values from the deck, not from memory);
- min area, and the compact-edge equivalent if the deck states one
  (record absent if absent — `min_area` A.3 then never fires, by an
  answered question);
- max width / slotting threshold if the deck constrains it;
- preferred direction per layer and track pitch — both labelled
  `engine-choice`, seeded from the proven hv discipline
  (`build_layout_cc_hv.il`: met1 H, met2 V) and the validated
  `MIN_TRACK_SPACE_UM`.

Source: Pegasus deck is the authority for DRC values; the techfile for
grid and defaults. Pattern for deck extraction:
`spec2si-tsmc28/tech/private/extract_dr.py` (runs on the cluster,
writes the card, commits values only).

### Card 3 — the via card (per cut: `licon1, mcon, via, via2, via3, via4`)

- cut size (square; record slot/rect variants if the delivery has them,
  else `via_rect_cut = absent` so the binding **raises** there, which is
  the correct 28 nm-proven behaviour for a kit with no rectangular cut);
- cut-to-cut spacing and array pitch;
- **enclosure per adjacent layer, per axis** — sky130's enclosures are
  asymmetric (the hand SKILL carries `0.115 x 0.145` met1-over-mcon and
  `0.15 x 0.20` on `hvVia12`; measure the real rule pair, those literals
  are what the card replaces);
- crowded-enclosure rule if the deck has an `EN.11`-class conditional
  (record absent if absent → the gate returns `[]`);
- **redundancy and plate-proximity families: measured-absent expected.**
  State `redundancy_tiers: []` and `plate_proximity_rules: []` with the
  deck section consulted, so `via_wide_landing`/`via_plates` answer
  clean rather than crash — this is the refuse-vs-absent distinction the
  whole card discipline turns on.

### Card 4 — the device / PCell geometry card

What the placement-seeded track-graph builder (phase 5) and any
block-level route plan needs, and what `cc_plan.py` currently hardcodes
from a hand-transcribed probe run:

- per PCell (`nfet_01v8`, `pfet_01v8`) at each used `(w, l, fingers)`:
  terminal pin rectangles per terminal (the S/D column offsets — today's
  `±0.14` source, `±(L + 0.14)` drain at `cc_plan.py:65-69`), gate x,
  column width/pitch;
- the abutment distance (`SOURCE_ABUT_UM = 0.28`) as a measured value;
- the PCell trap, recorded as data: `w` AND `fw` AND `fingers` must all
  be set or the callback silently emits default geometry
  (`build_layout.il:3-5`);
- tap/well cells' fixed geometry (`sky130_fixed_cells.il` output).

Source: `tech/probes/sky130_mos2_pcell.il` already dumps exactly this —
the work is a probe-output→card writer, so the probe run IS the card and
nothing is transcribed by hand again.

### Card 5 — the RC card

Sheet resistance per conductor, via resistance per cut, area/fringe cap
as available — from the Quantus qrcTech the digital flow already points
at (`tech/digital.tcl` → `SKY130_QRC_TECH`). Pattern:
`spec2si-tsmc28/tech/probes/extract_qrc_rc.py`. Consumer: the
route-budget/ohm-pricing layer (routekit phase 3); nothing blocks on it
for basic DRC-legal routing.

### Card 6 — the EM card

Idc limits per conductor width and per cut, with temperature derating,
from whatever the Cadence delivery states. If the delivery carries no EM
data (plausible for this kit), the card says so explicitly with the
sources consulted — the elec layer then refuses EM floors rather than
inventing them, and IR-only sizing applies.

### Card 7 — density / fill

Window sizes and min/max density per layer. Already tracked by the
repo's roadmap for signoff; lowest priority for routing. Record it as a
card when it lands so the router can price fill keepouts later.

## 3. The consumer contract (frozen — do not wait on phase 2)

The binding deliverable is `tech/rules_sky130.py`: a rules object
answering, from cards only,

    min_space(layer)        line_end_space(layer)   wide_metal_tiers(layer)
    min_width(layer)        min_area(layer)         landing_pad(layer)
    compact_edge()          via_geometry(cut)       via_enclosure_crowded()
    via_tier(cut)           via_redundancy_tiers(t) via_pair_space(cut)
    via_rect_cut([cut])     plate_proximity_rules()

plus the layer tables (`metals`, `short_layers`, `via_met`, `contact`)
from Card 1, passed as the keyword arguments `routekit.audit` already
takes. Missing card key → raise. Measured-absent → the documented empty
answer. `spec2si-tsmc28/analog/engine/layout/audit.py` is the worked
example of a binding (its accessors come from `tech/process.py`; here
they come from the JSON cards directly — sky130 has no process.py and
does not need one for this).

## 4. Definition of done (the phase-2 gate, sky130 edition)

1. **Contract**: `tech/rules_sky130.py` binds every accessor;
   `routekit/test_audit.py`'s stub swapped for the real binding runs the
   engine clean on a synthetic clean layout and FIRES on the poison
   twins (the upstream tests already encode both).
2. **Golden rule-probe**: one probe cell per rule class with deliberate
   violations, streamed and run through Pegasus on the cluster — every
   expected rule must fire (negative control), and a clean twin must
   pass. The expected-findings manifest is committed beside the probe.
3. **Replacement proof**: a table mapping every literal in
   `hv_plan.py`, `cc_plan.py`, `build_layout*.il` to its card field
   (file:line → card path), and `hv_plan.py` re-validated **from the
   card** with the signed `sky130_ota6*` layouts reproduced unchanged
   (their strmout digest must not move — signed cells are never
   re-routed, and a card that moves them is wrong or the literal was).
4. **Roadmap item 10** ("analog engine adapter — placement/router facts
   read only through `tech/`") flips to satisfied, and
   `analog/specs/flow_policy.json`'s `derive-from-geometry` moves from
   `not-implemented` toward `partial`/`enforced` with the card as its
   evidence.

## 5. What already exists (do not rebuild)

- probes: `tech/probes/sky130_mos2_pcell.il` (PCell pins — Card 4),
  `sky130_mos_pcell.il`, `sky130_fixed_cells.il`, `oa_probe.il`,
  `pdk_probe.py`; xt011's `tech/probes/tech_route_probe.il` (techfile
  rules/viaDefs — port for Cards 1–3); tsmc28's `tech/private/extract_dr.py`
  (deck→card) and `tech/probes/extract_qrc_rc.py` (qrcTech→card)
  patterns;
- cluster paths: `tech/digital.tcl` (`SKY130_QRC_TECH`, LEF, GDS
  accessors — LEF is a cross-check for the digital layers, never the
  authority for analog rules), `deployment/bnl/` for access,
  `tech/pdk_manifest.json` for the delivery inventory;
- signoff: `tech/signoff/run_drc.sh` (Pegasus) for the golden-probe
  runs; `SKY130_DRC_ALLOW_DENSITY=1` exists for density-only gating;
- the engine itself: `routekit/` is already vendored into the repo
  (committed 2026-08-26) with its 37 gates — `python -m pytest routekit/`
  is the fastest smoke that a binding is wired right.
