# Windows manual acceptance — cost preview (WP-05 §10.5)

The confirmation-time cost preview reads geometry the profile preflight already
produced, so most of it is covered by the hermetic suite. What is **not** covered
needs a real window: the cases below all turn on timing between a background scan
and a user who is clicking faster than it finishes.

Run on Windows, with the GUI (`drawing-analyzer`), on a set of at least 20 sheets
that includes one dense schedule sheet. Nothing here spends money — every step
stops at the confirmation dialog.

| # | Step | Expected |
|---|---|---|
| 1 | Load a set, wait for the profile checkboxes to settle, click **Analyze** | Dialog says *"Based on each page's measured size and text layer."* |
| 2 | Load a set and click **Analyze** immediately, before the checkboxes settle | Dialog says *"Conservative planning estimate…"*, and the figure is higher. No freeze, no spinner, no wait |
| 3 | Load set A, wait for it to settle, then replace it with set B and click **Analyze** at once | Conservative — never set A's measured figure applied to set B |
| 4 | Rapidly replace the file list 4–5 times, then wait | The checkboxes and the estimate settle on the **last** selection only |
| 5 | Include a deliberately damaged PDF (rename a `.txt`) | The set still loads, the estimate still appears (conservative), no traceback dialog |
| 6 | Toggle **QC markups**, **Economy/Hybrid/Fast**, and a focus with a set already measured | The per-stage table and the band update; the basis line still says *measured* — toggling options does not discard the scan |
| 7 | Click **Cancel** on the confirmation | Nothing is sent. No file appears in the Files API, no batch is created |
| 8 | Close the window while the preflight is still running | No error dialog, no hang on exit |
| 9 | Load a set from a path containing spaces and a non-ASCII character | Both the estimate and the confirmation render correctly |
| 10 | Compare step 1's figure against the run's actual reported cost afterwards | The measured estimate should be the closer of the two, and the run should not exceed it by more than the text-token caveat allows |

Step 10 is the only one that costs money; run it once, deliberately, on a set you
were going to review anyway.

**If step 2 shows a visible freeze**, the design assumption behind §10.3 has
failed and the plan's revision-1 background-worker design is the specification to
return to. It should not: nothing on the Analyze path opens a PDF. Record the
sheet count and word count if it happens.
