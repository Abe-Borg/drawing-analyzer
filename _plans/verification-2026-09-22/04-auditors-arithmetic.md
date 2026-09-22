> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-07, WP-08, WP-03 step 5 (B7). The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# auditors-arithmetic — FINAL REPORT (HEAD = 1.7.0 code)

Method: re-ran prior scratch scripts plus new ones (scratchpad/verify/auditors-arithmetic/). "Reproduced" = real functions executed; fix "simulations" = in-process monkeypatches. A3 CPU ≈ 60 s.

## 1. Verdicts

| ID | Verdict | Current anchor(s) | Evidence | Plan correction |
|---|---|---|---|---|
| N3 | STILL PRESENT (reproduced) | auditors/arithmetic.py::_operands_supported (278; reusable `any(p == n)` 291); ::audit_arithmetic (403; provenance 479-483 decided before anchoring 537-544) | Quote `20 + 20 = 40`, sum [20,20,20]=40 → status=DETERMINISTIC, operand_origin=TEXT_EXTRACTED, computation_method=HOST_DETERMINISTIC, severity high, anchor EXACT; same for `20 20 TOTAL 40`. Fabricated quote → UNANCHORED yet DETERMINISTIC; verifier skips it; inks in verified-only mode as "Math checked by computer from the sheet's own printed numbers". No-sheet claim also DETERMINISTIC | Multiset-only fix (simulated) closes N3 but role swap, sum/product confusion and A8 stay DETERMINISTIC → steps 2+4+5 all required |
| A8 | STILL PRESENT (reproduced) | arithmetic.py::_numbers_in_text (260), ::_head_denies (118), _PLAIN_NUMBER_RE (72) | `SEE FP101 TOTAL 540 AT 439 GPM` → [101,540,439]; sum [101,540]=439 → DETERMINISTIC. parse_number("1e3")=1, "2.5e-2"=2.5. Also `M-101 P-3 AHU-2` → [-101,-3,-2] (hyphen read as minus) | Step 5: add hyphen-after-letter case |
| B7 | STILL PRESENT (reproduced) | auditors/__init__.py::run_auditors (dedup 119-127); critique.py::_is_duplicate geometry branch (852); models.py::compute_finding_id (820) via Finding.__post_init__ (1259) | Two claims on one quote share id; run_auditors keeps 1, stats mismatched=2. With the coordinator bypassed, Ledger.add still merges them (both arrival orders); the UNCERTAIN factor claim vanishes into the DETERMINISTIC survivor | WP-03 step 5 insufficient (§2) |
| A1 | STILL PRESENT (reproduced) | references.py::_audit_spec_sections (565; division gate 588-609) | `FLOW TEST 20 20 20 TOTAL 540`, `CFM 10 15 25` → low DETERMINISTIC "Cites specification section…"; `SPEC SECTION 23 21 13` correct | Positive fixtures conflict (§2) |
| A2 | STILL PRESENT (reproduced) | naming.py::_cluster_key (74), ::_drift_pairs winner branch (216-222) | `20A 3P…` + `PUMP P-3` → DETERMINISTIC "P-3 … inconsistent spelling of '3P'"; reverse winner flips; 1A/A1, 2P/P-2 too | Step 2 literal reading breaks pinned tests (§2) |
| A3 | STILL PRESENT (reproduced, measured) | sheet_ids.py::classify_reference (447; id set rebuilt 471; eager closest 476), ::closest_in_set (281, renormalize+sort 292); references.py::SheetInventory (215); sheet_index.py:182 | 100 sheets×3000 words×40 refs: audit_references 3.37 s CPU cold. cProfile: detection ~50% (_merge_adjacent_id_words; per-word looks_like_sheet_id→NFKC), classify ~34% (1.68M normalize_sheet_id, 100.7k Levenshtein for 4,000 refs). Memo-warm: N=100 1.64 s → N=200 5.66 s (quadratic; 254→504 normalizes/ref; Levenshtein 99k→399k). Simulated normalized set + per-target memo + lazy closest: 0.49 s / 0.97 s, identical findings | Add measurable targets (§2) |
| A4 | STILL PRESENT (reproduced) | references.py::_PHRASE_RULES (116-125), ::_audit_sheet (482; quote dedup 491/526) | No harvest for SEE DWG, SEE DWG., REFER TO SHEET, SEE SHEET NO., REF., SEE DETAIL 3 ON, `SEE M-501 AND M-502 FOR`; `SEE DRAWINGS M-501, M-502` → only M-501 | Per-target quote spans (§2) |
| A5 | STILL PRESENT (reproduced) | references.py::_detect_sheet_id_word_uncached (339; score 386-393) | M-101 plus A23-101 to its right → A23-101; E1 below → E1; M-101-REV2 → M-101-REV2 | Label reuse (§2) |
| A6 | STILL PRESENT (reproduced); consequence CLAIM INACCURATE | sheet_ids.py::_STANDARD_BODIES (312-316), ::never_a_sheets_own_id (377), ::is_non_sheet_reference (346); references.py:381-384 | FM-101 alone → FM-101; plus a `SEE M-101 FOR…` note → M-101. References to FM sheets never become MISSING_FROM_SET: is_non_sheet_reference("FM-109") is True, so an FM-only set citing absent FM-109 yields 0 findings | §3 |
| A7 | STILL PRESENT (reproduced) | sheet_index.py::_as_index_sheet (86-143), ::_find_header_rect (67), `_MIN_INDEX_ENTRIES` (55), direction 2 (223+) | 7-sheet set + prose sheet → 3 low DETERMINISTIC "present but not listed"; all 3 survive run_auditors and the ledger | Step 7 names the wrong direction (§2) |
| dead `sug` | STILL PRESENT (reproduced) | references.py::_audit_sheet line 550 | `ruff check --no-cache --select F841` on auditors/ → only hit 550:17 | Fold into WP-08 A4 slice (same function), not WP-22/23 |

