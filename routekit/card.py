#!/usr/bin/env python3
"""The RoutingCard contract: load, validate, and bind a rules card.

This formalizes the card discipline the tsmc28 port converged on, so the
other three ports (and phase 3's solver) consume process facts one way:

  * a card is JSON. A repo may split it in two -- a TRACKED structure
    card (identifiers, laws, provenance, family membership) and an
    UNTRACKED values card where the numbers are foundry-confidential
    (tsmc28's `rules_card.json`, rebuilt on the cluster). `load_split`
    merges them; a public process (sky130) ships one file.
  * a value is either a bare number or `{"value": x, "rule": "Mx.W.1",
    ...provenance}` -- `card_num` accepts both, because the annotated
    form exists precisely where the rule number and the LEF disagree and
    someone had to say which is which.
  * **a metal's rule family is resolved by the family's own `layers`
    list, and ONLY by it.** The alternative -- a separate layer->family
    map -- is how tsmc28's `P_METAL_FAMILY` shipped shifted a tier for
    M5/M6/M7 and handed M7 rules four times too large, measured and
    worked around in five places before it was fixed. This module does
    not offer a side-map to get wrong: no `layers` list names the layer,
    `CardError` names the layer.
  * **missing is a refusal; absent is an answer.** A key the card does
    not carry raises `CardError` with the card path that needs the
    measurement. A rule the process genuinely lacks is recorded as an
    explicit empty (`"redundancy_tiers": []`) with provenance -- the
    engine's gate then returns clean by an answered question.

`CardRules` binds a resolved card to the fourteen-accessor `rules`
protocol `routekit.audit` documents, so a consumer with a conforming
card needs no hand-written binding at all (tsmc28 keeps its
`tech/process.py` binding -- both satisfy the same protocol; new ports
start here).

Python floor: the cluster's 3.6 -- no dataclasses, no walrus, `.format`.
"""
import io
import json


class CardError(KeyError):
    """A process fact the card does not carry. The message names the card
    path to fill and, where known, the probe that measures it."""


def load(path):
    """One card file, UTF-8 always -- cp1252 Windows defaults have cost
    41 green gates before (`routekit/corpus.json`, windows_note)."""
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_split(structure_path, values_path=None):
    """A tracked structure card, optionally deep-merged with an untracked
    values card (values win key-by-key). Returns the resolved dict.

    A missing values FILE is not an error here: the resolved card simply
    lacks the numeric keys, and every accessor that needs one refuses
    with the card path -- which turns "the confidential card is absent"
    into per-fact refusals instead of an import-time crash, exactly the
    behaviour tsmc28's `routing_rules()` chose."""
    card = load(structure_path)
    if values_path is not None:
        try:
            values = load(values_path)
        except (IOError, OSError):
            return card
        card = _deep_merge(card, values)
    return card


def _deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def card_num(v, default=None):
    """A number out of the card, whichever shape it is stored in --
    bare (`0.4`) or annotated (`{"value": 0.05, "rule": "Mx.W.1"}`).
    Assuming one shape is a measured failure mode: a pitch computed as
    float + dict died on the first real cell it was asked to build."""
    if isinstance(v, dict):
        return v.get("value", default)
    return default if v is None else v


def _need(entry, key, where):
    if key not in entry:
        raise CardError(
            "no {} recorded at {} -- measure it and add it to the card "
            "(a missing fact is a refusal, never a default)".format(
                key, where))
    return entry[key]


def _num(entry, key, where):
    """A REQUIRED number: present AND filled. A tracked template records
    an unfilled fact as `null` (bare or `{"value": null}`) so its schema
    and rule ids stay under version control -- and a consumer that binds
    `load_split(template, values)` merges those nulls in. `card_num`
    alone answers None for them, which is a default wearing a card's
    clothes: the 65 nm binding met it first (line-end recorded as an
    annotated null flowed into the spacing gate as None). Null refuses
    exactly as missing does, naming the same path."""
    v = card_num(_need(entry, key, where))
    if v is None:
        raise CardError(
            "{} at {} is recorded but not filled (null) -- measure it "
            "and fill the values card (an unfilled fact is a refusal, "
            "never a default)".format(key, where))
    return v


