# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 18C — mid-run source mutation detection, DA-001 §10.6)

- **A source PDF that changes on disk between analysis and markup can no longer
  get stale ink.** Every input is snapshotted (`content_sha256`) at inventory
  time; immediately before the markup writer reopens a file, the pipeline
  re-verifies each source against its snapshot (a `stat` fast-gate, then a full
  re-hash on any drift). A source whose bytes changed is **excluded from
  markup** — its findings, and any cross-sheet leg landing on it, are not inked
  (anchors computed from the earlier revision would land on the wrong content) —
  recorded on `ctx.errors` with a "re-run to mark up the current revision"
  message, and surfaced on the new `DrawingContext.mutated_sources`. Only the
  *findings* are filtered — the full accepted path list is preserved so the
  markup writer's `SRC-####` assignment does not renumber (dropping a middle
  path would misplace the survivors' ink); a mutated source ends up with no
  findings and is simply not written. The coverage tally accounts those skipped
  entries under a distinct `mutated` disposition ("N skipped (source changed)")
  rather than reporting ink no reviewed PDF contains. The good files still get
  their reviewed PDFs, and the standard artifacts already produced are retained.
  The check is pure (no PyMuPDF), so it stays outside the I-5 boundary.

### Added (Phase 18B — resilient input inventory, DA-002 / DA-035)

- **A corrupt, encrypted, or duplicate input no longer aborts an otherwise
  valid drawing set — or vanishes silently.** A new inventory step
  (`render.inspect_inputs`) classifies every selected path once as `ACCEPTED` /
  `DUPLICATE` / `UNREADABLE` (missing, permission-denied, corrupt, not a PDF) /
  `ENCRYPTED` (password-required) / `EMPTY` (zero pages), each with a sanitized,
  path-free reason. The pipeline processes only accepted documents and records
  every rejection on `ctx.errors`, so a mixed good/bad run ships a partial
  standard deliverable that names what it dropped. `source_id` is assigned over
  the **accepted** inputs in order, so a rejected file never consumes an id.
- **`SourceDocument` inventory records** (`source_registry`) carry the revision
  identity — a stat-guarded `content_sha256` (re-reads if the file changes
  mid-hash rather than register a mixed-revision hash), `byte_size`,
  `initial_mtime_ns`, and `page_count` — the foundation Phase 18C's mid-run
  mutation detection builds on.
- **Page-level resilience (§10.5):** if a single page fails to load or render,
  the remaining pages of that PDF — and every other file — still process; the
  failed page is recorded on `ctx.errors` and excluded, never a whole-run abort.
- **Preflight bounds (§10.7):** each page is dimension-checked *before*
  rasterization, so a pathological/NaN/oversized box fails visibly instead of
  allocating a ruinous pixmap; a large *legitimate* set above a configurable
  threshold (`DRAWING_ANALYZER_MAX_SHEETS` / `_MAX_FILES`) requires explicit
  confirmation (`extract_drawing_context(..., confirm_large_set=True)`) rather
  than being silently truncated; and a work/export-disk capacity check runs
  before a QC run begins (`qc_work_dir` set), blocking early rather than failing
  after paid API work. Inventory error reasons are scrubbed of any absolute-path
  token, and the `DRAWING_ANALYZER_MAX_*` overrides parse defensively (a config
  typo degrades to the default instead of crashing at import). PyMuPDF stays
  confined to `render.py` (I-5) — the inventory data model, hashing, and bounds
  are PyMuPDF-free in `source_registry`.

### Fixed (Phase 18A — host-owned source identity, DA-001)

- **A finding can no longer be attributed to the wrong source PDF when two
  inputs share a basename.** Previously every internal `(source, page)` lookup
  keyed on the file *basename*, so two `M-101.pdf` files from different folders
  collided: a finding from one could be anchored, verified, or **clouded onto
  the other**, and the reviewed copies received the union of both files'
  findings. Each accepted input now gets an opaque, host-generated `source_id`
  (`SRC-0001` …, assigned in input order by the new `source_registry`), which the
  model never sees and which does not depend on the filename.