## 2. Plan-text corrections

- **WP-03 step 5 (B7).** Removing the coordinator dedup does not keep the second mismatch.
  - audit_arithmetic anchors its own findings (537-544), so they reach Ledger.add already anchored.
  - _is_duplicate's geometry branch (852: IoU > 0.5 and equal quote, with no text or claim check) then fires, because critical_signature has no measurements for unitless numbers.
  - Needed: a claim discriminator (kind + Decimal-canonical terms + expected) that blocks this merge in Pass A and Pass B. It must also be folded into the arithmetic finding's id; otherwise two same-id entries hit the B8 consumers (models.py::assign_qc_ids tie-break 1437; annotate.py:2428 mark_page_by_finding).
  - Scope it to auditor_arithmetic findings: critique._cluster (963) uses the same predicate for cached self-consistency merges, and the v10 precedent (digest_cache.py:75-87) shows a general critical_signature change forces a cache-wide _SCHEMA_VERSION bump.
  - Regression: run_auditors → Ledger.add → reconcile_post_anchor → number(), both arrival orders. §7.1 B7 row: "survive the coordinator and the ledger".
- **WP-03 step 5 / WP-07 step 7.** critique._dedup_claims (1543) and arithmetic._claim_dedup_key (362) both key on raw `str(t)`. Terms 20 vs "20.0" and 540 vs "540" gave checked=2, mismatched=2 and two same-id findings (reproduced). Key on parsed Decimals.
- **WP-07 step 3.** Name the mechanism: provenance is decided (479-483) before anchoring and never consults the anchor or whether geometry resolved. Decide it after anchoring, and require a resolved sheet plus an EXACT (or numeric-vetoed FUZZY) quote anchor.
  - Re-baseline with sheet words (do not delete) three tests that call `audit_arithmetic(..., [])` and assert DETERMINISTIC: tests/test_drawing_auditors.py::test_a_comma_separated_operand_list_stays_text_extracted (131), ::test_arithmetic_text_extracted_operands_stay_deterministic (344) and ::test_arithmetic_mixed_fraction_operand_is_text_extracted (364).
  - ::test_arithmetic_unresolved_sheet_still_records_finding_unanchored (431) keeps its finding, but the finding becomes UNCERTAIN.
  - tests/test_drawing_acceptance.py::test_gauntlet_deterministic_auditors_fired (1061) must stay DETERMINISTIC; its quote "TOTAL 100 + 250 = 375" is on the sheet.
