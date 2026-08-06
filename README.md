<!--docmeta
title: SPEC2SI_FLOWKIT — the shared flow policy across process nodes
genre: overview
status: active
area: top
owner: soumyajit
updated: 2026-08-05
summary: The node-agnostic core of the Spec-to-Silicon flow policy, vendored into each process repo with a drift gate and a conformance test. What is shared, what deliberately is not, and how to add a node.
-->
# SPEC2SI_FLOWKIT

The **Spec-to-Silicon** flow now runs on three process nodes:

| Repo | Node | State |
|---|---|---|
| `AIML_ASIC` | TSMC 65 nm LP | mature — full flow, signed-off chip |
| `ONR_ADFT_ASIC` | TSMC 28 nm HPC+/ULL | porting — engine partially ported |
| `XT011_ASIC` | X-Fab XT011 PDSOI | bring-up — tech layer only |

Three copies of a lesson is where lessons start diverging. This repo holds
the part that must **not** diverge.

## What is shared, and what is not

**Shared: the rule set and its principle.** `policy/flow_policy.core.json`
— 17 rules, each stated as a portable principle.

**Not shared: the engine.** That is a deliberate decision, taken after
measuring the fork rather than assuming it. AIML's engine is 94 Python
files, ONR's 93 — **21 filenames overlap and only one (`mc.py`) is
byte-identical.** `netlist_route.py` differs by 2,649 lines. The divergence
is real work, not drift: Calibre vs PVS/Pegasus, PyCell vs SKILL PCells, one
substrate node vs per-tub isolation. Forcing those into one module would
produce a file of branches that nobody can reason about on any node.

**Not shared either: enforcement paths, evidence, wording detail.** The
enforcement point for `verify-log` is a Calibre report parser on one node and
a Pegasus one on another. A shared file claiming otherwise would be a lie
with a hash on it.

So the contract is narrow on purpose:

> Every consumer carries **every** core rule id in its own policy file, with
> a **status** — `enforced`, `partial`, `not-implemented`, or `waived` (with
> a reason). Its own wording, its own enforcement path, its own evidence,
> plus any process-specific rules it needs.

## `not-implemented` is a passing state

A bring-up repo declaring most of the set `not-implemented` **passes
conformance**. That is the design: the gap becomes a number printed on every
run instead of an absence nobody can see.

```
policy conformance: XT011_ASIC
  adoption: 2/17 enforced, 0 partial, 15 not-implemented, 0 waived
```

Which answers "are the repos consistent?" with a figure rather than an
impression — the same argument as counting unclassified runlog attempts, and
the opposite of a check that quietly has nothing to check.

## Distribution: vendored, with a drift gate

Chosen over a submodule, a subtree, or a package install because it costs
the consumers **nothing**: a clone stays a clone, the `deployment/bnl` rsync
push is unchanged, and the cluster keeps running raw `python3` through its
activation wrapper. The price is that real copies exist — so the copies are
hash-checked, which is the same shape as every other derived artifact in
these repos.

```bash
python3 sync.py --to C:\dev\XT011_ASIC     # vendor / update a consumer
python3 sync.py --check-all                # gate: has any copy drifted?
```

Each consumer gets `policy/flow_policy.core.json` (byte-identical) and
`policy/test_policy_conformance.py`, and runs:

```bash
python3 policy/test_policy_conformance.py
```

Never hand-edit a vendored copy. Change the core here, re-vendor, and let
each consumer decide whether its status for the changed rule still holds.

## Adding a process node

1. add it to `consumers.json`;
2. `python3 sync.py --to <repo>`;
3. write `analog/specs/flow_policy.json` in the new repo listing every core
   rule with a status — `not-implemented` for everything the port has not
   reached yet;
4. run the conformance test and commit.

## What this is not (yet)

Only the **policy** is shared today. The PDK-free modules that implement it
— `spec.py`, `provenance.py`, `runlog.py`, `regress/run.py` — still live in
`AIML_ASIC` alone, and ONR and XT011 have none of them. Sharing those is the
obvious next step and a larger one, because for the other two repos it means
*porting* as well as *sharing*. The rule set going first is what makes that
port a checklist with a number on it instead of a memory exercise.

## Plans

[`docs/em_ir_alignment.md`](docs/em_ir_alignment.md) — a fast IR-drop
calculator driven by the simulated operating point, and the prerequisite it
exposed: the EM and resistance features of the three flows are not aligned,
and both are keyed to a **metal option** that only one repo records. Carries
the measured feature matrix across the three cards, four divergences that are
defects rather than gaps, and the sequencing.

This is also the first candidate for sharing something *other* than policy: a
resistive solver touches no PDK API, so it splits cleanly into a vendored
node-agnostic half and a local half.
