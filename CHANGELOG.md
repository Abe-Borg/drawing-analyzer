# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-09-10

### Fixed

- **The exported Markdown and HTML carried API keys and private directory names
  that run.log carefully removed.** Measured on one export folder: `00_index.md`,
  the per-sheet Markdown and `report.html` each printed an
  `AuthenticationError` repr verbatim — including the user's own
  `…\Abe Borg\My Drawings\…` and the `x-api-key` header value from the failed
  request — while `run.log` and `run_manifest.json`, sitting in the same folder,
  were clean. The export folder is what gets emailed to a client. Host-generated
  status and error strings in all three artifacts (plus stage notes in the
  report's stage table) now pass through the same secret/path boundary the
  journal uses. Digest prose does **not**: a sheet note reading `TOKEN: 12` at
  `grid C:4` is drawing content, and redacting it would corrupt a review to
  defend against a credential that is not there (I-2).

- **A single lowercase drive letter leaked the user's home directory.** The
  known-private-roots pass replaced each root as a literal string, and Windows
  paths are case-insensitive with two legal separators — so a root recorded as
  `C:\Users\Abe Borg\My Drawings` (what `Path.resolve()` produces) did not match
  the same directory written `c:\Users\…` in an exception string. The regex
  backstop cannot bound a path containing spaces, so the name and folder
  structure survived into run.log and run_manifest.json. Roots are now matched
  case-insensitively and across both separators.

- **The private-roots list reached only one section of run.log.** A rejected
  input's `PermissionError`, a per-sheet error, a stage note, the ledger tally
  and a mutated-source name all render through the same sanitizer, and none of
  them was given the roots — so one string was scrubbed in the Errors section and
  printed in full two sections above it. Same for `run_manifest.json`'s `sources`
  and `markup_coverage` blocks. Every renderer now receives them, and a
  structural test over the module's own AST fails if a future call site omits
  them.

- **The mandatory browser exploit suite passed by skipping.** Every test in it
  skips itself when Chromium will not launch, and pytest exits 0 on an
  all-skipped run. Measured on one commit, one environment variable apart:
  `98 passed` and `98 skipped, 2180 deselected` — both exit 0. The required check
  was green over a suite that proved nothing about CSP, `file://` handling or
  event execution. CI now writes a JUnit report and
  `scripts/check_browser_suite.py` fails the job below a floor of genuinely
  executed tests. A skip is not a pass.

- **A release could publish an installer built from a commit whose tests were
  red.** Branch protection does not apply to a tag push, and a tag can name any
  commit, so `publish` needing only `build` meant the gate was "the installer
  compiled". `publish` now needs two tag-gated jobs that run **inside its own
  `needs` chain**: `gates` (the full `run_acceptance.py` — byte-compile, import
  isolation, the hermetic suite, the secret scan, the browser exploit suite with
  Chromium actually installed, and the wheel build — plus static analysis and the
  license and CVE audits) and `gates-windows` (the hermetic suite on Windows,
  where path length, case handling and the `\\?\` form actually apply). CI also
  triggers on `v*` tags, but that is for visibility only: a separate workflow run
  triggered by the same tag is **not** a dependency, so `publish` would otherwise
  create the release while those jobs were still running — or after one failed.

- **A private root matched any sibling directory sharing its prefix.** Root
  `C:\Users\…\Job` matched `C:\Users\…\Job2\Client Secret\file.pdf`, and the
  partial rewrite was *worse* than no match: it produced
  `...2\Client Secret\file.pdf`, and with the drive letter eaten the generic path
  scrub could no longer anchor the remainder to reduce it. A root match must now
  end at a component boundary — a separator or the end of the string — and a
  non-boundary match falls through to that backstop, which strips the drive and
  the first component. (Inherited from the `str.replace` it grew out of, which had
  the same prefix behaviour.)

- **Long-path support started one step too late.** The `\\?\` form was applied
  after the staging directory had already been probed and created through the
  plain path, so an operator-chosen parent deep enough that the export folder
  *itself* passed MAX_PATH failed before the first prefixed write was reached.
  The uniqueness probe and the `mkdir` now go through it too — and the probe
  matters twice over: past MAX_PATH an unprefixed `exists()` answers *False* for
  a directory that is really there, so the name read as free and the publish
  rename would move the new export over the old one.

- **The acceptance script's browser gate could pass on an all-skipped run too.**
  The CI job got the executed-test floor; `run_acceptance.py` — the one-command
  release gate — still treated "Playwright is installed" as evidence the suite
  ran. It now writes a JUnit report and applies the same floor through the same
  script, so the release gate and the CI job cannot disagree about what "passed"
  means.

- **Quitting the GUI mid-run discarded a paid run with no prompt.** The worker
  threads are daemons and the export happens *after* the analysis returns, so one
  stray click on the window's X threw away an hour of work and the API spend
  behind it — while the help, focus-popout and update windows each already
  confirmed on close. The main window now confirms, names which job is in flight,
  and says what quitting costs; an idle window still closes immediately.

- **The app could not report that its own UI toolkit was missing.**
  `customtkinter` is in the `gui` extra and the launcher is declared under
  `[project.gui-scripts]`, which on Windows builds a console-less executable — so
  `pip install drawing-analyzer` followed by `drawing-analyzer` produced *nothing
  at all*: no window, no message, no visible exit code. The import is now guarded
  and reports through a stdlib messagebox naming the fix
  (`pip install "drawing-analyzer[gui]"`). It raises `ImportError`, not
  `SystemExit`, because the frozen build's `--selfcheck` catches `Exception` and
  `SystemExit` would sail past it and report success.

- **An exception in a Tk callback looked like the click did nothing.** Tk's
  default handler writes a traceback to `sys.stderr`, which is `None` in a
  windowed build. `report_callback_exception` is now wired to record the failure
  in the diagnostics trace, put a line in the activity log, and tell the user —
  while staying non-fatal, exactly as Tk's own handler is.

- **The atomic-publish retry retried three times inside the same lock.** The
  export's final rename retried on `OSError` with no wait, so the three attempts
  for the "an antivirus or indexer handle cleared" case all landed inside the same
  hold; the retry only ever helped the other branch (a sibling export won the
  name), which re-derives a name and needs no wait. A short backoff now separates
  the attempts, sized for a filesystem lock rather than an API rate limit.

- **A deep export folder could not be written on Windows.** An artifact name may
  be 120 characters and the operator picks the parent, so a real path
  (`…\OneDrive - <Company>\Projects\2026\<job>\Fire Protection\QC Reviews\`
  plus the export folder, `sheet_text\` and the file name) passes 260 characters
  and the write is refused unless the machine has `LongPathsEnabled` — off by
  default on many images, and not something a desktop app can require. Every
  export write and the publish rename now go through the `\\?\` form; the path
  handed back to the caller and shown in the GUI stays plain. Identity function
  on POSIX.

- **Two artifact allocators deduped case-sensitively onto case-insensitive
  filesystems.** `M-101` and `m-101` are one file on Windows and macOS, so the
  second sheet's text or evidence directory silently overwrote the first. All
  three name allocators and the evidence-directory reserver now key on
  `casefold()` while still writing the original case.

- **A run that analyzed nothing left its work directory behind forever.** The
  zero-sheet early return skipped cleanup, and the lazily created
  `drawing_qc_*` directories had no owner at all — evidence crops accumulated in
  `%TEMP%` run after run. They are now age-pruned (24h, `0` disables), which the
  end-of-run alternative cannot be: `extract_drawing_context` returns *before*
  the caller exports, and the export copies evidence out.

- **The weekly dependency audit only ran when somebody happened to commit.** The
  pip-audit gate fired on push and pull request only, so a CVE disclosed against
  an already-pinned dependency went unnoticed for as long as the repository was
  quiet. CI now also runs on a weekly schedule, and `.github/dependabot.yml`
  opens grouped weekly updates for both the SHA-pinned actions and
  `requirements-release.lock`.

- **The shipped installer was the one build that ignored the dependency lock.**
  CI builds the wheel and runs its install smoke under
  `requirements-release.lock`, but the release job installed the app unconstrained
  — so the binary users run could bundle versions no gate had seen, while
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` carried a "Dependency lock used"
  checkbox saying otherwise. The installer build is now constrained by the lock.

- **Inno Setup — the one tool whose output *is* the shipped artifact — had no
  version recorded.** Two obvious fixes were both wrong, and CI said so:
  a pinned `choco install innosetup --version=6.2.2` fails outright, because the
  `windows-latest` image already ships Inno Setup (6.7.1 as of 2026-09) and
  Chocolatey refuses to downgrade (`0/1 packages`); and a floor comparison then
  failed on a *perfectly good* compiler, because `ISCC.exe` does not stamp its
  own version — its `ProductVersion` resource reads `0.0.0.0`. What ships is the
  version those attempts were groping for: the compiler comes from the runner
  image and is never downloaded (a build that fetches no compiler cannot be
  served a bad package — no feed, no checksum to trust), the compatibility
  contract is the `Inno Setup 6\ISCC.exe` directory that `installer.iss` targets,
  and the exact version is **recorded** — read from the file resources or the
  install registry, printed, written to the build summary, and given a row in
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`. Reading it is reporting, so it can never
  fail the job: an unreadable version logs as `unknown`. The pinned install
  survives only as the fallback for an image that stops shipping one, and the
  path is resolved once and handed to the compile step so no second hardcoded
  copy can bypass it.

- **Five documentation claims a skeptical reader could disprove.** Each was
  checked against the code or the wire and corrected: the CI smoke test proves the
  profile *mechanism*, not that packaged profiles ship (none do, by design);
  "written even for a failed run" holds for a run that analyzed nothing but not
  for one that crashed (there is no context to export); the update check contacts
  `release-assets.githubusercontent.com` as well as `github.com`, so "nothing
  else" named two hosts out of three; `verify.py` documented an
  `evidence/<finding_id>.png` layout that has been
  `evidence/<QC-###>/leg-NN__<sheet>_pN.png` since per-leg crops arrived; and the
  updater's SHA-256 ships in the same release as the installer, so it protects
  the transfer, not the publisher — the README, the in-app help and the Windows
  acceptance script now say so rather than implying tamper-proofing.

- **The NFPA 13 example did not say which edition it was written against.**
  `docs/examples/fire_protection.md` cites 2022 section numbers; the current
  edition is 2025 and NFPA 13 renumbers between editions (the 2019 reorganization
  is why one of its own checks exists). The title and a prominent note now state
  the edition and that the citations have **not** been re-verified against 2025.
  No section number was changed — renumbering on unverified numbers is the exact
  error the checklist exists to catch.

- **A real finding that began "No…" was thrown away as boilerplate.** The prose
  harvest's section-filler filter was anchored only at the *start* of an item, so
  "None of the sprinkler heads under the duct have clearance shown" was discarded
  exactly as if it read "None noted." — and an absence finding naturally opens
  with No/None/Nothing. All five realistic phrasings tested were being dropped.
  A separate 20-character floor discarded terse real findings ("Drain is
  undersized" is 19). Neither drop was counted: the reconcile builds its expected
  set from the items that already *survived* the filter, so `missing` read 0 and
  the harvest reported `complete` over a genuine loss — which is what let this go
  unnoticed. The filter is now anchored at both ends, the floor is 8, and a
  `filtered` count records what the filter took (observational only: filler is
  not a lost finding, so it does not make a clean run incomplete).

- **The review-plan item cap deleted whole disciplines, in alphabetical order.**
  Plans sort by discipline slug and the trim ate the last plan's tail until that
  plan was gone. Measured with five disciplines of 20 items against the 60-item
  cap: **`mechanical` and `plumbing` were removed outright** while
  `architectural`, `electrical` and `fire protection` kept all 20. On a set whose
  mechanical and fire-protection sheets are the point of the review, that deletes
  the checklist that mattered. The trim now takes from the longest plan each
  round, so the same input leaves 12 items on every discipline.

- **One malformed field in a model reply failed a whole stage — or bought web
  searches.** Both the identity and review-plan sanitizers are documented as
  never raising, and the pipeline treats any exception as a stage failure, so a
  dict where a list belonged took the stage from COMPLETE to FAILED via
  `TypeError: unhashable type: 'slice'`. A **string** was worse, because it is
  iterable and passed silently, consumed one character at a time:
  `"disciplines": "mechanical"` became `['a','c','e','h','i','l','m','n']`, and
  `"refs": "NFPA 13 2016 §8.17"` reached the citation check as the refs
  `('N', 'F', 'P')` — three live web searches for single letters, every run. A
  shared coercion now guards every such site: a string becomes the single value
  it plainly means, and anything else non-list becomes empty.

- **A sheet id written with a Unicode dash never matched its plain twin.**
  Cross-sheet handle matching was a bare `.strip().upper()`, so `M-101` written
  with a non-breaking hyphen, an en dash, a U+2010 hyphen, or fullwidth digits —
  all of which model replies and PDF text layers produce freely — missed. The leg
  was dropped, and a cross-sheet finding needs two grounded sheets, so the whole
  finding went with it. Handles now fold through the same helper the sheet-id
  grammar and every deterministic auditor already use — specifically
  `normalize_sheet_id`, the declared canonical form that `detect_sheet_id` itself
  returns, so cross-QC no longer has a normalization of its own (it also trims edge
  punctuation, so a handle written `"M-101."` resolves). Three other places
  compared a handle by hand and are folded the same way: the critique's leg targets
  (they feed the merge signature, so a disagreement would have one sheet id meaning
  two things inside one run), and both claim-dedup keys — where a Unicode dash in
  one of the two self-consistency transcriptions inflated the arithmetic tally.
  Worst of the four was the arithmetic auditor's geometry lookup, whose map is
  keyed by `detect_sheet_id` and therefore already canonical: an uncanonical lookup
  found **nothing at all**, so the claim resolved to no sheet.
  `cross_qc._CROSS_QC_CACHE_CONTRACT` 2 → 3, because this is host-side binding no
  cache key covers yet it changes which legs validate.

- **Lowercase drawing prose was read as an adopted code.** The international
  code-designation pattern ran case-insensitively, so ordinary notes matched: 6 of
  9 realistic lines produced a false adopted-code window, including "field verify
  **is 1000** mm clearance to the deflector" (read as Indian Standard 1000) and
  "the layout **is as 2019** drawings showed" (Australian Standard 2019). Each
  false window spends the bounded identity corpus a real edition mention needed,
  and invites a fabricated adopted-code entry. Now case-sensitive — 0 false
  windows, with all 13 genuine designations still matching (`Eurocode` keeps its
  own case-insensitive form, since it is conventionally written mixed-case).

- **A quote written `2½"` could not match a sheet reading `2-1/2"`.** Unicode
  normalization expands `½` to `1⁄2` with **no** separating space, so `2½"`
  became `21⁄2"` — twenty-one halves. On a pipe size that is the difference
  between a 2.5 inch drain and a 21 inch one. Vulgar fractions are now rewritten
  before normalization, and the fraction slash, division slash and multiplication
  sign fold to ASCII so `1⁄2"` and `300 × 200` match their typed equivalents.

- **A NUL byte cost a whole report block.** The report's inline renderer stashes
  code spans behind `\x00`-delimited placeholders, so a NUL in the digest text
  forged one and the restore step raised `IndexError`. NUL is stripped on entry —
  making the scheme unforgeable rather than merely guarded — and the restore is
  bounds-checked as well.

- **Spec documents from Windows tools decoded wrong, and their tables tripled.** A
  UTF-8 BOM (what Notepad writes) left a stray character on the first line so
  `SECTION 21 13 13` could never match a section header, and a UTF-16 file came
  back as mojibake studded with NUL bytes — one source of the crash above. Reading
  now honours the BOM and sniffs BOM-less UTF-16 by NUL density (a density test, so
  one stray NUL in a UTF-8 file does not flip the decode). Separately, a merged
  table cell was emitted once per column it spanned, so a 3-column merged heading
  appeared three times; and section **headers and footers** were not read at all,
  though a spec's section number frequently lives only in the running head.

- **The diagnostics redaction never fired on the commonest secret name.** A word
  boundary cannot match inside `ANTHROPIC_API_KEY`, because the character before
  `API` is `_` — itself a word character. The rule only *looked* effective because
  a separate pattern catches real `sk-ant-…` values; a credential of any other
  shape was written to the log in full. Underscore-joined prefixes are now matched
  and preserved, so the line still names which variable was redacted, and a token
  *count* (`input_tokens=1234`) is still left alone.

- **Invisible characters are no longer written as literals in the source.** Five
  zero-width and soft-hyphen code points sat as literal characters in the
  anchoring and sheet-id modules — invisible in every editor and diff, so a
  maintainer cannot see them and an ordinary edit can delete or duplicate one
  silently. They are now `\uXXXX` escapes, with a test that fails if a literal
  reappears.

- **A QC bookmark or index row could land nowhere near its mark.** A `/XYZ`
  destination is expressed in default user space, but the writer handed it a
  point in PyMuPDF's *annotation* space, which drops the CropBox origin and the
  MediaBox origin. Measured across rotation × CropBox × MediaBox-origin (24
  cases): the index and overflow links were wrong in **12**, and the bookmark
  outline in **22** — every rotated page, with errors reaching ~550 pt, i.e.
  off-sheet. Architectural sheets are routinely rotated, so the outline that
  makes a marked-up set navigable was wrong on most of a real set. The two
  PyMuPDF entry points apply *different* internal transforms, so each is now
  inverted separately, composed from PyMuPDF's own published matrices rather
  than a measured offset. `_derotate_point` is unchanged — it is correct for the
  annotation and leader-line sites it was written for.

- **A re-reviewed set fed its own prior QC callouts back to the model.**
  `page.get_text()` includes annotation text, so on a second pass each sheet's
  previous markups arrived as *sheet text* — the analyzer reading its own output
  as if the engineer had drawn it. The same contamination reached
  `full_sheet_text`, which host-side grounding treats as source evidence, and
  the word count, which decides `is_raster`: a scanned sheet carrying nothing
  but a prior callout was classified vector and rendered at the cheaper target.
  Extraction now reads the page's own content only. It is also ~1.6× faster on a
  dense sheet, since one display list serves both text and word extraction.
  `render._RENDER_IDENTITY_SCHEME` v3 → v4, because the annotation *bytes* did
  not move and an affected page would otherwise hit the cache and be served a
  digest built from contaminated text without re-extracting it.

- **A swapped digit still anchored onto the sheet's real text.** Fuzzy anchoring
  scores bag-of-token overlap, which is blind to the one substitution that
  matters most on a drawing. On a sheet reading `PROVIDE 6 INCH DRAIN AT COLUMN
  LINE 4`, *every* one-number substitution tried — `4`, `12`, `2-1/2`, and a
  changed column line — cleared the 0.85 floor at 6/7 = 0.857 and was clouded
  onto the real text, while a wholly invented sentence correctly went
  `UNANCHORED`. So the hallucination signal was blind exactly where a wrong
  number is least cosmetic: a finding claiming a 4-inch drain was clouded onto
  text specifying 6. Fixed by adding a veto — each measurement must sit at its
  own position in the matched span, within a drift budget derived from the
  overlap floor itself, with each span position consumed once. The 0.85
  threshold is untouched and a test now asserts that, so a future attempt to fix
  this by moving the floor fails loudly instead. Legitimate transcription
  variance — an extra word on the sheet, an abbreviation, a paraphrase, a
  spelling variant, digit-free prose — still anchors. The veto is applied to
  **every** window that clears the floor before they are ranked, not only to the
  best-scoring ones: a sheet carrying a wrong-number copy that outscores a correct
  one (0.95 against 0.90, the correct copy having two OCR errors) would otherwise
  have the good match discarded unseen and the finding reported as a
  hallucination.

- **FreeText truncation was written and then overwritten.** Three sites handed
  `add_freetext_annot` a truncated string and then called `set_info(content=…)`
  with the full one. For a plain FreeText annot `/Contents` *is* the displayed
  text, so the truncation was undone: 220 characters written, 469 restored.

- **Index text overflowed its column, and typography was mangled.** The findings
  column is 238 pt wide and the row text was capped by *character count*: at
  8 pt, realistic uppercase drawing text measured 248–285 pt. Lowercase prose
  fits, which is why it survived — sheets are lettered uppercase, the wider
  case. Separately, `insert_text` draws with the Base-14 fonts and silently
  renders anything outside Latin-1 as a **middle dot**, so `3″ drain` became
  `3· drain`: a mangled dimension in a fire-sprinkler index still reads as a
  number. Cells are now folded to Base-14-safe ASCII and fitted by measuring
  with the same metrics `insert_text` draws with.

- **A PNG or EPUB renamed `.pdf` was accepted as a drawing set.** PyMuPDF opens
  images, XPS, EPUB and CBZ, and a genuine one of those passed inventory and was
  pushed through a pipeline that assumes a PDF throughout. A *text* file renamed
  `.pdf` was already rejected on open, which is why the gap looked covered. The
  rejection names the detected format, because that is what makes it actionable.

- **A graphics-only finding was stamped with the hallucination signal.**
  `[QUOTE NOT FOUND]` means the quote should have been findable and was not.
  Every rect-less finding got it, so a finding reported off the drawing itself,
  with nothing to quote, was indistinguishable from a fabricated quote that
  matched nothing — opposite messages to a reviewer. The honest label already
  existed but was unreachable, because the evidence tag was suppressed on
  exactly the branch whose prefix was `[QUOTE NOT FOUND]`.

- **An index row could point at a page with no mark on it.** A callout that
  overflows to the *AI Review Notes* page has no mark on its sheet, yet its
  index row targeted the sheet — while the bookmark outline and the receipt both
  correctly named the notes page. The index is now built last, so its rows link
  to the page each mark actually landed on. The notes page's own back-link to its
  source sheet therefore resolves that sheet's *current* index and lets the front
  insertion shift the link — `insert_link` bakes the destination as a reference to
  the page object, so pre-applying the offset pointed every back-link at the wrong
  sheet.

- **A generated index page could inherit the drawing's CropBox.** `/CropBox` is
  an inheritable page-tree attribute, and in a set whose `/Pages` node carries
  one a new 612×792 page came back with a **512×712** visible area — clipped on
  the right and shifted vertically, against column widths computed for the full
  width. Every generated page now pins its CropBox to its own MediaBox.

- **The occupancy mask could not see a pipe.** Callout placement checked the
  fraction of dark *pixels* in a 0.12-scale render, where a 0.5 pt pipe line
  antialiases to ~223 — lighter than the 210 ink threshold. A single sprinkler
  main across a band scored 0.0000, the band was called clear, and the callout
  was stamped over the piping. Raising the scale does not fix it: with a
  pixel-fraction metric the verdict is *non-monotonic* in scale, and one 1 pt
  line measured clear at 0.12 and 0.25, occupied at 0.5, and clear again at 1.0.
  Sampling is now at 1:1, where a hairline really is dark, with a min-filter over
  cells measured in points — correct on all eleven contents tested, where the
  shipped sampler was wrong on five, at ~1 ms per page.

- **Callouts overflowed off sheets with room to spare.** A clear band had to be a
  y-range free of words at *any* x, which a real drawing almost never offers: a
  right-hand title block spans nearly the full sheet height. On a 1728×1188 sheet
  with a title block at y 60–1050, exactly **one** band was found and the whole
  1448×990 pt clear area beside it was unusable. Bands are now also computed per
  vertical column, from only the words that intersect that column. Separately,
  the minimum-height gate was applied to the raw gap with the breathing pad taken
  off afterwards, so a 58 pt gap returned a 50 pt band that could never hold a
  54 pt callout.

- **One cross-sheet hyperlink defeated per-page caching for the whole set.** A
  GOTO link annot references its destination *page*, whose `/Parent` was not
  stripped the way the hashed page's own is, so the dependency walk reached the
  page-tree root, `/Kids`, and every sibling. Editing one sheet therefore
  re-keyed every sheet — on a set carrying the internal navigation links an
  issued PDF normally has, the per-page cache did nothing. Any other
  `/Type /Page` object reached transitively is now an opaque leaf.

- **A question asked after "New chat" could 400 forever.** The report's Ask-AI
  turn loop committed the model's reply into `history` with no check that the
  thread it belonged to still existed — and New chat (and Load) *reassign*
  `history`, so a turn still in flight wrote its assistant turn into the brand
  new conversation. The API rejects a thread that opens on an assistant turn;
  `dropUnansweredTail` only trims a **trailing** unanswered exchange, so a
  reload never healed it; and the transcript was saved to `localStorage`, so
  the damage outlived the session. Every later question failed until another
  New chat. The generation check now guards the commit itself — before the
  assistant turn and again after tools, which run asynchronously and can
  outlive the thread on their own.

- **Stop stopped one request, not the turn.** The `AbortController` is built
  fresh inside every `streamOnce` call, so aborting the in-flight fetch ended
  one round and the loop opened the next with a signal that had never been
  aborted — a server `pause_turn` resume, or the request that follows a tool
  round, sailed straight past it. A per-turn latch now ends the turn, checked
  in two places: before the tools run (so a stopped turn does no work) and
  after they finish (the reader can press Stop while a tool is mid-flight).
  What already arrived is still committed — it was received and billed — and a
  tool that did run still gets its `tool_result`, because an unanswered
  `tool_use` would 400 the next question. The commit tests what will actually
  be stored, not what arrived: a reply that is a bare `tool_use` with no
  lead-in text is an ordinary shape, and stripping it empty would otherwise
  have committed an empty assistant message the API rejects.

- **A tool call the turn never answered poisoned the thread.** The assistant
  turn is committed before the stop reason is examined, so a turn that ended
  mid-tool-call — `max_tokens`, a refusal, a context-window stop, Stop — left
  `assistant(tool_use)` with nothing to answer it. `dropUnansweredTail` repairs
  that on **reload**; the live thread stayed broken and every question until
  then failed. A `tool_use` block that nothing will answer is now dropped
  before the turn is committed. Dropping beats synthesising an `is_error`
  result: the call never ran, and inventing an outcome would put a fabricated
  tool result into the transcript the model reads back. The turn's visible text
  is untouched.

- **A stopped turn annotated the previous answer.** When a turn was aborted
  before committing anything, the catch popped its entries and *then* wrote the
  "Stopped." note — by which point the end of `displays` was the **previous**
  turn's answer. Invisible live (the note draws on the current bubble) and
  wrong on reload, where a perfectly complete answer carried someone else's
  interruption. The note is now DOM-only when the turn owns no entry.

- **The chat widget 400d on any non-default model.** `DRAWING_ANALYZER_CHAT_MODEL`
  pointed at Haiku 4.5 (or an unregistered id) sent `thinking: {type: "adaptive"}`
  to a model that does not accept it — while the capability registry already
  knew. Two independent reasons, in fact: it also hardcoded the
  `web_search_20260209` tool, and Haiku 4.5 takes only the older basic
  `web_search_20250305` variant. Both are now resolved host-side from the
  registry and omitted by the browser, the same way `webFetch` already was, and
  the footer's capability line names what the request actually carries instead
  of a fixed "web search · thinking".

- **A `file://` report's stored key is readable by another local page in the
  same tab.** Measured, not assumed: in headless Chromium a second local HTML
  file navigated to in the same tab read the key back verbatim, while a page in
  a *new* tab read `null`. Local files do not get distinct origins, so
  `sessionStorage` is not isolated per file. The widget's footer and
  `SECURITY.md` now say so, with the scope (one tab) and the remedies (Forget
  key, close the tab, or serve the report over `http(s)://`).

- **A citation run that searched nothing reported an unknown total.**
  `billable_tool_uses` is truthy on its **keys**, so `{"web_search": 0}` — what
  a citation stage writes when every reference came warm from the verdict cache
  — read as billable usage. Under a model the pricing table cannot price, that
  turned the whole run's cost into "unknown" when nothing unpriceable had
  happened. Fixed at both ends, because either alone lets the other bring it
  back: the predicate counts **values**, and the writer never stores a
  zero-count entry.

- **The citation stage never recorded the cache tokens it was billed for.** It
  attaches a cache breakpoint to its tool schemas, so on every request after the
  first most of the input is billed as a cache **read** while `input_tokens`
  reports only the remainder. The stage read only the latter, so a multi-
  reference run looked near-free — and, since cache tokens are what
  `is_billable_but_unpriced` keys on, a cache-heavy record under an unpriceable
  model passed as "no usage" entirely. The prompt-cache split now rides
  `_CheckOutcome` through to the ledger, summed across `pause_turn` resumes and
  carried on the error and still-paused exits too, since those attempts were
  billed as well.

- **The investigation evidence budget is spent per request, not per turn.** The
  model may put several `tool_use` blocks in one assistant turn, and each is a
  real crop — an image rendered at 300 DPI, saved to the finding's evidence
  directory and sent back. Charging the *turn* let one turn buy three or more of
  them, so a 6-request budget bought 18+, per finding, across a task budget that
  scales to 40 findings. The prompt has always promised "up to N evidence
  request(s)"; the accounting now matches it, and the cap is enforced **before**
  execution rather than counted after — with five of six spent, a three-block
  turn would otherwise still render and send all three crops and only then
  notice it had reached eight. Excess blocks are refused unexecuted; every
  `tool_use` id is still answered in one user turn, because the API requires it,
  and a refusal costs nothing so it does not advance the counter. No prompt
  string moved, but `round_budget` is a cache-key input whose **meaning**
  changed, so `INVESTIGATE_PROMPT_VERSION` is bumped to `investigate-v3` —
  investigation verdicts only.

- **`find_text` could send an investigation to the wrong word.** The haystack
  was uppercased while the covered-word offsets walked the original-case list,
  so any glyph whose uppercase is longer shifted every later offset — and PDF
  extraction routinely yields ligatures (`ﬁ`→`FI`, `ﬄ`→`FFL`) and `ß`→`SS`. One
  character of drift is absorbed by the overlap test's slack; two is not. The
  rect then either swallowed the following word or, when the matched word was
  shorter than the drift, **landed on a different word entirely** — and short
  tokens (sheet ids, tags, dimensions) are exactly what an investigation
  searches for. The loop saves a crop of that rect as the finding's evidence, so
  the failure was silent and looked authoritative.

- **The refusal fallback is a model capability, not a hard-coded id.** The gate
  read `model != MODEL_OPUS_5`, so pointing `DRAWING_ANALYZER_MODEL` at any
  other id — a newer Opus, a future default — silently dropped the protection
  with nothing to notice: nothing raised, nothing logged, and a refusal simply
  became an unhandled `stop_reason`. It is now
  `ModelCapabilities.supports_refusal_fallback`, declared beside each model's
  other request-shape decisions, so registering a model forces the question to
  be answered. Behaviour is unchanged today — Opus 5 remains the only declarer,
  since Opus 4.8 is the fallback *target*, not a source.

- **A debug log could destroy itself.** The diagnostics ring is 2 MB × 5, and
  one sheet's base64 request body measures ~3 MB — so with SDK wire capture on,
  a *single* sheet rotated the ring and six flushed every backup. The trace was
  destroyed by its own payload, precisely when it was being collected to explain
  a failure. Long base64 runs are now elided with their size, and a record is
  capped as a backstop for something huge that is not base64. Ten sheets of
  debug traffic went from ~30 MB to **23 KB** with the request shape — model,
  params, message structure, headers, status — fully intact. Elision runs before
  redaction, so the mandatory secret boundary now works over a bounded string
  rather than megabytes of image data.

- **The cost dialog now names how long the run will actually wait**, derived
  from the engine's own bound rather than written beside it, so an operator who
  sets `DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS` is quoted their own number. A
  test asserts no user-facing string promises a longer wait than the engine
  allows — lower the bound without moving the prose and it fails.

### Added

- **`DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS`** (default `24`, `0` disables) —
  how long a leftover `drawing_qc_*` work directory may sit in the system temp
  directory before a later run reaps it. These hold the high-DPI evidence crops
  and were never cleaned up.

- **`scripts/check_browser_suite.py`** — fails a browser-suite run that executed
  nothing, from the JUnit report pytest writes. Used by the CI job and by
  `run_acceptance.py`'s own browser gate, so the two cannot disagree about what
  "passed" means.

- **Two tag-gated release-gate jobs** (`gates`, `gates-windows`) that `publish`
  now requires, so a release cannot be cut from a commit whose full automated
  gate set has not passed on that exact commit. CI also runs on `v*` tags.

- **Public helpers on the library surface:** `export.long_path` (the Windows
  `\\?\` form; an identity function elsewhere), `run_journal.redact_for_display`
  (the journal's secret/path boundary without line-flattening or truncation, for
  artifacts that render a block), and `models.name_is_taken` / `models.record_name`
  (the shared case-insensitive name-collision pair).

### Changed

- **Closing the GUI while a run is in flight now asks for confirmation** and
  names which job it would discard. An idle window still closes immediately.

- **The Inno Setup compiler used for the Windows installer is recorded** — its
  exact version is printed, written to the build summary, and has a row in
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`. It is taken from the runner image and
  never downloaded.

### Not done, and why

- **Explicit request timeouts (review item N19) were dropped on evidence.** The
  finding was that `client.py` sets no timeout. It does not — but the SDK is not
  unbounded: an `Anthropic()` client carries `Timeout(connect=5, read=600,
  write=600, pool=600)` with `max_retries=2`, and a non-streaming `create`
  derives a further cap from `max_tokens`. There is no hang to fix. Adding
  `with_options(timeout=…)` would have restated a default as though it were a
  policy, which is the kind of change the standing prohibitions exist to keep
  out. Raised here rather than shipped half-done.

- **A stalled batch was paid for twice.** The largest real-dollar defect in the
  review. Per-sheet results are filled **only** from a terminal `results()`
  read, so on a batch that never reached a terminal state — stalled, detached,
  or unpollable — *every* slot still read "unresolved", including the sheets the
  batch had completed and billed. The recovery list was therefore all of them.
  A real 40-sheet run detached at 3.5 h with 11 sheets already produced,
  resubmitted all 40, watched the resubmission detach too, and returned `0/40`
  with "not collected" — after paying for 12 digests.

  Cancellation on the Batches API is asynchronous: a canceled batch still
  transitions to `ended`, and the items it finished stay readable. Every site
  that abandons a batch now **harvests** it between the cancel and the recovery
  list, and resubmits only what is genuinely missing. There are **three** such
  sites, not one: the stalled primary, a stalled resubmission round (which
  re-billed once per round), and a stalled follow-up batch — that last handing
  its finished sheets to the direct-call rescue to be digested again at **full
  real-time rate**, the most expensive of the three. One shared helper serves
  all three rather than three copies of the rule.

  Three things about it are deliberate, because getting this wrong the other way
  is worse than the bug it fixes:

  - **Its time is additional, never deducted.** The harvest competes with the
    rescue for the same seconds precisely on the `detached` path, where the
    budget is spent by definition and the completed-item count is highest. The
    first cut charged it to the collection budget and turned a 3/3 direct rescue
    into 0/3 — trading re-billing for lost sheets. Each caller now adds what the
    harvest spent back to its own start mark, so the poll and the recovery keep
    the exact budgets they had before. The price is that a collect which
    harvests may run up to five minutes past its nominal bound per abandoned
    batch.
  - **A batch that will not settle changes nothing.** An unreadable batch, a
    failed `results()` read, or any exception falls through to resubmitting
    everything, exactly as before.
  - **Successes only, and counted once.** An item that came back `succeeded`
    but empty does not resolve its sheet — that sheet still needs recovery —
    yet the attempt *was* charged, so its billed usage record is carried
    forward onto whatever digest finally lands rather than dropped because the
    text was unusable. A sheet the batch answered is also excluded from the
    abandonment marker: `billable=False` means "submitted, no response", so
    marking one anyway wrote a second record at the same attempt number and
    one request read as two attempts (an empty primary plus one good retry
    showed three records for two submissions), corrupting both the attempt
    sequence and the per-attempt image-token estimate. A sheet the batch never
    answered keeps its marker.

- **The run now waits as long as it says it does.** The batch collection bound
  was hardcoded at **4 hours** while the cost dialog, the GUI and the help
  content all promised runs that "can run overnight (8+ hours)". It is now
  **24 hours** — the Batches API's own SLA — so the existing wording is true
  rather than reworded down, and `DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS`
  caps the wall clock for anyone who would rather. The override is resolved per
  call rather than frozen as a keyword default at import, which is what a GUI
  run needs. Raising the bound is safe **only** because of the harvest above:
  without it, a longer wait is simply a longer window in which finished sheets
  get billed twice.

- **"Stuck" and "slower than my bound" are no longer the same log line.**
  Hitting the elapsed bound now records whether the batch was still completing
  items or had completed none since the first poll. Both are still cancelled,
  harvested and recovered identically — the cancel is precisely what makes a
  detached batch's finished sheets readable, so "leave the healthy one running"
  would strand every sheet it had already been paid for — but the distinction
  reaches the diagnostics log, the per-sheet error and the usage ledger's
  terminal status, which is the first thing anyone tuning the bound needs to
  know.

---

## [1.4.0] - 2026-09-10

### Fixed

- **The deterministic auditors stop crying wolf.** Their findings ink as
  `DETERMINISTIC` — *"an exact text check of the drawings, not an AI judgment"* —
  which is why a false positive here costs more than one from the model. Two of
  these put a wrong number behind that label; the rest buried real findings under
  noise a reviewer learns to skip.

  - **A percent operand promoted a claim to ground truth.** `1500 SF + 30% =
    1950 SF` is not "the sum of 1500 and 30", but because the bare `30` appears
    literally in the quote, the claim *cleared* the independent-validation gate
    (§17.5) and inked a HIGH-severity *"the product of 1500, 30 is 45000"* as
    host-computed. The `%` was the thing that made it pass. Percent operands are
    now refused, so the claim is reported as **unchecked** rather than as a
    mismatch. Same rule for a term that is not one value: `12,5` is not 12 and
    `12'-6"` is twelve feet six. `12,5` was the sharpest — `_THOUSANDS_RE`
    deliberately declines to strip that comma so the value is "left alone rather
    than silently mangled", and `_PLAIN_NUMBER_RE` mangled it anyway one line
    later. A separator only disqualifies when it is **tight** — no whitespace on
    either side — so an ordinary operand list keeps every term (`0.5, 1.5,
    TOTAL 2.0`, `10 , 20 , 30`) while the compact malformed forms (`12,5`,
    `10,20`) stay rejected. A looser rule cost no wrong answers but downgraded
    such a list to `MODEL_TRANSCRIBED` / `UNCERTAIN`, withholding a deterministic
    result and paying for a crop check to re-learn what the quote already said.
    The quote scanner applies the identical head/tail rules **at the scan site**,
    because only it can see what bound a number, so the two can never disagree
    about what a number is.

  - **One bad claim lost the whole run's arithmetic.** The orchestrator wrapped
    the entire claim batch in a single `try`, so any per-claim failure aborted the
    loop mid-way and the caller discarded the result — every finding already
    produced, plus all four `arithmetic_*` stat keys. With the keys *absent*, the
    summary line then read `arith=0/0` through `stats.get(..., 0)`: the failure
    rendered as "nothing to check", indistinguishable from a set with no claims.
    Each claim now has its own `try` with a tally rollback, so
    `mismatched == len(findings)` still holds when a claim fails after its
    counters moved. And it did: `_fmt` expanded integrals with
    `quantize(Decimal(1))`, which raises above the decimal context's 28 digits
    from ordinary string terms — inside the `Finding(...)` constructor expression,
    after `mismatched` was incremented.

  - **`PER REV-2` was reported as a stale sheet reference.** REV / DET / DWG /
    TYP / SIM / NTS are among the most common words on a drawing and none was in
    the §17.3 negative corpus, so a revision note came back as *"Reference to
    REV-2 does not match this set's sheet-ID convention; did you mean E-2?"*. On a
    set with a three-letter discipline field they match the learned grammar
    outright and graduate to **medium** *"not present in the provided set"*
    findings. `DWG-4` and `TYP-2` escaped only because their edit distance
    happened to exceed the cutoff — luck, not a rule. Paper sizes are deliberately
    *not* added: `A1`–`A4` are ISO sizes **and** real architectural sheet ids, and
    the corpus never consults the set.

  - **A general note could become the sheet's own id, and redefine the set's
    grammar.** `detect_sheet_id_word` chose purely by distance toward the
    bottom-right, so a code citation or transmittal number placed further into the
    corner than the title block simply won. That is not a cosmetic mis-rank:
    `build_inventory` calls it to *build* the id list, and `learn_grammar` derives
    the convention every downstream auditor adjudicates against from that list.
    A **strict subset** of the negative corpus now vetoes candidates before the
    position score. Only a subset, because the corpus answers "does this token
    point at a sheet in the set?" — safely *no* for things a sheet can still be
    **named**. `SK-1` is a sketch issued as a sheet, and so are `PR-04` and
    `ADD-2`; using the full corpus removed such a sheet's real title-block id from
    the running, and then any un-vetoed id-shaped token on the page (one `A-101`
    in a note, at any position) won by default, so the sheet vanished from the
    inventory under its real name. What remains vetoed is only what a title block
    can never say: a code citation, a drawing annotation, a voltage. And only that
    structural veto — never the learned grammar, which would be circular — so a
    same-shape distractor can still win; closing that needs a two-pass harvest and
    is not attempted here.

  - **Naming drift was manufactured out of alphabetical order.** With no
    frequency winner (every spelling seen once), the auditor fell back to the
    *lexicographically first* member as canonical and reported everything else as
    drift from it. So a canonical NCS `FP-101` was reported as drift from the
    mangled `F-P101`, and `VAV-21` was called a misspelling of `VAV-2-1` — which
    on a real schedule are two different boxes. Without a winner, both spellings
    must now share an *arrangement* (same-kind runs, separators breaking them): a
    separator between two different kinds is formatting, a separator inside a
    digit run regroups the number. An established convention still outranks
    structural doubt, so `A1-2` beside four `A12` is still drift.

  - **`1/2"` and `2"` were the same measurement.** The signature's lookbehind
    excluded `[A-Za-z0-9.-]` but not `/`, so `1/2"` matched at the **denominator**
    and signed as `2in` — byte-identical to a real `2"`. *Provide 1/2" drain* and
    *Provide 2" drain* therefore merged as duplicates: two pipe sizes collapsing
    into one finding, exactly what the critical signature exists to prevent. A
    measurement is now compared by its **value**, so `2 1/2`, `2-1/2` and `2.5`
    are one quantity rather than the meaningless string `21/2`. Feet-inches keeps
    both halves and neither goes negative — the old lookbehind sat one character
    before the *sign*, and the character before the `-` in `12'-6"` is `'`, so
    `[-+]?` swallowed the separator and emitted `-6in`. Fixing that by excluding
    `-` outright would have been worse: it drops the inches half, and then
    `12'-6"` and `12'-8"` both sign as `{12ft}` and can merge. Plural units fold
    (`6 amps` == `6 amp`, which used to *split* one issue into two findings);
    `psig` deliberately does not fold into `psi`, because gauge and absolute are
    different measurements.

  - **The split-id scan was quadratic.** The reconstructed id was bounded by the
    grammar, but the *scan* was not — it kept concatenating and re-matching long
    after the text was too long to ever match. On a per-glyph CAD text layer,
    where no single glyph is an id and so nothing stops the run, 2,000 words took
    **10.0 s** and 10,000 extrapolated to **~5.3 minutes** of a "free" zero-API
    battery. Capping on **length, not fragment count** makes it linear with
    byte-identical output: the pathological input *is* a per-glyph layer, where a
    real `M-101` is five fragments, so a fragment cap would have stopped
    reconstructing the very ids the merge exists to find. `detect_sheet_id_word`
    is also memoized per sheet object — fourteen live call sites across twelve
    modules each re-ran the whole scan, and there was no memoization anywhere in
    the package.

- **The ledger no longer launders model text into ground truth.** Four defects in
  one place: the merge that folds a duplicate finding into an existing ledger
  entry. Together they let the model's own arithmetic reach the reviewer wearing
  the host's label.

  - **A `DETERMINISTIC` verdict could end up on text no host ever computed.**
    `_grounding_quality` decides which member's grounded bundle survives a merge,
    and its own docstring at the merge site claimed a deterministic auditor sorts
    first. It never did — the tuple ranked quote length, severity, id and text,
    and the auditor normally holds the *shorter* quote, because it quotes only
    the term it computed over while the model quotes a whole schedule line. So
    the model's "the sum is 560" beat the host's "the sum is 540", and the
    verdict — decided separately from the text, further down the function —
    followed the survivor. `verify._TERMINAL_STATUSES` then skipped the crop
    check and `annotate` inked it as *"Found by an exact text check of the
    drawings, not an AI judgment."* Provenance is now the top-ranked element of
    `_grounding_quality`, and the verdict rides the atomic grounding bundle with
    the text, quote, tile, rect and evidence state it belongs to. The loser's
    quote still lands in `supporting_quotes`; only its *verdict* stops
    travelling to text it did not produce.

  - **Which member survived depended on ingest order.** The severity union ran
    *before* the quality comparison it feeds, raising the survivor's severity to
    the max and erasing the very difference being compared: one order saw ranks
    (3, 2), the reverse saw (3, 3), and the tiebreak fell through to raw text —
    where `"…560…"` sorts above `"…540…"`. Both quality tuples are now computed
    before anything mutates a field they read (I-7).

  - **An unanchored member erased an exact rectangle.** The bundle adopted the
    winner's anchor unconditionally, and the upgrade further down could not
    restore it (it fires only when the *incoming* member is the anchored one).
    A survivor's rect is now kept when it places the new representative's quote.

  - **Pass B rebuilt its complete-link history from the mutated survivor.**
    Post-anchor reconciliation seeded a fresh `{id(entry): [entry]}` map instead
    of consulting the ledger's ingest snapshots, so it folded chains the ingest
    pass had explicitly refused one call earlier. Where the conflicting value
    lived in `text` rather than the quote — every arithmetic or quantity
    conflict — it was destroyed outright: not in the surviving text, not in the
    supporting quotes, only a provenance tag pointing at content that no longer
    existed. Pass B now seeds from `Ledger.member_history`, re-parents a folded
    entry's history onto the survivor, and the ledger's own snapshot is taken at
    the moment a merge is about to mutate an entry rather than eagerly at
    ingest — an eager copy is a permanently *unanchored* twin of a live,
    anchored entry, which would have blocked every geometry-based Pass B fold.

- **Verification erased arithmetic provenance from the finding it verified.**
  All eighteen `Verification(...)` constructions in `verify.py` replace the
  previous verdict wholesale and populate neither `computation_method` nor
  `operand_origin`. The effect on the reviewer was an inversion, not a
  weakening: `annotate._trust_note` reads `operand_origin` first, so *"Computed
  from numbers as read by the AI - re-check the math against the sheet."* became
  the flat *"AI-verified against the drawing."* And the exposure was precisely
  targeted — the arithmetic auditor emits `UNCERTAIN` for model-transcribed
  operands while only `DETERMINISTIC` is terminal in verification, so the
  findings whose provenance matters most are exactly the ones routed through the
  pass that lost it. Both public entry points now snapshot provenance on entry
  and restore it at every exit, including the skip and warm-cache paths.
  `investigate.py` already carried these forward at its three sites and now has
  tests saying so.

- **An entry could claim corroboration and its absence at once.** `confidence`
  is only ever raised by rank, and every non-critique channel carries `""`
  (rank 0), which can never raise a critique's `SINGLETON`. The same merge
  unions a second provenance *family* into `sources` and flips `reproduced` to
  True — so an entry read `reproduced = true` beside `confidence = SINGLETON`,
  i.e. "two channels independently raised it" beside "only one of the two reads
  saw it". `critique.merge_finding_groups` already settles this coherently; the
  ledger implemented only the `reproduced` half of that rule and now implements
  both.

- **A duplicate arriving after numbering silently rewrote a numbered entry.**
  `Ledger.add` merged and returned *before* the `sealed` guard, so the
  orchestration-invariant check was reachable only for a *fresh* finding. A
  post-seal duplicate therefore rewrote text, quote, content id, severity,
  sources, supporting quotes, tile, anchor and evidence state underneath a
  `QC-###` that numbering had already assigned — one that may already be
  exported, inked on a reviewed PDF, and the name of an evidence directory —
  while leaving `post_seal_adds` at 0, so nothing reported the run incomplete. A
  post-seal duplicate is now counted like any post-seal add and **dropped**: the
  run still ships (I-3), the number keeps pointing at the content it was
  assigned to, and the roll-up marks exhaustive QC incomplete.

- **Nothing truncated is accepted, and nothing truncated is cached.** Four
  defects that shared one shape: a reply the model did not finish was read as a
  reply it did finish.

  - **A truncated real-time digest was accepted as complete and cached
    forever.** The path checked only for *empty* text, so a body severed
    mid-sentence passed as a good digest — and was then stored, which served the
    truncation on every later run at zero cost, with nothing in `run.log` to
    show for it. The batch path already retried the empty case; real-time was
    the outlier. It now reads `stop_reason`, retries once at a raised cap
    (`MAX_TOKENS_RETRY_CEILING` moved into `digest.py` so both transports share
    one value rather than two that can drift), and if the reply is *still*
    truncated it marks the sheet failed and refuses the cache write. The partial
    prose still ships (I-3) and `SHEET_DIGESTED` now carries `stop_reason`
    whenever it is not the ordinary `end_turn`. This matters more than it
    sounds: the digest runs adaptive thinking at effort `high`, and thinking
    draws from the same envelope as the answer, so a dense sheet reaches the cap
    in the ordinary case.

  - **The fenced-block scanner was not line-anchored.** It hunted for a bare
    ```` ``` ```` at any offset, so an **inline** triple-backtick span that
    happened to end a line opened a phantom block — and the real ```` ```json ````
    opener then closed it. The findings block came back TRUNCATED with zero
    findings while its entire JSON body leaked into the prose the digest treats
    as sacred (I-2), and that prose was cached. The quieter half of the same
    defect: prose after the inline span was silently cut from `combined_text`.
    Four-backtick and `~~~` fences were not recognised at all, leaking the JSON
    the other way as ABSENT. Openers and closers are now line-anchored, longer
    and tilde fences are read, and a closing fence must match its opener's
    character and length. `scan_structured_blocks` is shared, so set identity,
    the review planner, cross-QC and the prose harvest all get the fix.

  - **A truncated or refused verification verdict read as a garbled one.** Both
    degrade to UNCERTAIN, but they are different failures — one is the model's
    judgment arriving malformed, the other means nothing was judged because the
    envelope was too small — and the note now says which. Neither is cached.

  - **The citation check lost work across `pause_turn` resumes, and threw away
    unfenced verdicts.** The resume rebuilt the conversation as `[user,
    assistant]` from scratch, which is right only for the *first* resume; on the
    second and third it discarded every earlier partial turn, so the model
    resumed from a conversation missing searches it had already run. A verdict
    returned as a bare JSON object with no fence was also discarded, reporting
    the claim UNCHECKED and holding the stage at PARTIAL — a formatting
    preference presented as a failed check. A reply cut off at `max_tokens` now
    says so instead of sharing the wording used when the model simply did not
    answer.

- **A run can no longer report COMPLETE over a sheet it never read.** Six
  status-accounting defects, each of which let an exhaustive run present a
  degraded result as a clean one. They are grouped because they share a failure
  shape: the run's own status was derived from something other than what
  happened.

  - **The digest had no `StageResult`.** It was the one stage with no typed
    outcome, so a failed sheet reached `ctx.errors` and the journal but never
    `roll_up_qc_status` — a run could announce "1/2 sheet(s) analyzed, 1 failed"
    and roll up `COMPLETE` in the same breath, contradicting I-1. It now carries
    one (`expected=True`, honest because the digest runs in every mode and safe
    because the roll-up returns early on a non-exhaustive run). This **replaces**
    the stage's hand-written `STAGE_END` rather than joining it: two `STAGE_END`
    events for one stage make `RunJournal.stage_durations()` pair the START with
    the second and lose the duration. That renames this stage's journal fields
    (`ok`/`failed`/`cached` become the shared `calls`/`items`); the per-sheet
    counts remain available from the `SHEET_DIGESTED` events and run.log's
    Sheets section.

  - **An error-free sheet with an empty digest recorded no error.** `sd.ok` is
    error-free *and* non-empty, so an empty digest is a failed sheet — but only
    the journal said so, leaving `ctx.errors` and every surface built from it
    undercounting the sheets the run never actually read.

  - **The critique silently dropped a sheet it could not obtain.** When the
    spool load and the one-page re-render both returned `None`, `_ordered_inputs`
    skipped the sheet and nothing reconciled critiqued against expected, so the
    stage reported COMPLETE having never read it. The unobtained sheets are now
    folded into the stage's degraded list.

  - **A crashed cross-verifier reported `SKIPPED_VALID`.** `counted == 0` was
    tested before `cross_failed`. An exception leaves its result `None`, so its
    findings never reach `counted`; when only cross-sheet findings were eligible
    (the single-crop pass excludes them by design), the crash was
    indistinguishable from "nothing to verify" and the roll-up accepted it as a
    clean run. Both failure flags are now tested before any count derived from a
    result. An exception is never a valid skip.

  - **The batch transport lost `on_page_error`.** An un-renderable page vanished
    from a batch run with no entry in `ctx.errors`, while the identical
    real-time run recorded it and went PARTIAL — one set reporting two different
    truths depending only on transport.

  - **`prose_harvest` could sit at `NOT_REQUESTED` while expected.** Its extra
    `and sheets` guard had no `elif expected: SKIPPED_VALID` arm, which every
    sibling stage has. An expected stage left `NOT_REQUESTED` fails the roll-up's
    `all_ok` without setting `any_failed`, so the run landed on PARTIAL or FAILED
    for a reason no stage row explained.

- **Numeric claims are pooled in deterministic order (I-7).** `claims` was
  extended as futures completed — both the cache-hit loop and `_ingest_miss`
  append as results land — while only `findings` was sorted. That order flowed
  through `audit_arithmetic` into ledger insertion order and out to
  `findings.json` / `findings.csv` and their sha256 in `run_manifest.json`, so
  two runs over byte-identical inputs published different manifests. QC numbering
  and the reviewed PDFs were already stable; the exports and their hashes were
  not. Sorting goes through the new `pipeline.claim_sort_key`, which keys
  `terms`/`expected` via `repr` because they are deliberately raw JSON — an int
  can sit beside `"2 1/2"`, and comparing those directly raises `TypeError`.

- **Stages that made no call no longer report phantom real-time calls.** The
  guard `if X.api_calls or not X.cache_hits` fired exactly in the no-work case it
  was meant to exclude (zero calls **and** zero hits), appending a zero-token
  REAL_TIME `UsageRecord`. A verification that verified nothing showed two calls,
  and the GUI printed `harvest: 1 call(s) · in 0 / out 0 tok` for a stage that
  never reached the API. The ledger describes work that happened, not stages that
  were configured. Costs and derived totals are unmoved — the phantom records
  carried no tokens — but per-family call counts in run.log, `run_manifest.json`
  and the GUI were wrong.

- **A lost open race could silently empty an intact digest cache.**
  `DigestCache._load` wrapped two different failures in one `except`:

  ```python
  try:
      _prepare_database_path(self._path)      # migrate legacy JSON -> SQLite
      self._connection = _open_database(self._path)
  except Exception:
      self._entries = _read_legacy_json(self._path)
  ```

  When migration **succeeded** and the open then failed, the artifact was no
  longer JSON — it was a database. `_read_legacy_json` parsed database bytes,
  returned `{}` by design, and the instance served an **empty cache** for the
  rest of the run: every sheet re-digested at full vision price against a cache
  sitting intact on disk.

  The failure is transient. `_open_database` finishes in
  `_ensure_database_schema`, which takes `BEGIN IMMEDIATE`, so with several
  instances opening at once somebody loses that write lock. POSIX advisory
  locking usually absorbs it inside `busy_timeout`; Windows share-mode locking
  does not, which is why `test_concurrent_instances_migrate_once_and_do_not_lose_writes`
  failed intermittently on the Windows CI job and never on Linux.

  `_load` now separates the cases: still-JSON means migration failed and the
  legacy read is right; already-a-database means the open lost a race, so it
  retries briefly (`_OPEN_RETRY_DELAYS`, ~0.6 s worst case) and, if the database
  truly will not open, degrades to in-memory for that run — never reporting the
  legacy reading of a SQLite file as a successful load.

  Three deterministic tests replace the coin flip. The concurrency test was a
  poor guard precisely because it passes on Linux whether or not the bug is
  present; the new ones force the sequence (migrate, then fail one open) and
  fail on any platform. They cover the lost race, a genuinely unopenable
  database, and the failed-migration case the fallback was written for.

- **The release benchmark was measuring nothing, and its failures read like app
  regressions (WP-08).** `scripts/benchmark_drawing_analyzer.py --check` asserts
  that a warm run makes zero digest calls and rasterizes nothing, and that
  editing one source re-digests exactly one sheet. Both gates were failing, with
  messages that named the application: "cached run still rasterized", "expected
  exactly 1 digest call, got 0".

  Neither was true. Every scenario reported `digest_api_calls=0`, `tok=0/0`,
  `cost≈$0.0000`, and `corrupt-partial` reported `ok_sheets=0; errors=9` — every
  sheet failing, including the sound ones. The cause was one line in a
  reproduction: `'OfflineClient' object has no attribute 'beta'`. Two production
  changes had landed after the benchmark's fake client was written and it tracked
  neither — `digest.stream_message` issues **every** digest / critique /
  review-plan / synthesis / focus request over `messages.stream` (unconditionally,
  not only above the ~21k cap), and `call_with_refusal_fallback` re-routes every
  Opus-5 real-time call through `client.beta.messages`.

  I-3 did exactly its job: it caught the `AttributeError` per sheet, appended to
  `ctx.errors`, and let the run finish. Correct for a real run, wrong for a
  benchmark — the run then "succeeded" having done no work, and the gate's own
  counters could not tell that from a cache regression.

  `OfflineClient` now mixes in `BetaClientMixin` and answers `messages.stream`
  through `FinalMessageStream`, both imported from `tests/fixtures/fake_anthropic.py`
  rather than reimplemented: a benchmark fake that restates the transport is a
  fake that drifts from it again. `tests/test_benchmark_harness.py` guards it by
  running the real pipeline and asserting work was **done**, not that particular
  attributes exist — production is free to rename those. One test reproduces the
  swallowed-error mode deliberately; another covers `messages.stream` directly,
  since Sonnet-routed stages bypass the beta namespace and an Opus-only scenario
  cannot see that half.

  First real medians from this gate, 8 sheets / 5 repeats, recorded in
  `docs/PERFORMANCE_AND_COST_VALIDATION.md`: cold 3.161 s, **warm 0.030 s with
  zero API calls and zero renders**, one-source-changed 0.417 s with exactly one
  digest call, peak RSS 189.0 MB.

### Changed

- **`digest_cache._SCHEMA_VERSION` 9 → 10 (one-time cache miss).** The critique
  entry stores the **post-merge** findings, and the measurement rule inside
  `critical_signature` changed — so a pre-v10 entry holds a merge the new rule
  would never have produced: a pair the new rule separates is already collapsed
  and unrecoverable, a pair it would now join is stored as two. Same reasoning as
  the v6 and v9 parser rebuilds. Everything in `DigestCache` re-derives on the
  next run.

- **A/B arm records carry an enforced contract version (`RECORD_CONTRACT_VERSION`
  1 → 2).** `critical_signature` is computed at arm-run time and stored inside
  each record, and the comparison re-applies `signatures_compatible` to those
  *stored* dicts rather than recomputing them. So an arm produced before this
  release would be scored under a rule it never ran with, and the resulting
  differences reported as if the arm's model or geometry swap caused them. The
  version was already written into every sidecar and echoed into every comparison
  — and read back by nobody, so the contract its own comment describes
  ("announced rather than assumed") was declarative only. `load_arm_records` now
  refuses a sidecar from a different contract, and a sidecar with no version is
  treated as stale rather than as current. Refusing beats warning because the
  failure is silent: every reader uses `.get(...) or {}` and a one-sided signal
  never blocks a match, so a stale record whose measurements simply vanished
  degrades toward "exact match". Re-run affected arms rather than comparing across
  versions.

- **The user-turn framing is now inside both prompt hashes (I-6).** How a sheet
  is introduced, how an omitted tile is disclosed, the overview label and the
  per-tile label are model-visible strings that sat outside `DIGEST_PROMPT_VERSION`
  *and* `CRITIQUE_PROMPT_VERSION`. Editing any of them changed what was sent
  while every cache key stayed byte-identical, so warm runs replayed reads taken
  under the old wording. They are now module constants gathered in one
  `SHARED_USER_FRAMING_STRINGS` tuple that both hashes splat, so a string added
  to the shared builder reaches both automatically instead of waiting to be
  noticed — the exact drift `CRITIQUE_PROMPT_VERSION`'s own comment records.
  The prompt bytes the model receives are unchanged, verified byte-identical
  before and after; only the hash inputs grew.

- **`digest_cache._SCHEMA_VERSION` 8 → 9 (one-time cache miss).** A stored entry
  holds the *post-parse* product — stripped prose plus parsed findings, never the
  raw response — so entries written under the old scanner cannot be re-derived in
  place and must miss once. Same reasoning as the v6 parser rebuild, which is the
  precedent it follows. Everything in `DigestCache` re-derives on the next run:
  digest, critique, identity, review plan, citation, investigation.

- **Documentation corrected against the code it describes (WP-07).** A
  documentation pass over the claims the review found stale or overstated. Each
  correction below was verified against the current implementation rather than
  taken from the review, and two of the review's own statements turned out to be
  imprecise — recorded here rather than copied forward.

  Three stale code comments:

  - `core/api_config.py` claimed verification "reserves Opus for escalation on
    CRITICAL/HIGH UNVERIFIED findings". `verify.py` resolves exactly one model
    and never escalates; `VERIFICATION_ESCALATION_MODEL` is consumed by
    `investigate.py`, whose trigger is an **anchored UNCERTAIN** verdict at any
    severity inside a per-run budget. `UNVERIFIED` is not one of
    `VERIFICATION_STATUSES` at all, so the comment named a severity gate and a
    status that both do not exist.
  - `pipeline.py` said the critique "re-renders each sheet (the digest images
    are gone by now)". They are not gone: `render_spool` reconstructs them
    byte-for-byte, and the batch path adopts the digest's uploads. A second
    rasterization is now the per-page fallback — an unspooled page, a grid
    mismatch, an unavailable manifest, a failed spool read/write — not the rule.
  - `cost.py` appealed to "the 'slightly high' bias the rest of this module aims
    for". No such module-wide bias exists, and implying one invited every figure
    to be read as a ceiling. The module has two explicitly-labelled bases and
    says which produced a number: the conservative allowance is deliberately
    high, the shape-aware path aims at the real figure. Neither is a guaranteed
    maximum.

  Documentation:

  - **A cold exhaustive run does not rasterize every sheet twice.** The
    performance doc said it did, and budgeting from that overstated cold wall
    time. Replaced with the spool-reuse story and its per-page fallbacks.
  - **Three vision reads is not three full-price image reads.** The two
    self-consistency critique reads share a byte-identical image prefix, so the
    second bills at the cache-read multiplier; the batch path is uncached and
    takes the batch discount instead. What a run cost is what its `UsageRecord`s
    say it cost.
  - **The two image-token regimes are now documented as a pair.** Above 20
    images the API rejects an oversized image and the token count is
    scale-invariant; at 20 or fewer it downscales instead, the target is the full
    2576 px native long edge, and the count is cap-dominated. The 2576 branch is
    deliberate policy, and `DRAWING_ANALYZER_TILE_TARGET_PX` overrides the vector
    target only — the raster target stays fixed so `raster >= vector` holds and
    the conservative allowance stays a true upper bound.
  - **Overlap is presented as approximate preservation of interior resolution**,
    with thinner edge context and an unaffected overview — not as a free
    resolution win. `--estimate` cannot see an overlap change and says so.
  - **Three-state grounding is named in the README**, with what each outcome
    does, and why the region — not the sheet — is the unit of the question.
  - **Recovered evidence costs more downstream, by design.** Findings that used
    to be dropped now reach verification and investigation, so a set with
    scanned or hybrid sheets can bill more than it used to with nothing wrong.
  - **The two evidence changes handled the cross-QC cache differently**, and the
    README now says which did what. Recovering quotes past the prompt cap keyed
    the uncapped text **only for a truncated sheet**, so untruncated keys stayed
    byte-identical and no stored result was discarded. Admitting visual evidence
    changed what a cached entry means, so every entry had to go — via the edited
    map prompt, which rides every key, not a second mechanism. The review
    described this as a contract invalidation; `_CROSS_QC_CACHE_CONTRACT` is at 2
    for an unrelated reason (entries stored as `complete` after a silent
    truncation, before the findings cap became loss-aware), and the README now
    warns against reading that number as the record of either change.
  - **Attached spec documents are priced differently per transport, and the help
    text now gives the real arithmetic.** Real-time caches the block behind a
    breakpoint; batch sets none, so every sheet bills the whole block as ordinary
    input at the batch discount. The first draft of this help text said real-time
    meant paying "roughly once", which understates it by an order of magnitude:
    across 100 sheets real-time comes to about **11** copies of the spec text
    (one 1.25× write plus 0.1× for each remaining sheet, and more when several
    sheets go out before the first response lands, since each pays a write),
    while batch comes to about **50** (half a copy each). So the spec block alone
    runs 4–5× more in Economy mode on a large set, even though Economy is cheaper
    overall for the drawings. The cost dialog already stated the mechanism
    correctly; only the help text did not.

  Four review items needed no change, verified rather than assumed: the three
  text representations and their consumers are already documented with `words`
  named; the quality-screen claims and finding-level review outputs were
  corrected when that harness work landed; model-variant estimates are already
  documented as resolving in their own processes, with the
  `REVIEW_MODEL_DEFAULT` fallback chain given as the reason an in-process fix is
  insufficient; and no stale predecessor-product terminology remains in the
  tree. `PRICING_EFFECTIVE_DATE` is deliberately unchanged — this documentation
  being newer is not evidence about the rate table.

### Added

- **`docs/REVIEW_RELEASE_EVIDENCE.md` (WP-08 §13.3).** The release evidence for
  the whole review sequence: test and gate results, the cache-invalidation scope
  and the single mechanism used for each change, measurements carried forward,
  the §13.2 independent review checklist worked item by item — and an explicit
  list of what was **not** done (the §7.2 discard-rate run, dense-fixture memory,
  Windows manual GUI, the live canary). Two checklist items are recorded partial
  and one class of work untouched, because a checklist whose every box is ticked
  is the one nobody reads.

### Removed

- **`docs/REVIEW_IMPLEMENTATION_PLAN.md` retired.** Its implementation packages
  (WP-00 … WP-08) are complete and merged; what they changed is in this
  changelog, and what was verified is in `docs/REVIEW_RELEASE_EVIDENCE.md`. A
  2,300-line plan describing work that is done reads as current intent to the
  next person who opens it.

  Two parts did not retire with it and were preserved in
  `docs/MEASUREMENT_PACKAGES.md`: the **measurement packages** (R-01 … R-06),
  which have never been run and still need approved drawing sets and a budget,
  along with the experiment protocol that keeps them honest; and the **standing
  prohibitions**, each recording a shortcut rejected for a reason usually
  discovered the expensive way.

  Five files cited the plan by section number — `measure_evidence_coverage.py`,
  three evidence/geometry test modules, and the release-evidence doc. Rather
  than leaving dangling references, each now points at the live documentation
  for the same fact (the README's grounding sections, the performance doc's
  image-token regimes, `models.sheet_evidence_text`). A citation to a deleted
  file is worse than none: it tells a reader there is an explanation and then
  fails to produce it. The plan remains in git history at `168f4ec`.

### Known limits

- The **sheet-index harvest is still unbounded** — it reads every word on the
  page, so an equipment tag in a legend can be collected as an index row. Both
  diff directions already run every entry through `classify_reference`, so a
  code citation or transmittal number never becomes a finding; an equipment tag
  is not in that corpus and still can. Two cheap patches were tried and rejected
  on the evidence: a second corpus check at the harvest is a restated rule that
  only changes which pages clear the recognition gate, and excluding the sheet's
  own id breaks an index that legitimately lists itself. The real fix is region
  bounding, which needs row/column geometry and re-baselines both diff directions
  together.
- `signatures_compatible` still blocks only on **disjoint** measurement sets, so
  `12'-6"` and `12'-8"` remain compatible on their shared `12ft`. That is the
  documented "don't over-block a real duplicate" conservatism and is unchanged
  here.

## [1.3.0] - 2026-09-08

### Added

- **The run now records what a sheet costs to send.** Each rendered sheet emits
  a `SHEET_RENDERED` journal event carrying its image count, PNG byte spread
  (min / median / max) and long edge — captured in `_rendered_stream`, the one
  point where the PNG bytes exist on both transports, since the batch path
  discards the rendered sheet immediately after upload. Nothing logged tile
  sizes before: the render path logged only the count of suppressed tiles, and
  byte sizes appeared solely on Files-API retry paths. That left the near-blank
  suppression threshold (`DRAWING_ANALYZER_NEAR_BLANK_MAX_BYTES`, default 3072)
  a guess with no way to check it against real sheets.

  The spread is a **median**, not a mean: one dense schedule tile among mostly
  empty plan tiles is the normal shape of a drawing, so a mean sits above nearly
  every tile and is useless for picking a "nearly empty" threshold. Tiles dropped
  by the strict pixel-uniform check are reported as a *count*, never as zero
  bytes — they are discarded before `tobytes("png")` and have no size, and
  counting them as zero would skew exactly the distribution the telemetry exists
  to produce. Emission is best-effort: observability never sinks a render (I-3).

- **`DRAWING_ANALYZER_TILE_TARGET_PX` — a render-resolution sweep knob, default
  unchanged.** Image tokens scale with the *square* of effective resolution, and
  the tiles ride the digest plus both critique reads, so the vector render target
  is the highest-leverage single number in the bill. Measured on a real rendered
  E-size sheet: 1560 px (the default) = 62,479 image tokens, 1400 px = 50,332,
  1240 px = 39,508 (−37%), 1100 px = 31,085 (−50%).

  Whether a lower target still reads the drawing is a quality question the
  hermetic fixtures cannot answer, so **the default is unchanged** and this
  exists only to make a sweep runnable without editing code. Read per call rather
  than captured at import (a module-level `os.environ.get` would freeze the first
  value the process saw), and clamped to `[400, 1992]` so no setting can breach
  the API's hard 2000 px many-image cap — a request over it is *rejected*, not
  downscaled. The rounding guard is now asserted at every value a sweep can
  select, not just the two fixed constants. Raster sheets are deliberately not
  overridable: with no text layer the pixels are the only channel.

- **`scripts/ab_sweep_drawing_analyzer.py` — A/B a cost lever against quality on
  a real drawing set.** The trust gauntlet routes canned responses by
  system-prompt identity and never reads the model id, so a model swap changes
  nothing it returns; it answers "did this break the contract", not "did this
  hurt findings quality". And a real permit set rarely has a ground-truth finding
  list.

  Three signals already in the pipeline need no oracle, and the harness reports
  all three: the **anchor tier mix** (UNANCHORED is the documented hallucination
  signal), the **verification verdict mix** (a rising REJECTED share is more
  false positives), and **self-consistency** (the critique already records
  REPRODUCED / SINGLETON, so the reproduced rate is an agreement score between
  two independent reads). It also screens for the quiet failure the rates alone
  miss — a large drop in finding count at a flat VERIFIED share, which reads as
  "cheaper and cleaner" on every other line while meaning real defects went
  unseen. A clean screen is reported as *"the screen found nothing"*, never as an
  approval.

  Each arm runs in a subprocess, which is necessary rather than tidy:
  `REVIEW_MODEL_DEFAULT` is an `os.environ.get` evaluated at module scope and
  bound as a second name by fourteen modules, so setting
  `DRAWING_ANALYZER_MODEL` in-process has no effect. Both arms get a private
  cache so both run cold; `--estimate` prices them at the transport they will
  actually run on before anything is spent.

- **`RunUsage.by_model()`**, beside the existing `by_family()` and surfaced into
  `run_manifest.json`. Every usage record already carried the model its stage
  resolved to, but nothing aggregated it — and a per-family rollup cannot tell
  two model configurations apart, because the family names are identical in
  both. The benchmark harness now also records the resolved stage-model
  configuration in its environment block; it previously called
  `collect_environment()` with no model at all, so two reports from different
  configurations were indistinguishable from their contents.

- **Every real-time Opus 5 call now opts into Anthropic's server-side refusal
  fallback.** Opus 5's elevated safety classifiers can decline a request
  outright (`stop_reason="refusal"`, a normal HTTP 200) — a construction-
  drawing review is unlikely to trip them, but an unrecovered false positive
  would silently drop that sheet or finding's coverage with no distinguishing
  signal from any other empty response. `digest.stream_message` (digest,
  critique, review plan, synthesis, focus, and the batch direct-call rescue),
  `verify.py`'s escalation calls, and the investigation loop now attach
  `fallbacks: "default"` via a new `core.api_config.call_with_refusal_fallback`,
  which routes the request through `client.beta.messages` and — mirroring the
  investigation loop's own task-budget self-healing — turns the feature off
  process-wide the first time a platform rejects the beta/parameter, so a
  deployment without it enabled degrades gracefully instead of breaking every
  subsequent Opus 5 call. Never touches batch-submitted traffic (the Batches
  API rejects the parameter). Opt out entirely via
  `DRAWING_ANALYZER_REFUSAL_FALLBACK=0`. New tests in
  `tests/test_refusal_fallback.py`.

### Changed

- **Upgraded the `anthropic` SDK from 0.97 to 1.4** (the 0.x → 1.x major
  version). The HTTP transport moved from `httpx`/`httpcore` to the
  maintained fork `httpx2`/`httpcore2` — nothing in this codebase imports
  `httpx` directly, so this was transparent. The Files API and Message
  Batches are now GA: uploads, deletes, and batch creation move off
  `client.beta.files` / `client.beta.messages.batches` (and drop the
  `files-api-2025-04-14` beta header, which the retired beta namespace no
  longer needs) onto the stable `client.files` / `client.messages.batches`
  namespace, with no behavior change. `requirements.txt` and
  `requirements-release.lock` were regenerated against the new pin (also
  picking up routine bumps to `pymupdf`, `pypdf`, `tiktoken`, and other
  transitive dependencies); `distro` dropped out as an `anthropic` dependency
  and `truststore` was added. No other breaking change in the 1.x migration
  guide (Text Completions, `temperature`/`top_p`/`top_k`, `with_raw_response`,
  Bedrock region handling, ...) touches this codebase.

- **The pre-run cost estimate resolves every stage's model, not just
  verification's.** `estimate_exhaustive_run_cost` priced nine of its eleven
  components at the single `model` argument, so any stage not on the review
  model was mis-quoted — on critique, the largest line in the dialog, by 1.67x.
  A new `resolve_stage_models()` resolves all eleven through the same functions
  the runtime itself calls (so a `DRAWING_ANALYZER_*_MODEL` override is priced
  where it will really run), and the confirmation header names each model the
  run will touch instead of claiming one model does all the work. The resolver
  is reused by the benchmark and the sweep harness.

### Fixed

- **A 1-hour cache write is priced at 2x base input, not 1.25x.**
  `core.pricing` carried a single `CACHE_WRITE_MULTIPLIER = 1.25`, which is the
  *5-minute* rate, while `api_config._cache_control_block` requests
  `ttl: "1h"`. Every stage reaching that breakpoint — today the investigation
  loop, via `system_prompt_with_cache` / `tools_with_cache` — therefore had its
  cache writes under-reported by 60% in an append-only ledger the run manifest
  publishes as fact. The multiplier is now split
  (`CACHE_WRITE_MULTIPLIER_5M` / `_1H`), the requested TTL is threaded from the
  call site through `_record_usage`, and it is recorded on `UsageRecord` so a
  stored ledger stays re-priceable. The digest and critique breakpoints emit a
  plain `{"type": "ephemeral"}` and correctly stay on the 1.25x rate.

- **An unpriced stage no longer silently drops out of the exhaustive cost
  total.** `_total()` filtered out components with `cost=None` and summed the
  rest, publishing the remaining stages as if they were the whole run. The stage
  most likely to be unpriced is the one behind
  `DRAWING_ANALYZER_CRITIQUE_MODEL` — both the documented cost lever and the
  single largest component — so the failure landed precisely on the
  configuration someone experimenting with model routing would reach for first:
  pointing critique at a model absent from `MODEL_PRICING` quoted
  "$20.83 – $25.92" for a 40-sheet run whose critique line alone is ~$37, with
  nothing marking the figure partial. An unknown price now means "no dollar
  figure", never "a smaller dollar figure", matching
  `estimate_drawing_set_cost` and `RunUsage.total_estimated_cost`; the
  unavailable message names the stage responsible.

- **`docs/PERFORMANCE_AND_COST_VALIDATION.md` no longer claims verification is
  uncached.** It has cached through `stage_cache` since `_VERIFY_CACHE_STAGE`
  landed, as have cross-QC, synthesis, focus and the prose harvest, so a warm
  exhaustive re-run should show near-zero API calls across the board — and a
  warm run that *does* re-bill verification is now a cache-correctness bug worth
  chasing rather than expected behavior.

## [1.2.0] - 2026-09-04

### Added

- **A report reader can now use their own API key.** The chat's key field was
  hard-hidden whenever a report was generated with `embed_api_key=True`, on the
  theory that the embedded key was authoritative. In practice that made a shared
  review deliverable bill every question to whoever generated it, and made a
  report whose embedded key had since been rotated permanently unusable — a 401
  told the reader to "regenerate the report", which is the one thing a reader is
  not able to do.

  The embedded key is now a **default, not a lock**. A key the reader saves is
  checked first and wins for their browser tab; **Use my own key** opens the
  field and **Use the report's key** hands it back; **Forget key** clears the
  reader's key and says plainly that the file's own credential is still in the
  file and still what the next question will use. A 401 on the embedded key now
  routes the reader to the field instead of to a dead end. Verified end to end
  in headless Chromium.

- **Repeated quotes collapse in the findings table.** A general note printed on
  every plan sheet becomes one ledger finding *per sheet* — correctly, since
  fifteen sheets carrying the note are fifteen places to check, which is why the
  ledger's dedup is same-sheet scoped (§12). But fifteen identical rows are
  noise: on a real 39-sheet fire-protection set, **190 of 287 findings shared a
  quote with another**, `INCOMING FIRE SERVICE REFER TO CIVIL AND PLUMBING` was
  raised fifteen times, and `PRELIMINARY` eighteen.

  Rows quoting the same verbatim text now collapse behind the first one, which
  grows a `+N more sheets` control that expands the group in place. Display
  only: the ledger, the exports, the markups and the badge total keep every
  finding (§18.6). The grouping recomputes after every sort and filter, so a
  collapsed row is never stranded without a lead; search still reaches a
  collapsed row; the assistant's *show me* still scrolls to one; and **Group
  repeated quotes** turns it off.

- **A batch that sits in the queue now says so.** The poll only logged at DEBUG,
  so a frozen batch emitted nothing at INFO between submit and the stall warning
  and the GUI held a motionless `Analyzing 0/39 sheet(s)` — an hour in which a
  working run is indistinguishable from a hung one. A heartbeat every five
  minutes now reports elapsed time, items done, and how long the watch will keep
  waiting, to both the log and the GUI activity list, and the progress line
  carries the elapsed clock.

- **`DRAWING_ANALYZER_BATCH_STALL_TIMEOUT_MIN`** sets the stall window directly,
  in minutes, applying to every watch in the run.

- **The Ask-AI assistant is no longer rationed, and shows how full it is.** The
  chat had a hardcoded 16,000-token answer ceiling — an eighth of what the
  configured model actually serves — so a long answer stopped mid-sentence and
  the reader's only recourse was to ask again and pay twice. It now requests the
  model's own maximum (128k on the default), resolved host-side from the
  capability registry so it follows `DRAWING_ANALYZER_CHAT_MODEL` instead of
  outliving it; the input side was already untrimmed and stays that way — the
  report goes over verbatim and the transcript accumulates untouched.

  Since nothing is trimmed, the context window is the one budget a long
  conversation can exhaust, and the failure is abrupt: the request that exceeds
  it is rejected outright, mid-thread. The chat footer now carries a **context
  readout** beside the cost one — how much of the model's window the live thread
  occupies, with a meter and a plain-language warning at 70% and 90% ("nearly
  full, start a New chat"). The two are deliberately separate readouts: the cost
  line accumulates across every round of every question (spend), while the
  context line is a snapshot of what the next request will carry (occupancy),
  and cached tokens count toward it — they still fill the window, they are
  merely billed cheaper. Both come from the API's own usage numbers rather than
  a local estimate, so both stay honest and both stay silent until there is
  something measured to report.

  And if a thread does reach the ceiling, the answer now says so. Generated
  tokens count toward the window too, so a long conversation can stop
  mid-sentence with `model_context_window_exceeded` — a different stop reason
  from `max_tokens`, and one the widget used to let fall through silently,
  committing the cut-off answer and replaying it from the transcript as though
  it were complete. It gets its own note now, naming *New chat* as the remedy.

- **Ask-AI conversations are kept.** The report's chat used to live only in the
  tab's memory: a refresh, a close, or a mis-clicked *New chat* destroyed it, and
  the only way out was *Save as PDF* — a picture of the conversation, not data.
  The thread now **auto-saves to the browser** under a key scoped to that report
  and replays on load, so reopening the file picks up where you left off, and
  **Save** / **Load** write and read a `chat_history.json`
  (`drawing_analyzer_chat_transcript`, schema v1) that can sit beside
  `report.html` in the export folder. Replay is faithful — questions, answers,
  reasoning, tool steps and citations all come back, and the excerpt disclosure
  stays distinct from the wrapped prompt actually sent — and a loaded transcript
  is a *resumable* conversation: its `turns[].message` array is the verbatim
  Messages API history, so the next question continues the thread. *New chat*
  erases the stored copy.

  A transcript never carries an API key (the whole document is scrubbed of
  `sk-ant-…` before any write, and the schema has no key field), and a loaded
  one is treated as hostile input: rendered through the same text-node-only path
  as streamed model output, with tool calls drawn as labels and never executed.
  Saving and loading are same-document operations, so the report's
  Content-Security-Policy is unchanged and `connect-src` stays Anthropic-only.

- **Runtime-transparency panel ("I'm not convinced").** A link at the foot of
  *Why trust it?* opens an in-depth briefing for the security- or
  trust-conscious reader: the single network destination, exactly what leaves
  the machine and what never does, which model runs which stage, a free/paid
  breakdown of every stage, the agentic investigation loop's three read-only
  tools and its hard caps, the citation check's server-side search and source
  blocklist, prompt-injection containment, what the model is structurally not
  allowed to decide, honest limits, and how to verify each claim. Includes
  ASCII diagrams and links to the source, `SECURITY.md`, and Anthropic's
  privacy/trust pages. Help content gains two block kinds — `pre` (verbatim
  monospace) and `modal` (a hand-off to another help document).

### Changed

- **The batch stall watch is tiered: 25 minutes on the first batch, 60 after.**
  A healthy 39-sheet drawing batch lands in about ten minutes, so a flat
  one-hour window was far more patience than the first watch needs. One real run
  spent **two consecutive frozen hours** — 14:55 and 15:55, each abandoned at
  exactly 60 minutes with zero items completed — before its third batch finished
  in 589 s: 2 h 16 m of wall clock for roughly 25 minutes of work.

  The first watch now asks the cheap question ("is this batch moving at all?")
  on a 25-minute window; every resubmission after it asks the expensive one
  ("deep queue, or sick backend?") and keeps the full hour, since churning out
  another batch is the costly answer. Recovery is otherwise unchanged: still
  bounded rounds, still on the batch transport, still never a silent drop to
  full-rate real-time calls.

- **`Not checked` is now distinct from `Uncertain` on a finding.** Both states
  collapsed to the amber `Uncertain` chip, so a standard run — where
  `verification` is `NOT_REQUESTED` and no verifier has looked at anything —
  presented **every one of its 287 findings as an inconclusive verdict**.
  `Uncertain` now means a verifier examined the finding and could not settle it;
  `Not checked` (grey) means no verification stage ran for it. The status column
  sorts the new state just below `Uncertain`.

- **Sonnet 5 is priced at $2/$10 per MTok.** The table carried the $3/$15 list
  rate on the assumption that the $2/$10 launch pricing was introductory through
  2026-08-31. Anthropic has since made $2/$10 the standard price and canceled
  the scheduled increase, so the hedge was over-stating every Sonnet-tier
  estimate by 50%. `PRICING_EFFECTIVE_DATE` is now `2026-09-04`.

- **The Ask-AI answer now streams smoothly instead of arriving in lurches.**
  Model deltas do not arrive evenly — the API hands over a lump of text, stalls,
  then hands over another — and the report painted each burst the moment it
  landed. A representative answer reached the screen in **7 repaints of ~120
  characters**, and because each repaint grew the pane by more than the 60px
  "near the bottom" threshold, the autoscroll decided the reader had scrolled
  away and stopped following, leaving one **611px snap** to the bottom when the
  turn ended. Both are gone. Text now accumulates off-screen and a single
  `requestAnimationFrame` loop reveals it at a rate proportional to how far
  behind the display is — quick when it has ground to make up, easing as it
  catches up — which turns the same answer into **110 frames averaging 8
  characters**, and eases the scroll on the same clock (~6px per frame, no jump
  over 18px). Time-to-first-token, previously an empty grey bubble, gets an
  animated placeholder, re-armed after each tool call.

  Two supporting changes. The repaint is now incremental: markdown up to the
  last *safe* block boundary is rendered once and left alone, and only the short
  live tail is rebuilt per frame — so a long table or list no longer has its DOM
  destroyed and rebuilt eleven times a second, and a reader's text selection
  survives. A boundary counts as safe only where
  `render(A) + render(B) === render(A + B)`, which rules out splitting a list or
  blockquote that fuses across a blank line. And the autoscroll's follow state is
  now a sticky flag driven by real scroll events rather than a distance test, so
  the eased follow can no longer mistake its own lag for the reader taking over —
  and a reader who *does* scroll up mid-answer keeps their place, including when
  the turn finishes.

  Because the reveal can still be catching up after the response has finished
  downloading, three things bound that window: **Stop** ends the reveal as well
  as the download (`abort()` does nothing to a finished fetch, so it would
  otherwise sit inert for the length of the drain), a timer backstop settles the
  turn if animation frames stop arriving at all — a backgrounded tab fires none,
  which would leave the composer locked and the transcript unsaved — and
  per-frame ceilings keep the frame that returns from a stall from landing as
  exactly the dump the pacing exists to avoid.

  What renders is unchanged: the final DOM is byte-identical to before, restored
  transcripts still replay in one synchronous pass, and `prefers-reduced-motion`
  opts out of the pacing entirely and keeps the original instant path.

- **Moved the pipeline defaults to Claude Opus 5 and Claude Sonnet 5.** Review
  and escalation now run on `claude-opus-5`; first-pass verification, cross-check,
  and the report's Ask-AI assistant run on `claude-sonnet-5`. Triage stays
  on Haiku 4.5. The assistant is the one role that deliberately does *not* take
  Opus 5: web fetch is unavailable on Opus 5 (one of two documented exceptions to
  its Opus 4.8 feature parity), and the widget needs it to read a linked page.
  `supports_web_fetch` joins the capability registry and gates the tool list the
  report emits, so overriding `DRAWING_ANALYZER_CHAT_MODEL` to a model without
  web fetch now degrades the widget to search-only instead of failing every
  question with a 400. Opus 4.8 and Sonnet 4.6 remain fully registered, so pinning one
  through a `DRAWING_ANALYZER_*_MODEL` variable still gets full capabilities
  rather than the conservative unknown-model fallback. Opus 5 is priced
  identically to Opus 4.8 ($5/$25 per MTok), so the estimator's Opus figures are
  unchanged; Sonnet 5 is quoted at its $3/$15 list rate rather than the
  introductory $2/$10 that runs through 2026-08-31, which over-states rather than
  under-states a pre-run estimate.
- **Model capability decisions now read from the capability registry rather than
  Opus family membership.** Sonnet 5 is the first Sonnet-tier model to match Opus
  on the 128k output ceiling, the `xhigh` effort level, and the high-resolution
  (2576 px / 4784-token) vision tier, so the old `model in OPUS_MODELS` tests
  would have silently downgraded every Sonnet 5 request on all three axes.
  `ModelCapabilities` gains a per-model `supported_effort_levels` roster (a
  boolean could not express "accepts `max` but not `xhigh`", which is exactly
  Sonnet 4.6) and a `supports_hires_vision` flag; `OPUS_MODELS` is now used only
  to identify the verification escalation tier, which is a routing decision
  rather than a capability. This also corrects Sonnet 4.6's registered output
  ceiling, which had been carrying Sonnet 4.5's 64k value.
- Cached digests, critiques, and stage results from Opus 4.8 / Sonnet 4.6 runs
  will not be reused, because the model id is part of every content-addressed
  cache key. The first run after upgrading re-reads the set at full cost; no
  cache schema version was bumped, so older entries remain on disk and are still
  served if you pin a previous model.

- The report chat's `beforeunload` warning now fires **only** when the
  conversation could not be persisted (quota exhausted, private mode, storage
  disabled). With the thread surviving a reload, warning on every close was a
  prompt for a loss that no longer happens.
- Brought the four header help modals back in sync with the pipeline: the
  set-identity / model-authored-review-plan stages, prose harvest, edition
  audit, per-severity markup layers, the reviewed-copy guarantee, and the
  `run.log` / `run_manifest.json` record are now described; *How to use* covers
  the focus pop-out editor, the review-profile panel, processing modes, tile
  export, and the embedded-key opt-in. Corrected the claim that *Deterministic
  audit only* makes a run offline — the auditors are zero-API, the run they
  ride on is not.

- Replaced whole-file JSON cache rewrites with transactional SQLite/WAL row
  storage and automatic in-place legacy migration.
- Added exact complete-result caching for paid post-digest review stages; failed,
  malformed, incomplete, or evidence-invalid results are never reused.
- Reused digest renders and Files-API uploads for critique, and overlapped Batch
  rendering with upload through a bounded one-sheet lookahead.
- Added bounded, deterministic concurrency for independent cross-QC, prose,
  verification, and per-source reviewed-PDF work while keeping PDF access safe.
- Narrowed pre-render invalidation to conservative page dependency graphs, with a
  whole-source fallback whenever page isolation cannot be proven.
- Added Economy, Hybrid, and Fast processing choices and full-stack QC estimates;
  model/retry usage now records each billable transport attempt separately.
- Accelerated exact anchoring and ledger de-duplication with indexed candidates,
  and moved Export All work off the GUI thread.

### Fixed

- **The run record no longer looks like it predates its own run.** Journal
  timestamps were stringified straight from their UTC-aware values
  (`2026-09-03 21:51:33.048120+00:00`) directly beneath a local-time header
  (`2026-09-03 18:59`) — two zones and two precisions in one panel, reading as a
  report written two hours before the run it describes. Both now render in the
  reader's own clock, to the second, with the offset spelled out. The panel also
  gained a **Wall clock** line, which is what makes a queued run legible at a
  glance.

- **The collect log named the wrong batch.** `batch collect done` reported the
  *submitted* batch id, so after a stalled primary was abandoned and recovered
  it pointed anyone tracing the run at a canceled batch holding none of its
  results. It now names both the batch that was submitted and the one that
  actually served the digests.

- **Abandoned batch attempts reach the usage ledger.** §15.6 wants every API
  call/attempt recorded, but a batch given up on mid-flight left no trace at
  all: two abandoned hours were invisible in `run_manifest.json`, which showed
  only the single batch that worked. Each abandoned batch now appends one
  zero-token, **non-billable** record per sheet (`ABANDONED_STALLED` and
  friends). Costs and derived totals are unmoved, and the image-token estimate
  still counts only response-bearing attempts, so an abandoned round cannot
  inflate it.

- **A refused storage write no longer discards the reader's key.** Browsers that
  block site data (private mode, storage off, quota full) throw from
  `sessionStorage.setItem`, and key resolution re-read storage to find the key
  just typed — so it vanished. On a key-less report that reopened the entry form
  forever; on a report carrying its own key, resolution fell through to that one
  while the panel said the reader's was in use. The reader's key is now held in
  memory with persistence best-effort, and the status line says which of the two
  actually happened.

- **Abandoned recovery rounds survive on a sheet recovery never resolves.** A
  sheet whose primary batch terminated with a retryable error — so it already
  held a result — and whose every recovery round was then abandoned kept its
  abandoned-attempt records stuck on the slot, because only a `None` result was
  drained at the end of collect. The manifest then omitted exactly the abandoned
  batches that explain the run's wall clock. Retained results are drained too.

### Security

- **`pypdf` 6.14.2 → 6.16.2**, clearing six advisories that landed against the
  pinned version since the last release (PYSEC-2026-3655, PYSEC-2026-3656,
  GHSA-jp53-mhqp-8xcg, GHSA-23w6-3w8w-8484, GHSA-763m-79hh-57f2,
  GHSA-fc8x-2rww-xw9m) and were failing the CI dependency audit. `pypdf` backs
  spec-document text extraction (`spec_documents.py`), which reads untrusted
  PDFs, so this is a live exposure rather than a lint. Only `PdfReader`,
  `is_encrypted`, `decrypt` and `pages` are used — all unchanged across the
  bump. Pinned in both `requirements.txt` and `requirements-release.lock`.

## [1.1.0] - 2026-07-18

A usability-focused release: the standalone GUI is now more compact and
self-explanatory. No engine, output, or pricing changes — analysis, exports, and
the review pipeline are byte-for-byte identical to 1.0.0. Installed 1.0.0 apps
are offered this update automatically.

### Added

- **Collapsible input sections in the GUI.** The optional inputs — Anthropic API
  Key, drawing-PDF drop zone, per-run focus, project specifications, QC review,
  and processing — each fold into a thin click-to-toggle header, so the window
  opens compact and a section only claims space when it's in use. Collapsed
  headers carry a live one-line state summary (e.g. `3 PDF(s)`, `2 on`,
  `loaded`). The drop zone auto-collapses once files are loaded and re-expands on
  Clear; the API-key section starts collapsed when a key is already present and
  expanded (prompting for one) when it isn't.
- **Collapsible activity log.** The activity log now folds away like the sections
  above it. Its collapsed header shows the latest status line, folding it never
  shifts the action buttons, and the always-visible progress line above it keeps
  live run status in view even while the log is collapsed.
- **In-app "How do I get a key?" guide.** A link beside the API-key field opens a
  short, step-by-step guide to creating an Anthropic API key, so a first-run user
  is never stranded at the first screen.
- **Cost & time expectations surfaced throughout the GUI.** Mode-aware hints now
  state the concrete cost/time to expect at each decision point (batch vs
  real-time transport, the exhaustive QC run), single-sourced so the checkbox,
  the cost dialog, and the help panel never disagree.

### Fixed

- Corrected the batch cost framing so the "~$0.50" figure is tied to the digest,
  not the full QC run.
- Fixed misaligned bullets in the GUI help modals.

## [1.0.0] - 2026-07-17

The first public release — the full vision pipeline, the exhaustive QC stack, the
run journal/manifests, and the Windows desktop app. (Entries below accumulated
during pre-1.0 development and all shipped in 1.0.0.)

### Added — QC markups on severity layers

- **Every finding's ink now lands on a per-severity PDF layer.** The reviewed
  PDFs group their markups into three optional-content layers —
  `QC markups - High/Medium/Low severity` — so a reviewer can show or hide a
  whole severity tier at once in Bluebeam Revu / Acrobat / Chromium (e.g. "just
  the high-severity issues"). Clouds, QC tags, margin callouts, leader lines, the
  overflow *AI Review Notes* callouts, and the set-level
  `Drawing_Set_Review_Notes.pdf` notes are all layered. Findings are grouped
  strictly by `severity` (a question-category finding rides its own tier even
  though its *color* stays blue; an unset/other severity folds into the low tier,
  mirroring the index triage rank). Layers are created only for tiers that carry
  ink, in a fixed high→medium→low order (deterministic output, I-7), and every
  layer ships **on** — a freshly-opened reviewed set renders exactly as before,
  the layers only add the option to filter. Additive and non-fatal (I-3): if the
  backend cannot create a layer the ink is drawn unlayered, and the DA-007
  reopen-and-reconcile coverage protocol is untouched (the `/OC` layer reference
  and the placement stamp are independent keys on the annotation object).

### Added — About modal in the GUI header

- **A fourth header button, "About", beside the three explainers.** It opens
  the same style of scrollable modal (content in `help_content.py`, pure data,
  hermetic-testable) showing the package version, the licensing story
  (AGPL-3.0-or-later, why PyMuPDF makes the copyleft mandatory, the NO
  WARRANTY notice), the author's copyright (© 2026 Abraham Borg), and a
  clickable link to the author's LinkedIn. `HelpBlock` gains an additive
  `kind="link"` / `href` field; `gui.py` renders link blocks as underlined
  labels that open the default browser. Short button labels get a narrower
  width so the four-button row still fits beside the title.

### Added — project specifications upload

- **Upload real spec documents to ground the QC read.** A new "Upload spec
  documents…" button (`.pdf`/`.docx`/`.txt`/`.md`, extracted via `pypdf`/
  `python-docx` — new core dependencies, no PyMuPDF import, I-5 intact) lets
  the operator attach the project's actual written specifications for a run,
  gated by a blocking quality warning shown every time it's clicked. The
  extracted text is folded into the digest system prompt as a distinct,
  clearly-labeled `<project_specifications>` block (never conflated with the
  unrelated external "Project Context" term, nor with the existing "Per-run
  focus" question field) — the model reports drawing-vs-spec conflicts as
  ordinary findings, so they flow through the existing ledger/anchor/verify/
  markup pipeline with no new plumbing. The block rides a prompt-cache
  breakpoint on the real-time path (never on the parallel batch-item build,
  which would only pay the cache-write premium with nothing to read); a
  two-tier character budget (400k/file, 400k total — a single spec may fill the
  whole budget) bounds cost and attention dilution, with truncation surfaced as
  a non-fatal run warning. Pre-run cost estimates now show the specs'
  contribution, priced correctly for each transport (flat repeated input on the
  batch path; cache write-once/read-many on real-time).
  `digest_cache._SCHEMA_VERSION` bumped 7→8.

### Changed — stuck/sick batch recovery stays on the batch transport

- **A stalled or backend-sick drawing batch is now recovered by resubmitting
  the unresolved sheets as a fresh batch, never by dropping to full-rate
  real-time calls.** Previously, when the primary batch made no per-item
  progress for the stall window (`Drawing batch stalled; digesting N sheet(s)
  directly`) — or when the Batches backend errored every item — the run rescued
  those sheets via synchronous, streamed Messages calls
  (`_rescue_failed_items_sync`), which forfeited the 50% batch discount for the
  rescued sheets (flagged `rescued`, billed at full rate). `collect_drawing_batch`
  now takes a `recovery_transport`, and the pipeline passes the new
  `RECOVERY_BATCH`: the stuck batch is canceled and its sheets resubmitted as
  fresh batches (same still-uploaded `file_id`s, same params, discount intact)
  in a bounded loop (`_recover_via_batch_resubmit`), each resubmission carrying
  its own stall watch. The loop is bounded on both axes — at most
  `DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS` (4, override
  `DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS`) fresh batches, and never past the
  collection budget — so a genuinely dead backend can't loop forever; once the
  rounds/budget are spent, unreached sheets keep a clean, retriable batch error
  (still never a real-time call). The original `RECOVERY_DIRECT` behavior is kept
  as the default for direct callers and the unit tests. Trade-off: a persistently
  stuck backend now takes longer to give up (repeated batch rounds rather than an
  immediate real-time rescue), in exchange for never silently degrading a run to
  real-time pricing.

### Changed (GUI export options cleanup — GUI-only)

- **Trimmed the GUI's per-artifact export buttons.** The standalone window's
  *Save Markdown…* and *Save Findings CSV…* buttons were removed to keep it fast
  and uncluttered; the window now shows *Save HTML Report…*, *Save Reviewed
  PDF(s)…* (after a QC run), and *Export All…*. **Export All… is kept** — it is
  the only GUI path that writes the `run.log` / `run_manifest.json` run record,
  including for a failed run that produced no digest and no reviewed PDF, so it
  stays enabled even then. This is a **GUI-only** change — no engine or export
  functionality was deleted. The two removed buttons' handlers (`_on_save`,
  `_on_save_csv`) remain in place as dead code (marked as such in `gui.py`), the
  folder export still emits `findings.json` / `findings.csv` / `sheet_text/` /
  the raw Markdown, and the library API (`write_drawing_export`,
  `write_findings_csv`, `build_html_report`) is unchanged, so either button can
  be re-surfaced later.

### Added (Phase 27 — end-to-end acceptance & release gate, DA-027)

- **The §19.1 automated trust gauntlet.** One deterministic synthetic *oracle
  set* (`tests/fixtures/gauntlet.py`) packs every product guarantee into a
  single hermetic exhaustive run: two different PDFs sharing a basename, pages
  at 0°/90°/180°/270° plus a reduced CropBox, vector/raster/hybrid pages, a
  pre-existing reviewer annotation (DA-029), unrelated same-tile findings,
  repeated source text disambiguated by tile hint, prose items that match /
  structure / degrade (one structuring call forced to fail), a critique finding
  reproduced across both reads plus a read-1 singleton, a deterministic
  arithmetic mismatch (`TEXT_EXTRACTED` operands, §17.5), a stale-reference
  auditor finding, a dual-leg cross-sheet conflict, a REJECTED finding, an
  unanchored margin finding, a set-level synthesis conflict, two materially
  different claims citing one code reference (DA-017), and a corrupt input.
  The cold run asserts the fifteen §19.1 guarantees (source isolation through
  byte-exact verifier evidence — every image the verifier saw equals a saved,
  hashed artifact — to receipt-backed coverage, output agreement across
  report/CSV/JSON/PDF/manifests/run.log, sacred prose, and
  `COMPLETE`-only-when-everything-succeeded). The second run proves the warm
  cache (zero digest/critique API calls, zero rasterization, findings rebound
  to current source identity, stable QC numbering); the third mutates one
  source and proves only it misses the cache and the new content reaches
  analysis. Per-stage failure injection (bad model output for
  synthesis/critique/cross-QC/citation; crashes for auditors/harvest/verify;
  a markup writer failure) proves every required stage degrades to
  PARTIAL/FAILED honestly — incomplete PDFs are renamed, tallies never claim
  unwritten ink — while the standard digest ships (I-3). A dense-page run
  proves callout overflow lands on the appended AI Review Notes page with
  receipts, never over drawing content (§17.6).
- **§19.2 large-set acceptance.** Synthetic-digest tests prove the 44-sheet
  two-discipline map→reconcile topology finds a conflict absent from every
  local shard, resolves both legs to distinct real sources, and bills every
  shard + reconciliation call; the 84-sheet three-shard variant proves the
  reduction never isolates a group; a failed shard holds the pass at
  PARTIAL with its findings still usable.
- **§19.3 live API canary** (`tests/test_live_api_canary.py`, `network`
  marker — skipped without a real key, never in CI): live digest schema +
  structured-findings parse, critique structured-output compliance across both
  reads, the pinned `web_search` tool type + real tool-result parsing with
  claim-complete assessments, the Files API upload→delete lifecycle (deleted
  ids must be unretrievable), no-key-in-exports redaction, and an
  environment-identity printout for the release record.
- **Release-gate tooling.** `scripts/run_acceptance.py` (one-command §19.8
  automated gates with a PASS/FAIL table), `scripts/scan_secrets.py`
  (credential-shape scan over tracked files; wired into CI),
  `scripts/check_licenses.py` (stdlib dependency-license/AGPL-notice audit),
  and `scripts/benchmark_drawing_analyzer.py` (§19.7 scenario harness —
  offline hermetic by default with mechanical gates: warm runs make zero
  digest/critique calls and rasterize nothing, sources hash once per run,
  usage totals reconcile; `--live` measures real tokens/cost descriptively).
- **CI release gates (§19.8).** Two new pinned, least-privilege jobs:
  `security-gates` (secret scan; ruff correctness-classes E9/F63/F7/F82 only —
  no style churn; the license/AGPL audit; `pip-audit` with a documented dated
  `--ignore-vuln` exception policy) and `build` (wheel/sdist under the new
  committed `requirements-release.lock` constraints, `twine check`, clean-venv
  install smoke proving packaged profiles + version metadata agreement).
- **Acceptance documents.** `docs/WINDOWS_ACCEPTANCE.md` (§19.4 real-Windows
  path/input/GUI matrix), `docs/PERFORMANCE_AND_COST_VALIDATION.md` (§19.7
  scenarios, gates, medians-based tolerance, recording template), and
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` (the master §19.9 record: automated
  gates, live canary, Windows, Bluebeam Revu / Acrobat / Chromium script
  (§19.5), Excel/Notepad script (§19.6), deferral/waiver table, sign-off).
- **Release metadata.** Version bumped to **1.0.0rc1** (release candidate; the
  final tag requires the completed acceptance record); a new
  `tests/test_release_metadata.py` pins `pyproject.toml` and
  `drawing_analyzer.__version__` together, and the CI install smoke pins the
  installed-distribution leg (what `run.log`'s `app=` reports).

### Fixed (Phase 27 gauntlet regressions — §3.3/§4 status honesty)

- **Incomplete critique reads now hold the critique stage at PARTIAL.** A
  sheet whose two self-consistency reads did not both return parse-valid
  output (or whose critique call raised) was logged and recorded in usage but
  never surfaced into the stage status, so a run with a partial critique could
  still roll up `COMPLETE — "Exhaustive QC complete"`. `_run_critique_stage`
  now returns the degraded sheets and the stage scores PARTIAL with the
  per-sheet reasons (§3.3: "incomplete critique reads → PARTIAL or FAILED,
  never a valid skip"); the useful findings are kept and the run error names
  the count. Caught by the gauntlet's failure-injection matrix.
- **A cross-QC response with no parseable findings object is no longer a
  clean empty.** Prose-only, malformed, or truncated structured output from
  the whole-set call, a shard map call, or a reconcile call parsed as
  "0 conflicts, COMPLETE" (§4 item 4 violation: a failed parser presented as
  a clean empty result). Each call site now returns an explicit error —
  holding the stage at PARTIAL and, on the sharded path, counting the shard
  failed — while still salvaging any parseable numeric claims (additive,
  I-3). Test fixtures that returned *bare unfenced* JSON for cross-QC calls
  (never valid under the fenced contract, silently tolerated before) were
  corrected to fenced blocks (§22).

### Added (Phase 26B — final exhaustive activation, export hardening & report completion, DA-010/025/026/031/033)

- **The exhaustive completeness gate is OPEN (§18.0, DA-010).** A clean NORMAL
  `qc_markups=True` run now rolls up to **`COMPLETE` — "Exhaustive QC
  complete"** end to end (pipeline status, GUI completion line, report banner,
  run.log/run_manifest). The §8 phase-gates are permanent regressions enforced
  by stage statuses themselves: a failed cross-shard reconciliation, an
  unchecked cited claim (DA-017), a missing evidence crop/leg, unresolved
  callout overflow, or a mid-run source mutation each hold a required stage at
  PARTIAL / coverage at INCOMPLETE, which the §3.3 roll-up can never call
  COMPLETE — gate or no gate (regression-tested). The GUI's "complete
  intentionally withheld" notice is replaced by an explicit DEBUG_OVERRIDE
  explanation (the one remaining cause of a no-degraded-stage PARTIAL).
- **Excel-safe `findings.csv` (§18.5.1, DA-031).** Model/drawing-controlled
  text cells whose first meaningful character is a formula sigil
  (`=`, `+`, `-`, `@`, tab, CR — even behind leading whitespace/control
  characters) are apostrophe-prefixed so `=HYPERLINK(...)`/DDE payloads open
  inert in Excel. Host-owned numeric/enum columns (page, rect, statuses) are
  untouched — an ordinary negative coordinate survives exactly — and
  `findings.json` keeps the canonical values.
- **Export containment + atomic publish (§18.5, DA-033).** Every artifact
  name/destination passes one allocator boundary (`safe_artifact_name` +
  `contained_target`): traversal components and absolute/drive prefixes are
  dropped (a POSIX file legally named `..\\..\\evil.pdf` lands flat), invalid
  and ADS-colon characters are substituted, Windows reserved device names and
  trailing dots/spaces neutralized, lengths capped, collisions deduped
  deterministically — and every resolved target is **proven** beneath the
  export root before a byte is written. Evidence copies never follow symlinks
  (`os.walk(followlinks=False)` + per-file checks). The export itself now
  writes into a temporary sibling directory and publishes with one atomic
  same-volume rename: an interrupted export leaves an explicit
  `*_INCOMPLETE`-labeled folder, never a final-looking one missing artifacts.
- **Severity-first reviewed-PDF index (§18.7, DA-025).** Index rows (and the
  per-source overflow notes + `Drawing_Set_Review_Notes.pdf`) now sort high →
  medium → low/question, then source input order → page → anchored position →
  QC id, so the index reads as a punch list. Section structure (rejected /
  operator-gated), GOTO links, receipts, and the stable `QC-###` ids are
  unchanged — display order simply stops tracking numeric id order.
- **GUI "Export All…" (§18.0/§18.5).** The GUI gains a primary action that
  writes the complete export folder via `write_drawing_export` — report.html,
  Markdown set, findings.json/csv, `sheet_text/`, reviewed PDFs, `evidence/`,
  `markup_manifest.json`, `run.log`, `run_manifest.json` — atomically
  published to a picked directory (the per-artifact save buttons remain). Key
  handling matches Save HTML Report: never embedded unless the checkbox opts
  in.
- **HTML report §18.6 completion.** Prominent status banners gain a per-stage
  status table; a **High severity only** toggle joins the existing
  issues-only/category/search controls (filters never change the underlying
  totals — a live "showing K of N" counter appears instead); duplicate display
  names are disambiguated with the opaque source id; citation assessments
  render per reference; prose carry-through and provenance chips; a "Run
  record" panel names the run id and the exported `run.log` /
  `run_manifest.json`; accessibility pass (labels, `aria-pressed`,
  `aria-sort`, keyboard sorting, live regions). Ask-AI key-on-first-use and
  the 401 session-key clear were verified already present (DA-026, Phase 17).

### Added (Phase 26A — run journal, run.log & run manifest, DA-024)

- **Per-run journal (`run_journal.py`, §18.1).** Every `extract_drawing_context`
  call — GUI or library, standard or exhaustive, even an all-inputs-rejected
  run — now owns a `RunJournal` (`ctx.run_journal`): an append-only event trace
  with a fresh opaque `RUN-…` id and a **thread-safe monotonic sequence**, so
  events emitted concurrently from the digest worker pool are totally ordered.
  The pipeline emits typed events end to end: `RUN_START` (with environment/
  version identity), per-input `INPUT_ACCEPTED`/`INPUT_REJECTED`, `RUN_BLOCKED`
  (preflight), `CACHE_PRESCAN`, per-sheet `SHEET_DIGESTED` (ok/failed, cache
  hit, digest size, raster/vector, text-layer length, omitted blank tiles,
  findings-parser drift), `STAGE_START`/`STAGE_END` for every stage (mirroring
  each recorded `StageResult`, giving the run.log stage table its durations),
  `LEDGER_SEALED`/`LEDGER_NUMBERED` (with post-seal adds), `SOURCE_MUTATED`,
  `MARKUP_RECEIPTS` (expected vs WRITTEN/INDEXED/FAILED, receipt-derived),
  `USAGE_TOTALS`, and `RUN_END`.
- **Sanitize-at-emit boundary (§18.3).** Every journal field value passes the
  shared Phase 17 secret-redaction filter (`diagnostics.redact_secrets`) plus a
  new absolute-path scrubber (`/home/user/…/M-101.pdf` → `.../M-101.pdf`;
  Windows drive/UNC/quoted/`file://` forms handled; https URLs untouched),
  is flattened to one line, and is length-bounded **before it is stored** — a
  secret or private directory name can never enter the journal, whatever
  renders it later. Emission never raises (advisory, I-3 spirit).
- **`run.log` in every export (§18.2, DA-024).** `write_drawing_export` now
  writes a per-run, human-readable log: run id + start/end, app/OS/Python/
  PyMuPDF/SDK versions, model + prompt/cache-schema/coordinate-space versions,
  the classified input inventory (submitted/accepted/rejected with `SRC-####`
  ids), normalized configuration + profile snapshots, a per-sheet table, a
  stage table (status/calls/items/duration), per-family usage + derived totals
  (sub-cent costs shown as `<$0.01`, never rounded to zero), ledger/receipt/
  coverage accounting, prose carry-through counts (§14.9), outputs written,
  sanitized errors, the full event trace, and the final three-state outcome —
  the same vocabulary as the GUI completion line (§3.3). UTF-8 + CRLF for
  Notepad. Explicitly excluded: keys, headers, base64/image bytes, prompts,
  drawing text, long quotes, raw wire logs, absolute paths.
- **`run_manifest.json` in every export (§18.4, DA-024).** The machine-readable
  counterpart (`schema_version` 1): run identity + environment, final status
  (`qc_status`/coverage/configuration kind/counts), `RunConfiguration`,
  source inventory (**no absolute paths, no content SHAs** — `source_id` +
  input order are the portable provenance; §6.1/§10.4), profile snapshots,
  typed stage results, the append-only usage ledger with derived totals +
  `pricing_effective_date`, findings/prose/evidence summaries, receipt-derived
  markup coverage, sanitized errors, and the **sha256 + byte size of every
  artifact in the export**. Non-circular finalization order: ordinary
  artifacts → `markup_manifest.json` → `run.log` → `run_manifest.json` (hashes
  everything, `run.log` included, excludes only itself). `00_index.md` lists
  both new artifacts.
- **Context additions.** `DrawingContext` gains `run_journal`,
  `input_inventory` (the §6.1 `SourceDocument` records, previously discarded),
  and `prose_accounting` (the §14.9 harvest carry-through counts, previously
  discarded with the `HarvestResult`). `SheetGeometry` gains
  `omitted_tile_count` (`None` = not recorded, e.g. a level-1 cache hit that
  never re-rendered — the run.log says so instead of claiming zero).

### Fixed (Phase 26A review — multi-angle adversarial review + Codex P2)

A 8-angle adversarial review of the Phase 26A diff (line-scan, removed-behavior,
cross-file, reuse, simplification, efficiency, altitude, conventions) plus a
Codex bot finding surfaced 17 issues, all fixed with regression tests:

- **Export can no longer fail after the deliverable is written.** The new
  `run.log`/`run_manifest.json` writers were unguarded on
  `write_drawing_export`'s critical path — a duck-typed context field (a raw
  `Decimal` from a third-party `to_dict`, a malformed `prose_accounting`)
  raised *after* every ordinary artifact was on disk. Rendering/serialization
  now degrades per section (run.log) or to an error-bearing stub manifest;
  stray non-JSON values serialize through the sanitize boundary
  (`json.dumps(default=…)` so a `Path` can't leak a directory); only real
  file-write failures propagate.
- **`omitted_tile_count` was dead on every cache-enabled run** (the GUI's
  default): with a cache active, all geometry came from the no-render prescan,
  so even freshly rendered misses reported nothing. A `_GeometryOmissionSink`
  now merges the render-time blank-tile count onto the prescan record for
  misses; true cache hits honestly stay "not recorded".
- **Run-level terminal status (Codex P2).** `journal.finish()` stored the QC
  status, so a clean standard run's manifest said `final_status:
  "NOT_REQUESTED"` — indistinguishable from "didn't finish". A shared
  `derive_run_outcome` (COMPLETE/PARTIAL/FAILED: nothing analyzed → FAILED;
  digest shipped but errors/partial QC → PARTIAL) now feeds both `finish()`
  and run.log's outcome line, and `RUN_END` carries `outcome=` alongside the
  QC `status=`.
- **Scrubber hardening (empirically reproduced cases):** URLs are masked
  during the path scrub and restored byte-identical, so a `:`-before-slash
  URL segment (`…/wiki/File:/x/y.png`) is never mangled; the Windows-drive
  pattern now requires a directory component (`option A:/B`, `drive C:\ is
  full` untouched); `file://` matching is case-insensitive; and the journal
  gains **known private roots** (input parents, work dir, home — registered
  by the pipeline) replaced literally before the regexes run, which is what
  makes spacey Windows directories (`C:\Users\John Smith\…`) scrub reliably.
  HTML 5xx bodies in exception strings are tag-stripped like the diagnostics
  file does.
- **Empty-but-error-free digests are now failures in every accounting
  surface** (`SheetDigest.ok` semantics): `SHEET_DIGESTED` status, the digest
  `STAGE_END` ok/failed counts, and run.log's per-sheet rows all agree with
  the header sums (previously such a sheet was "OK" in the event but "failed"
  in the summary).
- **Single-source helpers replace drift-prone copies:** one
  `models.receipt_status_counts` behind the journal event / run.log line /
  manifest coverage block (was 3 hand-kept tallies); `_finish_stage()` records
  a StageResult AND emits its journal event in one call (a stage can no longer
  land in the roll-up but miss the trace); run.log's outcome line composes
  from the shared `qc_status_label` (§3.3 vocabulary); `evidence_summary` is
  shared by run.log + manifest; prose accounting keys are defined once at the
  producer (`HarvestResult.accounting()`); `run_manifest.json`'s
  `generated_at` uses the journal's UTC-Z timestamp dialect (was naive local
  in the same document); critique usage labels derive from the stamped refs
  (no path-list ordering precondition); reviewed PDFs are hashed once per
  export (shared cache between the two manifests); run.log's Outputs section
  derives from the folder itself (cannot drift from what the manifest
  hashes); `_journal_environment` uses plain imports (a broken import can no
  longer silently erase the whole version-identity block); dead
  `events_for` removed; emit no longer runs the full sanitize pipeline on
  code-owned field keys.

### Changed (Phase 26A)

- **Usage `stage_instance` labels are now portable (§10.4).** The per-sheet
  digest/critique usage records previously embedded the raw PDF path
  (`digest:/abs/path/M-101.pdf:p0`); they now carry the host-owned portable
  identity (`digest:SRC-0001:p0`), because `run_manifest.json` exports usage
  records verbatim and an absolute path in a portable artifact would leak the
  user's directory layout. Rollups were always per-family, so no consumer
  changes. The manifest additionally passes the whole usage block through the
  sanitize boundary as defense in depth.
- `export.write_drawing_export` writes two more files into every export folder
  (`run.log`, `run_manifest.json`) and returns the same folder path as before;
  `build_export_documents` (the pure document builder) is unchanged.

### Added (Phase 25 — reference grammar, tile semantics, auditors & callout placement, DA-019/020/021/022)

- **Unified sheet-ID grammar & negative corpus (DA-020, §17.2/17.3).**
  `auditors/sheet_ids.py` is now the single host-owned foundation every auditor
  (reference / sheet-index / naming / title-block) and the profile / cross-sheet
  resolvers share. It learns the set's numbering **convention** from the ids it
  actually contains (alpha/digit/separator *signatures*) and recognizes the
  hyphenated (`M-101`), **compact** (`FP101`), and **dotted** (`M1.01`) families —
  the compact/dotted families were previously unrecognized, so a compact-numbered
  set had an *empty* inventory and no reference could resolve. A **negative
  corpus** (`is_non_sheet_reference`) keeps code/standard citations (`NFPA 13`,
  `IBC 202`), transmittal numbers (`RFI-123`), voltages (`480V`), room numbers,
  and dimensions from ever becoming a sheet finding, even when close to a real id.
  Strong/medium trigger tiering and a **low-confidence** mode (a one-sheet set runs
  strong triggers only, suppresses the fuzzy near-typo path, and reports the
  confidence limitation). Sheet IDs **split across adjacent PDF words** (`"M-"`
  `"101"`) are rejoined so the sheet still enters the inventory.
- **Stronger deterministic auditors (DA-021, §17.4).**
  - *Title-block:* a high-confidence **label→value** field-class path (project
    number, package/project **name** incl. multiword, date) flags a value that
    differs from the set consensus at **any** distance — catching substantially
    different and multiword values the recurrence path (edit-distance-≤2 single
    tokens) cannot. A labelled field on too few sheets, or a label-less lone token,
    stays telemetry; mere absence is never flagged.
  - *Sheet-index:* each entry is classified through the shared resolver, so a
    malformed / out-of-convention entry (a likely index typo, low) is surfaced —
    not silently dropped — and kept distinct from a grammar-valid absent entry
    ("not present in the provided set", medium).
  - *Naming:* clusters by a `(letters, digits)` key, so a changed **number** is
    meaning-bearing — `A1-2` no longer merges with `A2` — while `C1R`/`C1-R`
    (same digits, separator-only drift) still does.
- **`tile_label` contract removes tile base ambiguity (DA-019, §17.1).** The model
  now returns the exact visible label it saw (`"tile_label": "r1c1"`) instead of an
  ambiguous `[row, col]` array; `tiling.parse_tile_label` converts it to the
  canonical zero-based `[row, col]` with a grid bounds-check. A legacy `tile` array
  is still accepted, **explicitly** as zero-based and bounds-checked (never guessing
  `[1,1]` meant `r1c1`). `findings.csv` gains a human `tile_label` column.
- **Precise arithmetic provenance (§17.5).** A mismatch is trusted `DETERMINISTIC`
  only when the claim's own quote independently carries every operand
  (`operand_origin=TEXT_EXTRACTED`); a mismatch computed from model-transcribed
  terms stays `UNCERTAIN` and is crop-verified before it inks as ground truth. The
  popup states the provenance. A magnitude-aware relative tolerance replaces the
  blanket abs-0.5 rule that hid small-value errors (`0.2+0.2` printed `0.5`).
- **Non-obscuring callout placement + review-notes overflow (DA-022, §17.6).**
  Rect-less findings are packed into visually-clear bands — each box validated
  against the words, a rendered **occupancy mask** (piping/symbols/raster), and its
  siblings — and a leader is drawn only when it would not cross another callout.
  A callout that will not fit overflows to an appended **AI Review Notes** page
  (with a GOTO link back to its source), never stacked over the drawing.

### Changed (Phase 25)

- Digest cache schema **6 → 7**: the tile parse changed and `Verification` gained
  `computation_method` / `operand_origin`, so pre-v7 entries miss once and re-derive.
- `DIGEST_PROMPT_VERSION` / `CRITIQUE_PROMPT_VERSION` auto-bump (the findings
  instruction now requests `tile_label`), invalidating stale digest/critique caches.

### Fixed (Phase 24 review remediation — 16 adversarial-review findings)

A multi-agent adversarial review of the Phase 24 diff surfaced 16 confirmed
issues, now all fixed with regression tests:

- **`discipline_token` regression** — a compact two-letter discipline with a suffix
  segment (`FP101-A`, `FA101-N`, `CE201-X`) was misread as a project code and
  returned the wrong discipline. The project-prefix guard now requires **3+** leading
  letters (disciplines are 1-2; project codes are 3+), so `FP101-A` → `fp` again
  while `AVC10-F-D-01-1` → `f` still holds.
- **Sharded cross-QC numeric claims were orphaned** — the map/reconcile prompt keyed
  claims by `sheet_handle`, but the shared claim parser only reads `sheet_id`, so
  those claims never reached the arithmetic auditor. The prompt now emits the handle
  in `sheet_id`, and it is rebound to the real sheet host-side.
- **Cross-QC reduction tree missed cross-group conflicts** — when facts overflowed
  one reconcile call, the old tree kept only the first child (`merged[:cap]`). It now
  splits facts into half-cap groups and reconciles **every pair**, so a conflict whose
  two sheets land in different fact groups is still found (fan-out capped, honest
  degradation past the cap).
- **GUI profile leak & mislabel** — auto-suggested profiles now reset when the file
  set changes / on Clear (a fire-protection suggestion no longer carries into an
  unrelated electrical run), and a profile in the default user dir is labeled `user`,
  not `built-in`. The apply logic reuses the tested `resolve_profile_selection`.
- **GUI preflight PyMuPDF thread-safety** — overlapping preflights now serialize their
  PyMuPDF access under a lock (I-5) and only the most recent result is applied.
- **Citation cost, tally & handle tolerance** — the web-search fee is billed per
  *request* (a reference with many claims issues several), `CitationCheckResult.by_ref`
  is populated again, the no-client fallback records its assessments (so `items_out`
  is right), and claim/sheet handles are matched case/bracket-tolerantly.
- **Test-quality fixes** — the citation fake clients now route by request *content*
  instead of worker-thread arrival order (removing flakiness), the DA-017
  "verdict-never-covers-an-omitted-claim" guard now forces the cross-chunk scenario
  deterministically, and the dual-crop evidence test proves the two legs are
  byte-distinct crops from distinct sources.

### Added (Phase 24 — cross-sheet, profile, citation & evidence completion, DA-015/016/017/018/028)

- **Cross-sheet QC is now whole-set at every size (DA-015).** Above 40 sheets the
  pass no longer "shards and unions" (which silently missed any conflict whose two
  sheets fell in different shards — it made **no** reconciliation call at all).
  It now uses a **map → reconcile** architecture: it shards by discipline; each
  shard call returns its local conflicts *and* a set of compact, grounded
  `CrossQCFact`s (the comparable data points another shard might contradict); then a
  final **reconciliation** call compares those facts across *all* shards and emits
  the cross-shard conflicts, so a coordination error spanning a mechanical and a
  fire-protection sheet is found. Facts that overflow one call reduce through a
  balanced tree. The model never sees source identity — in the sharded path it works
  with **request-local opaque handles** (`S001` …) that are validated against the
  request manifest and translated to real sources on the host (an unknown handle
  leaves the item unbound); and every fact's `exact_quote` (and every reconciliation
  quote) is validated against the retained source text before it is trusted, so an
  ungrounded quote never becomes a trusted dual-anchor finding. `CrossQCResult` now
  reports shard/reconciliation completeness and a failed shard or reconciliation
  holds the stage at `PARTIAL` while its findings stay usable.
- **Cross-QC text budgeting is loss-aware (DA-028).** An over-long sheet text layer
  is still capped, but the omission is now **counted and surfaced**
  (`text_chars_omitted` / `budget_degraded`, a stage warning, and the run log),
  never a silent slice — and a degraded budget holds the pass at `PARTIAL`.
- **Citation verdicts are claim-complete (DA-017).** A citation verdict now attaches
  to a finding **only if that finding's claim was in the request that produced it**.
  Every distinct claim for a reference is checked (chunked into claim-complete
  requests when there are many — the old path sent only the first three finding
  texts and pinned that single verdict onto *every* citing finding), the model
  returns a **per-claim** verdict keyed by a request-local opaque handle validated
  against the request, and each `CitationAssessment` (`reference`,
  `claim_finding_ids`, `status`, `request_id`, editions, sources) is bound to exactly
  the findings whose claim it covered. A finding that cites several references keeps
  one assessment **per reference** (`finding.citations`); the legacy
  `finding.citation` is derived as a summary. A request/parser/tool failure leaves
  the claim `UNCHECKED` and marks the stage `PARTIAL` — and never downgrades the
  engineering finding.
- **The verifier's evidence trail is complete and byte-exact (DA-016).** Every crop
  a verify call saw is now saved **and hashed before it is sent**, and only saved
  crops are sent — a verdict may never rest on an image absent from the trail. Each
  finding gets an `evidence/<QC-ID>/` directory with one `leg-NN__<sheet>_pN.png` per
  leg (a cross-sheet conflict saves every sheet's crop, in request order) and a
  `request.json` recording the ordered artifact metadata + verdict (no key, no
  unrelated drawing text). Each `EvidenceArtifact` carries the crop's `sha256` (the
  hash of the bytes on disk, which are the bytes the model judged), rects, dpi, and
  request order. A cross-sheet conflict is **never** decided from a single crop —
  fewer than two saved legs degrades to `SKIPPED` with a precise missing-leg reason.
  The folder export copies the **complete nested** evidence tree, and the HTML report
  and PDF popup list **every** artifact. `Verification.evidence_png` is retained as a
  back-compat alias to the first artifact.
- **Profile auto-suggest, snapshot, and selection (DA-018, §16.0/§16.4).** A new
  shared, host-owned sheet-id foundation (`auditors/sheet_ids.py`) provides
  normalization, a candidate lexer, an ambiguity-safe inventory resolver
  (`RESOLVED` / `UNBOUND` / `AMBIGUOUS`, never a silent first-wins), and
  **project-prefix-aware** discipline detection — so a project-coded id like
  `AVC10-F-D-01-1` now detects the fire-protection segment (`F`) instead of the
  project code (`AVC`), while plain forms (`FP-101`, `M1`, `E1.01`) are unchanged.
  A cheap **text-only preflight** (`preflight_sheet_ids`, no rasterization) detects
  each sheet id and auto-suggests profiles; `resolve_profile_selection` makes manual
  choice win (a deselection survives a later suggest refresh); and the selected
  profiles are **snapshotted** (name + version + content hash + source) at Analyze
  time onto `DrawingContext.profile_snapshots`, with a typed `profiles` stage
  (`SKIPPED_VALID` with no applicable profile, `PARTIAL` when a requested profile
  can't be resolved). The GUI grows a review-profile multi-select panel that
  auto-suggests off the loaded files and passes the selection into the exhaustive run.

### Added (Phase 23C — batch critique & upload lifecycle, DA-030/DA-034)

- **The critique now rides the Message Batches path in a `use_batch` run, at the
  ~50% batch rate (DA-030).** Previously the reviewer's two self-consistency reads
  ran real-time and inlined each sheet's ~37 images as base64 *twice* (once per
  read), making the exhaustive QC pass the dominant cost and leaving the documented
  "roughly half via Batches" economics untrue for the critique. A new
  `batch_critique` module uploads each uncached sheet's images to the Files API
  **once** and submits both reads as batch items (distinct `custom_id`s
  `sheet__{i}__r1` / `…__r2`) referencing that single shared upload — so the
  imagery is neither re-rendered per read nor re-uploaded, and both reads are
  batch-priced. The usage ledger records the reads with `transport=BATCH`, so the
  cost preview's critique component is now batch-priced and the discount is real.
  The self-consistency merge, provenance stamping, caching, and partial/failed-read
  semantics are the *identical* code the real-time path uses (a shared
  `outcome_from_message` / `result_from_outcomes`), so a batched sheet's verdict is
  byte-for-byte what a real-time one would be. Additive and non-fatal (I-3): an
  upload failure degrades **only that sheet** to a real-time fallback reusing the
  in-hand render, and a batch that can't be collected degrades those sheets'
  critique while the standard digest deliverable ships untouched. A whole-run
  Files-API outage trips the same run-fatal upload circuit breaker the digest path
  uses (after a few consecutive 401/403/404s the remaining sheets skip the doomed
  upload and go straight to the real-time read). *Scope note:*
  the reuse is **within** the critique's two reads; sharing one upload across the
  digest **and** the critique (§15.8's ideal) is a deliberately deferred follow-up.
- **Uploaded Files-API images are released on every exit path (DA-034).** Cleanup
  is no longer reached only on specific branches. In the new critique batch it runs
  in a `try/finally`; in the digest batch, `submit_drawing_batch` now deletes every
  already-uploaded file if `batches.create` raises (a submit failure used to leak
  the whole batch's uploads), and `collect_drawing_batch` releases the files if an
  unexpected error escapes the terminal-collection path (`results()`/parse/the
  follow-up round raising) before re-raising. A batch that is neither collected nor
  cancelable keeps its files to expire server-side ("detach safely"), and that
  retention is logged.

### Fixed (Phase 23B — usage & cost accounting, DA-014)

- **Token accounting is now an append-only usage ledger; no stage can overwrite
  another's counters (DA-014).** The QC pipeline used to fold the prose-harvest
  tokens into `v_in, v_out` and then **overwrite** them with `v_in, v_out =
  vres.…` (`=`, not `+=`) when verification ran — silently dropping the harvest
  tokens from the run total. Every API call/attempt now appends a priced
  `UsageRecord` (`stage_family`, `stage_instance`, `transport`
  REAL_TIME/BATCH/CACHE, model, input/output/cache tokens, tool uses, `cache_hit`,
  `parse_success`, `terminal_status`, `estimated_cost`) to a `RunUsage` ledger on
  `DrawingContext.run_usage`; `total_input_tokens` / `total_output_tokens` /
  `total_estimated_cost` are **derived** sums over it, so the grand total always
  equals the exact sum of the records. A cache hit records zero billed tokens with
  its cache-hit metadata; a response that consumed tokens but failed to parse stays
  billable; a batch call is priced at the batch rate and a real-time call at the
  standard rate — per record, so a mixed run prices each stage correctly.
- **Per-record pricing with a verified effective date (§15.7).**
  `core.pricing.usage_record_cost` prices one record by its own rate class —
  ordinary input/output, cache read (0.1×) / write (1.25×), and per-use web-search
  tool fee, with the batch discount applied only to token cost. `PRICING_EFFECTIVE_DATE`
  stamps when the rates were last verified (surfaced in the GUI/report so a stale
  figure is never presented as authoritative).

### Added (Phase 23B — honest exhaustive cost preview + post-run actuals, §15.7)

- **The GUI cost dialog previews the *exhaustive* run when QC Markups is on** —
  `estimate_exhaustive_run_cost` breaks the spend down per stage (digest+synthesis
  on the batch path; two critique reads/sheet, cross-sheet QC, prose harvest,
  verification, and citation real-time) and quotes a low–high **range** because
  verification and citation scale with the finding / unique-claim count. The
  completion summary and a collapsible **Token usage & estimated cost by stage**
  table in the HTML report show the *actuals* from the ledger — the same records
  the totals derive from, so GUI, report, and context always agree.

### Changed (Phase 23A — run configuration, status & persistence, DA-010/DA-012/DA-013)

- **`qc_markups=True` now resolves to — and runs — the full exhaustive stack
  (DA-010).** The GUI's *QC Markups* checkbox and the public API used to run only
  digest → anchor → verify → markup on the digest's own findings; critique,
  cross-sheet QC, the deterministic auditors, and citation checks never ran unless
  each was passed separately. A single normalization point,
  `resolve_run_configuration(...)` → an immutable `RunConfiguration`, is now the one
  place the option matrix is interpreted (§15.1): `qc_markups=True` turns on
  synthesis (≥2 sheets), two critique reads per sheet, cross-sheet QC, the
  auditors, prose harvest, anchoring, verification, citation checks, markup, and
  coverage reconciliation. The GUI *QC Markups* label now reads "exhaustive
  engineering review + marked-up PDFs" and inherits this behavior. Every stage
  reads the resolved config; no call site re-derives the boolean combination.
- **Per-stage flags are now `bool | None` (a tri-state).** `synthesize`, `critique`,
  `cross_qc`, `citation_check`, and `verify_findings` default to `None` — "use the
  product default." An explicit `True`/`False` is honored as an expert override;
  disabling a normally-required exhaustive stage (e.g. `qc_markups=True,
  critique=False`) records a `DEBUG_OVERRIDE` configuration and forces
  `qc_status=PARTIAL`, never a clean `COMPLETE`. Every legacy keyword still works.
- **One canonical run-status vocabulary (§3.3).** `DrawingContext` gains
  `qc_status` (`NOT_REQUESTED`/`COMPLETE`/`PARTIAL`/`FAILED`), a typed
  `stage_results` list (`StageResult`, one per QC stage with
  `NOT_REQUESTED`/`COMPLETE`/`PARTIAL`/`FAILED`/`SKIPPED_VALID`), and the resolved
  `run_configuration`. `roll_up_qc_status` derives the overall status
  deterministically; the GUI completion dialog and a new HTML report banner lead
  with it. A **temporary completeness gate**
  (`EXHAUSTIVE_QC_COMPLETENESS_GATE_OPEN = False`) keeps a clean exhaustive run at
  `PARTIAL` — Phase 23 must not advertise a completeness that Phases 24–25 have not
  yet delivered (cross-shard reconciliation, claim-complete citations, evidence and
  callout completeness). Phase 26 opens the gate.

### Fixed (Phase 23A — run configuration, status & persistence, DA-010/DA-012/DA-013)

- **A standard run now retains and exports its findings and sheet text (DA-012).**
  With neither QC checkbox, the pipeline used to discard geometry and leave
  `ctx.findings` empty. It now always captures each sheet's lightweight text/geometry
  record, ingests the digest's JSON findings into the ledger, binds them to source
  identity, and anchors them offline **for free** (no verify/critique/citation/
  prose-structuring/markup). The folder export always writes `findings.json`,
  `findings.csv`, and `sheet_text/`, the HTML findings card renders, and the export
  index is labeled "Findings & sheet text" (not "QC review") for a run that did no QC.
- **The deterministic-audit-only path is now truly zero incremental API cost
  (DA-013).** The prose harvester's straggler-structuring model call is gated to
  exhaustive QC only; the *Deterministic audit only* selection runs the auditors over
  the already-extracted text/geometry and makes **no** model calls beyond the digest.
  Its GUI label now reads "Deterministic audit only — no additional API calls", and
  the checkbox is disabled/marked redundant while *QC Markups* is checked (the
  battery is already included).

### Fixed (Phase 22 — structured-output, critique & prose-harvest correctness, DA-008/DA-009/DA-023)

- **A truncated / unclosed findings block can no longer leak into the sacred prose
  (DA-009).** The old fenced-block scanner required a closing ` ``` `, so a response
  cut off mid-JSON (max_tokens) matched *nothing* and its whole partial machine block
  was returned verbatim as `combined_text`. A new line-aware scanner
  (`scan_structured_blocks`) recognises an **unclosed** fence too, and
  `parse_findings_detailed` classifies every ending (`ABSENT` / `PARSED_CLOSED` /
  `PARSED_UNCLOSED` / `MALFORMED_CLOSED` / `MALFORMED_UNCLOSED` / `TRUNCATED`): in
  every non-absent case the prose is cut at the opener, so no machine block reaches
  the prose regardless of how the response ended. Ordinary prose that merely contains
  the word "findings" is still returned byte-for-byte (I-2). The one scanner is shared
  by digest, critique, cross-QC, and prose-harvest, so all four are truncation-safe.
- **A malformed / partial critique read can no longer look clean or corroborated
  (DA-008).** A critique read is now a *success* only when it returned a valid findings
  schema (an explicit `{"findings": []}` counts); a prose-only, missing-object,
  truncated, or malformed body is a **failure** — never an empty success. So it is
  neither merged as a clean read nor cached as complete. Each read is a
  `CritiqueRunOutcome` stamped with its own provenance (`critique_1` / `critique_2`) at
  production; the report's `critique×2` chip now reads from **real** provenance rather
  than being re-inferred from the `reproduced` boolean (that pipeline heuristic is
  gone). Self-consistency follows the truth table: two valid reads → `REPRODUCED` /
  `SINGLETON`; a requested read that *failed* → `NOT_ASSESSED_PARTIAL` (never silently
  reproduced); single-read mode → `NOT_APPLICABLE`. `Finding.confidence` carries the
  verdict and `reproduced` is derived from it. A result is cached only when every
  requested read parsed validly (the entry records `requested_runs` / `completed_runs`).
- **A long review checklist is no longer split into different items across the two
  reads.** The reads are compared for self-consistency, so both now receive the *same*
  full checklist — a finding prompted only in read 1 can no longer be stamped an
  uncorroborated singleton merely because read 2 was never asked about it.
- **A synthesis conflict that names no in-set sheet is no longer dropped (DA-023).**
  It becomes a **set-level** finding (`scope=SET`, no `source_id`,
  `anchor_hint="SET_INDEX"`) written to a new deterministic
  **`Drawing_Set_Review_Notes.pdf`** — analyzer-owned pages with their own artifact,
  placement ids, and reopened-and-reconciled Phase-21 receipts (`REVIEW_NOTES`). It is
  never pinned onto an arbitrary drawing, and it sorts into a final section after every
  source-scoped `QC-###`.
- **Every enumerated prose item now has an artifact-backed carry-through guarantee
  (§14.9).** The harvest enumerates each candidate item into a stable
  `prose_item_id` *before* processing, runs each under its own guard (one item's
  failure can no longer abandon the rest), and at the end reconciles the enumerated
  ids against the ledger — degrading any straggler one last time and reporting any that
  is still unaccounted as an invariant failure (surfaced in `ctx.errors`). The ledger
  merge unions `prose_item_ids` so an item's provenance survives dedup.
- **New:** `Finding.confidence` and `Finding.prose_item_ids` (additively serialized);
  a `ProseItem` data contract; `CritiqueRunOutcome`; parser-status and confidence
  constants in `models`; `scope` + `confidence` columns appended to `findings.csv`.
- **Cache schema bumped to 6:** stored findings gained the new fields, the critique
  entry records the read counts, and the parser was rebuilt — so every pre-v6 entry
  misses once and is re-derived rather than served as current. Prompt versions are
  unchanged (the prompts did not change in this phase).
- Review hardening: a critique read whose findings array was **non-empty but every
  item failed validation** (e.g. a category outside the enum) is now a *failed* read,
  not a clean empty success — a content-bearing body can never be frozen clean
  (`FindingsParse.raw_item_count` exposes the pre-validation count). And a partial
  critique that produced **no** merged findings (a valid-but-empty read paired with a
  failed one) is surfaced on `CritiqueResult.error` instead of reading as a genuinely
  clean sheet. The set-level `Drawing_Set_Review_Notes.pdf` is intentionally exempt
  from the `markup_verified_only` gate (it is a review-notes artifact, not drawing
  ink) — documented at both call and writer sites.
- Adversarial-review hardening (5 confirmed findings fixed): (1) a `max_tokens`
  truncation that cut **before the `"findings":` colon** — or before any key — now
  strips the fragment instead of leaking the `\`\`\`json` fence into the prose;
  (2) a fence line **truncated before its newline** (`\`\`\`json` at EOF, even a
  partial `\`\`\`jso`) is likewise recognised and stripped; (3) `compute_prose_item_id`
  now folds `page_index`, so an identical boilerplate note on two pages of one
  multi-page PDF no longer collides to one id and silently drops a distinct item
  (§14.9); (4) a set-level item recovered by the final reconciliation is tallied as
  `set_level`, not `degraded`; (5) a failure inside the set-level notes writer no
  longer discards the per-source reviewed PDFs already written to disk (the source
  result is committed before the notes writer runs; a notes failure only rolls
  coverage to `INCOMPLETE`).

### Fixed (Phase 21 — artifact-backed markup coverage, DA-007/DA-029)

- **A finding can no longer be reported as clouded when no annotation was written.**
  The old coverage tally was computed from an *intention* classifier
  (`ink_disposition`) — it described what the writer *meant* to draw, never what
  landed in the saved PDF. The writer now follows a **plan → draw → stamp → save →
  reopen → reconcile** protocol (DA-007): every analyzer annotation and every
  generated index row is stamped with a private PDF object key carrying its logical
  **placement id**, and after saving the file is reopened and each placement is
  reconciled against what is actually found. A placement counts only when its
  stamped, mandatory component is found again in the saved artifact; anything
  missing, failed, duplicated, or unexpected is reported honestly.
- **`annotate_pdf` / `write_reviewed_pdfs` now return a
  [`MarkupRunResult`](src/drawing_analyzer/models.py)** — the per-placement
  `MarkupReceipt`s (`WRITTEN` / `INDEXED` / `FAILED`), a **receipt-derived** tally,
  the reviewed-PDF paths, and a `coverage_status` (`COMPLETE` / `INCOMPLETE`). The
  old integer/`list[Path]` returns are available as `result.annots_written` /
  `result.reviewed_pdfs`. A per-finding draw failure becomes a `FAILED` receipt, not
  a silent skip counted as a success (I-3 still holds — the file ships for
  diagnosis).
- **Pre-existing / prior-run annotations can no longer distort reconciliation
  (DA-029).** Stamps embed a per-run `artifact_run_id`, so a stamp left by an
  *earlier* review of the same PDF (a different run id) never satisfies this run's
  plan, and an annotation the analyzer never wrote carries no stamp at all — both
  are transparently ignored. Coverage counts only *this run's* proven marks.
- **Gated and rejected findings now carry a real, reconciled index row.** A
  conservatively **gated** finding (verified-only mode) earns a "Not inked by
  operator gate" index row and a **rejected** finding a "Rejected by verification"
  row — each a proven `INDEXED` placement, never a bare no-artifact status (§6.4).
- **Incomplete markup output is labeled, never presented as complete (§13.6).** A
  reviewed PDF whose planned placements did not all succeed is written under an
  explicit `…_reviewed_INCOMPLETE.pdf` name; the run's `coverage_status` rolls to
  `INCOMPLETE`; the HTML report shows a red **Markup coverage: INCOMPLETE** banner;
  and the GUI's completion line reads **QC incomplete** (distinct from *Completed*
  and *Completed with QC warnings*). A source that changed mid-run (§10.6) is a
  `FAILED` (source-changed) placement, so it forces `INCOMPLETE` too.
- **New `markup_manifest.json` export (§13.7):** every planned placement, its
  terminal receipt, the coverage status, the receipt-derived tally, and the sha256
  of each reviewed PDF. It contains no API key and no absolute path (receipts
  reference basenames only), so it is portable. `00_index.md` and the report list it
  and describe the coverage state.
- **The run summary line is now receipt-derived** — e.g.
  `Ledger 3: 2 clouded, 1 margin, 0 rejected (indexed); coverage COMPLETE` — with
  `failed` / skipped buckets and a coverage verdict; nothing is counted from
  intention.
- Review hardening: each index row is reconciled against **its own** GOTO link (by
  the row's unique position), so two same-page rejected/gated rows can't cover for
  each other's missing link; **every** planned placement gets exactly one terminal
  receipt — an unroutable finding (source id/name matching no supplied PDF) is an
  explicit `FAILED`, never silently dropped into a false `COMPLETE`; a mutated
  source forces `INCOMPLETE` even when it produced no findings; and `FAILED`
  receipt errors carry only the exception *type*, so no absolute path can reach the
  portable manifest.
- Tests: reversed every markup test that asserted an intention-based count or the
  old return types; added `tests/test_drawing_markup_coverage.py`, a
  failure-injection suite that forces clouds, callouts, index pages, saves, and
  reopens to fail and proves the receipts report it (coverage `INCOMPLETE`, no false
  ink), plus prior-run-stamp isolation, pre-existing-annotation isolation (DA-029),
  dual-leg partial coverage, rotated-page receipts, duplicate-basename isolation,
  same-page index-row link matching, unroutable-finding accounting, and the
  portable manifest.

### Fixed (Phase 20 — lossless ledger reconciliation & QC-ID lifecycle, DA-005/DA-006)

- **Deduplication no longer deletes unrelated findings, and no longer fabricates a
  finding by mixing one issue's text with another's quote.** Two findings merge only
  when they are semantically the same *and* their **critical signatures** agree:
  a shared **tile is a search hint, never identity** (same-tile-alone merging is
  gone, DA-005), geometric rectangle overlap alone is never sufficient, and a
  conflicting signature blocks the merge even when the prose is similar —
  `500 gpm` vs `550 gpm`, `M-101` vs `M-102`, `shown` vs `not shown`, or different
  cross-sheet legs. Clustering is now complete-link (compatible with *every* member,
  not just the representative), so an `A+B+C` chain where `A` conflicts with `C`
  never collapses.
- **Coherent grounding (DA-006/§12.2):** a merged entry's grounded bundle — text,
  category, quote, tile, anchor — comes from **one** representative atomically; the
  loser's distinct quote is preserved in a new `supporting_quotes` field rather than
  spliced onto the survivor's text (the reproduced K-factor/relief-valve mixed-finding
  trap is closed). The representative of a cluster is chosen by a **total** quality
  order, so a given set of duplicates always collapses to the same entry and id; the
  pipeline ingests channels in a fixed order, so the run is reproducible (I-7).
- **QC ids are now positional (DA-006/§12.4):** the ledger gained an explicit
  `OPEN → seal() → SEALED → number() → NUMBERED` lifecycle. Numbering happens
  **after** anchoring (the freeze-before-anchor ordering is gone), so `QC-001…`
  follow source input order → page → anchored-before-unanchored → top → left. A
  cautious post-anchor **Pass B** (`reconcile_post_anchor`) folds a duplicate the
  ingest pass couldn't see without geometry. A post-seal add is now an
  invariant failure that marks the run incomplete instead of inventing a `QC-XTRA`
  number that reads like ordinary output.

### Fixed (Phase 19B — cache identity & schema migration, DA-004)

- **A stale cached digest can no longer be served after a visible PDF change.** The
  level-1 (pre-render) cache key hashed only a page's content streams + referenced
  images + `page.rect` *dimensions*, which missed page **rotation** (a 180° flip
  changes neither), a same-size **CropBox** re-crop, and any rendered
  **annotation** — so an edited sheet could hit a stale entry and skip rendering,
  serving the wrong (and, after Phase 19A, wrong-coordinate-space) digest. The
  premise was confirmed empirically against the old fingerprint (180° rotation,
  same-dims CropBox offset, and an added markup all hashed identically).
- **Level-1 identity rebased on the whole source file's `content_sha256`** (§11.5):
  hashed **once per source** (reusing the inventory's value), it covers every byte —
  content, forms, images, rotation, CropBox, and annotation appearance streams — so
  any visible change re-keys. Folded in alongside it: the canonical coordinate-space
  version (`PAGE_VIEW_V2`), a **renderer-environment fingerprint** (OS/arch +
  PyMuPDF/MuPDF build, so a cache moved between installations misses rather than
  serving pixels this one wouldn't reproduce), the annotation-render policy, the
  page index/count, the grid/overlap/target, the blank-suppression mode, and the
  text-extraction cap. The per-page object-graph fingerprint is retired (the
  whole-source hash subsumes its form-XObject special case). The prescan hashes the
  bytes **on disk at prescan time**: it reuses the inventory hash through a `stat`
  fast-gate but **re-hashes on any drift** (`current_content_sha256`), so a source
  rewritten between the inventory and the prescan keys on its *current* revision —
  a stale level-1 hit that served the previous revision's digest is impossible
  (§10.6), including in a non-markup run the mid-run mutation check doesn't cover.
- **Critique level-1 cache added** (`critique_cache_key_level1`): the critique reads
  the same images as the digest, so an unchanged exhaustive re-run previously had to
  rasterize every sheet merely to compute the PNG-bytes critique key and discover
  the result was already cached. A pre-render level-1 scan now serves a cached
  critique with **neither a render nor an API call**; misses render, critique, and
  store under the level-1 key too (store-under-both). A warm exhaustive re-run now
  skips **both** the critique API calls and rasterization.
- **Cache schema bumped to 5**, so every pre-existing level-1 / critique entry
  misses once and is recomputed (a concise expectation, not a run error). Two
  critique cache-serving/storing helpers were extracted so the level-1 and level-2
  tiers materialize a hit and a stored entry through one code path.

### Fixed (Phase 19A — canonical page geometry, DA-003)

- **Findings are now placed correctly on rotated and cropped drawing pages.** A
  sheet with `/Rotate 90|180|270`, or a `CropBox` smaller than / offset from the
  `MediaBox`, previously mis-placed its findings: the anchor rectangle came from
  PyMuPDF's un-rotated, CropBox-relative text-extraction space, but the
  verification crop clips in the *rotated* page-view space — so on a rotated page
  the crop the verifier saw was blank, tile disambiguation chose the wrong
  occurrence of a repeated quote, and margin callouts drifted. The two spaces were
  characterized empirically against the pinned `pymupdf==1.28.0` (rendering real
  pixels, preserved as fixtures in `tests/test_drawing_geometry.py`), not assumed.
- **One canonical coordinate space, `PAGE_VIEW_V2`** (top-left origin, post-CropBox,
  post-rotation — the frame of the images the model reads) now carries every word
  rectangle, anchor, verification crop, and persisted finding rectangle.
  `render.py` transforms extracted words into view space once (via the page's
  rotation matrix) and captures a new `PageGeometry` (view dims, MediaBox/CropBox,
  rotation, and both affine matrices as plain floats) on `RenderedSheet` /
  `SheetGeometry`. `annotate.py` transforms each rectangle/point back to page space
  (via the derotation matrix) at the write boundary and draws FreeText callouts with
  `rotate=page.rotation` so they read upright on a rotated sheet. `anchor.py`,
  `tiling.py`, and `verify.py` are unchanged in logic — they now operate on
  view-space coordinates consistently and remain PyMuPDF-free.
- **New pure helpers** `models.normalize_rect` / `models.transform_rect` (finite +
  positive-area validation; a rect that inverts under a transform is *sorted*, never
  clamped — so the previously reproducible inverted rectangle is impossible by
  construction). `models.PageGeometry` round-trips to/from `dict` additively.
- **No coordinate flip on an ordinary page:** rotation 0 with a default CropBox
  yields identity transforms, so the common case is byte-for-byte unchanged. The
  digest cache is intentionally untouched here — anchors are recomputed every run
  from freshly-extracted view-space words, so no stale-space rectangle can be
  served; the level-1 fingerprint's coverage of rotation/CropBox/annotations is
  Phase 19B. I-5 is preserved (the new geometry math is pure Python; the PyMuPDF
  transforms live only in `render.py` / `annotate.py`).

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
