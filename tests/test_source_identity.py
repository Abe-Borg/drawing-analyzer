"""End-to-end source-identity isolation (DA-001, Phase 18A).

Ties the host-owned ``source_id`` together across the data model, the id
computation, the collision-safe key, the ledger, and the cache rebind — the
invariants that guarantee a finding can never be attributed to the wrong input
when two PDFs share a basename.
"""
from __future__ import annotations

from drawing_analyzer.digest import _rebind_cached_finding, findings_from_cache
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import (
    Anchor,
    Finding,
    SheetRef,
    compute_finding_id,
    source_page_key,
)


def _ref(source_id: str, name="M-101.pdf", page=0, path=None) -> SheetRef:
    from pathlib import Path

    return SheetRef(
        pdf_path=Path(path or f"/{source_id}/{name}"),
        page_index=page,
        source_name=name,
        page_count=1,
        source_id=source_id,
    )


def _finding(source_id, *, sheet_id="M-101", category="conflict", quote="VAV-3",
             name="M-101.pdf", page=0):
    return Finding(
        sheet_id=sheet_id, source_name=name, source_id=source_id, page_index=page,
        category=category, severity="high", text="issue", source_quote=quote,
    )


# --------------------------------------------------------------------------- #
# source_page_key — the one collision-safe key
# --------------------------------------------------------------------------- #


def test_source_page_key_uses_source_id_when_present():
    a = _finding("SRC-0001")
    b = _finding("SRC-0002")
    # Same basename + page, different source → different keys.
    assert source_page_key(a) != source_page_key(b)
    assert source_page_key(a) == ("SRC-0001", 0)


def test_source_page_key_falls_back_to_basename_without_id():
    a = _finding("", name="s.pdf")
    assert source_page_key(a) == ("s.pdf", 0)


def test_source_page_key_unwraps_ref():
    ref = _ref("SRC-0007")
    assert source_page_key(ref) == ("SRC-0007", 0)

    class _Geom:
        pass

    g = _Geom()
    g.ref = ref
    assert source_page_key(g) == ("SRC-0007", 0)


# --------------------------------------------------------------------------- #
# compute_finding_id — source-aware, back-compatible
# --------------------------------------------------------------------------- #


def test_finding_id_differs_by_source_but_is_stable():
    # Same sheet_id/category/quote on two different inputs → DIFFERENT ids, so
    # they can't collide in the evidence dir or the ledger.
    a = _finding("SRC-0001")
    b = _finding("SRC-0002")
    assert a.id != b.id
    # ...but identical inputs are still stable (recompute matches).
    assert a.id == compute_finding_id("M-101", "conflict", "VAV-3", "SRC-0001")


def test_finding_id_without_source_id_is_legacy_stable():
    # No source_id → the historical, source-independent id (back-compat).
    legacy = compute_finding_id("M-101", "conflict", "VAV-3")
    assert _finding("").id == legacy


# --------------------------------------------------------------------------- #
# ledger — same-basename findings never merge
# --------------------------------------------------------------------------- #


def test_ledger_keeps_same_basename_sources_separate():
    ledger = Ledger()
    # Two findings, identical except their source — must stay two entries.
    ledger.add([_finding("SRC-0001")], source="digest_json")
    ledger.add([_finding("SRC-0002")], source="digest_json")
    assert len(ledger) == 2
    # Each sheet's match pool holds only its own entry.
    assert len(ledger.entries_for(_ref("SRC-0001"))) == 1
    assert len(ledger.entries_for(_ref("SRC-0002"))) == 1


def test_ledger_still_merges_true_duplicates_on_one_source():
    ledger = Ledger()
    ledger.add([_finding("SRC-0001")], source="digest_json")
    ledger.add([_finding("SRC-0001")], source="critique_1")   # same source+issue
    assert len(ledger) == 1


# --------------------------------------------------------------------------- #
# cache rebind — a hit is re-attributed to the current source (§10.3)
# --------------------------------------------------------------------------- #


def test_cache_hit_rebinds_finding_to_current_source():
    # A finding cached under source A is served for source B (content-keyed
    # cache); it must come back stamped with B's identity, not A's.
    stored = _finding("SRC-0001", name="M-101.pdf").to_dict()
    ref_b = _ref("SRC-0002", name="M-101.pdf", path="/rev_b/M-101.pdf")

    (rebound,) = findings_from_cache({"findings": [stored]}, ref_b)

    assert rebound.source_id == "SRC-0002"
    assert rebound.source_name == "M-101.pdf"
    assert source_page_key(rebound) == ("SRC-0002", 0)
    # The content id was recomputed for the new source (no stale-id carryover).
    assert rebound.id == compute_finding_id(
        rebound.sheet_id, rebound.category, rebound.source_quote, "SRC-0002"
    )


def test_cache_rebind_rebuilds_source_derived_fallback_sheet_id():
    # A fallback sheet_id ("{stem}-p{n}") is source-derived → rebuilt on rebind;
    # a real model sheet_id ("M-101") is preserved.
    fb = _finding("SRC-0001", sheet_id="M-101-p1", name="M-101.pdf")
    ref_b = _ref("SRC-0002", name="E-201.pdf", path="/b/E-201.pdf")
    rebound = _rebind_cached_finding(Finding.from_dict(fb.to_dict()), ref_b)
    assert rebound.sheet_id == "E-201-p1"        # rebuilt from the new stem

    real = _finding("SRC-0001", sheet_id="M-101", name="M-101.pdf")
    rebound2 = _rebind_cached_finding(Finding.from_dict(real.to_dict()), ref_b)
    assert rebound2.sheet_id == "M-101"          # real model id preserved


