"""The ``diagnostics/`` folder every export carries: the run, call by call.

``run.log`` and ``run_manifest.json`` summarize a run. This folder holds the
detail behind those summaries, in forms a spreadsheet or a script can open:

- ``00_summary.md`` — the answers first (did the agents have room to work,
  were they starved by the API or the computer, which models ran where), then
  the per-stage headroom table, the model map and a guide to every file.
- ``api_calls.csv`` / ``api_calls.json`` — one row per model call: stage,
  work item (sheet / QC id / code reference), model asked for and model that
  answered, effort, thinking mode, output cap and how much of it was used,
  tools offered with their per-call limits and how many were used, stop
  reason, tokens, duration, message id (:mod:`~drawing_analyzer.call_telemetry`).
- ``agent_headroom.json`` — the per-stage provisioning and headroom verdicts
  and the model map (also embedded in ``run_manifest.json``).
- ``api_retries.csv`` — every transient API failure the run waited out or gave
  up on (:mod:`~drawing_analyzer.resource_pressure`).
- ``host_samples.csv`` — the host CPU / memory / disk / thread timeline the
  sampler recorded while the agents worked.
- ``events.csv`` — the run journal's event trace, one event per row.

Everything here is counts, labels and identifiers: no prompt, no drawing text,
no reply, no image, no key, no directory. Free-form strings pass the journal's
sanitize boundary (secrets redacted, private directories and absolute paths
scrubbed) exactly as ``run.log`` does. CSVs are UTF-8 with a BOM and CRLF, like
``findings.csv``, so Excel opens them directly. Each file is written
independently and a failure costs that file only (I-3 spirit): the folder is
advisory and must never sink the export.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Callable

from .call_telemetry import CSV_COLUMNS, csv_cell
from .run_journal import redact_for_display, sanitize_text

DIAGNOSTICS_DIR = "diagnostics"
SCHEMA_VERSION = 1

_RETRY_COLUMNS = (
    "at", "stage", "kind", "status", "attempt", "backoff_seconds",
    "retry_after_seconds", "gave_up", "request_id", "rate_limit",
)
_EVENT_COLUMNS = ("sequence", "timestamp", "level", "stage", "event_code", "fields")


def _roots(ctx: Any) -> tuple[str, ...]:
    return tuple(getattr(getattr(ctx, "run_journal", None), "private_roots", ()) or ())


def _qc_ids(ctx: Any) -> dict[str, str]:
    """Finding id → ``QC-###``: verify / investigate items name the finding id."""
    out: dict[str, str] = {}
    for f in list(getattr(ctx, "findings", None) or []) + list(
        getattr(ctx, "reference_findings", None) or []
    ):
        fid = str(getattr(f, "id", "") or "")
        qc = str(getattr(f, "qc_id", "") or "")
        if fid and qc:
            out[fid] = qc
    return out


def _call_rows(ctx: Any) -> list[dict]:
    telemetry = getattr(ctx, "call_telemetry", None)
    if telemetry is None:
        return []
    roots = _roots(ctx)
    qc_ids = _qc_ids(ctx)
    rows = []
    for record in telemetry.snapshot():
        row = record.to_dict()
        row["item"] = sanitize_text(row["item"], max_chars=160, private_roots=roots)
        row["error"] = sanitize_text(row["error"], max_chars=300, private_roots=roots)
        row["qc_id"] = qc_ids.get(row["item"].split(":", 1)[0], "")
        rows.append(row)
    return rows


def _csv_text(columns: tuple[str, ...], rows: list[dict]) -> str:
    from .export import _excel_safe

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col)
            cell = csv_cell(value)
            # Only text can carry a formula sigil; numbers keep their sign.
            cells.append(_excel_safe(cell) if isinstance(value, str) else cell)
        writer.writerow(cells)
    return buf.getvalue()


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        fp.write(_csv_text(columns, rows))


def _write_json(path: Path, payload: Any, roots: tuple[str, ...]) -> None:
    def _default(value: Any) -> str:
        return sanitize_text(value, private_roots=roots)

    path.write_text(json.dumps(payload, indent=2, default=_default), encoding="utf-8")


def _sanitized(value: Any, roots: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, private_roots=roots)
    if isinstance(value, dict):
        return {k: _sanitized(v, roots) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitized(v, roots) for v in value]
    return value


# --------------------------------------------------------------------------- #
# 00_summary.md
# --------------------------------------------------------------------------- #


