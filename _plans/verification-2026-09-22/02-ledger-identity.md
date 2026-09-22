> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-03, WP-04. The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# ledger-identity — FINAL REPORT (B1, B2, B3, B8, B9, B12, K5, N1; WP-03, WP-04)
Scripts: scratchpad/verify/ledger-identity/*.py (hermetic).

## 1. Verdicts
| ID | Verdict | Current anchor(s) | Evidence | Plan correction |
|---|---|---|---|---|
| B1 | STILL PRESENT (reproduced) | ledger.py::reconcile_post_anchor (628; predicate 691; adopt_members 703; survivor history 704/719) | b1_passb.py, 500/generic/550 over 6 orders: ABC/ACB/BAC → 1 entry "550", no "500"; BCA/CAB/CBA → 2 entries (also breaks I-7). Only the survivor side uses member_history; the incoming side uses the live `e` only. | The review's symmetric patch → 2 entries in 6/6 orders, and the 55 tests in test_drawing_dedup_lifecycle + test_drawing_ledger still pass. But "500" is still missing from exports in 3/6 orders (see WP-03 s6/s7). |
| B2 | STILL PRESENT (reproduced) | critique.py::_MEAS_RE (628; `\s*` 631), _ALPHA_UNIT (595) | `6-inch`/`4-inch`, `6-in`, `6-in.` → `[]` → _is_duplicate True; merge_self_consistency gives 1 finding marked REPRODUCED; Ledger keeps 1 entry. | — |
| B3 | STILL PRESENT (reproduced) | _MEAS_RE lookbehind (629), _meas_value (681) | `12,500`/`1,500 CFM` → both `500cfm` (dup); `12,500` vs `12500` blocked; `1,500.5`→`500.5gpm`; `1,2,500`→`500cfm`; `2,4,6 in`→`6in` | WP-04 s2 (opaque token) |
| B8 | STILL PRESENT (reproduced) | models.py::compute_finding_id (820), Finding.__post_init__ (1258); annotate.py::_set_findings_outline (2209; dedup 2242/2253); _annotate_units (2281; map 2424-2428) → _insert_index_pages (1703; lookup 1800) | Two findings quoting `PUMP P-1`: outline shows "QC Findings (1)". With forced overflow, the on-sheet twin's index row links to the notes page, not page 1. Mechanism: the map is filled only for notes-page placements, so any id-twin inherits that page (the review calls it last-write-wins, which is imprecise). The id also omits page_index and legs; both reproduced as dropped bookmarks. | §7.1 "evidence": evidence dirs are already unique (qc_id plus a `-N` suffix, DA-016). |
| B9 | STILL PRESENT (reproduced) | ledger.py::_merge_into (452; text 526, action 530, backfill-only 565/575); critique.py::_representative (884) | BFP-1 pair, both ingest orders: the loser's text and action are gone from to_dict and from the export._finding_row CSV. Only the loser's quote is kept. member_history and merge_trace exist only at runtime. | — |
| B12 | STILL PRESENT (reproduced) | _ALPHA_UNIT `deg` (597), _SYM_UNIT (599), _UNIT_SYNONYM (640) | `90 deg F`→`90deg` vs `90°F`→`90°f`: incompatible. Also: `90 deg F`/`90 deg C` both sign as `90deg`, so they are **compatible** (the scale is lost). `degrees F` and `degF` get no signature. Angles: `45 deg` vs `45°` are incompatible. | Add these pairs to the matrix |
| K5 | STILL PRESENT (reproduced) | models.py::assign_qc_ids (1409; key 1437) | Same id + same _pos: order XY → X=QC-001; order YX → Y=QC-001. The docstring's promise does not hold. | — |
| N1 | STILL PRESENT (reproduced) | critique.py::signatures_compatible (777; disjoint tests 790/793) | `6 in…100 psi` vs `4 in…100 psi`: compatible → Ledger 1 entry; the critique merge marks it REPRODUCED. Tags `P-1+V-3` vs `P-1+V-4`: dup. `12'-6"`/`12'-8"` share `12ft`, so the ledger merges them. The A/B harness reports the 6in/4in pair as an EXACT match. | WP-04 s6 |

## 2. Plan-text corrections
**WP-03**
- **s1 inventory (paste-ready).**
  - *Derive/serialize:* compute_finding_id (820: hashes sheet+category+quote-or-text+source_id; no page, no text when a quote exists, no legs); __post_init__ (1258); to_dict (1279); from_dict (1345, keeps the stored id).
  - *Cache rebinding:* digest._rebind_cached_finding (1329/1349) via findings_from_cache, used by digest (1509, 1600), batch_digest (1735) and critique.critique_result_from_entry (1129). No rebinding (stored id kept verbatim): cross_qc._cross_qc_from_cache (1420) and prose_harvest._structure_item (549).
  - *Merge/dedup:* ledger._grounding_quality (425); ledger._merge_into (484 trace; 563 id rides the bundle); critique._representative (913, 946); auditors.run_auditors (119-127); auditors.titleblock.audit_titleblock (336-345, id dedup, first-wins); auditors.references._audit_sheet (521-528, dedups on the quote, equivalent to the id); cross_qc._dedup_findings (1310, id-equivalent key).
  - *Ordering tie-breaks:* assign_qc_ids (1437); pipeline._run_critique_stage (1645, sort before ingest); investigate._candidates (1333); annotate._severity_first_key (1618); annotate._annotate_units (2356); _set_findings_outline (2257); tile_artifacts._finding_sort_key (130).
  - *Navigation:* bookmark dedup (2242/2253); mark_page_by_finding (2428, then lookup 1800).
  - *Placement/manifest:* _make_placement (433-434); _units_for_finding (467; synthetic leg Findings compute their own id, 486); annotate_pdf (2695); write_set_review_notes_pdf (3012-3013); MarkupPlacement.finding_id (1535/1550) → markup_manifest.json.
  - *Evidence/cache:* verify._reserve_evidence_dir (571, fallback only); verify._write_evidence_request (641); investigate._write_investigation_json (1143); investigate._payload_hash (1191, stage=investigation cache key); citation_check.check_citations (1064-1066) → CitationAssessment.claim_finding_ids (1133).
  - *Export:* export._finding_row (1058) and the CSV "id" column (954); findings.json and per-sheet JSON (1278, 1457); tile_artifacts._finding_summary (148); tile_artifacts._finding_note_lines (197).
  - *A/B:* ab_findings_diff finding_record (181), sorts (241, 617-623); a parallel identity_key (138).
  - *HTML:* none. The report "id" is qc_id (html_report 2554); deep links are keyed by qc_id (export 862).
  - *Logs only:* verify 737/746/1420/1577; investigate 1415/1500; annotate 1398/1572/1961/2335/2350/3067.
- **s2:** Recommend a new versioned `claim_id` field rather than redefining `id`. `id` is pinned by tests/test_drawing_models.py (12-44) and tests/test_source_identity.py (72-135, where the legacy id is "kept exactly"). It is exported and recomputed on every cache hit. Add "same source, different page, same label" to the regressions; it is reproduced in b8_samepage_label.py.
- **s3/s6, critique boundary (reproduced, b1_critique_boundary.py):** merge_self_consistency folds a "500 gpm" read into a generic read, and the result is marked REPRODUCED. Pass A then merges it into the digest's "550 gpm" finding, so one entry carries sources digest+critique×2 and has no "500". A symmetric Pass B cannot see this, because members absorbed upstream (critique._cluster/_representative, cross_qc._dedup_findings) never reach Ledger._members. Step 6 must require those upstream merges to hand their observations to the ledger.
- **s3/s8, cold/warm:** critique_cache_entry_from_result (1141) caches only post-merge findings. Observations must therefore be serialized in the critique entry, under a critique-scoped version term. Otherwise warm and cold runs diverge.
- **s5/B7:** Removing the coordinator's dedup is not enough on its own. Two same-row sums, `[20,20,20]=540` and `[30,30]=500`, share a quote and have Jaccard 0.667, so the ledger merges them into 1 (b7_ledger2.py). Arithmetic text carries bare numbers, so its signature is empty. A discriminator is needed, such as the computation in the signature, or never merging DETERMINISTIC findings whose computations differ.
- **s6, pre-anchor snapshots:** Member snapshots are taken before anchoring, so the IoU+same-quote branch never fires against one. Today a geometric fold already fails when the *survivor* absorbed members in Pass A. The symmetric patch makes it fail when *either* side did (b1_geom_snapshots.py). The plan must choose one: propagate the resolved anchor to same-quote snapshots, anchor each observation, or record the loss of recall. Also define "compatible" as Pass A's all-pairs `_is_duplicate` relation, not signature compatibility alone.
- **s7:** The coherent bundle and the no-verdict-borrowing rule already exist (test_a_deterministic_member_wins…, test_merge_never_mixes…). What is missing is specificity: a generic member with a longer quote erases a measurement from the exported text. The regression "both measurements survive" has to say where they survive (text or serialized observations). It cannot pass with step 6 alone.
- **Header:** §7.2 assigns N2 to WP-03/WP-06, but WP-03 never names N2 or cross_qc._dedup_findings.
- **Dependencies:** Only WP-03's *acceptance* needs WP-04. The B1 Pass-B fix, the K5 tie-break and the B8 navigation fix do not.
- **Migration:** Name the no-rebind restore paths above. Note that investigate._payload_hash re-keys every stage=investigation entry, which means paid re-runs.
- **WP-21 s6/s7:** Bookmarks and index destinations can key on the placement_id that already exists and is unique; notes_collected is already keyed by placement. No WP-03 dependency is needed.

**WP-04**
- **s2:** "Reject as whole token" must keep an opaque raw quantity. An absent signal never blocks a merge, so dropping the token makes merging *more* permissive.
- **s3:** Bare `deg` and `°` are also angles, as in `45° elbow`. Map `deg` to `°`; map `deg F` and `degrees F` to `°F`. Never infer a temperature scale.
- **s4:** Quantity "roles" are not extracted anywhere today. The minimum rule is a per-unit comparison of value sets; that blocks both the psi/diameter case and `12'-6"`/`12'-8"`. The survivor's `_sig_text` accumulates supporting_quotes, so its sets grow as it absorbs members; state how the rule treats that.
- **s6:** A restated copy of the rule already exists: scripts/ab_findings_diff.py::_signature_conflicts (362-381). After the fix it would return [] for pairs the new rule blocks. Move axis naming into critique, and bump RECORD_CONTRACT_VERSION (77). The tests are in tests/test_ab_findings_diff.py (123-163) and tests/test_ab_sweep.py (1498-1533).
- **Cache (omitted from the plan):** The critique cache stores post-merge findings. The v10 precedent bumped the global digest_cache._SCHEMA_VERSION (87), which re-bills every digest and breaks plan §2 rule 6. Use a critique-scoped term in both critique_cache_key (321) and critique_cache_key_level1 (251).
- **Matrix/acceptance:** `12'-6"/12'-8"` currently merges, so it is a failing case, not an intact safeguard. CLAUDE.md's claim about it is false and needs correcting.

## 3. Missing items
- Duct WxH sizes: `24x12` gives no signature, so "Duct 24x12…VAV-3" and "…24x10…" merge. `24"x12"` is blocked only by accident, because `x12` parses as a tag.
- Compact electrical units: `20A`/`30A` and `480V`/`208V` give no signature, and the breaker pair merges (sig_repro4.py). Adding these units needs a negative corpus: room `101A`, grid `2A`.
- Ranges (`4-6 in`) give no signature; lists (`2,4,6 in`) keep only the trailing fragment.
- The A/B harness is affected by N1.
- The B1 class also arises at the critique boundary (see WP-03 s3/s6).

## 4. Session slicing
**WP-04 (about 2 sessions)**
1. **WP-04.1 — quantity tokenizer.**
   - Closes: B2, B3, B12. Also covers `deg`/`°`, opaque malformed tokens and lists; WxH and V/A only with a negative corpus.
   - Files: critique.py; digest_cache.py (critique-scoped term); ab_findings_diff.py (contract v3); CLAUDE.md.
   - Tests: tests/test_drawing_critique.py, tests/test_drawing_cache_identity.py, tests/test_ab_sweep.py.
   - Depends on: none.
2. **WP-04.2 — compatibility rule.**
   - Closes: N1 (per-unit sets, feet-inches, partial tag overlap), plus a shared `signature_conflicts` used by the harness.
   - Files: critique.py, ab_findings_diff.py, digest_cache.py.
   - Tests: test_drawing_critique.py (test_duplicate_matrix), test_drawing_dedup_lifecycle.py, test_ab_findings_diff.py.
   - Depends on: 04.1.

**WP-03 (about 6 sessions)**
1. **WP-03.1 (S) — symmetric Pass B.**
   - Closes: B1 (entry count and order).
   - Files: ledger.py.
   - Tests: test_drawing_dedup_lifecycle.py (reverse twin, all permutations, severity and quote-length variants). Record the geometry trade-off.
   - Depends on: none.
2. **WP-03.2 (S) — numbering and navigation.**
   - Closes: K5, and B8's bookmark/index-destination part. Uses a total-order tie-break in assign_qc_ids and placement_id keys in annotate.
   - Files: models.py, annotate.py.
   - Tests: test_drawing_dedup_lifecycle.py, test_drawing_markup_rich.py (forced-overflow twin), test_drawing_annotate.py.
   - Depends on: none.
3. **WP-03.3 (S) — auditor dedup.**
   - Closes: B7. Remove the coordinator's id dedup, give titleblock an explicit (sheet, quote) key, and add an arithmetic discriminator.
   - Files: auditors/__init__.py, auditors/titleblock.py, critique.py or ledger.py.
   - Tests: test_drawing_auditors.py, test_drawing_dedup_lifecycle.py.
   - Depends on: 04.2; coordinate with WP-07.
4. **WP-03.4 (M) — claim identity (D-3).**
   - Closes: B8 identity. Switch every inventoried consumer; rebind the cross_qc and prose_harvest restores; add migration rows.
   - Files: models, digest, cross_qc, prose_harvest, annotate, investigate, citation_check, export, tile_artifacts, ab_findings_diff.
   - Tests: test_drawing_models.py, test_source_identity.py, test_drawing_export.py, test_tile_artifacts.py, test_ab_findings_diff.py.
   - Depends on: 03.2.
5. **WP-03.5 (M) — lossless observations.**
   - Closes: B9, the "both measurements survive" part of B1, and the critique boundary. Serialize observations and alternatives on Finding and in the critique cache; make representative selection specificity-aware; export the alternatives.
   - Files: ledger, critique, models, digest_cache, export, html_report.
   - Tests: test_drawing_ledger.py, test_drawing_dedup_lifecycle.py, test_drawing_critique.py, test_drawing_export.py, test_drawing_cache_identity.py.
   - Depends on: 03.1, 03.4, 04.2.
6. **WP-03.6 (M) — canonical final clustering.**
   - Closes: nontransitive A/B/C membership, provenance and actions. Needs per-observation anchors; reconciliation must stay idempotent.
   - Files: ledger.py, pipeline.py.
   - Tests: test_drawing_dedup_lifecycle.py, plus one pipeline integration test.
   - Depends on: 03.5.

---