# --------------------------------------------------------------------------- #
# cross-sheet legs carry source identity (#11)
# --------------------------------------------------------------------------- #


def test_conflict_leg_carries_source_id_and_is_collision_safe():
    from drawing_analyzer.models import ConflictLeg

    leg_a = ConflictLeg(sheet_id="M-101", source_name="M-101.pdf",
                        source_id="SRC-0001", page_index=0)
    leg_b = ConflictLeg(sheet_id="M-101", source_name="M-101.pdf",
                        source_id="SRC-0002", page_index=0)
    # Two legs on same-basename sheets from different inputs are distinct.
    assert source_page_key(leg_a) != source_page_key(leg_b)
    # source_id survives the JSON round-trip (additive serialization).
    assert ConflictLeg.from_dict(leg_a.to_dict()).source_id == "SRC-0001"


def test_conflict_legs_anchor_against_their_own_source():
    # resolve_conflict_legs groups legs by source_page_key, so two same-basename
    # legs anchor against the RIGHT geometry (not whichever won a basename map).
    from drawing_analyzer.anchor import resolve_conflict_legs
    from drawing_analyzer.models import ConflictLeg, SheetGeometry

    # geometry for source B carries the word the leg quotes; source A does not.
    def _geom(source_id, words):
        ref = _ref(source_id, name="M-101.pdf", path=f"/{source_id}/M-101.pdf")
        return SheetGeometry(ref=ref, page_width_pt=800, page_height_pt=600,
                             rows=6, cols=6, words=words)

    word_b = [10.0, 20.0, 60.0, 32.0, "VAV-9", 0, 0, 0]
    geom_a = _geom("SRC-0001", words=[])
    geom_b = _geom("SRC-0002", words=[word_b])
    geom_by_key = {source_page_key(geom_a.ref): geom_a,
                   source_page_key(geom_b.ref): geom_b}

    parent = _finding("SRC-0009", name="A-1.pdf")
    parent.also_on = [ConflictLeg(sheet_id="M-101", source_name="M-101.pdf",
                                  source_id="SRC-0002",
                                  source_quote="VAV-9", page_index=0)]
    resolve_conflict_legs([parent], geom_by_key)
    # The leg anchored against source B's geometry (where its quote lives).
    assert parent.also_on[0].anchor.status in ("EXACT", "FUZZY", "TILE")


# --------------------------------------------------------------------------- #
# public exports carry no absolute path (#10)
# --------------------------------------------------------------------------- #


def test_numeric_claims_carry_source_id_and_resolve_by_it():
    # Fresh claims must carry source_id (DA-001) so the arithmetic auditor
    # resolves a duplicate-basename claim to its OWN geometry, not the first
    # source's. Regression for the source-id-less-claim gap.
    from drawing_analyzer.digest import _validate_claim_item

    ref = _ref("SRC-0002", name="M-101.pdf")
    claim = _validate_claim_item(
        {"kind": "sum", "terms": [1, 2], "expected": 3, "quote": "1+2=3"}, ref
    )
    assert claim.source_id == "SRC-0002"
    assert source_page_key(claim) == ("SRC-0002", 0)


def test_claim_dedup_keeps_same_basename_sources_separate():
    from drawing_analyzer.auditors.arithmetic import _claim_dedup_key
    from drawing_analyzer.models import NumericClaim

    a = NumericClaim(sheet_id="M-101", quote="q", kind="sum", terms=[1, 2],
                     expected=3, source_name="M-101.pdf", source_id="SRC-0001")
    b = NumericClaim(sheet_id="M-101", quote="q", kind="sum", terms=[1, 2],
                     expected=3, source_name="M-101.pdf", source_id="SRC-0002")
    # Identical claims from two same-basename inputs must NOT collapse.
    assert _claim_dedup_key(a) != _claim_dedup_key(b)


def test_cache_hit_rebinds_claim_and_rebuilds_fallback_sheet_id():
    from drawing_analyzer.digest import claims_from_cache
    from drawing_analyzer.models import NumericClaim

    # A claim cached under source A with a source-derived fallback sheet_id...
    stored = NumericClaim(
        sheet_id="M-101-p1", quote="q", kind="sum", terms=[1, 2], expected=3,
        source_name="M-101.pdf", source_id="SRC-0001",
    ).to_dict()
    ref_b = _ref("SRC-0002", name="E-201.pdf", path="/b/E-201.pdf")

    (rebound,) = claims_from_cache({"claims": [stored]}, ref_b)

    assert rebound.source_id == "SRC-0002"
    assert rebound.sheet_id == "E-201-p1"        # fallback rebuilt for new source
    assert source_page_key(rebound) == ("SRC-0002", 0)

    # A real model sheet_id survives the rebind.
    real = NumericClaim(sheet_id="M-101", quote="q", kind="sum", terms=[1, 2],
                        expected=3, source_name="M-101.pdf", source_id="SRC-0001").to_dict()
    (rebound2,) = claims_from_cache({"claims": [real]}, ref_b)
    assert rebound2.sheet_id == "M-101"


def test_exports_carry_source_id_not_absolute_paths():
    import json

    from drawing_analyzer import export as dx

    f = _finding("SRC-0002", name="M-101.pdf")
    csv = dx.build_findings_csv([f])
    # The host id is present; the private absolute path never is.
    assert "SRC-0002" in csv
    assert "/SRC-" not in csv and "pdf_path" not in csv
    # JSON (to_dict form, as export writes it) likewise: source_id, no path.
    payload = json.dumps({"findings": [f.to_dict()]})
    assert '"source_id": "SRC-0002"' in payload
    assert "pdf_path" not in payload
