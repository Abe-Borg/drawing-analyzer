# Security & Privacy

This document describes the security boundary of Drawing Analyzer's outputs and
how it handles your Anthropic API key and project data. It reflects the behavior
shipped in Phase 17A of the remediation plan.

## Threat model: all model output is untrusted

Drawing content is untrusted input. It is rendered into the images and text
layers that are sent to the model as prompts, so **the model's output can be
attacker-influenced** — a malicious or malformed drawing can steer what the
model writes back. Every string that reaches a generated artifact is therefore
treated as hostile: model findings and prose, the Ask-AI assistant's answers,
source filenames, sheet IDs, titles, quotes, citation notes/URLs, evidence
paths, parser errors, run errors, and serialized configuration.

## The HTML report (`report.html`)

The report is a single self-contained file. Its security rests on four layers:

1. **Escaping on the Python side.** Every untrusted value is HTML-escaped into
   element content, or attribute-escaped into attributes. Dynamic values never
   form tag or attribute syntax. The one machine-readable data island (the
   Ask-AI config) is emitted as an inert `type="application/json"` script,
   serialized so that every `<` (and the U+2028/U+2029 line separators) becomes
   a JSON string escape — no value can close the script element or inject
   markup, and `JSON.parse` still round-trips it byte-for-byte.

2. **Safe DOM construction on the browser side.** The Ask-AI assistant renders
   the model's streamed Markdown by building DOM nodes with `createElement` and
   filling them via `textContent` — never `innerHTML`, `outerHTML`,
   `insertAdjacentHTML`, or `document.write` with model data. Attack strings in
   answers, code spans, tables, or thinking summaries appear as inert text.

3. **One URL policy for every link.** Markdown links in answers and the
   citation chips both go through a single validator that accepts **only
   absolute `https:` URLs**. It rejects `javascript:`, `data:`, `file:`,
   `blob:`, protocol-relative, malformed, credential-bearing (`user:pass@`), and
   control-character URLs (raw or percent-encoded). A rejected URL degrades to
   inert visible text — never a live link. Every emitted link carries
   `rel="noopener noreferrer"`.

4. **Content-Security-Policy (defense in depth).** The report ships a CSP
   `<meta>` tag that:
   - allows only the exact inline scripts this build emits, pinned by SHA-256
     hash (`script-src 'sha256-…'`) — there is no `'unsafe-inline'` for scripts
     and there are no inline event-handler attributes;
   - restricts `connect-src` to `https://api.anthropic.com` (the Ask-AI target)
     when the assistant is present, and `'none'` when it is omitted;
   - forbids objects (`object-src 'none'`), base-URI rewriting
     (`base-uri 'none'`), and form submission (`form-action 'none'`);
   - restricts images to the report's own relative evidence crops.

   The exact policy is exercised against `file://` in Chromium in the Phase 17B
   headless-browser test suite; the safe DOM boundary above is mandatory
   regardless of CSP support.

## The Ask-AI assistant and your API key

- The assistant is present **by default**, whether or not the report was built
  with a key. It calls the Anthropic Messages API directly from your browser
  (no server).
- **By default the key is never written into the file.** The assistant prompts
  for a key on first use and keeps it only in the browser tab's
  `sessionStorage`. A **Forget key** control clears both the in-memory copy and
  `sessionStorage`. A `401` clears the stored prompted key before retry.
- **Embedded-key mode is an explicit opt-in** (GUI checkbox / `embed_api_key=
  True`). The key is then baked into the HTML; the report shows a red warning,
  and the file must be treated as a credential. A runtime "forget" **cannot**
  remove an embedded key — only regenerating or deleting the file can, and the
  widget says exactly that.
- Pass `include_chat=False` to omit the assistant (and every network reference)
  entirely.
- The key literal never appears in the default HTML, in rendered chat text, or
  in logs. Request headers are never logged.

## Persistent API-key storage (GUI)

Saving a key for future sessions uses an **OS-secured credential store** —
Windows Credential Manager, macOS Keychain, or Secret Service / kwallet on Linux
— via the optional `keyring` package. A backend is trusted only after a verified
round-trip (store, then read the value back).

If no secure backend is available, the key is **not** silently written to disk.
The GUI asks for explicit consent before writing a plaintext fallback file;
declining keeps the key for the current session only. Any consented plaintext
file is created owner-only (`0600`) on POSIX. Legacy plaintext key files are
migrated into the credential store (and deleted) the next time the key is loaded
or saved on a machine with a working backend.

## Diagnostics logs

The optional diagnostics file passes every line through a shared redaction
filter before writing: `sk-ant-…` key material, `Authorization` / `Bearer`
values, and named secret fields (`x-api-key`, `api_key`, `token`, `secret`,
`password`, …) are replaced with `[REDACTED]`. This applies to our own log
lines, the optional SDK wire-capture (`DRAWING_ANALYZER_DEBUG`), and formatted
tracebacks. Token *counts* are preserved.

## What project data the artifacts contain

The generated artifacts contain information about your drawings. Treat them
accordingly:

- `report.html` — the full digest, findings, and (when embedded) your API key.
- `sheet_text/` — each sheet's extracted text layer.
- `evidence/` — the image crops the verifier saw for each finding.
- `findings.json` / `findings.csv` — the structured findings.
- `*_reviewed.pdf` — the marked-up drawings.

The Ask-AI assistant sends the report context and your question to Anthropic.
The verification, citation, and QC stages send their described crops and claims
to Anthropic. An embedded-key report is a credential and must not be shared.

## Reporting a vulnerability

Please report suspected security issues privately to the repository owner rather
than opening a public issue.