class CardRules(object):
    """The generic binding of a resolved card to `routekit.audit`'s
    `rules` protocol.

    `card` is the resolved mapping (see `load_split`). The sections it
    reads:

        metal:  {family: {layers: [..], min_width_um, min_space_um,
                          line_end_space_um[, line_end_def_um],
                          wide_metal_space_tiers: [..],
                          min_area_um2[, landing_pad_um], max_width_um}}
        via:    {tier: {cut_layers: [..], cut_um,
                        enclosure: {along_um, across_um[, crowded]},
                        min_space_pair_um[, rect_cut_um],
                        redundancy_tiers: [..],
                        plate_proximity_rules: [..]}}
        min_area_um2: {compact_edge_um}      (optional; family entries
                                              may carry min_area_um2
                                              directly instead)

    Every lookup resolves the family/tier by membership lists; every
    number goes through `card_num`; every miss is a `CardError` naming
    the path."""

    def __init__(self, card):
        self._c = card

    # -- family / tier resolution, by membership lists only ----------

    def _metal(self, layer):
        metal = _need(self._c, "metal", "card root")
        for fam in sorted(metal):
            e = metal[fam]
            if isinstance(e, dict) and layer in (e.get("layers") or []):
                return fam, e
        # a single-layer family may omit `layers` and use its own name
        if layer in metal and isinstance(metal[layer], dict):
            return layer, metal[layer]
        raise CardError(
            "no metal family's `layers` list names {} -- add the layer "
            "to its family in the card (membership lists are the ONE "
            "authority; a separate layer->family map is how a port "
            "shipped M7 with M8's rules)".format(layer))

    def _via(self, cut):
        via = _need(self._c, "via", "card root")
        for tier in sorted(via):
            e = via[tier]
            if isinstance(e, dict) and cut in (e.get("cut_layers") or []):
                return tier, e
        if cut in via and isinstance(via[cut], dict):
            return cut, via[cut]
        raise CardError(
            "no via tier's `cut_layers` list names {} -- add it to the "
            "card".format(cut))

    # -- the fourteen accessors --------------------------------------

    def min_width(self, layer):
        fam, e = self._metal(layer)
        return _num(e, "min_width_um", "metal." + fam)

    def min_space(self, layer):
        fam, e = self._metal(layer)
        return _num(e, "min_space_um", "metal." + fam)

    def line_end_space(self, layer):
        fam, e = self._metal(layer)
        return _num(e, "line_end_space_um", "metal." + fam)

    def wide_metal_tiers(self, layer):
        fam, e = self._metal(layer)
        tiers = _need(e, "wide_metal_space_tiers", "metal." + fam)
        # a tier with an unfilled threshold poisons the spacing gate's
        # arithmetic (None > float raises INSIDE the gate's loop, outside
        # its accessor try) -- refuse here, naming the entry to fill
        for i, t in enumerate(tiers):
            for k in ("width_gt_um", "parallel_run_gt_um", "space_um"):
                _num(t, k, "metal.{}.wide_metal_space_tiers[{}]".format(
                    fam, i))
        return tiers

    def min_area(self, layer):
        fam, e = self._metal(layer)
        if "min_area_um2" in e:
            return _num(e, "min_area_um2", "metal." + fam)
        sect = self._c.get("min_area_um2") or {}
        if fam in sect:
            return _num(sect, fam, "min_area_um2")
        if layer in sect:
            return _num(sect, layer, "min_area_um2")
        raise CardError(
            "no min_area_um2 for {} (family {}) in the card".format(
                layer, fam))

    def landing_pad(self, layer):
        fam, e = self._metal(layer)
        return _num(e, "landing_pad_um", "metal." + fam)

    def compact_edge(self):
        sect = _need(self._c, "min_area_um2", "card root")
        return _num(sect, "compact_edge_um", "min_area_um2")

    def via_tier(self, cut):
        tier, _e = self._via(cut)
        return tier

    def via_geometry(self, cut):
        tier, e = self._via(cut)
        cut_um = _num(e, "cut_um", "via." + tier)
        enc = _need(e, "enclosure", "via." + tier)
        along = _num(enc, "along_um", "via.%s.enclosure" % tier)
        across = _num(enc, "across_um", "via.%s.enclosure" % tier)
        return (cut_um, along, across)

    def via_enclosure_crowded(self, cut=None):
        # absent is an ANSWER: a kit without the conditional rule
        # records nothing and the gate returns [].
        if cut is None:
            via = self._c.get("metal") or {}
            for fam in sorted(via):
                cr = (via[fam] or {}).get("enclosure_crowded")
                if cr:
                    return cr
            return None
        _tier, e = self._via(cut)
        return (e.get("enclosure") or {}).get("crowded")

    def via_enclosure_for(self, cut, metal):
        """A per-LAYER enclosure override, or None for the tier's own
        pair. The schema home for the measured M9-over-VIA8 class: a
        layer whose enclosure requirement differs from its tier's is
        recorded under `enclosure.overrides.<layer>`."""
        _tier, e = self._via(cut)
        ov = (e.get("enclosure") or {}).get("overrides") or {}
        if metal not in ov:
            return None
        m = ov[metal]
        return (card_num(m.get("along_um")), card_num(m.get("across_um")))

    def via_redundancy_tiers(self, tier):
        via = _need(self._c, "via", "card root")
        if tier not in via:
            raise CardError("no via tier {} in the card".format(tier))
        return _need(via[tier], "redundancy_tiers", "via." + tier)

    def via_pair_space(self, cut):
        tier, e = self._via(cut)
        return _num(e, "min_space_pair_um", "via." + tier)

    def via_rect_cut(self, cut=None):
        if cut is None:
            raise CardError("via_rect_cut needs a cut layer with this "
                            "generic binding")
        tier, e = self._via(cut)
        rc = _need(e, "rect_cut_um", "via." + tier)
        if not rc:
            raise CardError(
                "via tier {} records no rectangular cut -- the kit has "
                "none (measured absent)".format(tier))
        long_um, short_um = card_num(rc[0]), card_num(rc[1])
        if long_um is None or short_um is None:
            raise CardError(
                "rect_cut_um at via.{} is recorded but not filled (null) "
                "-- measure it and fill the values card".format(tier))
        return (long_um, short_um)

    def plate_proximity_rules(self):
        via = _need(self._c, "via", "card root")
        out = []
        for tier in sorted(via):
            e = via[tier]
            if isinstance(e, dict) and "plate_proximity_rules" in e:
                out.extend(e["plate_proximity_rules"])
        if not any("plate_proximity_rules" in (via[t] or {})
                   for t in via if isinstance(via[t], dict)):
            raise CardError(
                "no via tier records plate_proximity_rules -- record [] "
                "with provenance if the kit has none (absent is an "
                "answer; missing is a refusal)")
        return tuple(out)