- **`source_id` threaded end to end.** Added to `SheetRef`, `Finding`,
  `ConflictLeg`, and `NumericClaim` (additive, defaults to `""`), stamped at
  every production site (digest, critique, cross-QC, prose harvest, and all five
  deterministic auditors) and carried through serialization. A new
  `source_page_key()` helper replaces every collision-prone
  `(source_name, page_index)` key across the pipeline, ledger, anchor, verify,
  cross-QC, prose-harvest, auditor, and report lookups. `source_name` remains
  display-only.
- **`verify.py` no longer skips same-basename sheets.** Its ambiguity guard —
  which used to mark a duplicate-basename finding `SKIPPED` rather than crop the
  wrong drawing — is now a fallback that only fires when no `source_id` was
  assigned; real runs verify every sheet against its own source.
- **Reviewed-PDF names are source-disambiguated, not order-dependent.** When two
  inputs share a stem, the reviewed copies are named
  `<stem>__SRC-0002_reviewed.pdf` (deterministic, source-identifying) instead of
  a bare `_2`; unique stems keep their friendly `<stem>_reviewed.pdf` name.
- **Content ids fold in source identity.** `compute_finding_id` now includes
  `source_id`, so two different inputs sharing a sheet id, category, and quote
  can never collide in the evidence directory or the ledger. When no `source_id`
  is present the historical (source-independent) id is preserved exactly.
- **Cache hits are rebound to the current source (§10.3).** A content-keyed
  digest/critique cache entry can carry a former run's identity; on a hit,
  restored findings/claims are re-stamped with the current `SheetRef`, a
  source-derived fallback `sheet_id` is rebuilt (a real model id like `M-101` is
  preserved), and the content id is recomputed. Digest cache
  `_SCHEMA_VERSION` 3 → 4, so pre-existing entries miss once and re-digest.
- **`NumericClaim` carries `source_id` through its whole path.** Fresh critique
  claims are stamped at production, the arithmetic auditor's geometry resolution
  and claim-dedup key are `source_page_key`-based (so a duplicate-basename claim
  resolves to — and is never merged across — the right source), and the
  critique-cache rebind rebuilds a source-derived fallback claim `sheet_id`.
- **CSV/JSON exports gain a `source_id` column/field**; no absolute path leaks
  into any public artifact. New tests cover same-basename isolation through
  anchor / verify / annotate / ledger / export / report, the registry's
  dedup/ordering (identical canonical path, relative-vs-absolute), the cache
  rebind, and the source-aware id. This is Phase 18A of the split; input
  resilience (18B) and mid-run mutation detection (18C) follow.

### Security / CI (Phase 17B — headless-browser exploit tests + CI foundation)

- **Real headless-Chromium exploit suite for the report (DA-011/DA-027),**
  `tests/test_report_browser_security.py` (marker `browser`). It builds the
  actual report, loads it over `file://`, and proves the trust boundary end to
  end where a DOM emulator can't: an execution sentinel must stay unset while a
  malicious answer streams through the assistant's **incremental and final**
  render paths, while a hostile corpus (filenames, sheet IDs, quotes,
  categories, findings, focus, errors, evidence paths) sits in the report body,
  and after real hover/focus/click/image-error events. It also asserts the
  https-only URL policy on streamed markdown links and citations, that the
  no-key report prompts on first use and **Forget key** clears sessionStorage,
  and that the CSP actually blocks an injected inline `<script>`. Hermetic: the
  Anthropic `fetch` is stubbed with a canned stream — no network, no key — and
  the suite skips cleanly when Playwright/its browser is absent.
- **Fixed a streamed-answer render race in the assistant:** a trailing debounced
  markdown re-render could fire after the final block render and wipe the
  citation chips it had just appended. `finishBlock` now cancels any pending
  debounced render so the final render (with citations) is authoritative. The
  browser citation test surfaced this.
- **PyMuPDF import-isolation test (I-5),** `tests/test_import_isolation.py`: a
  static AST scan asserting only `render.py` and `annotate.py` import PyMuPDF,
  so the AGPL-confinement invariant fails loudly the moment a stray import
  appears.
