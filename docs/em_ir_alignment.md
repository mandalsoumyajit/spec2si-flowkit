<!--docmeta
title: EM sizing and IR drop — aligning three cards, then computing a voltage
genre: decision
status: active
area: top
owner: soumyajit
updated: 2026-08-06
summary: Plan for a fast IR-drop calculator fed by the simulated operating point, and the prerequisite step it exposed — the EM and resistance features of the three flows are not aligned, and both are keyed to a metal option that only one repo records.
-->
# EM sizing and IR drop

*2026-08-06. The objective is **quick feedback during interconnect sizing**,
not a Voltus replacement. Voltus stays the signoff authority and the
correlation target; this is the number you want before you have a routed
block to give it.*

## 1. The gap, in the repos' own words

`ONR_ADFT_ASIC/chip/floorplan/pll_rails.json`, `_still_open`:

> IR drop is NOT modelled anywhere in this repo — `em_power.py` sizes for
> current density only. A 1.1 mA rail that meets EM can still drop
> millivolts a VCO's phase noise cares about, and VDDL is the supply whose
> noise becomes phase noise directly.

`ONR_ADFT_ASIC/tech/probes/extract_metal_res.py` opens with *"Nothing in
this repo could compute an IR drop."* That probe fixed half of it — the
metal sheet resistance was in the tech LEF the whole time. The other half
is a solver and the currents to drive it.

**EM and IR are the same knob and different criteria, and they do not bind
in the same place.** EM binds on the highest-current segment, near the pad.
IR binds on the longest cumulative path, at the far tap. An EM-clean grid
can have a far-end drop that EM sizing is structurally incapable of seeing.
That asymmetry is the whole argument for the tool.

## 2. What the calculator needs, and what already exists

Three inputs. Only one of them is new code.

| input | where it comes from | state |
|---|---|---|
| currents | `op1.dc` PSF (`Vdd:p`, per instance), or a transient mean | readers exist in every needed form |
| resistance | the rules card | ONR metal only; AIML none; XT011 none |
| topology | the rail plan already on disk | exists, already carries width and layer |

