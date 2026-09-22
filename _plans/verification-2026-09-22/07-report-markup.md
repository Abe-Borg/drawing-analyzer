> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-19, WP-20, WP-21. The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# report-markup — verification (HEAD src == 1.7.0)
Method: re-ran prior scratch (calc_run.js, h1_repro.py, r4_repro.py, r5_repro.py); added h2_repro, h3_repro, n9_collision, key_repro, search_ctx_repro, search_throttle, search_toggle (scratchpad/verify/report-markup/). Browser = headless Chromium via repo test helpers; calculator via node on a verbatim extract (diff-identical to html_report.py 4067-4131). One targeted pytest run. All anchors html_report.py unless noted.

## 1. Verdicts
| ID | Verdict | Current anchor(s) | Evidence | Plan correction |
|---|---|---|---|---|
| H1 | STILL PRESENT (reproduced) | sortBy (2398-2413); applyRepeatGrouping (2205); apply (2299) | Sheet-desc sort: hidden F-D-03/02/01 sit above visible lead F-D-00 until some later apply(). CLAUDE.md "recomputes after every sort/filter" is false for sort. | tests/test_report_browser_security.py:845 PASSES on the bug (counts only) — strengthen it; fix CLAUDE.md. |
| H2 | STILL PRESENT (reproduced) | _finding_display_status (690; 714-715); _findings_data_block "status" (2562); _starter_prompts (2742-2746); anchor.py::_tile_anchor (486-492) | Quote-less tile-less finding → chip "Unanchored", da-findings UNANCHORED, "could not be verified" starter, no evidence note. PDF prints [SHEET-WIDE] for SHEET hint (review's "[NO QUOTE TO CHECK]" applies only to non-SHEET). | Add WP-01/N5 dependency (§2). |
| H3 | STILL PRESENT (reproduced, modeled SSE) | SSE message_start (4946-4959), message_delta (4960-4977); renderUsage (4256-4291); _chat_bootstrap_html "rates" | Final message_delta {input 90k, 8 web_search_requests} after message_start input 1k → readout "1k in · 500 out · est. $0.01" (≈$0.27 at Sonnet 5 rates). Only output_tokens read; rates in/out only; cache writes a 1.25–2x band. No double count today. | Use final usage, `usage.cache_creation` 5m/1h split, core/pricing.py WEB_SEARCH_COST_PER_USE via CFG. |
| R4 | STILL PRESENT (reproduced) | stripDanglingToolUse (5459-5461); step: Stop branch (5504-5518), commit (5527-5536; cap falls through silently), catch (5589-5612); hasToolUse/dropUnansweredTail (5335-5353); restoreFromStorage (5366); saveTranscript (5204) | Next question carries an unpaired server_tool_use in all 4 scenarios: Stop after pause_turn arrived; Stop in mixed server+client group (client stripped, server kept); 8-continuation cap (no message); max_tokens mid-server-tool. Survives reload. | Also abort/stream failure after a committed pause_turn round (catch keeps it). |
| R5 | STILL PRESENT (reproduced) | annotate.py::_insert_review_notes_page (mutation 1963-1964); _execute_reviewed_pdf_job (2486); _run_reviewed_pdf_jobs (spawn 2587-2589); write_reviewed_pdfs (2939) | 2 sources, forced overflow: workers=1 plan REVIEW_NOTES 8 = receipts 8; workers=2 plan 0 vs receipts 8 (8 mismatches); coverage/tally equal. | Child placements already return in outcome.receipts[i].placement — rebuild plan by placement_id; no new outcome field. |
| N7 | STILL PRESENT (reproduced) | buildRequest `calculate` (3841-3844, "guaranteed correct"); evalArith (4067; strips whitespace 4068); toolCalculate (4117); runTool | `1.2.3 + 1`=2.2; `1e+ + 2`=3; `1 2 + 3`=15; `1..2`=1; 9007199254740993−9007199254740992=0; 12345678901234567−12345678901234566=2; `100000000000000.3+0` drops .3; 20k-deep parens → caught RangeError echoing 40k chars; errors sent is_error:false (traced). | Step 8 must say is_error:true. |
| N9 | STILL PRESENT (reproduced) | annotate.py::_insert_index_pages (1799-1810); _set_findings_outline (2253-2267); _annotate_units mark_page_by_finding (2424-2428); notes row `box` (1927) never returned | Overflow notes: every index link → (36,36), every bookmark → (0,0) on the notes page; rows at y0 96/166/236/306. Drawing-rect reuse happens only via finding.id collision: a TILE cloud sharing an id with an overflowed note → its index row goes to the notes page at (600,500); its bookmark is dropped (7 for 8). | Re-describe: overflow is rect-less by construction (is_margin_callout 547-559) so the dominant defect is page-top, not row; the rect variant is a B8 consumer. |
| §4 context | STILL PRESENT (traced+sized) | `REPORT` (3312-3313); systemBlocks (3585-3631); _raw_html (1710-1722) | Whole combined_text in a 1h-cached system block on every request; history never trimmed ("Nothing host-side trims"). 400 synthetic sheets × 3.8k chars = 1.55M chars ≈ 390k tokens; 1M reached at ≈10k chars/sheet. | — |
| §4 search | STILL PRESENT (reproduced, measured) | apply (2299-2334; 2313); applyFindings (2277); debounce (2357-2360); _rawtext_block (1189-1215) | 400 sheets: 1,601 blocks/7.55M chars lowercased per debounced keystroke: 18-20 ms (CPU x1), 95-137 ms (x4), 148-165 ms (x6); clearing costs 0.2/0.6/0.9 s, mostly layout. | Modest; caching fixes the scan only. |
| §4 key | STILL PRESENT (reproduced, Chromium) | KEY_STORE (3314); storedKey (3354); readerKey (3367); saveKeyFromInput (4421-4446) | Origin "file://": same tab navigated to an unrelated local HTML reads the dummy key; window.open child inherits it; other tab does not. | Transcript gap (§3). |

## 2. Plan-text corrections
WP-19
- Step 1/4 (and the review's fix): each pause_turn round is a separate assistant entry, and the resumed round begins with the previous round's *_tool_result. A per-message pairing check would strip srvtoolu_0..7 and orphan their results. Pair over the API-merged run of consecutive assistant entries (or merge rounds on commit).
- Step 2: "deferred server call" is not a documented mechanism; code already commits all blocks on tool_use (5527-5528). Settle mixed-group behavior in the canary. (Docs: a paused turn may end in a trailing server_tool_use, resumed with no new user message.)
- Step 4: TX_SCHEMA=1 (3324) + transcriptProblem (5324-5330) hard-reject other versions and restoreFromStorage then calls dropStoredTranscript() — a bump deletes every saved conversation. Accept v1; repair on load.
- Step 5/matrix "fallback": the widget sends no `fallbacks`/beta header; CHAT_MODEL_DEFAULT is Sonnet 5 (api_config.py:101). Conditional only.
- Step 6 already exists (turnGen guards 5499/5553/5593/5622; stopRequested latch; test_report_chat_tools.py:1980) — regression-only.
- Acceptance "real-SDK schema tests": raw-fetch JS; SDK params are TypedDicts and pairing is server-side semantics, so they cannot catch R4. Use one host-side history validator (commit/save/load) + live canary.

WP-20
- Step 1: rewrite tests/test_report_chat_tools.py::test_report_block_uses_one_hour_ttl (1232) and ::test_system_blocks_are_byte_stable_across_turns; preamble "The next system block is the complete report text" (3591); CLAUDE.md wrapper paragraph. Verbatim text exists only in #raw-md (2469: never duplicated) → per-sheet retrieval needs a host-side offsets map keyed by sheet-N/source_id/page (headers are host-made `## Sheet i/N: label`, pipeline._sheet_header 677); don't parse model prose in JS.
- Step 2 "output/continuation reserve" conflicts with the documented rule never to lower max_tokens below the ceiling (3727-3734, 5566-5584); record the decision.
- Step 3: toolScroll (3896) resolves labels by first substring match (M-10 → M-101; duplicates → first); query_findings sheet filter is substring.
- Step 7: CSP is hash-only inline script (_csp_meta 621, pinned by a test) → no CDN library; native BigInt rationals give exact arithmetic with explicit division rounding.
- Step 8: toolCalculate returns error strings; runTool flags only throws.
- Acceptance "400-sheet report answers questions": the stubbed harness can assert request shape and retrieval results only; answer quality is live/manual.
- Dependencies: steps 5-10 (H3, N7, key) need none of WP-03/14/19; don't hold them to wave 4.

WP-21
- Steps 1-2: "failed verification attempt" is not representable per finding: verify.py stores UNCERTAIN (739) or SKIPPED (fatal, 730-734) with the error only in `note`; DEGRADE_* lives on stage counters. Add WP-01/N5 dependency. PDF index merges SKIPPED+UNCERTAIN as "Check" (annotate._INDEX_STATUS_LABEL 212, shared _TRUST_NOTE). New states touch _FINDING_STATUS_CHIP (664), integer _STATUS_RANK (680; test_drawing_html_report.py:809), _UNCONFIRMED_STATUSES (687), .fchip-* CSS, query_findings status text (3797-3811), toolSummary (4015). CSV already has anchor_status/anchor_method (export.py:954): add a column.
- Step 4: "semantics identical" contradicts "exclude transient controls": row.textContent includes the repeat-toggle label, so "more sheet" now matches only the group lead. Highlights use the CSS Highlight API (no DOM text). Compare against a control-excluded reference with a measured budget.
- Steps 6-7: sites keyed by finding.id: mark_page_by_finding (2424-2428), outline `seen` (2253); keying by placement_id fixes misroute/bookmark loss before WP-03. `collected` tuples (component, xref, pno) feed stamping (2446-2457) and final_page_by_pid (2467-2473); MarkupReceipt (models.py:1564) has no rect → additive field + manifest.

## 3. Missing items
- localStorage transcript on file:// (saveTranscript 5209, TX_KEY 3326, ≤500k chars) is readable by any local HTML; WP-20.9-10 cover only the key (rule 11).
- CLAUDE.md sort-regrouping sentence; dropUnansweredTail comment (5331-5334) claims consecutive user turns are rejected (the API merges them).
- N7 length bound must also cap the echoed expression.

## 4. Session slicing
WP-19 (~1.5)
1. 19-A Pair-aware turn normalization — R4; steps 1/3/4/7 (validator at Stop, non-continuing commit, cap exit + note, catch, save, restore/adopt; accept TX v1). html_report.py; tests/test_report_chat_tools.py (1109-2129, port r4_repro scenarios + reload). ~600-900 lines. Deps: none.
2. 19-B Mixed-tool/pause semantics + replay canary — steps 2/5/6. test_report_chat_tools.py, tests/test_live_api_canary.py. ~300-500 lines. Deps: 19-A, WP-02.

WP-20 (~5)
1. 20-A Exact calculator — N7. html_report.py; test_report_chat_tools.py (221), test_drawing_html_report.py:741. ~300-500 lines. Deps: none.
2. 20-B Chat cost readout — H3. html_report.py (+core/pricing rates); test_report_chat_tools.py (1387, 1640). ~250-400 lines. Deps: none.
3. 20-C Reader credential + transcript storage — §4 key. html_report.py; test_report_browser_security.py (337-548, 905-925), test_drawing_html_report.py (378/402/433). ~300-500 lines. Deps: none.
4. 20-D1 Bounded context + retrieval tools — steps 1-3 (threshold, index, offsets map, paged search, duplicate labels, 400-sheet fixture). html_report.py; test_report_chat_tools.py (cache tests 1232+). ~1,000-1,500 lines (may split index vs paging). Deps: 19-A.
5. 20-D2 History budgeting at exchange boundaries — step 4. ~400-700 lines. Deps: 19-A, 20-D1.

WP-21 (~3.5-4)
1. 21-A Worker plan parity — R5; steps 5/8. annotate.py; tests/test_drawing_annotate.py (extend real-spawn parity test 359 with forced overflow). ~150-300 lines. Deps: none.
2. 21-C Regroup on sort + search text cache — H1, §4 search; steps 3-4 + CLAUDE.md. html_report.py; test_report_browser_security.py (845+). ~250-450 lines. Deps: none.
3. 21-B Actual destinations + placement-keyed navigation — N9, B8 consumers; steps 6-7. annotate.py, models.py, export.py; test_drawing_annotate.py, test_drawing_export.py. ~600-900 lines. Deps: 21-A.
4. 21-D Display vocabulary — H2; steps 1-2. html_report.py, annotate.py, export.py; test_drawing_html_report.py, test_report_browser_security.py, test_drawing_annotate.py. ~600-1,000 lines. Deps: WP-05; failed-attempt state after WP-01/N5.

Order: 21-A, 20-A, 19-A, 21-C, 21-B, 21-D, 20-B, 20-C, 19-B, 20-D1, 20-D2.

---
