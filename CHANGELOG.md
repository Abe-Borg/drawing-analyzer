# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- **README brought fully in line with the §18 gating amendment.** The GUI
  section no longer describes the retired "Verified findings only (on by
  default)" sub-toggle — it now documents the exhaustive-ink default, the
  renamed **Verified & deterministic only** opt-in (default off), and the
  **Include rejected (grey)** toggle; the cross-sheet-QC and anchoring sections
  no longer reference the old verified-only default (an `UNANCHORED` finding is
  documented as landing in a margin callout); the findings-card column list
  gains the `ID` column; the configuration table gains the previously
  undocumented `DRAWING_ANALYZER_CHAT_MODEL`, `DRAWING_ANALYZER_DIAGNOSTICS`,
  `DRAWING_ANALYZER_DEBUG`, and `DRAWING_ANALYZER_CACHE_DIAGNOSTICS` variables.
- **Package docstring updated** (`drawing_analyzer/__init__.py`): the module
  map now covers the full QC stack, and the stale "render.py is the ONLY module
  that imports PyMuPDF" claim is corrected (`annotate.py` is the second,
  deliberate importer — matching the README's licensing section).
- **`CLAUDE.md` added**: commands, big-picture architecture, the binding
  invariants (I-1…I-7, no-eval arithmetic, additive serialization, ledger
  coverage), and the PyMuPDF pitfalls, for AI-assisted development sessions.

### Fixed (post-Phase-16 review)

- **Synthesis sheet-id matching is boundary-aware.** A set holding both `A-1`
  and `A-10` no longer reads a synthesis mention of `A-10` as also naming
  `A-1` (which could make the never-named prefix sheet the conflict's primary
  anchor and add a bogus `also_on` leg): a neighbour that is alphanumeric —
  or a `.`/`-` connector with an alphanumeric beyond it, so naming detail
  `A-1.1` never names sheet `A-1` — rejects the match, while sentence
  punctuation (`"… on A-1."`) and slashes (`P-1/P-2`) stay valid boundaries;
  a shorter id additionally never counts inside a longer in-set id's mention.
- **A `DETERMINISTIC` verdict survives ledger merges without a rectangle.** A
  rect-less auditor duplicate (an arithmetic mismatch whose quote didn't
  resolve) no longer loses its host-computed verdict when merged into an
  earlier model entry — previously it would be treated as unverified and gated
  in verified-only mode; the anchored-member merge path also can no longer
  downgrade an existing deterministic verdict.
- **The §18 coverage tally only runs on markup runs.** A reference-audit-only
  run (`qc_markups=False`) no longer logs/reports `Ledger N: X clouded, …` for
  clouds that were never written to any PDF; `ctx.ledger_tally` stays empty and
  `ctx.ledger_tally_line` is `""` for such runs.

### The findings ledger — guaranteed carry-through of ALL QC items (Part III / Phase 16)

Nothing QC-flavored may live only in prose: every item from every channel lands
in one ledger and, from there, on the reviewed PDF.

#### Added