def _md(text: Any) -> str:
    """One Markdown table cell: no pipes, no newlines."""
    return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ")


def _tally_text(tally: dict) -> str:
    """``high`` when every call agreed, else ``high x3, medium x2``."""
    if len(tally) == 1:
        return str(next(iter(tally)))
    return ", ".join(f"{k} x{v}" for k, v in tally.items()) or "—"


def _stage_row(s: dict) -> str:
    cap = s.get("max_tokens")
    cap_text = "—" if not cap else (
        f"{cap['min']:,}" if cap["min"] == cap["max"] else f"{cap['min']:,}–{cap['max']:,}"
    )
    peak = s.get("output_fraction_peak")
    peak_text = "—" if peak is None else f"{peak:.0%} ({s['output_tokens_peak']:,} tok)"
    ceiling = s.get("model_effort_ceiling") or {}
    effort = _tally_text(s.get("effort") or {})
    if ceiling:
        effort += " (model max: " + "/".join(sorted(set(ceiling.values()))) + ")"
    tools = []
    for name, limit in (s.get("tools_offered") or {}).items():
        used = (s.get("tool_calls") or {}).get(name, 0)
        tools.append(f"{name} {used}" + (f" (≤{limit}/call)" if limit else ""))
    for name, info in (s.get("item_limits") or {}).items():
        tools.append(
            f"{name.replace('_', ' ')} ≤{info['limit']}/item, most asked {info['max_requested']}"
        )
    cells = [
        s["stage"], f"**{s['verdict']}**", s["calls"], _tally_text(s.get("models") or {}),
        effort, _tally_text(s.get("thinking") or {}), cap_text, peak_text,
        f"{s['max_tokens_stops']} ({s['max_tokens_unrecovered']} unrecovered)",
        "; ".join(tools) or "—",
    ]
    return "| " + " | ".join(_md(c) for c in cells) + " |"


