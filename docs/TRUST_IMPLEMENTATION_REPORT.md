# Trust surface implementation report

The reader is an AEC professional responsible for checking and signing a review.
The app is Drawing Analyzer. The existing header help is the entry point.
Discovery and the initial claims ledger preceded replacement copy.

## Delivered

- `help_content.py`: a short lead, eight mechanism-backed points and the exact
  requested closing box/button. The topic has 368 words including headings and
  the closing prompt.
- `trust_dossier.py`: twelve sections, a shared inline SVG, provenance/engine/
  security/tool tables, limits, money, audit steps and further-reading links.
- `trust_ui.py` and `gui.py`: a native stacked dialog with one scroll, section
  anchors, a highlighted contents rail on wide screens, narrow table reflow,
  keyboard containment and return focus. Escape closes one level.
- `docs/TRUST.html`: a local, self-contained reading edition of the same content,
  supporting light and dark browser themes. The application uses its existing
  fixed dark palette; it has no light-theme switch.
- `docs/TRUST_CLAIMS.md`: discovery inventory, file/symbol evidence, numerical
  sources, findings and the generated statement-to-source map.
- `tests/test_trust_contract.py`: inventory coverage, all five runtime rows,
  source symbols, models/settings/hosts/figures, no external assets, generated
  artifact agreement and native focus/Escape/reflow checks.
- `CLAUDE.md` and README: the same-change maintenance contract. README/help/
  SECURITY copy was aligned where the discovered claims overlap.

No dependency manifests changed. Analysis, networking, storage, spending,
update and cleanup behavior were left as shipped.

## Inventory

There are **41 user action families**, **19 automatic behavior families** and
**60 runtime cards**. Workflow aliases share a card; all aliases appear in the
ledger, with local-versus-sent/transport-versus-model branches made explicit.
File-picker cancellation and ordinary editor
editing/undo are included in their import/edit/export families. There is no
desktop analysis Stop, resumable project save/load or application undo.

There are **6 network destination classes**, **2 default model IDs** and
**7 registered model IDs**, including fallback alternatives. A finite hostname
guarantee would be false: redirects, manifest-supplied installer URLs,
provider-supplied batch results URLs, endpoint/proxy overrides and provider web
tools can change destinations. The ledger lists fixed hosts and these exceptions.

## Claims softened or dropped, and findings

Every entry below is disclosed in the ledger/dossier. The implementation behind
it was not silently repaired.

1. **A model check is not approval.** VERIFIED/REJECTED are crop-model judgments.
   COMPLETE describes configured stage outcomes; receipt coverage describes
   saved annotations. Neither certifies engineering correctness or completeness.
2. **Every judgment cannot be rederived.** Local arithmetic/matching/receipt
   checks can be inspected; model decisions can differ on repetition.
3. **Text extraction is not lossless engineering truth.** Wrong PDF text layers,
   extraction order and ambiguous pixels can produce wrong readings. Replaced
   the help/README claim that vector text cannot misread a digit.
4. **Not every quote anchors, and not every proposal survives.** List/text caps,
   partial/refused reads, parsing, prose filters and shard limits can omit items.
   Removed blanket losslessness and prose-mirroring guarantees.
5. **Originals are read during analysis, but exports can overwrite chosen files.**
   Save HTML/Reviewed destinations lack a complete source-path exclusion.
   Reviewed work is first written in temporary work, not beside the originals.
6. **Margin placement is a heuristic.** Detected occupancy is not proof that a
   region is empty; replaced the help claim that a callout never covers drawing
   content.
7. **Work continues automatically after approval.** Startup performs local work
   and an optional automatic update check. Approved analysis/chat starts retries,
   tools and cleanup without another click. “No AI runs on its own” is too broad.
8. **There is no desktop Stop or global dollar ceiling.** Quitting can lose
   unsaved in-memory output and leave accepted remote work billed/running.
   Chat Stop aborts the client fetch, not provider work or charges.
9. **The network boundary has exceptions.** Removed README's “talks only to
   Anthropic”/entirely-local claim; named updates, redirects, installers,
   batch results, custom routes and explicit browser links.
10. **Web queries can contain project information.** Citation claims and chat
    context reach the provider; its model chooses research queries/URLs. A
    source-quality blocklist does not enforce confidentiality.
11. **Call totals are not fixed.** Investigation slots scale with sheet count;
    cross-QC shards; retries and pauses add calls. Replaced the previous fixed
    investigation count and one-call implications.
12. **Bounds are layered.** SDK and app retries stack; refusal fallback can
    change the serving model. A rejected advisory task budget is removed; host
    evidence/iteration limits remain. No run spending cutoff exists.
13. **Chat's round comparison allows an extra tool-bearing round.** Search/fetch
    use limits reset with each request, rather than bounding the entire turn.
14. **Updates are not independently signed or confined to one host.** HTTPS and
    a hash supplied by the same manifest do not establish publisher identity;
    redirects and arbitrary HTTPS installer URLs are accepted.