- **`ledger.py`** — the append-only per-run findings collection. Every channel
  ingests into it (the digest's JSON findings, the critique reads, cross-sheet
  conflicts, the deterministic auditors, harvested prose); duplicates merge at
  ingest (Phase 11's rules), **unioning provenance** (`Finding.sources`, new),
  keeping the most severe severity and the longest quote, and preserving the best
  anchor/verification either member carries (an auditor's pre-anchored
  DETERMINISTIC duplicate upgrades a model entry). `freeze()` assigns the run's
  `QC-###` numbers. Anchoring, verification, the citation check, the markup
  writer, the exports, the report table, and the index page now consume the
  ledger and nothing else. Provenance renders as chips
  (`prose+json+critique×2`) in the report rows and markup popups, and as a
  `sources` CSV column.
- **`prose_harvest.py`** — the legacy channel's guarantee (§17). The digest's
  prose Coordination/Conflict sections are split into items (the same section
  grammar as the report's "⚠ Issues only" filter — the prose is mirrored, never
  modified, I-2) and fuzzy-matched against same-sheet ledger entries; each
  unmatched straggler gets one small structuring call (item + text layer → one
  finding with a verbatim quote); a failure ingests a **degraded sheet-level
  entry** — the invariant is that no prose QC item fails to produce a ledger
  entry. Synthesis conflict statements are harvested per referenced sheet,
  dual-anchored when two sheets are named (synthesis now runs *before* the QC
  stages so its text exists to harvest). Per-sheet Focus sections harvest only
  behind `focus_findings_to_markups` (default OFF). The digest prompt gained the
  coupling sentence (prose Coordination/Conflict items must also appear in the
  JSON block), bumping the digest prompt version.

#### Changed

- **Gating amendment (§18) — all findings get ink.** The exhaustive default inks
  everything except REJECTED: anchored entries cloud (UNCERTAIN/SKIPPED dashed),
  rect-less entries become margin callouts (`[SHEET]` / `[UNANCHORED]`
  prefixes — the unanchored hallucination signal is flagged on the page, never
  dropped). REJECTED findings carry no ink by default but are always listed on
  the index page under **"Rejected by verification (n)"** with page links; the
  new `ink_rejected=True` (GUI: **Include rejected (grey)**) draws them grey and
  dashed. The GUI's "Verified findings only" sub-toggle became **"Verified &
  deterministic only"**, defaulting **OFF** (`markup_verified_only` default
  flipped False); suppressed entries tally as *gated*.
- **Coverage assertion.** At run end every ledger entry must be exactly one of
  clouded / margin-callout / rejected-indexed (gated only under the opt-in
  conservative mode); the tally is logged
  (`Ledger 47: 39 clouded, 6 margin, 2 rejected (indexed)`) and surfaced on
  `ctx.ledger_tally` / `ledger_tally_line`, in the GUI completion summary, and
  on the report's findings card. An unaccounted entry is recorded as a run error
  and fails the hermetic end-to-end test.

### Markup richness, citation check & index pages (Phase 15)

The reviewed PDF now reads like a numbered, navigable, senior plan-review set.

#### Added

- **QC numbering.** Every finding gets a sequential review number (`QC-001` …,
  ordered sheet → position; `assign_qc_ids`, stable within a run). Inked findings
  carry the number as a small FreeText tag beside the markup in the severity
  color; the same id appears in `findings.csv` (new leading `qc_id` column),
  `findings.json`, the HTML report (new sortable ID column), and the index page.
- **Severity styling & annotation types.** high = red, medium = orange, low /
  question = blue. DETERMINISTIC findings draw a **solid** border, model findings
  a revision **cloud**, opted-in unverified findings **dashed** + `[UNVERIFIED]`.
  Sheet-level / absence findings (`anchor_hint="SHEET"`) are now inked as FreeText
  **callout boxes stacked in a computed clear margin band** (largest text-free
  horizontal band, found from the word rectangles — `find_clear_band`), with a
  **leader-line arrow** to the reported tile's centroid when known.
