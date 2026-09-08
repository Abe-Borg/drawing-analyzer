# External Review Brief — Drawing Analyzer

**To:** an independent reviewing model with strong reasoning ability
**From:** Claude Code, after a structured read of the repository at commit `89c8ecb` (v1.3.0rc1)
**Date of this brief:** 2026-09-08
**Repository:** `Abe-Borg/drawing-analyzer`

---

## 0. How to use this document

This is a briefing, not a specification. It exists so you do not have to spend
your first hours rediscovering the shape of a 46,000-line codebase. Everything
below is my reading — including the numbers, which I computed from the repo's
own functions but which you should re-derive rather than trust.

**You are explicitly not being asked to change anything.** "This is well-built
and the right call was already made" is a complete and acceptable answer, for
the whole system or for any individual item. Several of the things I flag below
may turn out to be deliberate, already-considered trade-offs — this codebase has
a strong habit of documenting *why* something was rejected, and I may have
missed the note. What is being asked for is your independent judgment, and a
plan only where a change is genuinely warranted.

Treat my "suspicions" in §7 and my cost hypotheses in §8 as leads to verify or
kill, not as a work list. Some of them are probably wrong. Say so where they
are, and say why — a well-argued rebuttal is more valuable to the owner than a
change made on my say-so.

---

## 1. What this software is, and who uses it

Drawing Analyzer reads construction-drawing PDF sets with a vision model and
produces (a) a structured text digest of every sheet, (b) a QC findings ledger,
and (c) a marked-up "reviewed" PDF with clouds, tags and callouts placed on the
actual drawings, plus a self-contained HTML report.

**The owner is a mechanical and fire-sprinkler designer working on nonresidential
projects — currently hyperscale data centers across the USA.** That context
matters for several judgments you will have to make:

