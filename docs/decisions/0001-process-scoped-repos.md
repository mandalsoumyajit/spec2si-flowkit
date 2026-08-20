<!--docmeta
title: ADR-0001 — repos are scoped to the PROCESS, and named for it
genre: decision
status: accepted
area: top
owner: soumyajit
updated: 2026-08-20
summary: One repo per process node, designs as directories inside it, named spec2si-<process> in lowercase-with-hyphens. Decided on a count rather than a preference: every repo already holds two or more designs and exactly one process, and the divergence that forced the engine forks is per-process (Calibre vs Pegasus, PyCell vs SKILL), not per-design. The lowercase is deliberate and argued — two of these names become package identifiers, where PyPI normalizes to lowercase anyway, and case-only path errors work on Windows but fail on the cluster. Commits us to renaming on GitHub now and the local directories only with the env-var refactor — ~85 files hardcode ~/Documents/ms_pilot or ~/Documents/onr_t28.
-->

# ADR-0001 — repos are scoped to the PROCESS, and named for it

**Status:** accepted · 2026-08-20 · supersedes nothing (first record in this
repo)

## Context

Four repos, named three different ways. `AIML_ASIC` and `ONR_ADFT_ASIC`
carry a **BNL project and a funder**; `XT011_ASIC` carries a **process**;
`SPEC2SI_FLOWKIT` carries the flow system. A newcomer cannot tell from the
names which of these are the same kind of thing.

The question — process-scoped or design-scoped — turned out to be
answerable by counting rather than by preference. Measured 2026-08-20:

| Repo | Processes | Designs |
|---|---|---|
| `AIML_ASIC` | 1 (TSMC 65 nm LP) | `hybrid_adc`, `snn_readout`, `v1_hdl` (the previous, silicon-proven generation) |
| `ONR_ADFT_ASIC` | 1 (TSMC 28 nm) | `chip/tx_chiplet`, `chip/rx_chiplet` |
| `XT011_ASIC` | 1 (X-FAB XT011 0.11 µm PDSOI) | one so far |

**Every repo already holds more than one design and exactly one process.**
The process is the invariant; the design is the variable. Three further
facts point the same way:

- **The divergence that matters is per-process.** The three analog engines
  are genuine forks, not drift: 94 files against 93, 21 filenames
  overlapping, **one byte-identical**, and `netlist_route.py` differing by
  2,649 lines. The reasons are Calibre vs PVS/Pegasus, PyCell vs SKILL
  PCells, one substrate vs per-tub — every one of them a property of the
  **node**, not of the chip built on it.
- **The flowkit's contract is already per-node.** `consumers.json` carries a
  `node` field per consumer, and each repo's `flow_policy.json` is a
  per-node adoption statement (65 nm 12/18 enforced, 28 nm 1/18, XT011
  1/18). The seam was drawn here long before this ADR.
- **The cluster directories drifted toward it on their own.** `onr_t28`
  encodes the node. `ms_pilot` encodes nothing.

## Decision

1. **One repo per process node.** Designs are directories inside it; a
   `tech/` tree holds the PDK adapter, the signoff decks and the policy
   adoption.
2. **Named `spec2si-<process>`** — `spec2si-tsmc65`, `spec2si-tsmc28`,
   `spec2si-xt011`, alongside `spec2si-flowkit`. The prefix is not
   decoration: the four repos are one family and an outside reader has no
   other way to see it. The `spec-to-silicon` mark already exists in
   `AIML_ASIC/docs/assets/`.
3. **The flowkit stays node-agnostic** and is the public face of the effort.

### Why lowercase-with-hyphens, and why that is not the inconsistency it looks like

The existing four repos are `SCREAMING_SNAKE_CASE`, so the new names look
like a break in convention. They are not, and the reasoning is worth
recording because it is the kind of thing that gets re-litigated:

- **Consistency with the old names is not a constraint, because all four
  rename at once.** There is no legacy set left to match. The only question
  is which convention the *new* set should adopt.
- **Existing practice does not settle it, and not because of age.**
  `photonic-filter-flow` (first commit 2026-06), `photonic-wirebond`
  (2026-08) and `nanohub-agent-exploration` are lowercase-kebab, while
  `FDFD_PE` (2026-07), `SFQ-ViPeR` (2026-07) and these four are upper or
  mixed. Both conventions are live in the same tree in the same months.
- ⭐ **Two of these names become IDENTIFIERS, not just labels.** The
  packaging plan ships `spec2si-irdrop` and `aiml65p2-sim` as
  distributions, and PyPI normalizes every name to lowercase-with-hyphens
  (PEP 503) — as do npm, Docker and Debian. A repo named
  `SPEC2SI_FLOWKIT` publishing a package named `spec2si-flowkit` creates a
  mapping that every README, install line and import has to bridge forever,
  for nothing.
- ⚠ **Case sensitivity is a real defect source in THIS tree.** Work crosses
  Windows, WSL and a Linux cluster. Windows is case-insensitive and the
  cluster is not, so a path typed in the wrong case works locally and fails
  on `asic7` — the works-here-breaks-there shape this repo keeps writing
  gates against. All-lowercase removes the class outright. The underscore
  also costs a shift keystroke in every clone, `cd` and rsync target.
- **The brand is unaffected.** The wordmark is `SPEC → SILICON`, in caps, in
  `spec-to-silicon.svg`, and stays that way. A display brand and a
  filesystem identifier are different things.

⚠ One mechanical consequence, recorded because it is invisible until it
bites: these names differ from the current ones **by more than case**, which
sidesteps git's case-only rename problem on a case-insensitive filesystem.
Had the choice been `SPEC2SI_FLOWKIT` → `spec2si_flowkit`, that rename would
have needed two steps through a temporary name to be tracked correctly.

## What this commits us to

- **A design does not move node.** Porting one is a re-spin, which the fork
  measurement above already establishes — so there is no case where a design
  would outlive the process repo that hosts it. This is what makes the
  containment safe.
- **Adding a process** is a new repo, a `consumers.json` entry, and a
  `flow_policy.json` declaring the core rules `not-implemented` — which is a
  *passing* conformance state, by design.
- ⛔ **Rename on GitHub now; rename the local directories LATER.** GitHub
  keeps redirects, so remotes keep working the moment the name changes. The
  local paths are a different matter: **~85 files hardcode
  `~/Documents/ms_pilot` or `~/Documents/onr_t28`**, the username `smandal`
  appears 33 times, and `consumers.json`, `browse/roots.json` and the
  cluster rsync targets all carry absolute paths. Renaming the directories
  before the `MS_PILOT`/`ANALOG_ROOT` env-var refactor lands would break the
  vendoring drift gate and the cluster push on the same day. Local renames
  belong **with** that refactor, not before it.
- **The `area` frontmatter field will need to name the design** once a repo
  visibly holds several. `ONR_ADFT_ASIC` already uses sub-paths
  (`analog/char`, `analog/pex`) where `AIML_ASIC` uses flat names. Deferred:
  it is a vocabulary question like the genre set, and it belongs in
  `policy/docmeta.core.json` when it is settled.

## Alternatives rejected

- **Design-scoped repos** (one per chip). Cleanest per-deliverable boundary,
  and the right answer if chips were handed to different owners — but it
  duplicates `tech/` per chip and grows the vendoring surface from three
  consumers to six or more, each a place the drift gate must be run.
- **Hybrid: a thin process-port repo plus one repo per design.**
  Architecturally the purest split, and the best story for an outside team
  adopting only a node port. Rejected on cost, not on merit: it roughly
  doubles the repo count for a solo effort, and nothing today needs the
  separation it buys. Revisit if a process port is ever adopted by someone
  who does not want the designs.
