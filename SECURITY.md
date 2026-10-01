# Security & Privacy

Drawing Analyzer processes private project information. Its output is review
material, not professional approval. Check your project restrictions and provider
agreement before sending drawings or specifications.

## What leaves your computer

Approved analysis sends sheet images, extracted text, supplied specifications,
focus and review context to Anthropic by default. QC may send evidence crops and
citation claims. Report Ask AI sends the report, question, conversation and tool
results from your browser. Provider web tools can research project-derived text;
a source-quality filter is not a confidentiality boundary.

The app also checks GitHub for updates; disable checks with
`DRAWING_ANALYZER_DISABLE_UPDATE_CHECK=1`. Installer URLs and redirects come from
the update manifest. Batch-result URLs come from the provider. Desktop endpoint
and proxy overrides, and links you click, can change destinations. The application
cannot prove the provider's retention, training or erasure policies.

## Keys

The GUI prefers a credential store whose save/read round-trip succeeds. When no
secure store works, it asks before saving a plaintext fallback; declining keeps
a session-only key. Verified legacy keys may migrate to the store; unverified or
different file contents are preserved. The run captures its key and the GUI does
not place it in the process environment for child programs to inherit.

HTML omits the key by default. Explicit **Embed API key in HTML report** writes
it into the file. Never share such a report: runtime **Forget key** cannot erase
an embedded credential. Regenerate without the key and rotate a disclosed key.

A prompted chat key uses memory and tab `sessionStorage`. Browser recovery and
disk behavior are outside the app's control. Local `file://` pages can share
storage origins; an untrusted local HTML file opened in the same tab can expose
a retained key. Use **Forget key** before opening untrusted files. Do not treat
browser storage as a credential vault.

## Local copies and retention

Reports, reviewed PDFs, findings, sheet text, evidence crops, caches and run
records contain project data. Cache entries have no general expiry; temporary
evidence is pruned on later runs, and remote upload deletion is best effort.
**Clear** or closing the app is not erasure of all local/provider copies.

Chat conversations auto-save to browser local storage. **New chat** clears that
report's stored conversation; separately saved JSON files remain. Transcripts
exclude the key field and redact recognized `sk-ant-` patterns, but other secrets
and project text can remain. Inspect before sharing. Loading is local; sending
a follow-up uploads the loaded conversation and report. Preserve original
specifications yourself; Export All does not archive their original files.

Logs redact recognized key/authorization/secret patterns and portable run records
reduce private paths to display names. Redaction is not general secret detection;
review diagnostics before sharing. Keys do not belong in source or test fixtures.

## HTML and spending boundaries

Drawing/model text, filenames and loaded transcripts are untrusted. Reports use
HTML escaping, safe DOM construction, validated HTTPS model/citation links,
inert JSON configuration and a hash-pinned Content-Security-Policy. These protect
against executing injected content; they do not make model claims or linked
websites trustworthy. A saved transcript's recorded tool calls are not executed
just by loading it.

Approved work can start retries, tools and cleanup automatically. There is no
desktop analysis Stop or global dollar ceiling. Closing/aborting does not refund
or necessarily cancel accepted provider work. Costs are estimates; incomplete
usage, fallback pricing and chat tool charges can be absent. Chat spending is
separate from the analysis run ledger. Check provider usage.

The updater's HTTPS and manifest-supplied SHA-256 protect transfer integrity, not
independent publisher identity. Installers are unsigned; download host redirects,
size and total duration are not comprehensively constrained. Verify release
sources before executing a downloaded installer.

## Report a vulnerability

Report suspected security issues privately to the repository owner, rather than
publishing a key, private drawing or exploit details in a public issue.