- **Findings index pages** at the front of each reviewed PDF ("AI DRAFT REVIEW -
  FINDINGS INDEX"): a table of ID / sheet / severity / status / one-line text
  where every row carries a GOTO link to the finding's page + rectangle
  (link targets account for the inserted pages). Multi-page as needed.
- **Citation check (`citation_check=True`).** One web-search-backed call per
  unique cited code ref (server-side `web_search_20260209` tool — verified
  current, env-overridable), judged against the editions the set adopts
  (harvested offline from the general-notes text) and the current edition.
  Verdict (`CHECKED_SUPPORTS` / `CHECKED_MISMATCH` / `UNCHECKED`) attaches to the
  citing findings and shows in the popup, CSV, and report; a MISMATCH downgrades
  nothing — sometimes the stale citation *is* the finding. Handles `pause_turn`
  resumption; real-time only; new `Citation` model.
- **Exhaustive popups**: finding text, verbatim quote, cross-sheet pointer (legs
  cite each other by QC number), verification status/note, refs + citation
  verdict, the reproduced flag when uncorroborated, evidence filename, both ids.
- **Optional appendix page** (`DRAWING_ANALYZER_MARKUP_APPENDIX=1`, off by
  default): "checked and consistent" — arithmetic relationships that checked out
  and references that resolved (the references auditor now counts its resolved
  pointers into `audit_stats`).

### Deterministic auditor expansion (Phase 14)

More high-precision, zero-API markups for free — the class of defect a vision
model is unreliable at but code is exact at.

#### Added

- **`auditors/` package.** The single reference auditor grew into a battery;
  `run_auditors(rendered_sheets, claims=…)` runs the whole set and returns the
  combined `DETERMINISTIC` findings plus a `stats` tally. Each auditor is isolated
  so one failing never loses the others (I-3), and the package imports no PDF
  engine (I-5). `reference_audit=True` (the GUI **Reference audit** checkbox) now
  runs the whole battery, and its checks-passed tally lands on `ctx.audit_stats`.
- **Arithmetic auditor.** The critique and cross-sheet QC passes now additionally
  emit a `claims` array — numeric relationships they *transcribed* off a sheet
  (`{sheet_id, quote, kind: sum|product|factor, terms, expected, note}`). The host
  does the arithmetic itself (exact `Decimal`, tolerant of commas / units /
  fractions like `2 1/2`), **never `eval`, never the model's math**, and flags only
  relationships that genuinely don't add up (a flow-test total, a DIPA row missing
  its +30%). Matches are counted and surfaced as *"N numeric relationships checked
  ✓"*. New `NumericClaim` model; `parse_numeric_claims()` lifts claims from the same
  fenced block the findings come from; the critique caches claims alongside findings.
- **Naming-consistency auditor.** Harvests the set's tag lexicon, clusters tags
  sharing an alphabet shape within a small edit distance, and flags a rare spelling
  that drifts from the established one (`C1R` vs `C1-R`; a one-off `A1-2` against an
  `A2` vocabulary) — without flagging a legitimately distinct vocabulary
  (`A1`/`A2`/`A3`). Low-severity questions, every flagged occurrence anchored.
- **Title-block auditor.** Learns each sheet's title-block x-band from its sheet-ID
  location and flags a field value (project number, date) that drifts to a close
  variant of the set-wide norm on one sheet. Conservative: fires only on a variant
  of a value most of the set agrees on, never on mere absence.
- **Sheet-index auditor.** Detects a drawing index and diffs it against the set
  inventory both ways — an entry listed but not present ("in the provided set"), or
  a set sheet the index omits.
- **`reference_audit.py` is now a backward-compatibility shim** re-exporting the
  auditor from its canonical home `drawing_analyzer.auditors.references`.

#### Changed

- The critique and cross-sheet QC findings instructions gained the `claims` array
  (the critique prompt version bumps, re-critiquing rather than serving a stale
  read). The reviewed-PDF gating, prose digest, and `combined_text` are untouched.

### Exhaustive QC — the critique pass

Part II of the QC work: make the markup read like an experienced engineer's
review, not the digest's incidental noticing.

#### Added

- **Critique pass (`critique=True`) — "the reviewer".** A second full-coverage
  vision read per sheet (the same overview + tiles + text layer the digest sees),
  under a senior-QA-engineer persona whose only job is to find problems: errors,
  code concerns (cited conservatively), RFI-worthy ambiguities, internal
  inconsistencies, stale/copy-paste text, and **absences** — content a complete
  sheet should show but doesn't (`anchor_hint: "SHEET"`, no quote). It emits only
  the findings block, so the prose digest and `combined_text` are untouched (I-2).
- **Self-consistency.** The critique runs twice; a finding both reads surface is
  corroborated (`reproduced`), a singleton is kept but flagged. The merge
  deduplicates by anchor-rect overlap (IoU) once anchored, else the reported tile,
  and by normalized-text overlap. Digest and critique findings then pool into one
  per-sheet set before anchoring — cross-source agreement also marks `reproduced`.
  The flag is a soft confidence signal; it never suppresses a finding.
