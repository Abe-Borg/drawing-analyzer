> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-05, WP-06, WP-10 (K2). The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# anchor-crossqc (verifier report, condensed but complete)
All 11 STILL PRESENT; 10 reproduced, 1 traced (§4c). Scripts: scratchpad/verify/anchor-crossqc/{b4_repro,b5_repro,crossqc_repro}.py

Verdicts/anchors:
- B4 reproduced. anchor.py::_normalize(104), _Stream.__init__(139), _numbers_agree(281), _numbers_aligned(311), _try_fuzzy_window(367), _try_fuzzy_subphrase(440), _anchor_one(495); consumers verify._is_verifiable(207), investigate._candidates(1325), annotate UNANCHORED label(153). All 7 pairs UNANCHORED; veto needs same whitespace token.
- B5 reproduced. cross_qc._grounded(487; len<6 at 496), classify_quote_evidence(536; match test 575 before no-text 577), _finding_from_handles(775), _parse_facts(1148), anchor tile fallback(526). Short tags TEXT_GROUNDED on textless & absent; counted legs_accepted_grounded but UNANCHORED. >=6-char substring has no word boundary: AHU-10 grounds in AHU-101; VAV-2-1 in VAV-2-10.
- B6 reproduced. CROSS_QC_SYSTEM_PROMPT(154; sentence 171-173; shared by whole-set + map), _validate_cross_item(601-602), _finding_from_handles(735-736), INFO log(1082). severity:"question" -> 0 findings, complete=True, error=None, CACHED. Loss invisible.
- B10 reproduced. _dedup_findings(1310-1331); Ledger.add buckets by primary sheet (ledger 246-247); critique._same_sheet(574), _leg_targets(739), signatures_compatible leg check(797-799). A->B + B->A = 2 findings; ledger keeps 2.
- K2 reproduced. _cross_qc_cache_key(1348-1410), _CROSS_QC_TASK(175), _build_whole_set_input(951), _build_map_input(969), _build_reconcile_input(993), [TRUNCATED N chars](897).
- N2 reproduced. _dedup_findings._key(1316-1321) = (label, category, quote, sorted legs). Valve+airflow collapse to 1; ledger alone keeps both.
- N6 reproduced. cross_sheet_qc first-wins sheet_map(1537-1550), headers(951-966), lookup(624). Sharded uses unique S### handles (1597). arithmetic._build_maps first-wins by id (384). Two identical "===== SHEET M-101 =====" headers; b.pdf quote bound to a.pdf; M-101<->M-101 conflict dropped; sharded _dedup_findings collapses same-label SRC-1/SRC-2; whole-set claim (no source) binds SRC-A -> UNANCHORED.
- §4a reproduced. api_config CROSS_QC_OUTPUT_CAP(162), _PHASE_OUTPUT_BUDGET(212); cross_qc._call(1018; max_tokens 1025; method="create" 1041; stop_reason only read when text empty 1052); digest.scan_structured_blocks(948 accepts unclosed fence), _tolerant_json_object(1046). max_tokens 16000 + adaptive thinking on plain create; max_tokens w/ closed object, no closing fence -> complete=True, cached, warm replays 0 calls; cut mid-array loses all, no retry.
- §4b reproduced. _TEXT_LAYER_BUDGET(112), _budgeted_text_layer(887), completeness(1578,1679-1683), cache refusal(1413,1450). One 4001-char sheet -> degraded -> PARTIAL, never cached; qc_status capped PARTIAL.
- §4c traced. DEFAULT_MAP_MAX_FACTS(107), _parse_facts cap(1125), _shard_by_discipline(1294). 41 single-discipline -> [40,1]; 60 facts->40 kept, 20 dropped uncounted.
- §4d reproduced. _validate_cross_item(588-662), whole-set branch(1567-1585). Invented quotes accepted; evidence_state ""; discards None.

