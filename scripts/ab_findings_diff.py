"""Finding-level comparison between two A/B sweep arms (WP-06 §11.2/§11.3).

The aggregate tables in ``ab_sweep_drawing_analyzer`` answer *how many* and *how
much*. They cannot answer the question an operator actually has after a
model/geometry swap: **is this the same set of findings?** Two arms can report
287 findings each, with identical severity and anchor mixes, and share only 200
of them — a swap of 87 real issues for 87 different ones reads as "no change" on
every aggregate line there is.

This module builds one compact record per finding before the arm's temporary
workspace is destroyed, and matches the two arms' records deterministically.

**What is deliberately NOT done here**

- No fuzzy score is ever promoted to an equivalence. A similarity number can rank
  candidates for a human; it cannot decide that two differently-worded findings
  are the same issue.
- No unmatched finding is dropped. An unmatched record on either side is the
  *output*, not noise to be tidied away.
- No second model is asked to adjudicate. That would make a comparison harness
  cost money and depend on the very thing under test.
- ``QC-###`` is never an identity. It is assigned positionally *after* anchoring
  (``assign_qc_ids``), so removing one finding renumbers every finding below it:
  matching on it would report an arm that dropped finding #12 as having changed
  all 275 findings after it.
- ``Finding.id`` alone is never an identity either. ``compute_finding_id`` hashes
  sheet id, category, quote-or-text and source id — **legs and severity are
  excluded**, so two cross-sheet conflicts that share a primary quote but point
  at different secondary sheets collide on one id. The identity built here adds
  the leg signature for exactly that reason.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

# --------------------------------------------------------------------------- #
# Record building
# --------------------------------------------------------------------------- #

#: Bumped whenever the record shape changes in a way a reader must notice.
#: Arm JSON from an older harness still loads (every consumer uses ``.get``),
#: but a comparison across contract versions is announced rather than assumed.
RECORD_CONTRACT_VERSION = 1

_WS_RE = re.compile(r"\s+")


def _norm(text) -> str:
    """Case- and whitespace-insensitive form used for *identity keys only*.

    Deliberately not shared with ``critique._normalize``: that one decides
    whether two findings inside one run are the same issue and may be tuned for
    merge behaviour. This one decides whether two findings from *different runs*
    are the same record, and must stay stable for the life of a saved artifact.
    They answer different questions, so they are allowed to differ — unlike the
    critical-signature rule below, which must not.
    """
    if not isinstance(text, str):
        return ""
    return _WS_RE.sub(" ", text).strip().casefold()


def _source_key(source_id, source_name) -> str:
    """Source correspondence that is stable within one input set and path-free.

    ``SRC-####`` is assigned by input position, so both arms — given the same
    ordered file list — agree on it without either arm's absolute paths reaching
    the artifact. ``source_name`` (a basename) is the documented fallback when a
    finding predates DA-001 or belongs to no single source.
    """
    sid = str(source_id or "").strip()
    return sid or str(source_name or "").strip()


def _leg_signature(finding) -> list[list[str]]:
    """Sorted ``[sheet_id, normalized quote]`` pairs for every cross-sheet leg.

    Part of the identity: a conflict's *secondary* sheets are what distinguishes
    two findings that quote the same primary text, and ``compute_finding_id``
    does not see them.
    """
    legs = []
    for leg in (getattr(finding, "also_on", None) or []):
        legs.append([
            _norm(getattr(leg, "sheet_id", "")),
            _norm(getattr(leg, "source_quote", "")),
        ])
    return sorted(legs)


def _identity_parts(finding) -> dict:
    return {
        "source_key": _source_key(getattr(finding, "source_id", ""),
                                  getattr(finding, "source_name", "")),
        "page_index": int(getattr(finding, "page_index", 0) or 0),
        "sheet_id": _norm(getattr(finding, "sheet_id", "")),
        "category": _norm(getattr(finding, "category", "")),
        "quote_or_text": _norm(getattr(finding, "source_quote", "")
                               or getattr(finding, "text", "")),
        "legs": _leg_signature(finding),
    }


def identity_key(parts: dict) -> str:
    """A short, stable hash of the identity parts.

    Hashed rather than concatenated so the key is a fixed width and can never
    carry quote text into a place a reader might mistake for evidence.
    """
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _anchor_record(anchor) -> dict:
    rect = getattr(anchor, "rect_pdf", None)
    return {
        "status": str(getattr(anchor, "status", "") or "UNANCHORED"),
        "method": str(getattr(anchor, "method", "") or ""),
        "rect_pdf": [float(v) for v in rect] if rect else None,
    }


def finding_record(finding) -> dict:
    """One comparable record for a finished :class:`Finding`.

    Compact by design: the plan's minimum output is "compact JSON plus
    source/page references", and a record that embedded whole reviewed pages
    would make a 300-finding arm unreadable. Everything a reviewer needs to find
    the finding again on paper is here — source, page, sheet, tile, rect, quote.

    ``critical_signature`` is computed by the production rule
    (``critique.critical_signature``), never restated here: the tags,
    quantities and absence polarity that block a merge inside one run are the
    same ones that must block an "exact match" claim across two runs.
    """
    from drawing_analyzer.critique import critical_signature

    parts = _identity_parts(finding)
    verification = getattr(finding, "verification", None)
    return {
        "identity_key": identity_key(parts),
        "identity": parts,
        # References only — see the module docstring on why neither is an
        # identity. Kept so a reviewer can jump from this record to the arm's
        # own report/markup.
        "finding_id": str(getattr(finding, "id", "") or ""),
        "qc_id": str(getattr(finding, "qc_id", "") or ""),
        "source_id": str(getattr(finding, "source_id", "") or ""),
        "source_name": str(getattr(finding, "source_name", "") or ""),
        "page_index": int(getattr(finding, "page_index", 0) or 0),
        "sheet_id": str(getattr(finding, "sheet_id", "") or ""),
        "category": str(getattr(finding, "category", "") or ""),
        "severity": str(getattr(finding, "severity", "") or ""),
        "text": str(getattr(finding, "text", "") or ""),
        "source_quote": str(getattr(finding, "source_quote", "") or ""),
        "supporting_quotes": list(getattr(finding, "supporting_quotes", None) or []),
        "refs": list(getattr(finding, "refs", None) or []),
        "anchor_hint": str(getattr(finding, "anchor_hint", "") or ""),
        "tile": list(getattr(finding, "tile", None) or []) or None,
        "confidence": str(getattr(finding, "confidence", "") or ""),
        "sources": list(getattr(finding, "sources", None) or []),
        "evidence_state": str(getattr(finding, "evidence_state", "") or ""),
        "anchor": _anchor_record(getattr(finding, "anchor", None)),
        "verification": {
            "status": str(getattr(verification, "status", "") or "SKIPPED"),
            "computation_method": str(
                getattr(verification, "computation_method", "") or ""),
            "operand_origin": str(getattr(verification, "operand_origin", "") or ""),
            "investigated": bool(getattr(verification, "investigated", False)),
            "investigation_rounds": int(
                getattr(verification, "investigation_rounds", 0) or 0),
        },
        "legs": [
            {
                "sheet_id": str(getattr(leg, "sheet_id", "") or ""),
                "source_id": str(getattr(leg, "source_id", "") or ""),
                "source_name": str(getattr(leg, "source_name", "") or ""),
                "page_index": int(getattr(leg, "page_index", 0) or 0),
                "source_quote": str(getattr(leg, "source_quote", "") or ""),
                "evidence_state": str(getattr(leg, "evidence_state", "") or ""),
                "anchor": _anchor_record(getattr(leg, "anchor", None)),
            }
            for leg in (getattr(finding, "also_on", None) or [])
        ],
        "evidence_artifacts": [
            {
                "evidence_id": str(getattr(a, "evidence_id", "") or ""),
                "leg_index": int(getattr(a, "leg_index", 0) or 0),
                "relative_path": str(getattr(a, "relative_path", "") or ""),
                "sha256": str(getattr(a, "sha256", "") or ""),
            }
            for a in (getattr(verification, "evidence", None) or [])
        ],
        "critical_signature": critical_signature(finding),
    }


def finding_records(findings) -> list[dict]:
    """Records for a whole arm, in a deterministic order (I-7).

    Sorted by the identity key rather than by production order so two arms'
    files are diffable by eye and a re-run of the same arm produces the same
    file. ``finding_id`` breaks ties, so even a duplicated identity is ordered.
    """
    records = [finding_record(f) for f in (findings or [])]
    records.sort(key=lambda r: (r["identity_key"], r["finding_id"]))
    return records


# --------------------------------------------------------------------------- #
# Evidence-trust composition (§11.3)
# --------------------------------------------------------------------------- #

#: A *unit* is one grounded claim: the finding's own quote, plus each
#: cross-sheet leg's quote. A conflict can be text-grounded on one sheet and
#: read off a raster detail on the other, so the finding-level state alone
#: cannot describe it.
TRUST_STATES = (
    "TEXT_GROUNDED", "TEXT_EVIDENCE_UNAVAILABLE", "NOT_MATCHED_IN_TEXT",
    "NOT_ASSESSED",
)
_TRUSTED_VERDICTS = ("VERIFIED", "DETERMINISTIC")


def _trust_state(raw) -> str:
    state = str(raw or "").strip().upper()
    if not state:
        return "NOT_ASSESSED"
    return state if state in TRUST_STATES else "other"


def evidence_trust_composition(findings) -> dict:
    """How much of an arm's output stands on text the host could actually find.

    §11.3: an arm whose finding count held up on reduced-trust, unverified legs
    is **not** equivalent to one whose findings were text-grounded and verified.
    Counting only findings would hide that: the composition is tallied per unit,
    so a conflict grounded on one sheet and unavailable on the other contributes
    to both columns instead of being flattened into whichever state the parent
    happens to carry.

    ``NOT_ASSESSED`` is its own state and never folded into either extreme — a
    standard (non-cross-QC) run assesses nothing, and reporting all of it as
    "grounded" or all of it as "reduced trust" would be a fabricated signal.
    """
    by_state = {k: 0 for k in TRUST_STATES}
    by_state["other"] = 0
    units = 0
    reduced = 0
    reduced_unverified = 0
    grounded_verified = 0
    for f in (findings or []):
        verdict = str(getattr(getattr(f, "verification", None), "status", "") or "")
        trusted_verdict = verdict in _TRUSTED_VERDICTS
        states = [_trust_state(getattr(f, "evidence_state", ""))]
        for leg in (getattr(f, "also_on", None) or []):
            states.append(_trust_state(getattr(leg, "evidence_state", "")))
        for state in states:
            units += 1
            by_state[state] = by_state.get(state, 0) + 1
            if state == "TEXT_EVIDENCE_UNAVAILABLE":
                reduced += 1
                if not trusted_verdict:
                    reduced_unverified += 1
            elif state == "TEXT_GROUNDED" and trusted_verdict:
                grounded_verified += 1
    return {
        "units": units,
        "unit_definition": "one per finding quote plus one per cross-sheet leg",
        "by_state": by_state,
        "reduced_trust_units": reduced,
        "reduced_trust_unverified_units": reduced_unverified,
        "grounded_verified_units": grounded_verified,
    }


# --------------------------------------------------------------------------- #
# Matching (pure — operates on records, never on live findings)
# --------------------------------------------------------------------------- #

#: Minimum rectangle intersection-over-union for geometry to *suggest* a
#: candidate. It never produces an exact match: §11.5 requires that changed
#: quantities/tags/polarity cannot become an exact match merely because the
#: geometry overlaps, and the only way to guarantee that is to keep geometry out
#: of tier 1 entirely.
CANDIDATE_IOU = 0.5

MATCH_EXACT = "EXACT"
MATCH_CANDIDATE = "CANDIDATE"
AMBIGUOUS_IDENTITY_COLLISION = "IDENTITY_COLLISION"
AMBIGUOUS_MANY_TO_MANY = "MANY_TO_MANY"


def _ref(record: dict, index: int) -> dict:
    """A compact pointer to one record — enough to navigate, not a second copy."""
    return {
        "index": index,
        "finding_id": record.get("finding_id", ""),
        "qc_id": record.get("qc_id", ""),
        "source_name": record.get("source_name", ""),
        "source_id": record.get("source_id", ""),
        "page_index": record.get("page_index", 0),
        "sheet_id": record.get("sheet_id", ""),
        "category": record.get("category", ""),
        "severity": record.get("severity", ""),
        "text": record.get("text", ""),
        "source_quote": record.get("source_quote", ""),
    }


def _iou(a, b) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax0, ay0, ax1, ay1 = (float(v) for v in a)
    bx0, by0, bx1, by1 = (float(v) for v in b)
    if ax1 <= ax0 or ay1 <= ay0 or bx1 <= bx0 or by1 <= by0:
        return 0.0
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return 0.0 if union <= 0 else inter / union


def _signature_conflicts(a: dict, b: dict) -> list[str]:
    """Which critical axes disagree — the *reason* a match is not exact.

    The verdict itself comes from ``critique.signatures_compatible``; this only
    names the axis for the report, so the two can never disagree about whether
    a pair is compatible.
    """
    out: list[str] = []
    ta, tb = set(a.get("tags") or ()), set(b.get("tags") or ())
    if ta and tb and ta.isdisjoint(tb):
        out.append("tags")
    ma, mb = set(a.get("measurements") or ()), set(b.get("measurements") or ())
    if ma and mb and ma.isdisjoint(mb):
        out.append("measurements")
    if bool(a.get("absence")) != bool(b.get("absence")):
        out.append("absence_polarity")
    la, lb = set(a.get("leg_targets") or ()), set(b.get("leg_targets") or ())
    if la and lb and la != lb:
        out.append("cross_sheet_legs")
    return out


def _compatible(a: dict, b: dict) -> bool:
    from drawing_analyzer.critique import signatures_compatible
    return signatures_compatible(a.get("critical_signature") or {},
                                 b.get("critical_signature") or {})


def _attribute_deltas(base: dict, var: dict) -> dict:
    """What changed about a finding both arms found. Empty when nothing did."""
    out: dict = {}
    for key in ("severity", "confidence", "evidence_state"):
        if base.get(key, "") != var.get(key, ""):
            out[key] = {"base": base.get(key, ""), "variant": var.get(key, "")}
    for key, path in (("anchor_status", "anchor"), ("verification_status",
                                                    "verification")):
        b = (base.get(path) or {}).get("status", "")
        v = (var.get(path) or {}).get("status", "")
        if b != v:
            out[key] = {"base": b, "variant": v}
    bs, vs = sorted(base.get("sources") or []), sorted(var.get("sources") or [])
    if bs != vs:
        out["sources"] = {"base": bs, "variant": vs}
    return out


def _candidate_reasons(base: dict, var: dict) -> list[str]:
    """Why a *human* should look at this pair. Never an equivalence claim."""
    reasons: list[str] = []
    bq = _norm(base.get("source_quote", ""))
    vq = _norm(var.get("source_quote", ""))
    if bq and bq == vq:
        reasons.append("same verbatim quote")
    b_legs = base.get("identity", {}).get("legs") or []
    v_legs = var.get("identity", {}).get("legs") or []
    if b_legs and v_legs and b_legs == v_legs:
        reasons.append("same cross-sheet legs")
    elif bq and bq == vq and b_legs != v_legs:
        reasons.append("same quote, different cross-sheet legs")
    iou = _iou((base.get("anchor") or {}).get("rect_pdf"),
               (var.get("anchor") or {}).get("rect_pdf"))
    same_category = _norm(base.get("category", "")) == _norm(var.get("category", ""))
    if iou >= CANDIDATE_IOU and same_category:
        reasons.append(f"anchor rects overlap (IoU {iou:.2f})")
    if reasons and not same_category:
        reasons.append(
            f"category changed {base.get('category', '')!r} -> "
            f"{var.get('category', '')!r}"
        )
    return reasons


def _components(pairs, base_ids, var_ids):
    """Connected components of the bipartite candidate graph, deterministically.

    A component that is not exactly one base record and one variant record is
    ambiguous by construction: a chain b1-v1-b2 offers no non-arbitrary pairing,
    and picking one would launder a guess into a reported match — the same
    failure ``cross_qc.fact_tile_lookup`` exists to avoid.
    """
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for bi in base_ids:
        find(("b", bi))
    for vi in var_ids:
        find(("v", vi))
    for bi, vi, _reasons in pairs:
        union(("b", bi), ("v", vi))

    groups: dict = {}
    for node in sorted(parent):
        groups.setdefault(find(node), []).append(node)
    out = []
    for root in sorted(groups, key=lambda r: sorted(groups[r])):
        members = groups[root]
        out.append((
            sorted(i for kind, i in members if kind == "b"),
            sorted(i for kind, i in members if kind == "v"),
        ))
    return out


def match_records(base_records: list[dict], variant_records: list[dict]) -> dict:
    """Match two arms' finding records with the three deterministic tiers.

    Tier 1 (``exact``) — equal identity **and** compatible critical signatures,
    and unique on both sides. This is the only tier that may be called a match.

    Tier 2 (``candidates``) — a 1:1 pair a human should look at: same quote with
    different wording, same legs, or heavily-overlapping anchors. Also where an
    identity-equal pair lands when its critical signatures conflict, since
    "same words, different quantity" is a change, not a match.

    Tier 3 — ``unmatched_base`` / ``unmatched_variant`` / ``ambiguous``. Nothing
    is deleted and nothing is guessed; an ambiguous group names every record in
    it and stays unresolved.
    """
    base_records = list(base_records or [])
    variant_records = list(variant_records or [])

    def group(records):
        out: dict = {}
        for i, r in enumerate(records):
            out.setdefault(r.get("identity_key", ""), []).append(i)
        return out

    b_by_key, v_by_key = group(base_records), group(variant_records)
    exact: list[dict] = []
    candidates: list[dict] = []
    ambiguous: list[dict] = []
    consumed_b: set = set()
    consumed_v: set = set()

    for key in sorted(set(b_by_key) & set(v_by_key)):
        bs, vs = b_by_key[key], v_by_key[key]
        consumed_b.update(bs)
        consumed_v.update(vs)
        if len(bs) != 1 or len(vs) != 1:
            ambiguous.append({
                "kind": AMBIGUOUS_IDENTITY_COLLISION,
                "identity_key": key,
                "note": "the same identity occurs more than once in an arm; "
                        "pairing would be arbitrary, so it is left unresolved",
                "base": [_ref(base_records[i], i) for i in bs],
                "variant": [_ref(variant_records[i], i) for i in vs],
            })
            continue
        bi, vi = bs[0], vs[0]
        b, v = base_records[bi], variant_records[vi]
        if _compatible(b, v):
            exact.append({
                "tier": MATCH_EXACT,
                "identity_key": key,
                "base": _ref(b, bi),
                "variant": _ref(v, vi),
                # A finding's identity here is quote-anchored, exactly as
                # ``compute_finding_id`` makes it, so an arm that reworded the
                # *description* of the same grounded quote is still the same
                # finding — but the reviewer is told, because a rewording that
                # changed a quantity or a polarity would have failed the
                # critical-signature check above and never reached this branch.
                "text_changed": _norm(b.get("text", "")) != _norm(v.get("text", "")),
                "attribute_deltas": _attribute_deltas(b, v),
            })
        else:
            conflicts = _signature_conflicts(
                b.get("critical_signature") or {}, v.get("critical_signature") or {})
            candidates.append({
                "tier": MATCH_CANDIDATE,
                "identity_key": key,
                "base": _ref(b, bi),
                "variant": _ref(v, vi),
                "reasons": ["identical identity, conflicting critical signature"],
                "signature_conflicts": conflicts,
                "attribute_deltas": _attribute_deltas(b, v),
            })

    rest_b = [i for i in range(len(base_records)) if i not in consumed_b]
    rest_v = [i for i in range(len(variant_records)) if i not in consumed_v]

    def bucket(records, ids):
        out: dict = {}
        for i in ids:
            ident = records[i].get("identity", {})
            out.setdefault(
                (ident.get("source_key", ""), ident.get("page_index", 0)), []
            ).append(i)
        return out

    b_buckets, v_buckets = bucket(base_records, rest_b), bucket(variant_records, rest_v)
    pairs: list[tuple] = []
    for key in sorted(set(b_buckets) & set(v_buckets)):
        for bi in b_buckets[key]:
            for vi in v_buckets[key]:
                reasons = _candidate_reasons(base_records[bi], variant_records[vi])
                if reasons:
                    pairs.append((bi, vi, reasons))

    unmatched_b: list[dict] = []
    unmatched_v: list[dict] = []
    for bs, vs in _components(pairs, rest_b, rest_v):
        if len(bs) == 1 and len(vs) == 1:
            bi, vi = bs[0], vs[0]
            b, v = base_records[bi], variant_records[vi]
            reasons = next(r for pb, pv, r in pairs if pb == bi and pv == vi)
            candidates.append({
                "tier": MATCH_CANDIDATE,
                "identity_key": "",
                "base": _ref(b, bi),
                "variant": _ref(v, vi),
                "reasons": reasons,
                "signature_conflicts": _signature_conflicts(
                    b.get("critical_signature") or {},
                    v.get("critical_signature") or {}),
                "attribute_deltas": _attribute_deltas(b, v),
            })
        elif not vs:
            unmatched_b.extend(_ref(base_records[i], i) for i in bs)
        elif not bs:
            unmatched_v.extend(_ref(variant_records[i], i) for i in vs)
        else:
            ambiguous.append({
                "kind": AMBIGUOUS_MANY_TO_MANY,
                "identity_key": "",
                "note": "several candidate pairings are equally supported; "
                        "left unresolved for human review",
                "base": [_ref(base_records[i], i) for i in bs],
                "variant": [_ref(variant_records[i], i) for i in vs],
            })

    exact.sort(key=lambda m: (m["identity_key"], m["base"]["finding_id"]))
    candidates.sort(key=lambda m: (m["base"]["source_name"], m["base"]["page_index"],
                                   m["base"]["finding_id"]))
    unmatched_b.sort(key=lambda r: (r["source_name"], r["page_index"], r["finding_id"]))
    unmatched_v.sort(key=lambda r: (r["source_name"], r["page_index"], r["finding_id"]))
    ambiguous.sort(key=lambda a: (a["kind"], a["identity_key"],
                                  [r["finding_id"] for r in a["base"]]))

    amb_b = sum(len(a["base"]) for a in ambiguous)
    amb_v = sum(len(a["variant"]) for a in ambiguous)
    pair_count = len(exact) + len(candidates)
    counts = {
        "base_total": len(base_records),
        "variant_total": len(variant_records),
        "exact": len(exact),
        "candidates": len(candidates),
        "unmatched_base": len(unmatched_b),
        "unmatched_variant": len(unmatched_v),
        "ambiguous_groups": len(ambiguous),
        "ambiguous_base": amb_b,
        "ambiguous_variant": amb_v,
        "duplicate_identity_base": sum(
            len(v) - 1 for v in b_by_key.values() if len(v) > 1),
        "duplicate_identity_variant": sum(
            len(v) - 1 for v in v_by_key.values() if len(v) > 1),
    }
    # Every record on both sides lands in exactly one bucket. A reconciliation
    # that fails means the matcher lost a finding, which is the one outcome a
    # comparison harness must never report quietly.
    counts["reconciles"] = (
        pair_count + len(unmatched_b) + amb_b == len(base_records)
        and pair_count + len(unmatched_v) + amb_v == len(variant_records)
    )
    return {
        "contract_version": RECORD_CONTRACT_VERSION,
        "counts": counts,
        "exact": exact,
        "candidates": candidates,
        "unmatched_base": unmatched_b,
        "unmatched_variant": unmatched_v,
        "ambiguous": ambiguous,
    }


# --------------------------------------------------------------------------- #
# Artifact links (§11.2: copy before cleanup; never link into a deleted dir)
# --------------------------------------------------------------------------- #

def copy_linked_artifacts(records, src_root, dest_root, *, link_from) -> int:
    """Copy every artifact a record references out of the arm's temp workspace.

    Called **before** the workspace is destroyed. Each copied artifact gets a
    ``link`` relative to ``link_from`` (the directory the JSON is written to), so
    the saved comparison stays portable: no absolute path, and no link into a
    directory that will not exist by the time anyone reads it.

    Returns the number of artifacts copied. Missing sources are skipped rather
    than raising — an arm that produced no crops must still produce its records.
    """
    src_root, dest_root = Path(src_root), Path(dest_root)
    link_from = Path(link_from)
    copied = 0
    for record in (records or []):
        for artifact in (record.get("evidence_artifacts") or []):
            rel = str(artifact.get("relative_path") or "")
            if not rel:
                continue
            source = src_root / rel
            if not source.is_file():
                continue
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
            try:
                artifact["link"] = target.relative_to(link_from).as_posix()
            except ValueError:
                # Only reachable if a caller passes unrelated roots; a relative
                # link is impossible then, and an absolute one is not allowed.
                artifact["link"] = ""
    return copied


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _line(ref: dict) -> str:
    quote = (ref.get("source_quote") or ref.get("text") or "").strip()
    quote = _WS_RE.sub(" ", quote)
    if len(quote) > 68:
        quote = quote[:65] + "..."
    return (f"      {ref.get('sheet_id', '') or '(no sheet)':<12}"
            f"{ref.get('source_name', ''):<22} p{int(ref.get('page_index', 0)) + 1:<4}"
            f"{ref.get('severity', ''):<8}{quote}")


def render_findings_diff(match: dict, *, base_label: str, var_label: str) -> str:
    """The human-facing block appended to ``diff.txt``."""
    c = match.get("counts", {})
    lines = [
        "  FINDING-LEVEL COMPARISON",
        f"    base:    {base_label}",
        f"    variant: {var_label}",
        "",
        f"    {'exact matches':<34}{c.get('exact', 0):>6}",
        f"    {'candidates (human review)':<34}{c.get('candidates', 0):>6}",
        f"    {'only in baseline':<34}{c.get('unmatched_base', 0):>6}",
        f"    {'only in variant':<34}{c.get('unmatched_variant', 0):>6}",
        f"    {'ambiguous groups':<34}{c.get('ambiguous_groups', 0):>6}"
        f"  ({c.get('ambiguous_base', 0)} base / "
        f"{c.get('ambiguous_variant', 0)} variant records)",
        f"    {'totals':<34}{c.get('base_total', 0):>6} base, "
        f"{c.get('variant_total', 0)} variant",
    ]
    if not c.get("reconciles", True):
        lines.append("    [ERROR] the buckets do not account for every record — "
                     "treat this comparison as unusable")
    changed = [m for m in match.get("exact", [])
               if m.get("attribute_deltas") or m.get("text_changed")]
    if changed:
        lines += ["", f"    {len(changed)} matched finding(s) changed disposition:"]
        for m in changed[:20]:
            deltas = ", ".join(
                f"{k} {d['base'] or '-'}->{d['variant'] or '-'}"
                for k, d in sorted(m["attribute_deltas"].items())
                if isinstance(d, dict) and not isinstance(d.get("base"), list)
            )
            if m.get("text_changed"):
                deltas = (deltas + ", " if deltas else "") + "text reworded"
            lines.append(_line(m["base"]))
            if deltas:
                lines.append(f"        {deltas}")
        if len(changed) > 20:
            lines.append(f"      ... {len(changed) - 20} more in findings_diff.json")
    for title, key in (("only in baseline", "unmatched_base"),
                       ("only in variant", "unmatched_variant")):
        rows = match.get(key, [])
        if not rows:
            continue
        lines += ["", f"    {len(rows)} {title}:"]
        lines += [_line(r) for r in rows[:20]]
        if len(rows) > 20:
            lines.append(f"      ... {len(rows) - 20} more in findings_diff.json")
    if match.get("candidates"):
        lines += ["", f"    {len(match['candidates'])} candidate pair(s) — these are"
                      " NOT matches; a human decides:"]
        for m in match["candidates"][:20]:
            lines.append(_line(m["base"]))
            why = "; ".join(m.get("reasons") or [])
            conflicts = ", ".join(m.get("signature_conflicts") or [])
            lines.append(f"        why: {why}"
                         + (f"  [conflicting: {conflicts}]" if conflicts else ""))
        if len(match["candidates"]) > 20:
            lines.append(
                f"      ... {len(match['candidates']) - 20} more in findings_diff.json")
    if match.get("ambiguous"):
        lines += ["", "    Ambiguous — left unresolved on purpose:"]
        for a in match["ambiguous"][:10]:
            lines.append(f"      [{a['kind']}] {len(a['base'])} base / "
                         f"{len(a['variant'])} variant record(s)")
    lines += [
        "",
        "    Only 'exact' means the same finding. A candidate is a pointer for a",
        "    reviewer, never an equivalence; unmatched records are the result, not",
        "    noise. Equal totals with unmatched records on both sides means the",
        "    arms swapped findings, which every aggregate table reads as no change.",
    ]
    return "\n".join(lines)