- **`Finding` gains `anchor_hint` and `reproduced`** (both optional, backward-
  compatible — read tolerantly from cache, no cache invalidation) and the critique
  is cached under its own key (a distinct namespace from the digest).
- **Cross-sheet QC pass (`cross_qc=True`).** A deliberate whole-set conflict
  hunt — one text-only reasoning call over all the digests + text layers (no
  images; large sets shard by discipline) that finds conflicts *between* sheets:
  the same tag valued two ways, twin notes diverged, a note contradicted
  elsewhere, a cross-reference whose target disclaims the pointer's claim.
  Distinct from the prose synthesis (untouched); `combined_text` never sees it
  (I-2). Findings carry **dual anchors** — a primary plus `also_on` legs resolved
  to their own sheets via the set's title-block ids — so the markup writer clouds
  **both** sheets of a conflict, each popup cross-referencing the other. `Finding`
  gains a backward-compatible `also_on`; the anchor resolver, markup writer,
  verification pass, and pipeline gained additive dual-leg support (a finding with
  no legs is unchanged). Cross-sheet findings are verified with a **dual-crop**
  pass — one crop per sheet in a single call — so a conflict can reach `VERIFIED`
  and cloud under the default verified-only gating (a single-sheet crop could only
  ever say NOT_VISIBLE).
- **Review profiles (`profiles=[…]`).** The owner's QC knowledge as versioned,
  injectable Markdown checklists: each profile's items are appended to the
  critique prompt ("APPLY THIS REVIEW CHECKLIST EXPLICITLY, ITEM BY ITEM"), so the
  reviewer applies encoded checks deliberately, not incidentally. Profiles load
  from the package's built-in set and from `~/.drawing_analyzer/profiles/`
  (override `DRAWING_ANALYZER_PROFILES_DIR`; a user file wins over a built-in by
  reusing its `name`). The selected profiles' fingerprint (name + version +
  content hash) folds into the critique cache key, so editing a checklist
  re-critiques; a very long checklist is split across the self-consistency runs
  rather than truncated. A starter **fire-protection** (NFPA 13) profile ships,
  and `profiles.suggest_profiles(sheet_ids)` proposes profiles by discipline.

### QC findings, verification & markup integration

Turns the analyzer from a pure coverage instrument into one that also
*proposes, verifies, and marks up* discrete review findings — **coverage
proposes, precision disposes.** Everything below is additive and off by default;
a plain digest run is byte-for-byte what it was before, and the prose digest that
feeds the downstream spec reviewer is never touched.

#### Added

- **Vector text-layer grounding.** Each sheet's `page.get_text()` text layer is
  lifted losslessly and sent verbatim in the digest prompt, ahead of the images,
  as the source of truth for exact strings (tags, schedule values, note numbers,
  sheet references) — the antidote to the OCR-of-raster digit errors that vector
  text can't make.
- **Structured findings.** The digest model additionally emits a machine-readable
  `findings` JSON block (category / severity / text / verbatim `source_quote` /
  tile / refs), parsed out of the response by a tolerant parser without
  disturbing the prose. Findings are cached alongside the digest.
- **Reference audit** (`reference_audit=True`, or the GUI **Reference audit**
  checkbox) — a deterministic, zero-API pass over the text layers that learns the
  set's own sheet-ID grammar and flags stale / missing / malformed
  cross-references, each anchored to its exact word rectangle with a closest-in-set
  suggestion. It never claims a sheet "doesn't exist," only that it "isn't in the
  provided set."
- **Anchor resolver.** Maps each finding's `source_quote` back to a rectangle on
  its page (EXACT / FUZZY / TILE / UNANCHORED tiers), offline and PDF-engine-free;
  an unmatched non-empty quote is the hallucination signal and is never clouded by
  default.