def build_summary_markdown(ctx: Any, *, call_rows: list[dict] | None = None) -> str:
    """The folder's ``00_summary.md`` (pure; no I/O)."""
    roots = _roots(ctx)
    journal = getattr(ctx, "run_journal", None)
    pressure = getattr(ctx, "resource_pressure", None)
    telemetry = getattr(ctx, "call_telemetry", None)
    call_rows = _call_rows(ctx) if call_rows is None else call_rows

    lines = ["# Run diagnostics", ""]
    ident = []
    if journal is not None:
        ident.append(f"Run `{getattr(journal, 'run_id', '')}`")
        started = getattr(journal, "started_at", None)
        if started is not None:
            ident.append(f"started {started.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        final = str(getattr(journal, "final_status", "") or "")
        if final:
            ident.append(f"outcome **{final}**")
    if ident:
        lines += [" · ".join(ident), ""]

    stages = telemetry.stage_summaries() if telemetry is not None else []
    headroom = (
        sanitize_text(telemetry.summary_line(), max_chars=600, private_roots=roots)
        if telemetry is not None else "not assessed (no per-call record was attached)"
    )
    starvation = "not assessed (no resource-pressure record was attached)"
    if callable(getattr(pressure, "summary_line", None)):
        starvation = sanitize_text(pressure.summary_line(), max_chars=600, private_roots=roots)
    fallbacks = getattr(getattr(ctx, "run_usage", None), "model_fallbacks", None)
    fallback_rows = list(fallbacks()) if callable(fallbacks) else []
    fallback_text = "No — every response came from the model the stage asked for."
    if fallback_rows:
        fallback_text = "Yes — " + "; ".join(
            f"{r['stage_family']}: {r['requested_model']} declined, "
            f"{r['served_model']} served {r.get('responses', 0)}"
            for r in fallback_rows
        )
    models: dict[str, int] = {}
    for row in call_rows:
        model = row.get("served_model") or row.get("model") or "(unknown)"
        models[model] = models.get(model, 0) + 1
    calls_text = (
        f"{len(call_rows)} model call(s): " + _tally_text(dict(sorted(models.items())))
        if call_rows else "No model call was made (every stage was served from cache or did not run)."
    )
    lines += [
        "| Question | Answer |",
        "|---|---|",
        "| Did the agents have enough room to work — output cap, effort, thinking, "
        f"tools and their limits, per-item budgets? | {_md(headroom)} |",
        "| Were they starved by the API (throttling) or by this computer "
        f"(CPU, memory, disk)? | {_md(starvation)} |",
        f"| Did another model answer after a refusal? | {_md(fallback_text)} |",
        f"| How many model calls, on which models? | {_md(calls_text)} |",
        "",
    ]

    lines += ["## Agent headroom by stage", ""]
    if stages:
        lines += [
            "What each stage was given, and how close to each limit it ran. "
            "Output used counts thinking and reply together (adaptive thinking "
            "shares the `max_tokens` envelope).",
            "",
            "| Stage | Verdict | Calls | Model | Effort | Thinking | Output cap "
            "(max_tokens) | Peak output used | Cap hits | Tools used (limit) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += [_stage_row(s) for s in stages]
        flagged = [s for s in stages if s.get("reasons")]
        if flagged:
            lines += ["", "**Why**", ""]
            for s in flagged:
                for reason in s["reasons"]:
                    lines.append(
                        f"- **{s['stage']} — {s['verdict']}**: "
                        + sanitize_text(reason, max_chars=300, private_roots=roots)
                    )
        lost = [s for s in stages if s.get("abilities_dropped")]
        if lost:
            lines += ["", "Abilities lost mid-run (a self-healing latch turned them off "
                      "after an API rejection):", ""]
            lines += [f"- {s['stage']}: " + ", ".join(s["abilities_dropped"]) for s in lost]
    else:
        lines.append("No model call was recorded for this run.")
    lines.append("")

    lines += ["## Where each model was called", ""]
    model_map = telemetry.model_map() if telemetry is not None else []
    if model_map:
        lines += [
            "| Model | Stage | Calls | Real-time | Batch | Work items | Input tokens | Output tokens |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in model_map:
            model = r["model"]
            if r.get("requested_as"):
                model += " (refusal fallback for " + ", ".join(r["requested_as"]) + ")"
            lines.append("| " + " | ".join(_md(c) for c in (
                model, r["stage"], r["calls"], r["real_time_calls"], r["batch_calls"],
                r["items"], f"{r['input_tokens']:,}", f"{r['output_tokens']:,}",
            )) + " |")
        lines += ["", "Cache hits make no model call and are not counted here; "
                  "`run.log`'s *Usage* table counts them."]
    else:
        lines.append("No model call was made.")
    lines.append("")

    if callable(getattr(pressure, "render_lines", None)):
        lines += ["## Resource pressure (API throttling, host CPU/memory/disk, budgets)", "",
                  "```text"]
        lines += [redact_for_display(line, private_roots=roots)
                  for line in pressure.render_lines()]
        lines += ["```", ""]

    lines += [
        "## Files in this folder",
        "",
        "- `api_calls.csv` — one row per model call. Open in Excel and filter by "
        "`stage`, `outcome` or `output_fraction` (share of `max_tokens` used). "
        "`item` is the work item (`SRC-0001:p0` = source 1, first page; a finding id, "
        "with its `qc_id` alongside; or a code reference). `tools_at_limit` names a "
        "tool the call used up to its per-call limit; `forced_close` means tools were "
        "withheld because an allotment was reached.",
        "- `api_calls.json` — the same calls with every field, for scripts.",
        "- `agent_headroom.json` — the per-stage table above, with all counters, "
        "and the model map.",
        "- `api_retries.csv` — every transient API failure (429 / 529 / 503 / 5xx / "
        "timeout / connection) the run waited out or gave up on, with backoff and "
        "`retry-after`.",
        "- `host_samples.csv` — this computer's CPU, memory, disk and thread counts, "
        "sampled every few seconds during the run (`lag_seconds` is how late the "
        "sampler woke: the direct sign of CPU starvation).",
        "- `events.csv` — the run journal's event trace (stage starts/ends, retries, "
        "budget notes), one event per row.",
        "",
        "## Elsewhere in this export",
        "",
        "- `../run.log` — the human-readable run record, including the *Agent "
        "provisioning & headroom* and *Model calls by stage* sections.",
        "- `../run_manifest.json` — the machine-readable record (`agent_headroom`, "
        "`resource_pressure`, `usage`) with a sha256 of every file, these included.",
        "- `../evidence/<finding>/investigation.json` — the full tool trace of each "
        "investigated finding (when the investigation stage ran).",
        "- Not in the export: the app's own rotating log, `drawing_analyzer.log`, in "
        "the `logs` folder of the app's settings directory. It stays on this computer "
        "and holds request-level detail (request ids, batch ids). Set "
        "`DRAWING_ANALYZER_DEBUG=1` before launching to add the SDK's wire-level "
        "request/response lines to it.",
        "",
        "## How the headroom verdict is decided",
        "",
        "- **STARVED** — a stage ran out of something it needed and its result shows "
        "it: a work item still cut off at `max_tokens` on its last call, a server tool "
        "that refused a use because `max_uses` was spent, a `pause_turn` still "
        "unresolved when resumes ran out, or an allotment the pipeline saw it exhaust "
        "(investigation evidence rounds, the per-run finding or reference cap, a batch "
        "abandoned by the time bound).",
        "- **TIGHT** — it finished, but with no margin or with less than it was built "
        "for: a call at 90%+ of `max_tokens`, a cap hit recovered by a raised-cap "
        "retry, a tool used up to its per-call limit, an item that asked for its whole "
        "allotment, a forced no-tools close, a recovered `pause_turn`, or an ability "
        "turned off mid-run.",
        "- **ADEQUATE** — every call finished inside its limits with room to spare.",
        "",
        "Effort and thinking are reported as sent, next to the highest effort level "
        "the model accepts. They are design choices per stage, not a verdict input.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The writer.
# --------------------------------------------------------------------------- #


def write_diagnostics_folder(ctx: Any, folder: Path) -> list[str]:
    """Write ``diagnostics/`` under ``folder``; return the relative names written.

    Each file is independent: a failure writes a one-line note in its place
    (or skips it) and the rest still land. Only the directory creation itself
    may raise, as any export write would.
    """
    out_dir = Path(folder) / DIAGNOSTICS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    roots = _roots(ctx)
    written: list[str] = []
    pressure = getattr(ctx, "resource_pressure", None)
    telemetry = getattr(ctx, "call_telemetry", None)
    journal = getattr(ctx, "run_journal", None)

    def attempt(name: str, write: Callable[[Path], None]) -> None:
        target = out_dir / name
        try:
            write(target)
            written.append(f"{DIAGNOSTICS_DIR}/{name}")
        except Exception as exc:  # noqa: BLE001 - advisory artifact, never fatal
            try:
                target.with_suffix(target.suffix + ".error.txt").write_text(
                    f"{name} could not be written: "
                    + sanitize_text(f"{type(exc).__name__}: {exc}", private_roots=roots)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

    call_rows: list[dict] = []
    try:
        call_rows = _call_rows(ctx)
    except Exception:  # noqa: BLE001
        call_rows = []

    attempt("00_summary.md", lambda p: p.write_text(
        build_summary_markdown(ctx, call_rows=call_rows), encoding="utf-8",
    ))
    attempt("api_calls.csv", lambda p: _write_csv(p, CSV_COLUMNS + ("qc_id",), call_rows))
    attempt("api_calls.json", lambda p: _write_json(p, {
        "schema_version": SCHEMA_VERSION,
        "kind": "drawing_analyzer_api_calls",
        "calls_seen": getattr(telemetry, "calls_seen", len(call_rows)),
        "calls_not_stored": getattr(telemetry, "dropped", 0),
        "calls": call_rows,
    }, roots))
    if telemetry is not None:
        attempt("agent_headroom.json", lambda p: _write_json(p, {
            "schema_version": SCHEMA_VERSION,
            "kind": "drawing_analyzer_agent_headroom",
            **_sanitized(telemetry.to_dict(), roots),
        }, roots))
    if pressure is not None:
        retries = [
            _sanitized(e.to_dict(), roots) for e in list(getattr(pressure, "api_events", []))
        ]
        attempt("api_retries.csv", lambda p: _write_csv(p, _RETRY_COLUMNS, retries))
        series = list(getattr(pressure, "host_series", []) or [])
        columns = tuple(dict.fromkeys(k for row in series for k in row)) or (
            "at", "t_seconds", "lag_seconds",
        )
        attempt("host_samples.csv", lambda p: _write_csv(p, columns, series))
    if journal is not None:
        events = [
            {
                "sequence": e.sequence, "timestamp": e.timestamp, "level": e.level,
                "stage": e.stage, "event_code": e.event_code,
                "fields": "; ".join(f"{k}={v}" for k, v in e.fields.items()),
            }
            for e in list(getattr(journal, "events", []) or [])
        ]
        attempt("events.csv", lambda p: _write_csv(p, _EVENT_COLUMNS, events))
    return written