- Sheets are large. E-size (34×44") and 30×42" are the common formats;
  D-size (24×36") and 11×17" detail sheets appear in the same sets.
- The findings have professional consequences. A missed conflict between a
  sprinkler layout and a structural member, or a stale code-edition citation,
  is a real-world cost. **A false negative is worse than a dollar.**
- Code correctness matters: NFPA 13 and its adopted edition per jurisdiction is
  a first-class concern in the pipeline (there is an entire edition-audit and
  citation-check stage). If you touch anything that reasons about code editions,
  it must remain edition-aware and never assume an edition.
- The user runs Windows. Any tooling proposal must work there.

The economics: a full exhaustive run on a 39-sheet set costs roughly **$30–60**
depending on transport. That is cheap against the cost of the review it partly
replaces, but it is expensive enough that the owner cares, and it is the reason
a cost section is in this brief at all.

---

## 2. Repository facts

| | |
|---|---|
| Language / runtime | Python 3.11+, `src/` layout, package `drawing_analyzer` |
| Source | 54 files, 46,117 lines |
| Tests | 71 files, 35,318 lines, hermetic by default |
| Scripts | `run_acceptance.py`, `benchmark_drawing_analyzer.py`, `ab_sweep_drawing_analyzer.py`, `scan_secrets.py`, `check_licenses.py` |
| License | AGPL-3.0-or-later (forced by PyMuPDF) |
| GUI | CustomTkinter, `gui.py`, ships as a Windows installer |
| CI | tests on ubuntu/windows × py3.11/3.12; headless-Chromium report-security suite; secret scan; ruff **correctness classes only** (E9/F63/F7/F82); license audit; pip-audit; wheel build + clean-install smoke |

**Test state as I found it:** `1590 passed, 10 skipped, 3 failed` in ~104 s.
The 3 failures are all in `tests/test_spec_documents.py` and are caused by a
broken `cryptography` install in *this sandbox* (`ModuleNotFoundError:
_cffi_backend` surfacing as a `pyo3_runtime.PanicException`), not by the code.
See §7.1 — the failure mode is nonetheless interesting.

Commands:

```bash
pip install -e ".[dev]"          # engine + pytest   (GUI: ".[gui,dev]")
python -m pytest                 # hermetic: no API key, no network
drawing-analyzer                 # launch the GUI
python scripts/run_acceptance.py # release gates
```

---

## 3. Architecture — the shape you need in your head

### 3.1 The core pipeline

One PDF page = one *sheet*. `pipeline.extract_drawing_context()` orchestrates
everything and returns a `DrawingContext`.

```
PDFs
 └─ source_registry.py   host-owned source identity (SRC-####), input inventory
 └─ render.py            PyMuPDF rasterization  ── ONE OF ONLY TWO PyMuPDF IMPORTERS
     ├─ tiling.py        pure geometry: 6×6 clip rects + render zoom (no PDF engine)
     └─ per sheet →  overview image + 36 tiles + VERBATIM VECTOR TEXT LAYER
 └─ digest.py            one vision request per sheet → Markdown prose + JSON findings block
     └─ batch_digest.py  same request via Message Batches + Files API (~50% cheaper)
     └─ digest_cache.py  two-level content-keyed cache (level-1 skips rendering entirely)
 └─ QC stack (all optional, all independently cached)
 └─ ledger.py            THE findings container — everything ingests here
 └─ anchor.py            quote → PDF rect (EXACT / FUZZY / TILE / UNANCHORED)
 └─ verify.py            per-finding high-DPI crop re-check
 └─ investigate.py       agentic tool loop for UNCERTAIN verdicts
 └─ citation_check.py    web-search/fetch check of cited code sections
 └─ annotate.py          reviewed-PDF writer  ── PyMuPDF IMPORTER 2 OF 2
 └─ export.py / html_report.py
```

### 3.2 The three run modes

Resolved once, in `models.resolve_run_configuration()`, into an immutable
`RunConfiguration`. Nothing downstream re-derives the booleans.

| Mode | Trigger | What runs | Cost |
|---|---|---|---|
| **Standard** | default | digest only; findings retained and anchored offline | ~$0.26–0.51/sheet |
| **Free audit** | `reference_audit=True` alone | + five deterministic zero-API auditors | **$0 extra** |
| **Exhaustive** | `qc_markups=True` | + identity, review plan, critique ×2, cross-sheet QC, prose harvest, verification, investigation, citation, markup, coverage reconciliation | ~$2–3.5/sheet |

The GUI defaults to **standard + Economy transport** (`qc_markups=False`,
batch on).

### 3.3 The QC stack in detail

- **Planning (Phase A).** `set_identity.py` — one text-only call producing a
  bounded `SetIdentity` (disciplines, jurisdiction, units, adopted codes with
  evidence quotes), with a *regex edition harvest* unioned in as a backstop the
  model cannot argue away. Advisory only; consumers take `SetIdentity | None`
  and never gate a finding on it — which is why it runs on Sonnet 5.
  `review_planner.py` — one text-only call authoring a per-discipline review
  checklist (≤60 items, code items must name code+section+edition inline).
  Plans become caller-built `Profile` objects injected after user profiles.
- **Finders.** The digest's own findings block; `critique.py` (a second full
  vision read, run **twice** for self-consistency); `cross_qc.py` (text-only
  cross-sheet conflict hunt with dual `also_on` anchors); `auditors/` (five
  deterministic zero-API auditors over the text layers, all grounded on a shared
  learned sheet-numbering grammar in `auditors/sheet_ids.py`);
  `prose_harvest.py` (mirrors prose Coordination/Conflict items into findings).
- **Ledger.** `ledger.py` is the exclusive container. Dedup is conservative and
  lossless: geometric overlap is *never* sufficient; merges need semantic
  sameness with compatible critical signatures (tags, measurements, absence
  polarity, cross-sheet legs). Lifecycle: `seal()` → anchor →
  `reconcile_post_anchor` → `number()` (positional `QC-###` assigned **after**
  anchoring, so numbers follow visual order).
- **Edition audit (Phase B).** `citation_check.reconcile_cited_editions` — a
  zero-API, strictly pre-seal check turning an adopted-vs-cited edition
  divergence into a first-class finding. Two-tier trust: both operands re-found
  in sheet text → medium + `DETERMINISTIC`; else low + advisory.
- **Disposition.** anchor → verify → investigate → citation → annotate → export.

### 3.4 The binding invariants

These are cited by number throughout the code. **Do not propose anything that
breaks one without saying explicitly that you are doing so and why.**

- **I-1 full coverage** — every sheet is read whole; optimizations may never
  drop content-bearing tiles.
- **I-2 the prose digest is sacred** — nothing may alter `combined_text`.
- **I-3 QC is additive and non-fatal** — every stage catches its own exceptions
  and lets the standard deliverable ship.
- **I-4 hermetic tests** — no network, no key, ever.
- **I-5 PyMuPDF isolation** — only `render.py` and `annotate.py` may import it;
  the AGPL story depends on this.
- **I-6 cache correctness** — prompt versions are content hashes;
  `digest_cache._SCHEMA_VERSION` (currently 8) is manual.
- **I-7 deterministic assembly** — same inputs → same ordering. One documented
  carve-out (the citation cache's TTL clock, admission only).
- **The model never calculates** — models transcribe `NumericClaim`s;
  `auditors/arithmetic.py` does the math with `Decimal`. Operands are trusted
  (`DETERMINISTIC`) only when the quote independently carries every one.
- **Tiles use the `tile_label` contract** — the model returns the visible 1-based
  `"r1c1"`; `tiling.parse_tile_label` converts to zero-based internal.
- **Thinking is always explicit** — on Opus 5 / Sonnet 5 an *omitted* `thinking`
  key runs adaptive thinking; it does not disable it. Three stages once starved
  their own output by relying on omission meaning "off".
- **Above ~21k `max_tokens`, streaming is mandatory** — the SDK refuses a
  non-streaming `create` client-side. `digest.stream_message` is the one place
  that knows this.
- **Every real-time Opus 5 call opts into the server-side refusal fallback** —
  `core.api_config.call_with_refusal_fallback`, self-healing via a
  process-level latch if the platform rejects the beta.
- **Ledger coverage is artifact-backed (DA-007)** — the markup writer stamps
  each drawn mark with a private per-run key, reopens the saved PDF, and
  reconciles. Coverage is derived from receipts, never from intention.

### 3.5 Cross-cutting machinery worth knowing about

- **`RunUsage` (§15.6)** — an *append-only* priced ledger. Every API call or
  attempt appends a `UsageRecord` (family, transport REAL_TIME/BATCH/CACHE,
  model, tokens, tool uses, cache-hit, `estimated_cost`). Totals are *derived*
  sums; no stage can overwrite another's counters.
- **`RunJournal` (§18.1–18.4)** — append-only event trace, every field sanitized
  at emit time (secret redaction + absolute-path scrubbing). Every export gets
  `run.log` and `run_manifest.json` with sha256 of every artifact, written last
  in a documented non-circular order.
- **`render_spool.py`** — ephemeral exact-byte handoff of rendered sheets from
  the digest stage to the critique stage, so the critique does not re-rasterize.
- **`core/api_config.py`** — the model-capability registry (`_MODEL_CAPABILITIES`),
  per-phase output caps, effort policy, thinking policy, tool builders. Unknown
  model ids fall through to conservative defaults *and* log one WARNING.
- **`core/pricing.py`** — the rate table, `PRICING_EFFECTIVE_DATE`, cache
  read/write multipliers (including the 5m vs 1h write-rate distinction).

---

## 4. Where the money goes

I computed these using the repo's own `tiling` and `core.tokenizer` functions,
for a 34×44" E-size sheet at the shipping defaults (6×6 grid, 8% overlap,
1560 px vector target, Opus 5 hi-res vision tier). **Re-derive them.**

**Per sheet, per full-coverage vision read:**

| Sheet | Grid | Image tokens | Effective tile DPI |
|---|---|---|---|
| E 34×44 | 6×6 | **92,871** | ~183–197 |
| 30×42 | 6×6 | 85,854 | ~206 |
| D 24×36 | 6×6 | 80,148 | ~241 |
| C 18×24 | 6×6 | 90,162 | ~361 |
| B 11×17 | 6×6 | 77,767 | ~510 |
| A 8.5×11 | 6×6 | 92,871 | ~788 |

**Per-sheet digest cost (92.6k image tokens in, ~2k out):**

| | Real-time | Batch |
|---|---|---|
| Opus 5 ($5/$25) | $0.513 | $0.257 |
| Sonnet 5 ($2/$10) | $0.205 | $0.103 |

**An exhaustive run is three full-coverage reads per sheet** (digest + critique
read 1 + critique read 2), plus text-only stages, plus one small crop-verify
call per finding, plus investigation and citation. A 39-sheet exhaustive run:
~$60 real-time / ~$30 batch on the vision stages alone, before verification.

**The image tokens are ~97% of a digest request.** Everything else — the system
prompt, the verbatim text layer (15k chars ≈ 4k tokens), the instruction — is
noise by comparison. **Any serious cost work is work on pixels.**

---

## 5. What is already good (so you don't "fix" it)

I want to be explicit about this, because the density of the code invites
rewriting things that are correct.

- The invariant discipline is real and enforced by tests, not just documented.
- The usage ledger being append-only with derived totals is the right shape and
  fixed a real class of bug (a stage overwriting another's counters).
- Coverage being *artifact-backed* — reopening the saved PDF and reconciling
  stamped marks rather than trusting the writer's intention — is unusually
  rigorous and should not be traded away for speed.
- The two-level digest cache (a pre-render key that skips rasterization
  entirely) is a genuine win and its identity is conservatively constructed
  (false misses possible, false hits not).
- Blank-tile suppression uses `Pixmap.color_topusage` rather than
  `is_unicolor` for a documented performance reason. The near-blank heuristic
  is off by default — data over savings. That is the right default.
- The rotation/CropBox coordinate-space work (`PAGE_VIEW_V2`) is subtle and
  correct-looking, and the PyMuPDF gotchas file is hard-won knowledge.
- `scripts/ab_sweep_drawing_analyzer.py` already establishes a *decision
  procedure* for cost levers using three oracle-free signals (anchor tier mix,
  verification verdict mix, self-consistency rate) and explicitly warns that a
  clean screen is not an approval. Use this harness. Do not invent a new one.
- The refusal-fallback and task-budget self-healing latches are good defensive
  engineering.

---

## 6. Exhaustive review checklist

Work through this. Skip nothing without saying you skipped it. For each area,
the question is *"is this correct, and is it the right design?"* — not *"can I
make it different?"*

### 6.1 Correctness of the vision path
1. `tiling.py` — is the "render under the 2000 px hard cap, not to it" reasoning
   still sound? Is the 8 px margin adequate for the pinned PyMuPDF's
   `fz_round_rect` behavior on every rotation/CropBox case?
2. Does `tile_rects` genuinely cover the page with no gap at every aspect ratio
   and every overlap value, including `overlap_frac=0`?
3. `parse_tile_label` — can any model output produce a mis-anchored tile? Is the
   legacy zero-based `tile` array path safely bounds-checked?
4. `render.py` `_words_to_view` / `page.rotation_matrix` — verify the canonical
   `PAGE_VIEW_V2` space is applied consistently across render, anchor, verify,
   and annotate. This is the single most subtle thing in the codebase.
5. Blank-tile suppression: can a tile with faint but real content be
   pixel-uniform after rasterization at 1560 px? (Consider thin light-gray
   linework, or a tile containing only a hairline.)
6. Does the omitted-tile disclosure to the model correctly use 1-based labels
   matching the per-tile labels? (It appears to; confirm.)
7. Sheet text truncation at `SHEET_TEXT_MAX_CHARS = 15_000` — what happens to a
   finding whose `source_quote` lives in the truncated tail? Does it become
   UNANCHORED, and is that visible to the operator?

### 6.2 Request shape and model policy
8. `_MODEL_CAPABILITIES` — verify every flag against current Anthropic
   documentation: output ceilings, effort rosters, hi-res vision tier,
   `supports_web_fetch`. The code asserts Opus 5 lacks web fetch; confirm.
9. `core/pricing.py` — verify every rate and both cache-write multipliers
   against published pricing, and whether `PRICING_EFFECTIVE_DATE` needs moving.
10. Is `thinking: {"type": "adaptive"}` plus an explicit `effort` the right shape
    for every stage, and are the per-stage effort levels defensible?
11. `phase_output_cap` — is any stage's cap starving its own output now that
    thinking shares the envelope? (This bug has happened here before.)
12. `assert_extended_output_allowed` and `model_supports_extended_output_beta` —
    the latter is self-documented as having no production caller. Dead or
    load-bearing?
13. `call_with_refusal_fallback` — is the 400-detection heuristic
    (`_refusal_fallback_available`) tight enough to not disable itself on an
    unrelated 400?
14. Streaming: is *every* path above ~21k `max_tokens` routed through
    `stream_message`, including all batch→real-time fallbacks?

### 6.3 Caching correctness (I-6)
15. Does every input that can change a model's answer ride the relevant cache
    key? Walk each of the seven key builders in `digest_cache.py`.
16. The level-1 page-dependency hash — can it produce a *false hit* under any
    PDF structure (shared resource dictionaries, inherited page attributes,
    incremental updates, object streams)? False misses are fine; false hits are
    not.
17. Citation verdict cache TTL — is the I-7 carve-out argument airtight? Is a
    warm run's assembled output truly byte-identical?
18. Investigation cache replay — the code claims a warm hit *deterministically
    replays the tool trace with sha-compare* so evidence bytes are recreated.
    Verify that claim holds when a crop render is non-deterministic across
    PyMuPDF versions.
19. `_SCHEMA_VERSION = 8` — does anything currently stored need a bump that was
    missed?
20. SQLite cache: concurrency, `busy_timeout`, atomic replace, and the
    legacy-JSON migration path.

### 6.4 The ledger, dedup and lifecycle
21. `_is_duplicate` / `_signatures_compatible` — construct adversarial pairs.
    Can two genuinely different findings merge? Can two identical findings fail
    to merge and double-count?
22. `_representative` — is the "total quality order" actually total (no ties
    resolved by dict/iteration order, per I-7)?
23. Post-seal adds: is every channel guaranteed to ingest before `seal()`?
24. `number()` after anchoring — is positional order deterministic for
    rect-less and cross-sheet entries?
25. Cross-sheet `also_on` legs through merge, anchor, verify, and markup.

### 6.5 Anchoring and verification
26. `anchor.py` EXACT/FUZZY/TILE tiers — is the fuzzy threshold tuned such that
    a hallucinated quote can pass as FUZZY? UNANCHORED is the hallucination
    signal; anything that weakens it is a quality regression.
27. `verify.py` — the crop `context_rect` growth policy; can a finding be
    REJECTED because the evidence sat just outside the crop?
28. Is `NOT_VISIBLE → UNCERTAIN` (never REJECTED) honored on every path,
    including the dual-crop cross-sheet path?
29. `investigate.py` — the client-tool loop. Every `tool_use` id answered in one
    user turn; assistant turn committed before tools answered; forced no-tools
    close at the cap. Verify no path can dangle. Verify a capped outcome stays
    UNCERTAIN.
30. Investigation budget scaling (`10 + sheets/4`, ceiling 40) — is severity-first
    selection stable and deterministic?

### 6.6 Batch transport
31. `batch_digest.py` — the tiered stall watch (25 min primary / 60 min
    resubmission), bounded resubmit rounds, collection budget. Can a run hang
    past `DEFAULT_BATCH_MAX_ELAPSED_SECONDS = 4h`?
32. Are uploaded Files-API objects released on *every* exit path, including
    unexpected exceptions and process death?
33. `_mark_batch_abandoned` non-billable attempts — do they correctly stay out of
    the image-token estimate while remaining visible in §15.6?
34. The `RECOVERY_BATCH` vs `RECOVERY_DIRECT` split — is the pipeline genuinely
    never able to fall to full-rate real-time silently?
35. Request-body size: 32 MB Messages-API limit vs 37 base64 PNGs on the
    real-time path. Is the inline path safe on a dense raster sheet at 1992 px?

### 6.7 Markup writer and coverage
36. `annotate.py` — every PyMuPDF gotcha in `CLAUDE.md` is a scar. Verify each is
    still honored (FreeText `/Contents`, `annot.update()`, annot unbinding,
    base-14 glyph gaps, `derotation_matrix`).
37. Margin-callout band packing (§17.6) — can a callout still obscure drawing
    content on a pathological sheet? Is the overflow-to-appended-page path
    correct at every rotation?
38. Optional-content layers per severity — created only for tiers with ink, in
    fixed order, `/OC` independent of the DA-007 stamp. Verify reconciliation is
    truly untouched.
39. DA-029: are prior-run annotations reliably ignored?
40. Is `coverage_status = INCOMPLETE` reachable in a way that renames the PDF but
    leaves the operator without a clear reason?

### 6.8 The HTML report (5,851 lines — the largest file)
41. CSP: hash-sourced inline scripts, the JSON config island, `file://` behavior.
    The browser test suite exists — read it and decide whether it covers the
    real surface.
42. The embedded-API-key mode. Reader-supplied key outranks embedded. Is the
    redaction of `sk-ant-…` from saved chat history complete?
43. `_STATUS_RANK` must stay integer-valued (browser sorts via `parseInt`).
44. `data-repeat-key` collapsing — display-only; confirm exports, ledger,
    markups and the badge total keep every finding.
45. Is a 5,851-line generator with inline JS/CSS maintainable, or is this the one
    place a build step or a template split would pay for itself? (Ask whether it
    is *worth* it, not whether it is possible.)

### 6.9 Cross-cutting
46. **I-5 isolation** — grep for PyMuPDF imports outside the two modules; the
    test exists, confirm it can't be bypassed.
47. **I-3 non-fatality** — every stage's `except`. See §7.1 for a specific gap.
48. Run journal sanitization: secrets *and* absolute paths, at emit time, one
    line, bounded. Test the path scrubber against Windows UNC paths.
49. `run_manifest.json` schema v1 — non-circular write order, artifact hashes.
50. Thread safety: `_stage_overlap_enabled` gating, `ThreadPoolExecutor`
    lifecycle, `render_spool` locking, `RunUsage`/`RunJournal` under concurrency.
51. GUI: is any long operation on the Tk main thread? Is cancellation clean?
52. Windows specifics: paths, `keyring` backend fallback, the installer flow,
    `packaging/windows/`.
53. Security posture in `SECURITY.md` vs what the code actually does.
54. Dependency pinning: `requirements.txt`, `requirements-release.lock`, and
    `pyproject.toml`'s `anthropic>=1.4,<1.5` — is that band right?

### 6.10 Documentation and naming debt
55. `core/api_config.py` opens *"Centralized Anthropic API configuration for
    **Spec Critic**"*, and `core/tokenizer.py`'s entire docstring is about
    "per-spec review" and "cross-check" limits from a predecessor product. The
    orphaned `PHASE_REVIEW` / `PHASE_CROSS_CHECK` entries are documented as
    having no call site in this pipeline. Decide whether this lineage debt is
    harmless or actively misleading.
56. `pipeline.py:2373` still says the critique *"re-renders each sheet (the
    digest images are gone by then)"*. `render_spool.py` made that false. Find
    other drift of the same kind — the docs are load-bearing here.
57. `README.md` is 1,495 lines and `CHANGELOG.md` 1,876. Are the cost claims
    ($0.4–0.6/sheet standard, $2–3.5/sheet exhaustive) still accurate?

---

## 7. My suspicions — verify or kill each

These are leads. I have low-to-moderate confidence in most of them.

### 7.1 A dependency panic escapes the I-3 guard *(highest confidence, narrow blast radius)*

`spec_documents.py:109` catches `except Exception` with the comment *"one bad
spec file must never sink the upload."* In this sandbox, `pypdf` → `cryptography`
raised `pyo3_runtime.PanicException`, whose MRO is
`(PanicException, BaseException, object)` — **it is not an `Exception`**. The
guard did not catch it; three tests failed with a Rust panic traceback.

The environment is broken, not the code. But the same class of escape applies to
every `except Exception` guard in the codebase whenever a pyo3-backed dependency
panics — and `tiktoken` and `pydantic-core` are both pyo3 extensions on hot
paths. A panic in `core.tokenizer.count_tokens` would take down a run that I-3
promises will still ship its deliverable.

Questions for you: is this worth defending against at all? If yes, where — a
narrow `except BaseException` at the few extension-calling boundaries, or
nowhere because a panicking interpreter is not a state worth continuing from?
There is a real argument for "do nothing": catching `BaseException` also
swallows `KeyboardInterrupt`, and a panicked Rust extension may have left the
process unsound. I lean toward a narrow, explicitly-scoped guard at the
`tiktoken` and PDF-text-extraction boundaries only, but I hold that loosely.

### 7.2 The pre-run cost estimate overstates by ~1.9× *(high confidence)*

`pipeline.estimate_image_tokens_for_set` assumes every image is a **square** at
the **raster** long-edge target and lands at the per-model cap:

```
37 images × estimate_image_tokens(1992, 1992) = 37 × 4784 = 177,008 tokens/sheet
```

The actual figure for the common (vector) sheet is **92,871** — the estimator is
**1.9× high**. Even for a genuinely raster sheet it over-quotes (151,432 actual
vs 177,008 quoted, +17%), because real tiles are not square.

The docstring defends this as "a true upper bound that never under-quotes," and
that reasoning is coherent. But the number is surfaced in the GUI's
cost-confirmation dialog, which is the moment the operator decides whether to
run. A dialog that says $20 for a $10 job trains the operator to distrust the
dialog. Consider quoting a low–high band (vector target → raster target), the
way the exhaustive per-stage estimate already quotes verification and citation.

This is a *presentation* fix, not a correctness one. Judge whether it's worth
touching.

### 7.3 `REVIEW_MODEL_DEFAULT` binds at import *(high confidence, known)*

`core/api_config.py` evaluates `os.environ.get("DRAWING_ANALYZER_MODEL", ...)` at
module scope, and eleven modules bind it as a second name via
`from ... import REVIEW_MODEL_DEFAULT`. Setting the env var after import does
nothing; monkeypatching the attribute does not change what `critique_model()`
returns. `scripts/ab_sweep_drawing_analyzer.py` documents this at length and
works around it by running each arm in a **subprocess**.

A `review_model()` accessor function (matching the `critique_model()` /
`citation_model()` pattern already used elsewhere) would remove the trap. The
counter-argument is that the subprocess workaround exists, works, and a
refactor touching eleven modules to fix a thing that is already handled is
churn. Your call.

### 7.4 There is no digest-specific model knob *(high confidence)*

Every other stage has one: `DRAWING_ANALYZER_CRITIQUE_MODEL`,
`_CROSS_QC_MODEL`, `_IDENTITY_MODEL`, `_HARVEST_MODEL`, `_CITATION_MODEL`,
`_SYNTHESIS_MODEL`, `_FOCUS_MODEL`, `_REVIEW_PLAN_MODEL`,
`_INVESTIGATION_MODEL`, `_VERIFICATION_MODEL`. The digest — the single most
expensive stage in the app — can only be moved via `DRAWING_ANALYZER_MODEL`,
which is also the *fallback* for critique and cross-QC. So "put the digest on
Sonnet, keep the critique on Opus" requires setting two variables in the right
order and knowing the fallback chain.

This blocks the cheapest experiment in §8.3 from being run cleanly. A
`DRAWING_ANALYZER_DIGEST_MODEL` reading through the same accessor pattern is
about fifteen lines.

### 7.5 The tile overlap may be spending resolution it doesn't need to *(moderate confidence — verify my geometry)*

`zoom_for_rect` targets a fixed **long edge in pixels per tile**. An overlapping
tile is physically larger, so it renders at *lower* zoom to hit the same pixel
count. Consequence: **overlap costs zero image tokens and instead costs effective
DPI.**

At the shipping 8% overlap, an E-size interior tile is 612.5 pt tall rendered to
1560 px → ~183 DPI. At 4% overlap the same tile is 570 pt → the *same* 183 DPI
needs only ~1452 px. Tokens scale with area, so `(1452/1560)² ≈ 0.866` — a
**~13% image-token reduction at identical rendered resolution.**

That is not free: 4% of an E-size cell is ~0.23" of overlap per edge, and the
overlap exists so a symbol straddling a tile boundary appears whole somewhere.
Whether 0.23" is enough for the symbols on a fire-sprinkler sheet is an
empirical question I cannot answer and you probably can't either without
running it. But if my geometry is right, it is a lever nobody has priced, and
the `--variant` harness can test it. **Check my arithmetic first — if
`zoom_for_rect` doesn't behave as I read it, this whole item evaporates.**

### 7.6 Fixed 6×6 grid regardless of sheet size *(high confidence in the fact, open on the fix)*

`rows`/`cols` are a **run-level** parameter, not per-sheet. An 8.5×11 cover
sheet and a 34×44 plan sheet both get 37 images and both cost ~$0.51. The small
sheet renders at ~788 DPI — roughly four times what the text needs. See §8.1;
this is the biggest single cost finding in this brief.

### 7.7 Three full-coverage reads, two of which are compared *(moderate confidence, high stakes)*

Per sheet, exhaustive mode issues:
- 1 digest read — emits prose **and** a JSON findings block (up to 40 findings)
- 2 critique reads — emit findings only, compared for self-consistency

So three full-coverage vision passes produce findings, but the `reproduced`
signal is computed from only two of them. The digest's findings enter the ledger
as a separate source family and contribute to the multi-source provenance chip,
but they are not part of the self-consistency truth table (§14.4).

The question worth asking: **could digest-findings + one critique read serve as
the two arms of self-consistency, eliminating one full read (−33% of the
dominant cost)?** The honest counter-argument, which I think is strong: the two
critique reads are *identical prompts* — that is what makes their disagreement a
sampling-variance measurement. Digest and critique are different personas with
different jobs, so agreement between them means something different (arguably
*stronger* — cross-persona corroboration — but different), and §14.5 is emphatic
that both reads must be prompted identically or a finding can be falsely stamped
an uncorroborated singleton.

I am not proposing this change. I am proposing that you decide whether it's a
real option or a category error, and record the reasoning either way, because
it's the largest single lever in the architecture and I could not find a note
saying it had been considered.

### 7.8 Digest and critique cannot share a prompt cache *(moderate confidence)*

Anthropic's prompt cache matches a **prefix** over `tools → system → messages`.
The digest and critique of the same sheet send byte-identical imagery but
*different system prompts*, so the prefix diverges at the first block and the
~93k image tokens are billed at full rate in all three reads.

`critique.py` already exploits caching *within* itself: when `runs >= 2` it puts
a `cache_control` breakpoint on the last content block so read 2 serves the
image prefix at ~0.1×. The machinery exists; it just can't reach across the
stage boundary.

If the persona instruction moved out of `system` and into a trailing **user**
block after the images — leaving a shared, byte-identical
`system + text-layer + images` prefix — then digest, critique 1 and critique 2
could share one cache entry: `93k × (1.25 + 0.1 + 0.1)` vs `93k × 3` ≈ **52%
cheaper on the real-time exhaustive path.**

Costs and risks I can see, which may sink it:
- The three reads must land inside the 5-minute TTL, i.e. per-sheet
  digest-then-critique ordering, which fights the current stage-at-a-time
  pipeline shape and the `render_spool` handoff design. A `ttl: "1h"` breakpoint
  relaxes that at a 2× write cost — still ~27% cheaper.
- Moving the persona from `system` to `user` **changes the prompt**, which
  changes `DIGEST_PROMPT_VERSION` / `CRITIQUE_PROMPT_VERSION`, invalidates every
  cached digest and critique in existence, and — more importantly — may change
  what the model produces. Instruction placement is not cost-neutral to quality.
- It does nothing for the batch path (parallel submission, no ordered prefix),
  and batch is already the GUI default and already 50% off.

That last point may make the whole idea uneconomic: the population that would
benefit is real-time exhaustive runs, which the app already nudges operators
away from. Weigh it.

### 7.9 Verification has no batch transport *(moderate confidence)*

`verify.py` issues one small real-time Sonnet call per anchored finding, with a
crop image. A 39-sheet run with ~287 findings is ~287 real-time calls. The
digest and critique both have batch transports; verification does not, and
`citation_check.py` documents itself as "real-time only."

Verification is latency-tolerant in a way the digest is not — the operator is
already waiting on a long run. Batching it would be a straight 50% on that
stage. Whether that stage is big enough to matter, I don't know: measure it
against the ledger from a real run before proposing anything. The counter-argument
is that verification is per-finding and adaptive (escalation on CRITICAL/HIGH
UNVERIFIED), and a batch round-trip in the middle of the disposition chain adds
a stall point to an already-long run.

### 7.10 Sheet text is capped at 15k chars while pixels are unbounded *(moderate confidence)*

`SHEET_TEXT_MAX_CHARS = 15_000` ≈ 4k tokens ≈ **$0.02** on Opus. The images on
the same request are 93k tokens ≈ **$0.46**. The text layer is roughly **25×
cheaper per unit of information** than the pixels, and it is the *source of
truth* for exact strings — the whole reason the tile target could be dropped
from 1992 px to 1560 px in the first place.

Yet the text is the thing that's capped. On a schedule-dense sheet — and a
hyperscale-data-center fire-protection sheet with a full hydraulic-calculation
schedule is exactly that — truncation silently removes the grounding that
`source_quote` depends on, and a finding in the truncated tail can only come back
UNANCHORED.

Raising the cap to 40–60k chars costs cents per sheet. Verify first whether
truncation actually fires on real sets (it logs at INFO, so the owner's run logs
should say), and whether anything downstream assumes the cap.

### 7.11 Smaller things I noticed but did not chase

- `model_supports_extended_output_beta` is documented as having no production
  caller. The 300k extended-output path is unreachable.
- `gui.py:741` and `gui.py:1913` acknowledge dead handler code left in place.
- `gui.py` (2,790 lines) and `html_report.py` (5,851 lines) are the two files
  where size is plausibly a maintenance problem rather than just a fact.
- The overview image renders at the *same* long-edge target as a tile, so a
  whole E-size sheet is compressed to ~35 DPI. It is only ~2.7% of the sheet's
  image budget, so shrinking it saves almost nothing — but ask whether 35 DPI is
  actually doing the "global layout and match-lines" job the prompt claims.
- `requirements.txt` pins `httpx2==2.12.0` / `httpcore2==2.12.0`. Confirm those
  are the intended distributions.

---

## 8. Cost hypotheses, ranked

My framing, which you should attack: **the text layer is ~25× cheaper per unit
of information than the pixels, and the pixels are ~97% of the bill. Every good
cost idea in this codebase is a way of spending fewer pixel-tokens for the same
evidence.**

Every one of these must be validated through `scripts/ab_sweep_drawing_analyzer.py`
against its three oracle-free signals — anchor tier mix (UNANCHORED share),
verification verdict mix (REJECTED share), and self-consistency (REPRODUCED
share) — plus the quiet-failure check the harness already implements: *a large
drop in finding count at a flat VERIFIED share means real defects went unseen.*
And per that harness's own warning: **a clean screen is not an approval.**

### 8.1 Per-sheet adaptive grid at constant DPI — largest, lowest-risk

Choose `rows`/`cols` **per sheet** so effective tile DPI hits a target (~180–200,
what E-size already gets today) instead of fixing the grid at 6×6.

| Sheet | Now | Adaptive | Image tokens | Change |
|---|---|---|---|---|
| E 34×44 | 6×6 @ 197 DPI | 6×6 @ 197 DPI | 92,871 | **0%** |
| 30×42 | 6×6 @ 206 DPI | 6×6 @ 206 DPI | 85,854 | **0%** |
| D 24×36 | 6×6 @ 241 DPI | 5×5 @ 201 DPI | 56,324 | **−30%** |
| C 18×24 | 6×6 @ 361 DPI | 3×3 @ 181 DPI | 24,366 | **−73%** |
| B 11×17 | 6×6 @ 510 DPI | 3×3 @ 255 DPI | 21,016 | **−73%** |
| A 8.5×11 | 6×6 @ 788 DPI | 2×2 @ 263 DPI | 12,535 | **−86%** |

The owner's own sets (E-size and 30×42) see **zero change** — which is exactly
why this is safe: it takes nothing away from the sheets that need it. The
savings land on D-size sets, and on the 11×17 detail sheets, cover sheets and
index sheets that ride along in nearly every submittal. For a mixed set the
blended saving is plausibly 20–40%.

Considerations you must work through:
- **I-1 is untouched** — coverage stays whole; only the subdivision changes.
- The grid rides the level-1 render identity (`rows=`, `cols=`), so changing it
  invalidates cached digests for affected sheets **once**. Acceptable, but say so.
- `tile_label` is grid-relative, so a per-sheet grid must be plumbed into the
  label contract, the omitted-tile disclosure, `parse_tile_label`'s bounds check,
  anchor's TILE tier, and the cache key. This is the real cost of the change —
  it is not a one-line default swap.
- `estimate_image_tokens_for_set` and `cost.py` would need to become
  page-size-aware to stay honest (and see §7.2).
- Decide the target DPI empirically. 3/32" note text at 180 DPI is ~17 px tall;
  that is the constraint the current numbers were built around.

### 8.2 Overlap/target rebalance — ~13%, needs my geometry checked first

See §7.5. If overlap genuinely costs DPI rather than tokens, then dropping
overlap to 4% and the target to ~1452 px holds resolution constant and cuts
~13% of image tokens. Cheap to test with two `--variant` runs. Kill it
immediately if my reading of `zoom_for_rect` is wrong.

### 8.3 Split-model routing: Sonnet digest, Opus critique — up to 60% on the digest

`_MODEL_CAPABILITIES` registers Sonnet 5 with **hi-res vision, `xhigh` effort,
128k output and a 1M context** — full parity with Opus 5 on every axis this
pipeline gates. It is 2.5× cheaper ($2/$10 vs $5/$25).

The digest's job is *transcription and description* — grounded by a verbatim
text layer that already carries the exact strings. The critique's job is
*adversarial reasoning*. Those are different difficulties, and the pipeline
already routes identity, harvest, citation and first-pass verification to
Sonnet on exactly this logic.

Per-sheet digest: $0.513 → $0.205 real-time, $0.257 → $0.103 batch.

Blockers and risks:
- Needs `DRAWING_ANALYZER_DIGEST_MODEL` first (§7.4).
- The digest also emits up to 40 findings per sheet, so it is *not* purely
  transcription — a Sonnet digest may find less, and the ab-sweep's
  "finding count drops at flat VERIFIED share" signal is precisely the trap.
- Watch the **tokenizer difference**: `core/tokenizer.py` notes Sonnet 5 emits
  ~30% more Claude tokens than Sonnet 4.6 for identical text. Confirm the
  budget math still holds.
- Ask whether cheaper-per-sheet would tempt the owner into raising resolution or
  reads elsewhere — that is a legitimate way to spend the savings on quality
  rather than banking them.

### 8.4 Prompt-cache the image prefix across digest + both critiques — ~52% real-time

See §7.8. Highest theoretical saving on the real-time path, but it requires a
prompt restructure that invalidates every cache and may move quality, and it
does nothing for the batch path that is already the default. I rank it below
8.1–8.3 for that reason, not because the arithmetic is worse.

### 8.5 Content-density-aware tiling — unknown size, needs measurement

Blank-tile suppression today is strictly pixel-uniform (always on) with an
opt-in near-blank byte heuristic (off by default, correctly). A middle path
exists that the current code does not use: the pipeline **already has the vector
word rectangles** and could ask, per tile region, whether it contains any words
*and* any vector drawing operations. A tile with neither is provably empty
without a pixel heuristic — stronger evidence than a PNG byte count, and it
could run *before* rasterization, saving render time as well as tokens.

Sparse sheets (large plan areas, title-block-heavy detail sheets) could drop
several tiles each. I have no measurement of how often this fires on real sets —
get one before building anything. And it must stay conservative: I-1 permits
dropping only tiles that are genuinely content-free.

### 8.6 Raise the text cap — costs a little, may buy quality

See §7.10. This *increases* spend by cents per sheet. I list it here because the
thesis of this section is the ratio, not the absolute: moving grounding work
from pixels to text is how you get cheaper *and* better, and the cap is
currently pointing the wrong way.

### 8.7 Batch the verification stage — ~50% of that stage

See §7.9. Size it against a real run's usage ledger before deciding it's worth
the added stall point.

### 8.8 Things I considered and rejected

- **Image format (JPEG/WebP instead of PNG).** Image tokens are computed from
  *dimensions*, not bytes. Format changes upload time and nothing on the bill,
  and lossy compression on line-work is a quality risk for zero token gain.
- **Shrinking the overview image.** ~2.7% of a sheet's image budget. Not worth
  the risk to the global-layout job it performs.
- **Reducing `max_tokens` caps.** Output is billed by actual tokens; the caps are
  fail-fast guards. The code already says this and the code is right.
- **Dropping to a non-hi-res vision model.** Would cut the per-image token cap
  but destroy the resolution the whole tiling design exists to deliver.

---

## 9. Constraints on any proposal you make

1. **Never trade a false negative for a dollar.** This tool exists to catch
   things a human reviewer missed on drawings that will be built. A cost change
   that measurably reduces findings is a reject, not a trade-off, unless the
   lost findings are demonstrably noise.
2. **The invariants in §3.4 are load-bearing.** If you propose breaking one,
   say so in a section headed with the invariant number and argue it explicitly.
3. **I-5 (PyMuPDF isolation) is a licensing constraint, not a style one.**
4. **Tests must stay hermetic (I-4)** — no network, no API key.
5. **Cache keys must stay honest (I-6).** Any change to what is sent must
   invalidate. A `_SCHEMA_VERSION` bump is cheap; a stale hit is not.
6. **Determinism (I-7).** No new time- or randomness-dependence in assembly.
7. **Validate cost levers through the existing ab-sweep harness.** Do not invent
   a parallel methodology; if the harness is inadequate, say how and why.
8. **Windows is the deployment target.**
9. **Anything NFPA 13 related must be edition-aware** and must reflect the
   current edition. Do not hardcode an edition anywhere.
10. **Respect the docs habit.** This codebase explains *why*, including why
    things were rejected. Any change should extend that record, not thin it. If
    the implementation changes, the README/CLAUDE.md should follow; if
    dependencies change, `requirements.txt` should follow.

---

## 10. What to deliver

A written report containing:

1. **Your independent assessment** of the architecture — what is right, what is
   fragile, what is over-engineered, what is under-engineered. Disagree with
   this brief where you disagree; I would rather be corrected than agreed with.
2. **Findings**, each with: file and line, severity, what actually breaks and
   under what conditions, your confidence, and whether you verified it or are
   reasoning about it. Distinguish *"this is a bug"* from *"this is a smell"*
   from *"this is a design choice I would have made differently."*
3. **A verdict on each of my §7 suspicions and §8 hypotheses** — confirmed,
   refuted, or unresolved with what evidence would settle it. Refutations are as
   valuable as confirmations. §7.5 in particular rests on my reading of
   `zoom_for_rect`; check it before building on it.
4. **A cost analysis** with your own numbers, derived from the repo's own
   functions, on a realistic mixed set (say: 20× E-size plan sheets, 8× D-size,
   6× 11×17 details, 2 cover/index) — real-time and batch, standard and
   exhaustive. Say what you would actually change and what it would save.
5. **An implementation plan, only if warranted.** If you propose changes:
   ordered by value-per-risk, each with the files touched, the tests needed, the
   invariants engaged, cache-invalidation consequences, and how the change would
   be *validated* — not just implemented. Separate what is safe to do now from
   what needs a measured run first.
6. **An explicit "do not do this" list** — the things that look like
   improvements and aren't, with reasons. This is often the most valuable part
   of a review of a codebase this deliberate.

### On scope

You are not compelled to find problems, and you are not compelled to propose
changes. A report that says *"I examined all of this, here is what I verified,
and my recommendation is to change nothing except X"* is a good outcome — better
than a long list of marginal edits. This codebase shows evidence of many
previous review cycles; the low-hanging fruit is gone, and the remaining
questions are genuine judgment calls rather than defects.

Where you're uncertain, say you're uncertain and say what would resolve it.
Where a change requires a measured run against a real drawing set to justify,
say that rather than guessing — the owner has real sets and a harness built for
exactly this, and "here is the experiment to run" is a legitimate deliverable.

---

*Prepared by Claude Code from a direct read of the repository. Every number in
§4 and §8 was computed from the repo's own `tiling` and `core.tokenizer`
functions; re-derive them rather than trusting them.*