- **Continuous integration,** `.github/workflows/ci.yml`: the hermetic suite on
  Windows + Ubuntu across Python 3.11/3.12 (byte-compile → import-isolation →
  full suite) plus the headless-Chromium security suite on Linux. Actions are
  pinned to immutable commit SHAs, permissions are read-only, and it triggers on
  `pull_request` (never `pull_request_target`). New `browsertest` extra pins
  Playwright for reproducible browser CI. (Marking the checks *required* is a
  one-time branch-protection step for an owner/admin.)

### Security (Phase 17A — report trust boundary, key store, log redaction)

- **The HTML report can no longer execute model-controlled HTML (DA-011).** The
  in-report Ask-AI assistant previously rendered streamed Markdown by assigning
  model output to `innerHTML` — drawing text feeds the prompts, so that output
  is attacker-influenceable. The renderer is rebuilt as a **safe DOM builder**
  (`createElement` + `textContent` only; no `innerHTML`/`outerHTML`/
  `insertAdjacentHTML`/`document.write` with model data anywhere in the report
  scripts). Every link — Markdown links **and** streamed citations — passes
  through a single URL validator that accepts only absolute `https:` URLs and
  rejects `javascript:`/`data:`/`file:`/`blob:`, protocol-relative, credential-
  bearing, and control-character URLs; a rejected URL degrades to inert text.
- **The whole report is now a hardened trust boundary, not just the chat.**
  Every untrusted value (source filenames, sheet IDs, titles, findings, quotes,
  errors, focus text, configuration) is escaped into element content or
  attributes on the Python side. The chat config is emitted as an inert
  `type="application/json"` island serialized so every `<` (and U+2028/U+2029)
  becomes a JSON string escape — no value can close the script element or form
  markup, and `JSON.parse` still round-trips it exactly.
- **Defense in depth: a hash-pinned Content-Security-Policy.** Reports carry a
  CSP `<meta>` that allows only the exact inline scripts by SHA-256 hash (no
  `'unsafe-inline'` for scripts; there are no inline event handlers), restricts
  `connect-src` to the Anthropic API (or `'none'` when the assistant is
  omitted), and forbids objects, `<base>` rewriting, and form submission.
- **Ask AI is present by default and prompts for a key on first use (DA-026).**
  A report built with no key previously omitted the assistant entirely; it now
  ships the assistant and asks the reader for a key at first use (kept only in
  the browser tab's `sessionStorage`), with a **Forget key** control that
  clears memory + `sessionStorage`. Embedded-key mode states truthfully that a
  runtime "forget" cannot remove the key from the file. New `include_chat`
  parameter (`build_html_report` / export builders) opts the assistant out.
- **Credential-safe API-key persistence (DA-032).** `save_api_key` now stores
  the key only in an OS credential store (Windows Credential Manager / macOS
  Keychain / Secret Service via `keyring`), trusted **only** after a verified
  round-trip. With no secure backend it raises `SecureKeyStorageUnavailable`
  instead of silently writing a plaintext file; the GUI turns that into an
  explicit consent prompt (declining keeps the key session-only). Legacy
  plaintext key files are migrated into the keyring on load/save and removed.
  `keyring` added to the `gui` extra.
- **Shared secret-redaction filter for diagnostics logs.** A
  `RedactingFormatter` masks `sk-ant-…` key material, `Authorization`/`Bearer`
  values, and named secret fields (`x-api-key`, `api_key`, `token`, `secret`,
  `password`, …) in every line the diagnostics file handler writes — including
  the optional SDK wire capture and formatted tracebacks — before serialization.
  Token *counts* (`input_tokens=…`) are preserved. This is the shared boundary
  the Phase 26 run journal will reuse.
- Added **SECURITY.md** documenting the report trust boundary, URL policy, CSP,
  API-key handling, log redaction, and the project data each artifact contains.

*Note:* the mandatory headless-Chromium exploit test and the Windows/Linux CI
matrix are Phase 17B (pre-authorized split); this change lands the safe
renderer, redaction, key-store hardening, and their hermetic tests.

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