- **Verification pass.** For each anchored model finding, renders a high-DPI crop
  and asks one small Opus call whether the finding holds *in that crop*, mapping
  to VERIFIED / REJECTED / UNCERTAIN; the crop is written to
  `evidence/<finding_id>.png` regardless of verdict. Additive and non-fatal.
- **Reviewed PDFs + findings CSV** (`qc_markups=True`, or the GUI **QC Markups**
  checkbox) — a `<stem>_reviewed.pdf` per source PDF with real revision-cloud
  annotations (severity-colored, authored *"Drawing Analyzer (AI review)"*,
  populating Bluebeam Revu's Markups List), plus a Windows-Excel-friendly
  `findings.csv` (UTF-8 BOM, CRLF). VERIFIED + DETERMINISTIC findings are clouded
  by default; the original source PDF is never modified.
- **Folder-export QC inventory** — `findings.json`, `findings.csv`,
  `sheet_text/<sheet>.txt` per sheet, and `evidence/<finding_id>.png` crops
  written alongside the existing report / Markdown, plus the reviewed PDFs.
- **HTML report findings.** A pinned, sortable **QC Findings** card with
  color-coded status chips (Verified / Deterministic / Uncertain / Unanchored /
  Rejected); a per-sheet raw text-layer block that now feeds the report's
  full-text search; and a **Raster** badge on empty-text-layer sheets.
- **Performance.** A two-level digest cache that recognizes an unchanged sheet
  *before* rendering — skipping ~4.5 s/sheet of rasterization on a cached re-run —
  and a bounded parallel Files-API upload pool
  (`DRAWING_ANALYZER_UPLOAD_WORKERS`, default 6).
- **Hermetic acceptance suite** (`tests/test_drawing_acceptance.py`) encoding the
  end-to-end acceptance script: a fresh both-checkbox run, the reviewed-PDF
  appearance-stream guarantee, the stale-reference closest-match suggestion, a
  zero-digest-API cached re-run with identical outputs, and the raster fallback.

#### Changed

- **Render target 1992 px → 1560 px** per tile for ordinary vector sheets, now
  that the text layer carries the exact strings — cutting PNG bytes and image
  tokens ~40%. A sheet with an *empty* text layer (scanned / pasted raster) still
  renders at 1992 px, where the pixels are the only information channel.
- **Strict blank-tile suppression.** Only provably pixel-uniform tiles are
  dropped, and the omission is disclosed to the model. An opt-in near-blank
  heuristic (`DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK`) defaults off.
- **Digest cache schema and prompt versions bumped.** The render-target change,
  the text-layer block, the findings block, and the two-level key each invalidate
  prior cache entries once; the first run after upgrading re-digests every sheet,
  then caches as before.
- **API facts re-verified** against the current Anthropic docs
  (`platform.claude.com`, 2026-07). The vision per-image caps (Opus 4.8 = 4784
  tokens / 2576 px), the >20-image 2000 px hard-reject rule, the 32 MB request-size
  limit, and the ~50% Message Batches discount all still hold, so **no `tiling.py`
  constant changed**; only the docstring's section citation ("General limits" →
  "Request limits") and the token estimator's hi-res-roster note were refreshed.
  (The high-resolution vision tier has since grown beyond Opus; the estimator
  intentionally keys the hi-res tier off the Opus whitelist, which is exact for
  this Opus-only tool and a safe under-estimate for anything else.)

#### Security

- **The API key is no longer embedded in the HTML report by default.** The
  in-report Ask-AI assistant prompts for a key on first use and keeps it only in
  the browser tab's `sessionStorage`, so the report file is safe to share. The old
  behavior is opt-in (`embed_api_key=True`, or a GUI checkbox) and stamps the
  report with a red *"don't share this file"* warning.

#### Isolation

- PyMuPDF (AGPL-3.0) imports remain confined to named modules: `render.py`
  (rasterizing sheets and crops) and now `annotate.py` (writing cloud annotations
  onto reviewed PDFs). No other module imports the PDF backend, so it can be
  swapped for a permissively-licensed one by rewriting just those two files.
