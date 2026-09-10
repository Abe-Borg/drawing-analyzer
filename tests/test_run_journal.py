"""Tests for the Phase 26A run journal (§18.1–18.3, DA-024).

Fully hermetic: plain Python objects, no PyMuPDF, no network, no key. The
journal is the storage boundary for everything ``run.log`` will show, so the
tests here concentrate on the §18.3 guarantees — secrets and absolute paths
can never *enter* the journal — and on the §18.1 concurrency contract (a
thread-safe, monotonic, unambiguous event sequence).
"""
from __future__ import annotations

import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

from drawing_analyzer.run_journal import (
    MAX_FIELD_CHARS,
    RunJournal,
    collect_environment,
    new_run_id,
    redact_for_display,
    render_run_log,
    sanitize_text,
    scrub_paths,
)

# Assembled from fragments so no live-looking key shape exists in the source
# (mirrors tests/test_diagnostics.py).
_ANT = "sk-" + "ant-"
_FAKE_KEY = _ANT + "api03-abcdef1234567890"


# --------------------------------------------------------------------------- #
# sanitization: scrub_paths / sanitize_text (§18.3)
# --------------------------------------------------------------------------- #


def test_scrub_paths_reduces_absolute_paths_to_basename():
    # The product invariant (§18.2): no absolute path in a portable artifact —
    # the directory structure is private; the basename matches display names.
    assert scrub_paths("/home/user/secret/M-101.pdf") == ".../M-101.pdf"
    assert scrub_paths(r"C:\Users\abe\Desktop\M-101.pdf") == ".../M-101.pdf"
    assert scrub_paths(r"\\server\share\dwg\M-101.pdf") == ".../M-101.pdf"
    assert scrub_paths("at C:/data/dwg/x.pdf end") == "at .../x.pdf end"


def test_scrub_paths_handles_quoted_spacey_and_file_urls():
    # OSError reprs quote the path, making spaces unambiguous.
    assert (
        scrub_paths("[Errno 2] No such file: '/home/a b/f.pdf'")
        == "[Errno 2] No such file: '.../f.pdf'"
    )
    assert (
        scrub_paths(r"open('C:\Program Files\App\y.pdf')")
        == "open('.../y.pdf')"
    )
    assert scrub_paths("file:///home/user/x.pdf") == "file://.../x.pdf"


def test_scrub_paths_leaves_urls_and_relative_paths_alone():
    # https URLs (citation sources) and relative/token slashes are not paths.
    assert (
        scrub_paths("see https://example.com/a/b for details")
        == "see https://example.com/a/b for details"
    )
    assert scrub_paths("//cdn.example.com/x/y") == "//cdn.example.com/x/y"
    assert scrub_paths("tile r1c1/r2c2 and a/b/c stay") == "tile r1c1/r2c2 and a/b/c stay"


def test_sanitize_text_redacts_secrets_flattens_and_bounds():
    out = sanitize_text(f"key {_FAKE_KEY}\nnext /home/x/y.png line")
    assert _FAKE_KEY not in out
    assert "sk-ant-[REDACTED]" in out
    assert "\n" not in out                       # one event = one line
    assert ".../y.png" in out

    long = sanitize_text("x" * 1000)
    assert len(long) < 1000
    assert long.startswith("x" * MAX_FIELD_CHARS)
    assert "chars]" in long                      # explicit truncation marker


def test_sanitize_text_never_raises_on_hostile_objects():
    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    out = sanitize_text(Unprintable())
    assert "Unprintable" in out


def test_sanitize_text_redacts_nested_dict_reprs():
    payload = {"headers": {"x-api-key": _FAKE_KEY}, "path": "/home/user/f.pdf"}
    out = sanitize_text(payload)
    assert _FAKE_KEY not in out
    assert "/home/user" not in out


# --------------------------------------------------------------------------- #
# RunJournal: identity, emit, concurrency, isolation (§18.1)
# --------------------------------------------------------------------------- #


def test_new_run_id_shape_and_uniqueness():
    a, b = new_run_id(), new_run_id()
    assert a.startswith("RUN-") and len(a) == 4 + 12
    assert a != b