def validate(card):
    """Structural findings on a resolved card, as printable strings.

    NOT a rule checker -- a card-shape checker: every finding is a way a
    card has actually gone wrong. Returns [] for a conforming card.

    Two conforming profiles exist and both are validated: the FAMILY
    profile (`metal`/`via` sections with membership lists -- the TSMC
    shape this module's `CardRules` binds) and the PER-LAYER profile
    (`routing_layers`/`vias` keyed by layer name -- sky130's shape,
    bound by its own strict `Sky130Rules`). The contract both serve is
    the fourteen-accessor protocol; a validator that only knew one
    shape would false-alarm on a conforming card, which is its own
    failure mode."""
    if "routing_layers" in card:
        return _validate_per_layer(card)
    if "metal" not in card and "via" not in card:
        # a stack, device, RC, EM or density card is a different KIND
        # with its own shape -- judging it against the routing shape
        # reports the validator, not the card. Said out loud in the
        # NOT-EVALUATED spirit, never silently passed.
        return ["NOT-A-ROUTING-CARD: no metal/via or routing_layers "
                "section -- this validator judges routing cards only"]
    out = []
    metal = card.get("metal")
    if not isinstance(metal, dict) or not metal:
        out.append("CARD no `metal` section")
        metal = {}
    claimed = {}
    for fam in sorted(metal):
        e = metal[fam]
        if not isinstance(e, dict):
            out.append("CARD metal.{} is not a mapping".format(fam))
            continue
        lys = e.get("layers")
        if lys is None and len(metal) > 1:
            out.append(
                "CARD metal.{}: no `layers` membership list -- family "
                "resolution has nothing to go on (this is the "
                "P_METAL_FAMILY failure shape)".format(fam))
        for ly in (lys or []):
            if ly in claimed:
                out.append(
                    "CARD layer {} claimed by families {} AND {}".format(
                        ly, claimed[ly], fam))
            claimed[ly] = fam
    via = card.get("via")
    if not isinstance(via, dict) or not via:
        out.append("CARD no `via` section")
        via = {}
    cut_claimed = {}
    for tier in sorted(via):
        e = via[tier]
        if not isinstance(e, dict):
            continue
        for c in (e.get("cut_layers") or []):
            if c in cut_claimed:
                out.append(
                    "CARD cut {} claimed by tiers {} AND {}".format(
                        c, cut_claimed[c], tier))
            cut_claimed[c] = tier
        if "redundancy_tiers" not in e:
            out.append(
                "CARD via.{}: redundancy_tiers not recorded -- record "
                "[] with provenance if the kit has none".format(tier))
    return out


def _validate_per_layer(card):
    """The per-layer profile: `routing_layers` and `vias` keyed by the
    layer/cut name itself (no families). Checks the same failure
    shapes: empty sections, entries that are not mappings, and via
    entries recording neither a redundancy answer nor a measured
    absence (a `global_absences` section counts as the answer)."""
    out = []
    layers = card.get("routing_layers")
    if not isinstance(layers, dict) or not layers:
        out.append("CARD no `routing_layers` section")
        layers = {}
    for ly in sorted(layers):
        if not isinstance(layers[ly], dict):
            out.append("CARD routing_layers.{} is not a mapping"
                       .format(ly))
    vias = card.get("vias")
    if not isinstance(vias, dict) or not vias:
        out.append("CARD no `vias` section")
        vias = {}
    absent = card.get("global_absences") or {}
    for cut in sorted(vias):
        e = vias[cut]
        if not isinstance(e, dict):
            out.append("CARD vias.{} is not a mapping".format(cut))
            continue
        if "redundancy_tiers" not in e and not absent:
            out.append(
                "CARD vias.{}: no redundancy answer -- record it per "
                "cut or in `global_absences` with provenance".format(cut))
    return out
