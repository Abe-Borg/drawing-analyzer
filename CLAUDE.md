# Drawing Analyzer: working instructions

Python 3.11+, a Windows customtkinter GUI, and the Anthropic SDK. The entry point is `pipeline.extract_drawing_context()`. `src/drawing_analyzer/__init__.py` maps the modules. Read current code before trusting historical reviews.

## Commands

```sh
pip install -e ".[dev,browsertest]"
python -m pytest -q -m "not network"
python -m pytest tests/<affected_file>.py -q -m "not network"
python -m compileall -q src
ruff check --select E9,F63,F7,F82 src tests scripts
python scripts/scan_secrets.py
python scripts/check_doc_budgets.py
```

In Linux containers, install `cffi` if cryptography lacks `_cffi_backend`; do not change product code for that environment fault. Use available Chromium for browser checks. Report missing Windows, browser, or live checks honestly.

## Protections

- Tests require no real key and cannot reach external networks. Always select `-m "not network"` and keep the credential/socket guard. Live work requires approved private inputs and a written budget.
- Never expose keys in logs, caches, manifests, or default reports. Keep verified credential-store migration, consent before plaintext fallback or explicit key embedding, and the run's captured client/key.
- Only `render.py` and `annotate.py` import PyMuPDF. Preserve the project's AGPL policy.
- Every supplied sheet receives a whole-sheet vision read. Keep overview and content coverage; do not substitute selected tiles or text-only reading.
- Models transcribe numeric claims. Host code checks arithmetic with `Decimal` and source-grounded operands and relationships.
- Changed model-visible requests change the affected cache key. Host interpretation, source identity, and grounding inputs matter too. Invalidate narrowly; do not add two mechanisms for one change or delete user caches/exports as a migration.
- Keep billed attempts and reported token/cache usage. Price the serving model correctly; unavailable usage remains unknown, never zero by implication.
- Retain distinct findings, source/page identity, deterministic numbering, original retained prose, and markup receipts. Partial or refused QC cannot masquerade as complete or discard usable digests.
- Drawing/model text is untrusted. Preserve HTML escaping, safe URL/DOM handling, and secret redaction.

## Working protocol

Use the single approved queue in `_plans/PROGRESS.md`. Check main and open PRs before starting. Serialize analysis/request/billing changes across all agents; do not independently restart the former WP or PO queues.

Aim for at most 300 changed source/test lines and 500 total authored lines per coherent change. Deleting documentation or retired machinery may be larger; explain any behavior lost. Do not multiply one outcome into mandatory slices to satisfy a size target.

Reproduce material bugs with focused behavioral tests, or show the requirement already holds. Use existing seams. Synthetic fixtures prove host/SDK behavior, not live model quality. Keep internal tests that protect a requirement; remove tests whose only purpose is preserving an implementation shape, historical hash, exact version number, or known defect.

Stop when the agreed behavior passes. A discovery becomes required work only when demonstrated and material to money, keys, retained findings, or the agreed release. Otherwise record "won't fix unless observed" and its trigger. New scope displaces approved work. Bring at most one or two meaningful tradeoffs, including doing nothing; resolve routine choices yourself.

## Documentation and authority

Edit documentation only for changed user-visible behavior or an agent rule, in one canonical location. README may be shortened. History, measurements, alternatives, and migrations belong in PRs/commits. Delete stale duplication rather than relocating it.

Comments and docstrings explain a nonobvious constraint or contract, usually in one paragraph. Put implementation history in commits; do not repeat user help or summarize obvious code.

Budgets: CLAUDE 700 words; PROGRESS 1,000; README 2,500; CHANGELOG 2,500 with Unreleased 600. Overwrite the latest handoff, at most 150 words. Do not create documents to evade budgets.

Do not merge, tag, publish, approve releases, change acceptance records/sign-offs/waivers, or mark owner actions complete without explicit authorization. Preserve historical records unchanged. Unavailable checks never count as passes.