- **WP-07 step 4.** Keep relationship validation host-side: adding role/operator fields edits the claims contract in _CRITIQUE_FINDINGS_INSTRUCTION (critique.py:217-229, hashed into CRITIQUE_PROMPT_VERSION 238) and cross_qc (~200), re-keying every critique/cross-QC cache entry.
- **WP-07 step 5.** `_NUM_IN_TEXT_RE`'s `[-+]?` reads a hyphen after a letter as a minus sign (tag digits become negatives). Keep the scanner↔parser agreement test (test_drawing_auditors.py:171). Trailing letters are units (20A, 150GPM) and must still parse.
- **WP-07 step 7.** The matched path never checks provenance (ungrounded operands still count "checked out OK"). Consumers to name: annotate.py::_insert_appendix_page (1836), html_report.py::_audit_checks_line (1118), gui.py (~2197), run_journal.py (~821).
- **WP-08 step 1 vs acceptance.** The existing positive CSI fixtures are bare triples: tests/test_drawing_reference_audit.py::_fp_set (163, used by the test at 205) and the test at 343 ("23 21 13" / "26 05 00"). Word spacing cannot separate them from "20 20 20", and a "real division" rule would not stop "CFM 10 15 25" (Division 10 exists). The plan must state that these fixtures move to cue-bearing forms and that a bare triple is no longer reported.
- **WP-08 step 2.** Read literally, "apply arrangement with a winner" fails test_drawing_auditors.py::test_an_established_convention_outranks_structural_doubt (524) and ::test_naming_still_flags_pure_format_drift_same_digits, and contradicts CLAUDE.md ("An established winner still outranks structural doubt"). Instead, add kind order (letters first vs digits first, separators ignored) to naming._cluster_key. Simulated: all 9 naming tests pass, and 3P/P-3, 1A/A1 and 2P/P-2 no longer cluster.
- **WP-08 step 3.** _audit_sheet dedups on the verbatim quote (491/526), and Finding.id hashes that quote. A list rule that emits targets 2..n with quote=m.group(0) therefore drops them silently, so give each target its own quote span and rect. test_audit_various_trigger_phrases (240) pins "SEE SHEET M-999", "ON DRAWING M-998" and "SEE M-997 FOR"; new rules must not widen those quotes.
- **WP-08 step 4.**
  - Reuse titleblock's label helpers (_FIELD_LABELS 76-82, _group_lines, _extract_labeled_fields 119) by moving them into sheet_ids.py. titleblock already imports references (line 29), so importing it back would be circular.
  - titleblock._sheet_band (180) derives its band from the chosen id word; ranking changes move it.
  - Surface ambiguity without changing detect_sheet_id's str|None return (14 call sites, incl. cross_qc 1520, investigate 506, profiles 310, prose_harvest 1032/1042) or dropping sheets from build_inventory; name the observable (e.g. an audit_stats key, which run_journal prints).