15. **A download has no byte/total-time cap, and dismissal is not cancellation.**
    The worker can finish and leave an installer cached after its window closes.
16. **Remote erasure is best effort.** Delete failures are swallowed; failed
    cancellations can retain uploaded files for live batches. Provider backup/
    retention/training policies cannot be proved by this client.
17. **Local retention is broader than Clear/close.** The cache has no general
    expiry; temporary evidence survives until later pruning; browser transcripts
    have no app expiry. Clear does not erase saved credentials or these copies.
18. **Browser keys are not a guaranteed disk-free vault.** Browser recovery and
    file-origin sharing are outside the app. Forget can fall back to an embedded
    author key; it cannot remove the literal credential from HTML.
19. **A scrubbed transcript is not generally secret-free.** The serializer
    excludes the credential field and recognizes `sk-ant-` patterns; other
    credentials/project text can remain. SECURITY/README now name this limit.
20. **Spending figures are estimates.** Requested-model pricing can understate
    fallback costs; interrupted usage and chat search fees can be absent. Chat
    spending is outside the analysis run ledger. Failures/stops do not refund it.
21. **The advertised token-count preflight does not run.** The helper has no
    production caller. GUI estimates stay local approximations; source comments
    promising a preflight remain a recorded disagreement.
22. **Default profiles do not sharpen the estimate.** No built-in profiles ship,
    so the profile-dependent geometry preflight normally does not run.
23. **Prompts do not prohibit model arithmetic or prompt injection.** Host
    arithmetic checks supported grounded claims; chat uses a restricted browser
    calculator. Neither implies every answer is host-calculated or reliable.
24. **Sort does not regroup repeated quotes.** The README and an HTML comment
    claimed regrouping after sort/filter; the sort handler does not call it.
    README now names the exception; the behavior/comment remain unchanged.
25. **Specifications have a source-audit gap.** The pipeline receives extracted
    spec text, rather than original spec-file fingerprints; Export All does not
    preserve original spec files or a separate spec-text artifact. The provenance
    table qualifies the drawing-hash claim and tells you to keep your own copies.
26. **Batch submission starts AI work.** Uploads/polls/cancel/delete have no model
    answer of their own; submitted and recovered items run the digest/critique
    models. The transport card names both branches instead of a blanket “None.”
    The chat question card similarly distinguishes local composition from Send.

The older runtime briefing and short trust topic were replaced. Historical
developer notes/comments were not treated as evidence; remaining known
disagreements are the token-count-preflight comments, the report sorting comment,
and CLAUDE.md's already-labeled historical geometry/grouping claims.
The legacy How it works topic also retains broad code-recognition/edition-backstop
and “lossless” de-duplication wording (`help_content.py: _HOW_IT_WORKS`). Those
phrases are stronger than the dossier's scoped parsing/model/provenance claims;
they should be read with its explicit limits. They are listed here rather than
treated as code guarantees.

## Sections and open questions

No required section was dropped. Titles were adapted to review work: runtime
includes “and afterward”; engine/privacy/money titles name the app's mechanisms.
The three opening commitments were narrowed to distinguish origin, approved
follow-ups and inspectable evidence, because repeatable AI judgments and no
automatic work would be unsupported promises.

No answer is needed to use the delivered trust surfaces. Future product decisions
remain: should retention gain explicit deletion controls; should desktop analysis
gain Stop; should updater downloads get independent signatures/host/size limits;
and should fallback/chat pricing discrepancies be repaired? These are separate
behavior changes, outside this task.

## Verification

- The full hermetic suite passed: **5,924 passed, 10 live canaries deselected**.
  Three disjoint file groups covered all 115 test files: 2,422 / 1,678 / 1,824
  passed. No browser/native test was skipped.
- After the final conditional-AI copy and display-scaling adjustment, the
  affected trust/help/GUI-lifecycle checks passed: **126 passed**. This includes
  two additional native scaling cases and four light/dark wide/narrow browser
  cases; the generated page/ledger agreement and source facts pass.
- The existing browser suite separately passed **105 checks**. Its anti-skip
  gate confirmed 105 executed. Playwright remains the declared 1.63.0; this
  environment used Chromium headless shell 140.0.7339.16 from the approved
  Microsoft distribution mirror and local DejaVu fonts. The pinned browser's
  Google redirect remained outside the enforced allowlist.
- The final wheel and source distribution built successfully. A clean virtual
  environment imported the installed version, profile mechanism and trust
  modules. Ruff's required correctness classes and `git diff --check` passed.
- Manual browser inspection at 1440 and 375 pixels, in light/dark themes, showed
  readable text, no horizontal overflow and zero external asset requests. Native
  checks exercise real Tk windows on Linux, stacked focus/Escape, narrow reflow,
  the contents rail and simulated 1.5×/2× scaling. Actual Windows screen-reader
  behavior and Windows installer compilation require their own platform checks.

No live model calls, paid evaluations, release, installer execution or
publication were run. No answer or approval remains pending for this task.