Plan corrections:
WP-05 header: "grounding portion of B6" is mislabel -> "review §4(d) whole-set grounding" (B6 has no grounding part).
WP-05 s1: two normalizers disagree: anchor._normalize vs cross_qc._norm_for_match (fold_text only; no curly quotes/primes/½/×/Ø/infix hyphens). Reproduced: PROVIDE 6” DRAIN, 2½"<->2-1/2", Ø6, 300×200 NOT_MATCHED in cross-QC -> leg dropped. fact_tile_lookup(678) joins on _norm_for_match.
WP-05 s2: existing veto compares exact whitespace tokens; after char-stream match it rejects 3/7 positives (6" vs 6+", 2% vs 2+%, 12'-6" vs 12',-,6"). Veto must compare canonical number+unit quantities (WP-04). Don't lower _FUZZY_WINDOW_MIN_OVERLAP (asserted 0.85 tests/test_drawing_anchor.py:248-250; CLAUDE.md standing prohibition).
WP-05 s3: not only short quotes: _grounded substring no boundaries for any length; anchor.py infix hyphen folding -> VAV-2 EXACT inside VAV-2-1, AHU-1 inside AHU-1-2 (reproduced). Require matched spans start/end on source-word boundaries (_Stream.word_of).
WP-05 negatives: add leading decimal (.5 must not become 5).
WP-05 cache: B5 changes stored evidence_state/admitted legs -> _CROSS_QC_CACHE_CONTRACT 3->4 (P8-11 precedent); three tripwires assert ==3: test_drawing_cross_qc.py::test_cross_qc_contract_bumped_for_the_norm_id_fold, test_evidence_visual.py::test_contract_counter_is_not_bumped_by_this_package, test_evidence_tail.py::test_no_cross_qc_contract_bump_was_needed.
WP-05: verify.py needs no edit (TILE anchors already pass _is_verifiable/_has_anchored_legs); extend test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation for short tags.
WP-06 s1/N6 scope: also (i) _dedup_findings keys labels (both paths), (ii) whole-set claims carry no source; arithmetic._build_maps first-wins by id -> rebind via _resolve_claim_handles; ambiguous id lookup must refuse, (iii) critique._leg_targets label-based (drives ledger merges), (iv) _fallback_id (stem-pN) collides for same-basename PDFs w/o detected id, (v) a conflict between two same-label sheets is inexpressible.
WP-06 s1: keep human id visible next to handle (S001 = M-101) like reconcile manifest; map input shows only handle today.
WP-06 s4 (B10) can't work as written: Ledger.add buckets by primary source_page_key; _is_duplicate needs same primary + equal leg_targets -> A->B vs B->A never compared. Need symmetric leg-set predicate or symmetric merge inside cross-QC unioning legs/quotes. N2 alone: hand dups to ledger instead of destructive dedup.
WP-06 acceptance "reversed duplicates produce one finding" needs a stated same-claim predicate (shard vs reconciler phrase differently).
WP-06 s5: add invalid-fields counter to CrossQCDiscardCounts on both paths; one prompt edit fixes whole-set + map; prompt hash auto-invalidates.
WP-06 s6 reverses recorded decision: WP-03A scoped whole-set out of grounding (test_evidence_tail.py::test_forty_entries_take_the_whole_set_path_unchanged). Ground via classify_quote_evidence against sheet_evidence_text (uncapped), never 4k prompt text; discards becomes non-None on whole-set: update comments pipeline.py:603, :3681, cross_qc.py:1605, CLAUDE.md line ~554. Paraphrased quotes lose recall -> measure with §7.2 counters.
WP-06 s7: _call is the one text stage still on plain create; missing from CLAUDE.md streaming list; cap raise >~21k must move to digest.stream_message same change. Partial preservation needs a bounded salvage parser (_tolerant_json_object all-or-nothing; only claims salvaged today).
WP-06 s8: text omission already counted (text_chars_omitted, stage warning); invisible: _parse_facts drops facts past 40 (1125) -> name counter.
WP-06 migration: every host-binding change needs contract bump; cached entries store already-bound findings, no raw reply -> "legacy response" handling can't apply to cache.
WP-06 unnamed consumers: tests/fixtures/gauntlet.py CROSS_CONFLICT (whole-set sheet_id items, underpins run_acceptance.py), tests/test_drawing_acceptance.py, whole-set fixtures in test_drawing_cross_qc.py; tests/test_source_identity.py natural home for N6.
WP-06 deps: B6 and N2 don't need WP-01 or WP-03.
WP-06 whole-set/sharded equivalence testable only at parser level.
WP-10 s2 (K2): accurate; pre-call effective-request fingerprint can't cover reconcile (depends on map outputs) -> hash framing constants like SHARED_USER_FRAMING_STRINGS. [TRUNCATED N] never reaches cache today (degraded never admitted) -> test only that it's in key.
Register: N6 row add arithmetic/dedup/leg_targets sites; truncation/40-fact row name missing fact-cap counter.

Missing items: (1) normalizer disagreement -> WP-05 5A; (2) hyphen-segment prefix false EXACT in anchor.py (VAV-2 in VAV-2-1) -> 5B; (3) degraded cross-QC never cached -> re-bills full Opus cross-QC every warm run, qc_status permanently PARTIAL -> WP-10/WP-25 decide whether to cache with PARTIAL status (then truncation marker load-bearing); (4) arithmetic by-id first-wins for sourceless claims -> WP-06.

Slices (~7 sessions): 5A cross-QC grounding (B5 + normalizer; contract 3->4; tests evidence_visual/cross_qc/evidence_tail); 5B anchor punctuation folding + word-boundary tag rule (B4 PSI,/NOTE 3:/(568 L/MIN); hyphen prefix; .5/sign negatives; test_drawing_anchor.py); 5C char-stream tier + quantity-aware veto (B4 6 "/INCHDRAIN/12' - 6"/2 %; needs WP-04). 6A B6 prompt + validation-loss counters + claim-preserving dedup (N2) (cross_qc, pipeline warning); 6B whole-set on host handles + grounding + claims rebound + K2 framing hash (N6, §4d, K2; cross_qc, arithmetic, pipeline, CLAUDE.md, gauntlet; needs 5A; largest ~1-1.5k); 6D cross-QC terminal-state honesty (stop_reason, streaming, bounded raised-cap retry billed, partial-array salvage, fact-cap + per-sheet omission counters; §4a + observability of §4b/c; needs WP-01 contract; cross_qc, pipeline, api_config); 6C direction-free merge (B10; after WP-03; cross_qc, opt ledger/critique; tests cross_qc + ledger). Order: 5A -> 6A -> 5B -> 6B -> 6D -> 6C -> 5C.