- **WP-08 step 7.** The partial-package flood is direction 1, at medium severity. A real index listing 50 ids with 5 sheets submitted gave 45 "The drawing index lists M-1xx, which is not present in the provided set" findings (reproduced). The step names only "present-but-not-listed" (direction 2, A7's case, which step 6 fixes).
- **WP-08 step 8 / acceptance.**
  - sheet_index.py:182 calls classify_reference directly, bypassing references._resolve, so the memo belongs on SheetInventory (a plain @dataclass).
  - Proposed targets on the seeded 200 sheets × 2000 words × 40 refs fixture:
    - normalize_sheet_id calls during classification: 4.03M today → at most N + distinct targets.
    - Levenshtein calls: 399,200 today → at most (distinct unresolved targets) × N.
    - Warm audit_references: 5.7–6.4 s today → about 1.2 s or less, and at most ~2.2× when the sheet count doubles.
  - Cold detection (~50% at N=100) is linear; out of step 8's scope unless stated.

## 3. Missing items

- **A6 references.** FM-* targets are always IGNOREd, even when the inventory itself is FM-numbered. Add set-aware adjudication in classify_reference. Do not put it in is_non_sheet_reference, which is documented as never consulting the set.
- **Contradictory arithmetic reads.** Two critique reads of one quote, [20,20]=40 and [20,20,20]=40, give checked=2, matched=1 and a DETERMINISTIC mismatch. Conflicting transcriptions of the same quote should be downgraded or flagged, not split into "OK" plus a ground-truth mismatch.

## 4. Session slicing

**B7 (WP-03 step 5): 1 session.**
- **S3-B7 "Distinct same-row arithmetic mismatches survive"**
  - Closes: B7 plus the counter drift.
  - Files: auditors/__init__.py, auditors/arithmetic.py, critique.py (arithmetic-scoped discriminator), models.py (additive field only if needed).
  - Tests: tests/test_drawing_auditors.py (run_auditors section), tests/test_drawing_ledger.py.
  - Depends on: nothing; coordinate with ledger.py/critique.py owner and WP-04.

**WP-07: about 2.5 sessions.**
- **S7-1 "Occurrence-aware, sheet-grounded operand support"**
  - Closes: N3, the fabricated/absent quote case, and the no-geometry DETERMINISTIC case.
  - Files: auditors/arithmetic.py.
  - Tests: tests/test_drawing_auditors.py (re-baseline 131/344/364/431), tests/test_drawing_acceptance.py (gauntlet), tests/test_drawing_qc_pipeline.py.
  - Depends on: nothing.
- **S7-2 "Relationship/role validation + strict tokens"**
  - Closes: role swap, sum-vs-product confusion, A8 (tag and sheet-id digits, hyphen-as-minus, `1e3`).
  - Files: auditors/arithmetic.py.
  - Tests: tests/test_drawing_auditors.py.
  - Depends on: S7-1. Can split into A8 tokens (small) and relationships if needed.
- **S7-3 "Truthful arithmetic counters"**
  - Closes: WP-07 step 7 (provenance-split matched/mismatched counts, Decimal dedup keys).
  - Files: arithmetic.py, critique.py::_dedup_claims, annotate.py, html_report.py, gui.py.
  - Tests: tests/test_drawing_auditors.py, tests/test_drawing_markup_rich.py, tests/test_drawing_html_report.py.
  - Depends on: S7-1 and S3-B7. Could merge into S3-B7.

**WP-08: 5 sessions.**
- **S8-1 "Numeric-row CSI + pump/breaker naming"**
  - Closes: A1, A2.
  - Files: references.py (_audit_spec_sections), naming.py (_cluster_key).
  - Tests: tests/test_drawing_reference_audit.py (re-baseline fixtures at 163/343), tests/test_drawing_auditors.py.
  - Depends on: nothing.
- **S8-2 "Inventory-scoped resolution memo"**
  - Closes: A3.
  - Files: sheet_ids.py, references.py, sheet_index.py.
  - Tests: tests/test_drawing_reference_audit.py or tests/test_drawing_sheet_ids.py (operation-count and identical-output tests).
  - Depends on: nothing.
- **S8-3 "Reference phrase recall + dead sug"**
  - Closes: A4, dead `sug`.
  - Files: references.py.
  - Tests: tests/test_drawing_reference_audit.py.
  - Depends on: S8-2 (same functions).
- **S8-4 "Label-aware own-ID ranking + FM"**
  - Closes: A5, A6 (including FM references).
  - Files: references.py, sheet_ids.py, titleblock.py (move label helpers).
  - Tests: tests/test_drawing_reference_audit.py (detection tests 59, 484-600), tests/test_drawing_auditors.py (title block).
  - Depends on: S8-2.
- **S8-5 "Index region + partial packages"**
  - Closes: A7 and WP-08 step 7 (both directions).
  - Files: sheet_index.py.
  - Tests: tests/test_drawing_auditors.py (sheet-index section, 657-800).
  - Depends on: S8-4.