def test_emit_assigns_contiguous_sequences_under_concurrency():
    # §18.1: a thread-safe monotonic sequence so concurrent stage events are
    # unambiguous — digest workers emit from a pool.
    journal = RunJournal(run_id="RUN-concurrency")
    threads = [
        threading.Thread(
            target=lambda i=i: [
                journal.emit("SHEET_DIGESTED", stage="digest", worker=i, n=n)
                for n in range(50)
            ]
        )
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sequences = [e.sequence for e in journal.events]
    assert len(sequences) == 400
    assert sequences == sorted(sequences)                 # append order == sequence order
    assert sequences == list(range(1, 401))               # contiguous from 1, no gaps/dupes


def test_emit_sanitizes_every_field_value_at_storage_time():
    journal = RunJournal()
    journal.emit(
        "API_ERROR",
        stage="digest",
        detail=f"401 x-api-key: {_FAKE_KEY}",
        path="/home/user/drawings/M-101.pdf",
    )
    event = journal.events[0]
    stored = " ".join(event.fields.values())
    assert _FAKE_KEY not in stored
    assert "/home/user" not in stored
    assert ".../M-101.pdf" in stored
    # And the rendered forms can't reintroduce it.
    assert _FAKE_KEY not in event.line()
    assert _FAKE_KEY not in str(event.to_dict())


def test_emit_never_raises_and_degrades_bad_levels():
    journal = RunJournal()

    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    journal.emit("WEIRD", level="chartreuse", value=Unprintable())
    assert journal.events[0].level == "INFO"
    assert "Unprintable" in journal.events[0].fields["value"]


def test_two_journals_never_contaminate_each_other():
    # §18.2 required test: two runs never contaminate one another.
    a, b = RunJournal(), RunJournal()
    a.emit("RUN_START", run="a")
    b.emit("RUN_START", run="b")
    a.emit("RUN_END")
    assert a.run_id != b.run_id
    assert [e.event_code for e in a.events] == ["RUN_START", "RUN_END"]
    assert [e.event_code for e in b.events] == ["RUN_START"]
    assert b.events[0].sequence == 1                      # sequences are per-journal


def test_finish_stamps_end_time_and_status():
    journal = RunJournal()
    assert journal.ended_at is None
    journal.finish("PARTIAL")
    assert journal.ended_at is not None
    assert journal.final_status == "PARTIAL"


def test_stage_durations_pair_start_and_end_events():
    t0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    ticks = [t0, t0, t0 + timedelta(seconds=2.5), t0 + timedelta(seconds=9)]

    def clock() -> datetime:
        return ticks.pop(0) if ticks else t0 + timedelta(seconds=9)

    journal = RunJournal(clock=clock)                     # first tick = started_at
    journal.emit("STAGE_START", stage="critique")
    journal.emit("STAGE_END", stage="critique", status="COMPLETE")
    journal.emit("STAGE_END", stage="verify", status="COMPLETE")  # no start → absent
    durations = journal.stage_durations()
    assert durations == {"critique": 2.5}


def test_collect_environment_reports_versions_without_pymupdf_import():
    env = collect_environment(model="claude-opus-5")
    assert set(env) >= {"os", "python", "app", "pymupdf", "anthropic_sdk", "model"}
    # Values are strings and already sanitized.
    assert all(isinstance(v, str) for v in env.values())


# --------------------------------------------------------------------------- #
# render_run_log (§18.2) — duck-typed on the context like export.py
# --------------------------------------------------------------------------- #


class _MiniCtx:
    """The minimum duck-typed context render_run_log must tolerate."""

    qc_status = "NOT_REQUESTED"
    coverage_status = "NOT_REQUESTED"
    sheet_count = 2
    errors: list = []
    sheets: list = []


def test_render_without_journal_still_produces_a_log():
    text = render_run_log(_MiniCtx())
    assert "Drawing Analyzer — run log" in text
    assert "no run journal was recorded" in text
    assert "Final status:" in text


def test_render_includes_header_events_and_outputs():
    journal = RunJournal(run_id="RUN-render-test")
    journal.set_environment(collect_environment(model="claude-opus-5"))
    journal.emit("RUN_START", files=1)
    journal.emit("RUN_END", status="NOT_REQUESTED")
    journal.finish("NOT_REQUESTED")
    ctx = _MiniCtx()
    ctx.run_journal = journal

    text = render_run_log(ctx, outputs=["report.html", "findings.json"])
    assert "RUN-render-test" in text
    assert "Event trace (2 event(s))" in text
    assert "RUN_START" in text and "RUN_END" in text
    assert "report.html" in text and "findings.json" in text
    assert "run.log — this file" in text
    assert "run_manifest.json — written after this log" in text
    # §18.2: environment identity in the header.
    assert "python=" in text and "model=claude-opus-5" in text


def test_render_outcome_lines_match_gui_three_state():
    # §3.3: the GUI dialog, run.log, and report header must show the same state.
    def outcome(**kw):
        ctx = _MiniCtx()
        for k, v in kw.items():
            setattr(ctx, k, v)
        return render_run_log(ctx)

    assert "FAILED — no sheets were analyzed" in outcome(sheet_count=0)
    # A failed/incomplete QC still shipped its digest → run outcome PARTIAL.
    assert "PARTIAL — QC incomplete" in outcome(qc_status="FAILED")
    assert "QC incomplete" in outcome(qc_status="PARTIAL", markup_incomplete=True)
    # Label wording matches DrawingContext.qc_status_label exactly (§3.3).
    assert "PARTIAL — Completed with QC warnings" in outcome(qc_status="PARTIAL")
    assert "Exhaustive QC complete" in outcome(qc_status="COMPLETE")
    assert "no QC requested" in outcome(qc_status="NOT_REQUESTED")
    # And the run-level outcome distinguishes a clean standard run (COMPLETE)
    # from one with errors (PARTIAL) even though QC was never requested.
    assert "COMPLETE — standard analysis (no QC requested)" in outcome()
    assert "PARTIAL — standard analysis completed with warnings" in outcome(
        errors=["boom"]
    )


def test_render_never_leaks_secrets_or_paths_from_context_errors():
    ctx = _MiniCtx()
    ctx.errors = [f"boom {_FAKE_KEY} at /home/user/private/x.pdf"]
    text = render_run_log(ctx)
    assert _FAKE_KEY not in text
    assert "/home/user/private" not in text
    assert "sk-ant-[REDACTED]" in text
    assert ".../x.pdf" in text


# --------------------------------------------------------------------------- #
# Review-fix regressions (Phase 26A review)
# --------------------------------------------------------------------------- #

from drawing_analyzer.run_journal import derive_run_outcome  # noqa: E402


def test_scrub_paths_never_mangles_urls_with_colon_segments():
    # A ':' immediately before a path slash inside a URL (MediaWiki File:,
    # drive-style S3 keys) must survive byte-identical — URLs are masked
    # during the scrub, not pattern-dodged.
    url = "see https://en.wikipedia.org/wiki/File:/x/y.png ok"
    assert scrub_paths(url) == url
    # …while a colon-label PATH (usage-instance style) still scrubs.
    assert scrub_paths("digest:/home/user/private/M-101.pdf:p0") == "digest:.../M-101.pdf:p0"


def test_scrub_paths_drive_form_needs_a_directory():
    # Prose like "option A:/B" or "drive C:\ is full" is not a path (no
    # directory component → nothing to leak) and must not be eaten.
    assert scrub_paths("option A:/B") == "option A:/B"
    assert scrub_paths("drive C:\\ is full") == "drive C:\\ is full"
    assert scrub_paths("bare C:/x stays") == "bare C:/x stays"
    assert scrub_paths("C:/Users/x.pdf") == ".../x.pdf"


def test_scrub_paths_file_urls_case_insensitive():
    assert scrub_paths("File:///home/user/private/M-101.pdf") == "file://.../M-101.pdf"
    assert scrub_paths("FILE://C:/Users/abe/x.pdf") == "file://.../x.pdf"


def test_private_roots_scrub_spacey_directories():
    # The literal known-roots pass is what handles spacey Windows dirs the
    # bare regexes cannot bound (§18.3).
    journal = RunJournal()
    journal.add_private_roots([r"C:\Users\John Smith\Project X"])
    journal.emit(
        "API_ERROR",
        detail=r"open failed: C:\Users\John Smith\Project X\M-101.pdf busy",
    )
    stored = journal.events[0].fields["detail"]
    assert "John Smith" not in stored and "Project X" not in stored
    assert "M-101.pdf" in stored
    # Forward-slash spelling of the same root scrubs too.
    journal.emit("API_ERROR", detail="C:/Users/John Smith/Project X/E-201.pdf")
    assert "John Smith" not in journal.events[1].fields["detail"]


def test_private_roots_scrub_whatever_case_the_path_arrives_in():
    """P9 item 44 — a Windows path is the same directory in any case.

    ``Path.resolve()`` yields ``C:\\…``; a path echoed from a config file, a
    drag-and-drop or a lowercased comparison can arrive as ``c:\\…``, and
    ``str.replace`` matches neither the other's spelling. The regex backstop in
    ``scrub_paths`` cannot bound a path containing spaces, so that one lowercase
    drive letter put ``Abe Borg\\My Drawings`` — the user's own name — into
    run.log and run_manifest.json, both of which exist to be shareable.
    """
    root = r"C:\Users\Abe Borg\My Drawings"
    spellings = [
        rf"open failed: {root}\SET 01.pdf",                          # as registered
        r"open failed: c:\Users\Abe Borg\My Drawings\SET 01.pdf",     # lower drive
        r"open failed: c:\users\abe borg\my drawings\SET 01.pdf",     # all lower
        r"open failed: C:/Users/Abe Borg/My Drawings/SET 01.pdf",     # forward
        r"open failed: c:\Users/Abe Borg\My Drawings/SET 01.pdf",     # mixed
    ]
    for text in spellings:
        out = sanitize_text(text, private_roots=(root,))
        assert "Abe Borg" not in out and "My Drawings" not in out, text
        # The basename is the useful, non-private part and must survive.
        assert "SET 01.pdf" in out, text


def test_a_private_root_never_matches_a_sibling_directory():
    """A root match must end at a component boundary (Codex review, P9).

    Without one, root ``C:\\Projects\\Job`` matched the *sibling*
    ``C:\\Projects\\Job2\\…`` on its prefix, and the partial rewrite was worse
    than no match at all: it produced ``...2\\Client Secret\\file.pdf``, and with
    the drive letter eaten ``scrub_paths`` could no longer anchor the remainder
    to reduce it. A non-boundary match now falls through to that backstop, which
    strips the drive and the first component.
    """
    root = r"C:\Projects\Job"
    for sibling in (
        r"PermissionError: C:\Projects\Job2\Client Secret\file.pdf",
        r"PermissionError: C:\Projects\JobArchive\Client X\a.pdf",
        r"PermissionError: C:/Projects/Job-old/Client Y/b.pdf",
    ):
        out = sanitize_text(sibling, private_roots=(root,))
        # The tell-tale of the prefix match: a bare "..." glued to the rest of
        # the sibling's own name.
        assert not out.startswith("PermissionError: ...2"), out
        assert "...2" not in out and "...Archive" not in out and "...-old" not in out
        # The backstop still ran, so the drive and first component are gone.
        assert "C:" not in out and "Projects" not in out, out

    # ...and the real root, with or beyond a boundary, still scrubs.
    assert "Projects" not in sanitize_text(
        rf"PermissionError: {root}\SET 01.pdf", private_roots=(root,)
    )
    assert sanitize_text(f"open {root}", private_roots=(root,)) == "open ..."
    assert "Projects" not in sanitize_text(
        r'open "C:\Projects\Job\SET 01.pdf" failed', private_roots=(root,)
    )


def test_private_root_matching_is_literal_not_a_pattern():
    """Regex metacharacters in a real directory name must not become syntax."""
    root = r"C:\Users\a+b (draft) [v2]"
    out = sanitize_text(rf"open failed: {root}\SET.pdf", private_roots=(root,))
    assert "a+b" not in out and "(draft)" not in out
    assert "SET.pdf" in out
    # ...and the wildcard reading of "." must not eat an unrelated character.
    assert sanitize_text("CxUsers stays", private_roots=(r"C:Users",)) == "CxUsers stays"


def test_every_run_log_section_scrubs_the_known_roots():
    """P9 item 44 — the roots reached only the Errors section.

    A rejected input's ``PermissionError``, a per-sheet error, a stage note and a
    mutated-source name all render through ``sanitize_text`` too; none of them
    was given the roots, so the same string was scrubbed in one section of
    run.log and printed in full two sections above it.
    """
    root = r"C:\Users\Abe Borg\My Drawings"
    leak = r"PermissionError: c:\Users\Abe Borg\My Drawings\Job 4471\SET 01.pdf"
    journal = RunJournal()
    journal.add_private_roots([root])

    class _Ref:
        display_label = "M-101"
        key = ("src", 0)
        page_index = 0

    class _Sheet:
        ref = _Ref()
        ok = False
        cached = False
        text = ""
        error = leak
        findings_note = leak

    class _Doc:
        source_id = "SRC-0001"
        status = "REJECTED"
        display_name = "SET 01.pdf"
        page_count = 0
        accepted = False
        error = leak
        duplicate_of = ""

    class _Stage:
        stage = "digest"
        status = "FAILED"
        expected = True
        calls_planned = 1
        calls_succeeded = 0
        items_in = 1
        items_out = 0
        errors = [leak]
        warnings: list = []

    class _Inventory:
        documents = [_Doc()]

    class _Ctx:
        run_journal = journal
        errors = [leak]
        sheets = [_Sheet()]
        sheet_geometries: list = []
        stage_results = [_Stage()]
        input_inventory = _Inventory()
        mutated_sources = [leak]
        reviewed_pdf_paths: list = []
        findings: list = []
        reference_findings: list = []
        markup_run = None
        coverage_status = "INCOMPLETE"
        ledger_tally_line = leak

    log = render_run_log(_Ctx())
    assert "Abe Borg" not in log and "My Drawings" not in log
    # Each of those sections still rendered its row — the roots are removed, not
    # the diagnostic.
    assert "SRC-0001" in log and "M-101" in log and "digest" in log


def test_no_sanitize_call_in_this_module_omits_the_private_roots():
    """Structural: the next renderer cannot silently forget the roots.

    The bug was one call site out of nine passing ``private_roots``. An
    assertion about today's nine cannot see the tenth, so this asserts the rule
    over the module's AST instead — the same technique
    ``test_run_acceptance.py`` uses for the ``pytest`` argv literal.
    """
    import ast

    source = (
        Path(__file__).resolve().parent.parent
        / "src" / "drawing_analyzer" / "run_journal.py"
    ).read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in ("sanitize_text", "redact_for_display"):
            continue
        if not any(kw.arg == "private_roots" for kw in node.keywords):
            offenders.append(f"line {node.lineno}")
    assert not offenders, (
        "every sanitize_text/redact_for_display call in run_journal.py must pass "
        f"private_roots (P9 item 44); missing at: {offenders}"
    )


def test_redact_for_display_keeps_newlines_and_length():
    """The report boundary is the log boundary minus flattening and truncation."""
    long_text = "detail " * 400
    out = redact_for_display("line one\nline two")
    assert out == "line one\nline two"
    assert "[+" not in redact_for_display(long_text)
    # ...but the secret and path passes are the same ones.
    assert "[REDACTED]" in redact_for_display("x-api-key: placeholder-value-0000")
    assert redact_for_display("/home/user/private/M-101.pdf") == ".../M-101.pdf"


def test_sanitize_text_strips_html_error_pages_only():
    flooded = "<html><head><title>503</title></head><body>Service Unavailable</body></html>"
    out = sanitize_text(f"API error: {flooded}")
    assert "<html>" not in out and "Service Unavailable" in out
    # An ordinary comparison with angle brackets survives.
    assert sanitize_text("expects a < b and c > d") == "expects a < b and c > d"


def test_derive_run_outcome_matrix():
    # Run-level terminal status is distinct from the §3.3 QC status (§18.2).
    assert derive_run_outcome(ok_sheets=0, error_count=0, qc_status="NOT_REQUESTED") == "FAILED"
    assert derive_run_outcome(ok_sheets=3, error_count=0, qc_status="NOT_REQUESTED") == "COMPLETE"
    assert derive_run_outcome(ok_sheets=3, error_count=1, qc_status="NOT_REQUESTED") == "PARTIAL"
    assert derive_run_outcome(ok_sheets=3, error_count=0, qc_status="PARTIAL") == "PARTIAL"
    assert derive_run_outcome(ok_sheets=3, error_count=0, qc_status="FAILED") == "PARTIAL"
    assert (
        derive_run_outcome(
            ok_sheets=3, error_count=0, qc_status="COMPLETE", coverage_status="INCOMPLETE"
        )
        == "PARTIAL"
    )
    assert derive_run_outcome(ok_sheets=3, error_count=0, qc_status="COMPLETE") == "COMPLETE"


def test_render_counts_empty_error_free_digest_as_failed():
    # SheetDigest.ok = error-free AND non-empty: an empty, error-free digest is
    # a failure in every accounting surface, not a phantom "ok" row.
    from types import SimpleNamespace

    ref = SimpleNamespace(display_label="M-101.pdf (page 1/1)", key=("SRC-0001", 0))
    ctx = _MiniCtx()
    ctx.sheets = [
        SimpleNamespace(ref=ref, ok=False, error=None, text="", cached=False,
                        findings_note=""),
    ]
    text = render_run_log(ctx)
    assert "1 sheet(s): 0 ok, 1 failed" in text
    assert "(empty digest)" in text


def test_render_section_failure_costs_one_section_not_the_log():
    # A hostile duck-typed field degrades its own section; the log still
    # renders end to end (the export's never-fatal charter).
    ctx = _MiniCtx()
    ctx.prose_accounting = {"items": object()}   # unformattable in the order tuple
    ctx.usage_by_family = {"digest": {"calls": "three"}}
    text = render_run_log(ctx)
    assert "Drawing Analyzer — run log" in text
    assert "Final status:" in text