**Currents.** `AIML_ASIC/analog/engine/wave.py` (`read_psf`, and it already
handles this flow's misnamed `op1.dc`), `spectre_flow.parse_value`/`afile`,
and `ONR_ADFT_ASIC/tech/probes/parse_oppoint.py` (SI-prefix aware — a naive
`float()` on a Spectre oppoint mis-scales by the prefix). Two call sites
already pull supply current off the operating point:
`AIML_ASIC/analog/engine/layout/pex_ota.py:58` and `pex_vref.py:41`.
On the transient side `ONR_ADFT_ASIC/analog/engine/char/libgen.py`
`measure_supply_current` already returns **`(mean_A, peak_A)`** — the peak
is measured today and nothing consumes it.

**Topology.** `AIML_ASIC/analog/engine/layout/assemble_top.py` `plan_rails()`
returns `{net: {y, x1, x2, w, layer}}` and `plan["nets"]` carries endpoints
with per-net current; ONR has `chip/floorplan/pll_rails.json` (inputs, each
with a `basis`) and the derived `pll_power.json`.

**The solver.** Nodes at taps and branch points; conductance `w/(L·Rs)` per
metal segment and `n_cuts/R_cut` per via stack; inject tap currents, pin the
pad, solve `G·v = i`. These grids are tens to a few hundred nodes — a
pure-Python LU is milliseconds and adds no dependency, which matters given
that these repos run raw `python3` through a cluster activation wrapper.

The output worth having is **both checks on one line**: per-tap drop, worst
node, the binding segment, and the EM margin on that same segment.

## 3. The prerequisite: the three flows are not aligned

Measured 2026-08-06, not assumed.

| capability | AIML_ASIC (65 nm) | ONR_ADFT_ASIC (28 nm) | XT011_ASIC (110 nm) |
|---|---|---|---|
| metal Imax | `em_card.metal_imax_ma`, keyed **by layer name** M1–M9 | `em.metal_mA`, keyed **by tier class** M1/Mx/My/Mz/Mu/Mr | — |
| Imax formula | `k·(w − dw)`, `w` **drawn** | `k·(0.9·w − offset)`, `0.9` an effective/drawn shrink | — |
| length/width boost | **hardcoded in `routing.em_width`** | `em.length_width_boost`, a card table keyed on length *and* width, per class | — |
| temperature derate | table on the card, **never read** | `em.temp_derate`, applied in `metal_imax_mA` and `via_imax_mA` | — |
| via per-cut Imax | `via_imax_ma_per_cut`, VIA1–8 | `em.via_mA`, CO + VIA1–8 | — |
| via array rule | `via_array_factor` (a **credit** for ≥2 cuts) | none — `ceil(I / per_cut)` | — |
| stack limit | `stack_imax_ma_per_stack` | none | — |
| poly Imax | `poly_imax_ma_per_um` | none | — |
| sheet resistance | **none** | `metal.<tier>.rs_ohm_per_sq`, with a `suspect` flag | — |
| per-cut resistance | none | **none** — see §5 | — |
| API surface | `routing.em_width / em_cuts / em_stack_ok` | `process.metal_imax_mA / width_for_current / via_imax_mA / vias_for_current / em_temp_derate / sheet_res / line_res` | — |

Four of these are **defects, not gaps**:

**(a) AIML applies no temperature derate at all.** `em_card.json` carries a
`temp_rating` table; `grep` finds no reader for it, and `em_width`,
`em_cuts` and `em_stack_ok` take no temperature argument. ONR applies its
derate and defaults to 125 °C. So the same rail sized on the two nodes is
sized against different physics, and on AIML it is the reference-temperature
number regardless of junction temperature. The derate spans a large factor
across its tabulated range, so this is not a rounding-order difference.
Fixing it will move existing widths — it is the change with real blast
radius, and it needs a re-spin audit rather than a quiet edit.

**(b) The width argument means two different things.** ONR's `0.9` is not a
fudge: `tech/probes/extract_via_em.py` recovered it independently from two
via tiers, at four decimals, from different densities — it is how that card
states limits, on both metal and cuts. Whether the 65 nm DRM states its
limit against drawn or effective width is **unresolved**, and it decides
whether every AIML EM width is optimistic by about 10 %.

**(c) A boost law is living in a `.py` file.** AIML hardcodes the short-line
enhancement inside `em_width`; ONR reads it from the card. Both repos'
policy says rule values do not go in tracked source. The AIML form is also
width-blind where ONR's is not.

**(d) The via array factor points in an unexpected direction.** AIML's
`em_cuts` computes `ceil(i / (via_array_factor · per_cut))`, and the card's
factor is greater than one — i.e. an array is granted a **credit**. The
conventional direction is a derate, because current crowds into the outer
cuts of an array. ONR grants no credit at all. One of the two is wrong and
the DRM decides which.

## 4. Both features are keyed to the process flavor — and only one repo records it

This is the part that must not be left implicit. **EM limits and sheet
resistance are both properties of the metal *option*, not of the node.**

| repo | node | option string | recorded where | read from |
|---|---|---|---|---|
| AIML_ASIC | TSMC 65 nm LP | `1P9M 6X1Z1U` | grid card id `tsmc65_1p9m6x1z1u`; deck path `CLN65S_9M_6X1Z1U.24a` | implicit — no `process` section |
| ONR_ADFT_ASIC | TSMC 28 nm HPC+/ULL | `9M_5X1Y1Z1U_UT-AlRDL`, flavor `HPC_PLUS`, PDK `CRN28HPC+ULL_v1.8_2p3a_20211109` | `tech/cards/tsmc28_gridcard.json` → `process` | the `nch_mac` CDF `pdkVersion` parameter |
| XT011_ASIC | X-FAB XT011 PDSOI | option `1157` — **adopted, not decoded**; `metal_count: null` | `tech/cards/xt011_gridcard.template.json` → `process` | reference designs |

Read the two TSMC options against each other:

- `6X1Z1U` — above M1, six thin (X), one thick (Z), one ultra-thick (U).
  So M2–M7 thin, M8 = Z, M9 = U.
- `5X1Y1Z1U` — five thin, one intermediate (Y), one Z, one U.
  So M2–M6 thin, **M7 = Y**, M8 = Z, M9 = U.

Both are nine-metal stacks. Both have an M7. On one node M7 is a thin tier
and on the other it is an intermediate one — **different rule family,
different `k`, different minimum width, different sheet resistance, same
layer name.** A layer name carries no EM or resistance meaning without the
option string beside it.

This is not hypothetical. It has already fired once, on the only node that
has an explicit map: `ONR_ADFT_ASIC/tech/process.py` `METAL_CLASS` had M6,
M7 and M8 each mapped one tier too high, and **M8 landed on `Mr`, the
aluminium redistribution tier, whose limits are far more permissive** — a
power rail on M8 would have been sized against the wrong metal entirely.
Corrected 2026-07-31 against the tech LEF's own minimum widths, which
identify each tier unambiguously. The card's `metal_mA` still carries an
`Mr` entry that `METAL_CLASS` deliberately maps nothing to.

AIML has no such map. Its `em_card.json` is keyed by layer name, so
`6X1Z1U` is encoded in it *implicitly*, with no place for the assumption to
fail. A shuttle flavor change would leave every number in it silently
wrong. The card's own `_stack` note records that it stopped at M7 until
2026-07-31 and had to be extended to the thick tiers — which is the same
fact discovered the hard way rather than declared.

XT011 cannot write either card yet, and should not try. Its `CLAUDE.md` is
already explicit: *"`1157` is adopted from the reference designs, not
decoded. It must hold identically across `PRIMLIB_1157`, `TECH_XT011_1157`,
the PVS runset `XT011_1157`, and the Tanner tech library. Any flavour change
moves all of them together. Do not freeze a grid card before SCOPE WP 0.5
decodes it."* The EM and resistance sections inherit that discipline: schema
now, `null` values that **raise** at the point of use, populated after WP 0.5.

**The requirement that follows.** On every node:

1. the layer → tier-class map is an explicit **card** artifact, derived from
   the tech LEF's minimum widths (which identify a tier unambiguously) and
   never from a layer's name or index;
2. every EM and resistance entry is stamped with the **option string** it
   was read under, alongside the rule or file that fixed it;
3. an option change invalidates both cards together — they are one fact with
   two consumers, not two facts.

## 5. Open questions

**Settled 2026-08-06 — per-cut via resistance is not available.** The
populated ONR rules card carries `rs_ohm_per_sq` on all five metal tiers and
**no `r_ohm_per_cut` on any of its six via tiers**. `extract_metal_res.py`
has a correct parser for it (a `RESISTANCE` line is ohm/sq on a `ROUTING`
layer and ohm/cut on a `CUT` layer — one column, two units), so the parser
ran and found nothing: the 28 nm tech LEF has no `RESISTANCE` on cut layers.
`process.line_res`'s "metal only, so this is a **lower bound**" caveat is
therefore correct, and the claim in `extract_metal_res.py`'s own title line
that it extracts per-cut resistance is not currently met. **Any IR number
this flow produces is a lower bound until a per-cut resistance is sourced
elsewhere** — the DR document, the QRC tech file, or measurement. On a rail
climbing M2→M9 the via stacks are often the dominant term, so this decides
whether the tool is useful or merely directional. It is the highest-value
open item.

**Does the effective/drawn shrink apply to resistance too?** If the LEF's
`RPERSQ` is per square of *drawn* width while the conducting width is
`0.9·w`, then `line_res` — which divides by the drawn width — is optimistic
by about 11 %. Answer it, don't assume it.

**DC vs AC limits — the repo contradicts itself.** `tech/process.py`'s
2026-07-31 correction states the tech LEF carries `DCCURRENTDENSITY` on all
nine routing layers *and* `ACCURRENTDENSITY` beside it.
`analog/engine/char/libgen.py:1177` states the technology LEF carries **no**
`ACCURRENTDENSITY`. Both cannot be true, and it bears directly on the
transient half of this plan.

**Three currents, not one.** A transient yields `I_avg` (the EM DC rule —
what `divider_idd.py` measures), `I_rms` (Joule self-heat, which feeds back
into the temperature derate), and `I_peak` (static IR worst case).
`divider_idd.py` names the gap: *"a via array sized for the average is not
sized for `Irms`. No rule in the card asks for those, and nothing here
models it."*

## 6. Where the code should live

The flowkit's contract is deliberate — **shared rule set, not shared
engine** — and it was set on measured evidence: 94 Python files against 93,
21 overlapping filenames, exactly one byte-identical.

An IR solver is the rare piece that is genuinely node-agnostic: it touches
no PDK API, no deck, no PCell, only numbers a card hands it. So it splits
along the seam that already exists here:

- **vendored, byte-identical, hash-gated by `sync.py`**: the solver and the
  report schema;
- **local to each repo**: the resistance lookup, the current reader, and the
  topology adapter.

Plus a new core policy rule — `supply-drop-is-computed` — so XT011 carries
it as `not-implemented` and the gap is *counted* rather than invisible,
which is what that contract is for.

## 7. Voltus

Worth doing, and cheaper than expected: the recipe is already written down
in `AIML_ASIC/dig_flows/dig_tools_dig_flow_18.x_19.x/CERN_generic_flow_2020/built_project/signoff/voltus/`
— `voltus_init.tcl` (`read_db`, `read_spef` across three RC corners,
`check_pg_shorts`, `check_power_vias`, `set_pg_nets`,
`set_rail_analysis_domain`, `write_pg_library` → `techonly.cl`), plus
`voltus_static.tcl`, `voltus_dynamic.tcl` and `em_analysis.tcl`. It needs a
QRC tech file and a license check on the cluster.

Its role here is **correlation, not competition**. `ctrl_top` is the one
block with a real Innovus PG mesh (29 % / 27 % M8/M9 occupancy per
`AIML_ASIC/hybrid_adc/POWER_PLAN.md`), so it is the natural place to run
both and measure how far the fast estimate lands from signoff.

## 8. Sequencing

Alignment first — the calculator is not worth building on two cards that
disagree about what a width means.

| # | step | repo | note |
|---|---|---|---|
| 1 | stamp the option string into every EM/resistance entry; make the layer→tier map a card artifact | ONR | the map already exists in `process.py`; move and cite it |
| 2 | add the EM + resistance schema as `null`s that raise | XT011 | schema only; populate after SCOPE WP 0.5 decodes `1157` |
| 3 | locate the 65 nm tech LEF / QRC tech file; write the `extract_metal_res.py` equivalent | AIML | unblocks IR on the mature node |
| 4 | give the AIML EM API a temperature and read `temp_rating` | AIML | **moves existing widths** — needs a re-spin audit |
| 5 | move the AIML length/width boost onto the card | AIML | rule values out of tracked source |
| 6 | resolve drawn vs effective width against the 65 nm DRM | AIML | §3(b) |
| 7 | resolve the via array factor direction | AIML + ONR | §3(d); one of the two is wrong |
| 8 | source a per-cut via resistance, or label every result a lower bound | ONR first | §5 — highest value |
| 9 | the solver, vendored; the new core policy rule | flowkit | §6 |
| 10 | correlate against Voltus on `ctrl_top` | AIML | §7 |

Steps 1–3 are independent and can run in parallel. Step 4 is the one with
blast radius. Step 8 gates whether step 9's output is a value or a bound.

## What this document does not contain

No rule values. The EM constants, derate tables, boost tables and sheet
resistances are foundry-confidential and live in the gitignored cards
(`AIML_ASIC` `em_card.json`, `ONR_ADFT_ASIC` `tech/cards/rules_card.json`).
What is recorded here is **structure** — which keys exist, which are read,
which formula shape each node uses, and which option string fixes them.
