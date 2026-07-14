"""Run-scoped journal + ``run.log`` rendering (Phase 26A, §18.1–18.3, DA-024).

The process-wide diagnostics file (:mod:`drawing_analyzer.diagnostics`) is a
rotating trace shared by every run in a session — useful, but it cannot ship
inside one analysis export, and slicing it per run was explicitly ruled out
(§18.1). This module is the per-run counterpart: a :class:`RunJournal` owned by
**exactly one** ``extract_drawing_context`` call. The pipeline emits typed
:class:`RunEvent` records as the run progresses; the export then renders the
journal (plus the finished ``DrawingContext``) into the human-readable
``run.log`` that lands in every export folder, next to the machine-readable
``run_manifest.json`` (built in :mod:`drawing_analyzer.export`).

Sanitization is a *storage* boundary, not a rendering afterthought: every field
value is scrubbed **at emit time** — secrets via the shared Phase 17 filter
(:func:`drawing_analyzer.diagnostics.redact_secrets`), absolute paths reduced
to their basenames (:func:`scrub_paths`), newlines flattened, and length
bounded — so a secret or a private directory name never *enters* the journal,
regardless of which renderer or serializer later touches it (§18.3). The
journal never stores image bytes, prompts, full drawing text, or wire logs;
callers emit counts and identifiers, not payloads (§18.2).

Thread-safety: stages emit from worker threads (the digest pool), so the
monotonic ``sequence`` is assigned under a lock — concurrent events are
totally ordered and unambiguous (§18.1). Emission is advisory and must never
sink a run: :meth:`RunJournal.emit` swallows its own failures (I-3 spirit).

Dependency-free (no PyMuPDF — I-5): environment identity that needs the
renderer is collected by the pipeline and passed in as plain strings.
"""
from __future__ import annotations

import os
import platform
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .diagnostics import redact_secrets

# Levels a journal event may carry (a bad level degrades to INFO, never raises).
EVENT_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Per-field ceiling: run.log carries counts, identifiers, and short reasons —
# never long quotes or drawing text (§18.2). A longer value is truncated with an
# explicit marker so the reader knows content was bounded, not lost silently.
MAX_FIELD_CHARS = 300

# Optional build/commit identifier surfaced in the run.log header ("commit/build
# identifier when available", §18.2). Packaged installs have no .git dir, so an
# environment variable is the one channel a build pipeline can populate.
ENV_BUILD = "DRAWING_ANALYZER_BUILD"


def new_run_id() -> str:
    """A fresh opaque run id (``RUN-`` + 12 hex chars).

    Mirrors the markup writer's ``run-…`` artifact id style
    (:func:`drawing_analyzer.annotate.new_artifact_run_id`) but identifies the
    whole analysis run: one id per ``extract_drawing_context`` call, stamped on
    the journal, ``run.log``, and ``run_manifest.json``.
    """
    return "RUN-" + uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# Sanitization — applied to every stored field value (§18.3: redact BEFORE
# serialization; §18.2: no absolute paths in the portable export by default).
# --------------------------------------------------------------------------- #

# A file:// URL embeds a local path — the one URL form that must scrub.
# Case-insensitive: RFC 3986 schemes are, and Windows tooling emits ``File://``.
_FILE_URL_RE = re.compile(r"(?i)\bfile://[^\s'\"<>]+")

# Any other scheme://… URL is *masked* while the path scrubbers run and then
# restored verbatim, so a colon or slash inside a URL path (a MediaWiki
# ``File:`` segment, an S3 drive-style key) can never be mangled into ``...``.
_URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"<>]+")

# A quoted absolute path (as OSError reprs render them: ``'/a/b c/f.pdf'``).
# Handled first because inside quotes a space is unambiguously part of the
# path, so spacey Windows directories scrub fully here.
_QUOTED_PATH_RE = re.compile(r"(['\"])((?:[A-Za-z]:[\\/]|\\\\|/)[^'\"\r\n]{2,})\1")

# Bare Windows absolute paths, group 1 = final component. Two roots:
# - UNC ``\\server\share`` + separator + any components (server/share already
#   prove it is a path);
# - a drive ``C:`` + separator + AT LEAST ONE directory component, so prose
#   like ``option A:/B`` or ``drive C:\ is full`` is not a match (a bare
#   ``C:/x`` also isn't — with no directory there is no layout to leak).
# The lookbehind stops a scheme's last letter reading as a drive. Components
# deliberately exclude spaces: in running prose the end of a spacey path is
# ambiguous, and over-matching would swallow the sentence (the known-roots
# literal pass in sanitize_text handles the run's own spacey directories).
_WIN_PATH_RE = re.compile(
    r"(?:\\\\[^\\/:*?\"<>|\s]+\\[^\\/:*?\"<>|\s]+[\\/](?:[^\\/:*?\"<>|\r\n ]+[\\/])*"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n ]+[\\/])+)"
    r"([^\\/:*?\"<>|\r\n ]*)"
)

# Bare POSIX absolute paths with at least one directory component. The
# lookbehind keeps this away from mid-token slashes (``r1c1/r2c2``, relative
# ``a/b/c``); ``(?!/)`` skips protocol-relative ``//host/…`` (kept verbatim —
# indistinguishable from a URL; the known-roots pass covers slash-UNC inputs).
# A colon *may* precede (``instance=digest:/home/…``): real URLs were masked
# away above, so the colon-label form is unambiguous here.
_POSIX_PATH_RE = re.compile(r"(?<![\w./])/(?!/)(?:[^/\s]+/)+([^/\s]*)")


def _basename_of(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def scrub_paths(text: str) -> str:
    """Reduce absolute paths in ``text`` to ``.../basename``.

    The basename is the useful, non-private part (it matches the display names
    the rest of the run.log uses); the directory structure is the user's
    private filesystem layout and stays out of portable artifacts (§18.2).
    Relative paths pass through; ``scheme://`` URLs are masked during the scrub
    and restored byte-identical. Best-effort by design — the primary defense is
    that the pipeline emits display names and source ids, never paths; this
    (plus the known-roots pass in :func:`sanitize_text`) catches paths smuggled
    in exception strings.
    """
    text = _FILE_URL_RE.sub(lambda m: "file://.../" + _basename_of(m.group(0)), text)
    masked: list[str] = []

    def _mask(m: "re.Match[str]") -> str:
        masked.append(m.group(0))
        return f"\x00U{len(masked) - 1}\x00"

    text = _URL_RE.sub(_mask, text)
    text = _QUOTED_PATH_RE.sub(
        lambda m: m.group(1) + ".../" + _basename_of(m.group(2)) + m.group(1), text
    )
    text = _WIN_PATH_RE.sub(lambda m: ".../" + m.group(1), text)
    text = _POSIX_PATH_RE.sub(lambda m: ".../" + m.group(1), text)
    for i, url in enumerate(masked):
        text = text.replace(f"\x00U{i}\x00", url)
    return text


# HTML-ish payloads (a 5xx error page in an exception string) are tag-stripped
# like diagnostics._short does, but only when a tag signature is present — a
# bare "a < b" comparison in ordinary text must survive.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_text(
    value: Any,
    *,
    max_chars: int = MAX_FIELD_CHARS,
    private_roots: "tuple[str, ...] | list[str]" = (),
) -> str:
    """One journal-safe line: stringified, secret-redacted, path-scrubbed, bounded.

    The storage boundary for everything the journal keeps (§18.3), in order:
    flatten to one line; strip HTML tags when a tag signature is present (an
    HTML 5xx body must not flood the log); replace each ``private_roots``
    literal with ``...`` (the run's *known* directories — input parents, work
    dir, home — which handles spacey Windows paths the bare regexes cannot);
    redact secrets (before truncation, so a secret can never survive as a
    recognizable prefix); scrub remaining absolute paths; bound the length.
    Never raises — an unprintable object becomes a placeholder rather than
    sinking the emitting stage.
    """
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - journal writes must never raise
        text = "(unprintable " + type(value).__name__ + ")"
    text = " ".join(text.split())  # flatten newlines/runs: one event = one line
    if "</" in text or "/>" in text or "<html" in text.lower():
        text = " ".join(_HTML_TAG_RE.sub(" ", text).split())
    for root in private_roots:
        if root:
            text = text.replace(root, "...")
    text = redact_secrets(text)
    text = scrub_paths(text)
    if len(text) > max_chars:
        text = text[:max_chars] + f"... [+{len(text) - max_chars} chars]"
    return text


def derive_run_outcome(
    *, ok_sheets: int, error_count: int, qc_status: str, coverage_status: str = ""
) -> str:
    """The run-level terminal COMPLETE/PARTIAL/FAILED status (§18.2).

    Deliberately distinct from the §3.3 *QC* status: a standard run that
    analyzed everything cleanly is COMPLETE even though its QC status is
    NOT_REQUESTED (QC simply was not asked for), and a run whose QC failed but
    whose digest shipped is PARTIAL (I-3: the standard deliverable survives).
    FAILED means nothing was analyzed. One derivation, shared by the journal's
    ``finish()`` caller and the run.log outcome line, so run.log and
    run_manifest.json can never disagree about the same run.
    """
    if ok_sheets <= 0:
        return "FAILED"
    if (
        error_count
        or qc_status in ("PARTIAL", "FAILED")
        or coverage_status == "INCOMPLETE"
    ):
        return "PARTIAL"
    return "COMPLETE"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """Millisecond ISO-8601 UTC (``2026-07-14T02:31:05.123Z``)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def collect_environment(**extra: Any) -> dict[str, str]:
    """The §18.2 environment block: OS / Python / library versions, as strings.

    Library versions come from package *metadata* (no imports), so this stays
    PyMuPDF-free (I-5) and never drags the SDK into a hermetic context. The
    pipeline passes renderer/model/prompt-version identity via ``extra``.
    """
    env: dict[str, str] = {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
    }
    from importlib import metadata

    for label, dist in (
        ("app", "drawing-analyzer"),
        ("pymupdf", "PyMuPDF"),
        ("anthropic_sdk", "anthropic"),
    ):
        try:
            env[label] = metadata.version(dist)
        except Exception:  # noqa: BLE001 - a missing dist is informational only
            env[label] = "unavailable"
    build = os.environ.get(ENV_BUILD, "").strip()
    if build:
        env["build"] = build
    for key, value in extra.items():
        env[str(key)] = str(value)
    return env   # plain strings; RunJournal.set_environment owns sanitization


# --------------------------------------------------------------------------- #
# The journal itself.
# --------------------------------------------------------------------------- #


@dataclass
class RunEvent:
    """One sanitized, sequence-numbered journal entry (§18.1)."""

    sequence: int
    timestamp: str                      # ISO-8601 UTC, millisecond precision
    level: str                          # one of EVENT_LEVELS
    stage: str                          # producing stage ("run", "digest", …)
    event_code: str                     # SCREAMING_SNAKE machine code
    fields: dict[str, str] = field(default_factory=dict)   # already sanitized

    def line(self) -> str:
        """The one-line trace rendering used by ``run.log``'s event section."""
        parts = [
            f"{self.sequence:04d}",
            self.timestamp[11:],        # time-of-day; the date is in the header
            f"{self.level:<7}",
            f"{self.stage:<13}",
            self.event_code,
        ]
        if self.fields:
            parts.append(" ".join(_kv(k, v) for k, v in self.fields.items()))
        return "  ".join(parts)

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "level": self.level,
            "stage": self.stage,
            "event_code": self.event_code,
            "fields": dict(self.fields),
        }


def _kv(key: str, value: str) -> str:
    """``key=value``, quoting the value when it contains whitespace."""
    if any(ch.isspace() for ch in value):
        return f'{key}="{value}"'
    return f"{key}={value}"


class RunJournal:
    """Event journal owned by exactly one analysis run (§18.1).

    Created at the top of ``extract_drawing_context`` and carried on
    ``DrawingContext.run_journal``; the export renders it to ``run.log``.
    ``run_id`` and ``clock`` are injectable so tests are deterministic; the
    defaults mint a fresh id and use UTC wall-clock. All mutation happens under
    one lock, and the ``sequence`` is monotonic from 1, so concurrently-emitted
    events (digest worker threads) are totally ordered.
    """

    def __init__(
        self,
        run_id: str | None = None,
        *,
        clock: "Callable[[], datetime] | None" = None,
    ) -> None:
        self.run_id = run_id or new_run_id()
        self._clock = clock or _utc_now
        self._lock = threading.Lock()
        self._next_sequence = 1
        self.events: list[RunEvent] = []
        self.environment: dict[str, str] = {}
        self.started_at: datetime = self._clock()
        self.ended_at: "datetime | None" = None
        self.final_status: str = ""
        # Known private directory literals (input parents, work dir, home) —
        # replaced with "..." by the sanitize boundary. In-memory only: never
        # rendered, never serialized (to_dict/render_text exclude them).
        self.private_roots: tuple[str, ...] = ()

    # -- writing ------------------------------------------------------------ #

    def add_private_roots(self, roots: "list | tuple") -> None:
        """Register directory prefixes to strip from every future field value.

        Longest-first so a nested root cannot leave a parent's tail behind;
        both native and forward-slash spellings are registered (exception text
        mixes them on Windows). This literal pass is what makes spacey
        directories (``C:\\Users\\John Smith\\…``) scrub reliably — the bare
        regexes cannot know where a spacey path ends (§18.3).
        """
        try:
            expanded = set(self.private_roots)
            for root in roots:
                raw = str(root).rstrip("\\/")
                if len(raw) > 1:
                    expanded.add(raw)
                    expanded.add(raw.replace("\\", "/"))
            self.private_roots = tuple(sorted(expanded, key=len, reverse=True))
        except Exception:  # noqa: BLE001 - advisory, never fatal
            pass

    def _sanitize(self, value: Any, *, max_chars: int = MAX_FIELD_CHARS) -> str:
        return sanitize_text(value, max_chars=max_chars, private_roots=self.private_roots)

    def set_environment(self, mapping: dict) -> None:
        """Record the run's environment block (values sanitized; header-rendered)."""
        try:
            self.environment = {
                str(k)[:80]: self._sanitize(v) for k, v in dict(mapping).items()
            }
        except Exception:  # noqa: BLE001 - advisory, never fatal
            pass

    def emit(
        self,
        event_code: str,
        *,
        stage: str = "run",
        level: str = "INFO",
        **fields: Any,
    ) -> "RunEvent | None":
        """Append one event; returns it (or ``None`` if journaling failed).

        Every field VALUE passes the sanitize boundary *now*, so nothing
        secret- or path-bearing is ever stored (§18.3). Field keys are code-
        owned ``**kwargs`` identifiers, not data — bounded, never sanitized.
        Never raises: the journal is advisory and a logging failure must not
        fail the run.
        """
        try:
            event_fields = {str(k)[:80]: self._sanitize(v) for k, v in fields.items()}
            lvl = str(level).upper()
            if lvl not in EVENT_LEVELS:
                lvl = "INFO"
            with self._lock:
                event = RunEvent(
                    sequence=self._next_sequence,
                    timestamp=_iso(self._clock()),
                    level=lvl,
                    stage=str(stage)[:40] or "run",
                    event_code=str(event_code)[:60] or "EVENT",
                    fields=event_fields,
                )
                self._next_sequence += 1
                self.events.append(event)
            return event
        except Exception:  # noqa: BLE001 - journal writes must never raise
            return None

    def finish(self, status: str) -> None:
        """Stamp the run's end time and terminal run outcome (last call wins).

        ``status`` is the RUN-level COMPLETE/PARTIAL/FAILED outcome from
        :func:`derive_run_outcome` — not the §3.3 QC status, which is
        NOT_REQUESTED for every standard run and would make completed runs
        indistinguishable from anything else in ``run_manifest.json``.
        """
        try:
            self.ended_at = self._clock()
            self.final_status = str(status)[:60]
        except Exception:  # noqa: BLE001
            pass

    # -- reading ------------------------------------------------------------ #

    @property
    def event_count(self) -> int:
        return len(self.events)

    def stage_durations(self) -> dict[str, float]:
        """Seconds between each stage's STAGE_START and STAGE_END events.

        Keyed by the event's ``stage``; a stage missing either endpoint is
        absent (the run.log table then leaves its duration blank rather than
        inventing one).
        """
        starts: dict[str, str] = {}
        durations: dict[str, float] = {}
        for e in self.events:
            if e.event_code == "STAGE_START":
                starts.setdefault(e.stage, e.timestamp)
            elif e.event_code == "STAGE_END" and e.stage in starts:
                try:
                    t0 = datetime.strptime(starts[e.stage], "%Y-%m-%dT%H:%M:%S.%fZ")
                    t1 = datetime.strptime(e.timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
                    durations[e.stage] = max((t1 - t0).total_seconds(), 0.0)
                except ValueError:
                    continue
        return durations

    def to_dict(self) -> dict:
        """JSON-ready journal (the manifest embeds the summary, not the trace)."""
        return {
            "run_id": self.run_id,
            "started_at": _iso(self.started_at),
            "ended_at": _iso(self.ended_at) if self.ended_at else None,
            "final_status": self.final_status,
            "environment": dict(self.environment),
            "event_count": self.event_count,
        }

    def render_text(self, context: Any = None, outputs: "list[str] | None" = None) -> str:
        """The complete human-readable ``run.log`` document (§18.2).

        ``context`` (a ``DrawingContext`` or duck-typed equivalent) supplies the
        structured summaries — inputs, configuration, stages, usage, ledger,
        coverage — and the journal supplies identity, environment, and the
        chronological event trace. ``outputs`` is the list of artifact names the
        export actually wrote (passed by ``write_drawing_export`` because the
        log is finalized *before* ``run_manifest.json`` exists, §18.4).
        Renders with plain ``\\n``; the writer chooses the on-disk line ending.
        """
        return render_run_log(context, journal=self, outputs=outputs)


# --------------------------------------------------------------------------- #
# run.log rendering (§18.2). Duck-typed on the context exactly like export.py —
# every attribute is read with getattr + a default, so a partial/fake context
# still renders (and a section with nothing to say is skipped, not invented).
# --------------------------------------------------------------------------- #

_RULE = "-" * 78
_HEAVY_RULE = "=" * 78


def _int(value: Any, default: int = 0) -> int:
    """Defensive int coercion — a duck-typed context field must never raise
    out of the renderer (the export's never-fatal charter, I-3 spirit)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ok_sheets(ctx: Any) -> int:
    """ok-sheet count, falling back to ``sheet_count`` for duck-typed contexts
    that don't derive the ok property (assume analyzed unless told otherwise)."""
    value = getattr(ctx, "ok_sheet_count", None)
    if value is None:
        value = getattr(ctx, "sheet_count", 0)
    return _int(value or 0)


def context_run_outcome(ctx: Any) -> str:
    """:func:`derive_run_outcome` over a (duck-typed) context's fields."""
    return derive_run_outcome(
        ok_sheets=_ok_sheets(ctx),
        error_count=len(list(getattr(ctx, "errors", None) or [])),
        qc_status=str(getattr(ctx, "qc_status", "NOT_REQUESTED") or "NOT_REQUESTED"),
        coverage_status=str(getattr(ctx, "coverage_status", "") or ""),
    )


def _outcome_line(ctx: Any) -> str:
    """The header's one-line outcome: run-level status + the GUI's §3.3 label.

    Leads with :func:`derive_run_outcome` (the same value ``finish()`` stored,
    so run.log and run_manifest.json agree) and takes the label wording from
    ``ctx.qc_status_label`` — the shared property the GUI/report/manifest use —
    folding ``markup_incomplete`` exactly like ``gui._on_done``.
    """
    if ctx is None:
        return "(no context attached — journal-only rendering)"
    qc_status = str(getattr(ctx, "qc_status", "NOT_REQUESTED") or "NOT_REQUESTED")
    outcome = context_run_outcome(ctx)
    if _ok_sheets(ctx) <= 0:
        return "FAILED — no sheets were analyzed (see Errors below)"
    if getattr(ctx, "markup_incomplete", False) or qc_status == "FAILED":
        return f"{outcome} — QC incomplete"
    # The label wording comes from the shared DrawingContext.qc_status_label
    # property (the §3.3 vocabulary the GUI/report/manifest all use); the map
    # below is only the fallback for duck-typed contexts without the property,
    # and deliberately repeats that property's exact strings.
    label = str(getattr(ctx, "qc_status_label", "") or "") or {
        "PARTIAL": "Completed with QC warnings",
        "COMPLETE": "Exhaustive QC complete",
    }.get(qc_status, qc_status)
    if qc_status in ("PARTIAL", "COMPLETE"):
        return f"{outcome} — {label}"
    if list(getattr(ctx, "errors", None) or []):
        return f"{outcome} — standard analysis completed with warnings (no QC requested)"
    return f"{outcome} — standard analysis (no QC requested)"


def _fmt_cost(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if 0 < cost < 0.01:
        return "<$0.01"     # honest for tiny runs; never rounds a real cost to zero
    return f"${cost:,.2f}"


def _config_lines(ctx: Any) -> list[str]:
    cfg = getattr(ctx, "run_configuration", None)
    if cfg is None:
        return ["  (no resolved run configuration was recorded)"]
    to_dict = getattr(cfg, "to_dict", None)
    d = to_dict() if callable(to_dict) else {}
    if getattr(cfg, "exhaustive_qc", False):
        mode = "exhaustive QC (QC Markups)"
    elif getattr(cfg, "deterministic_audit_only", False):
        mode = "deterministic audit only (no additional API calls)"
    else:
        mode = "standard analysis"
    kind = str(d.get("configuration_kind", "NORMAL") or "NORMAL")
    lines = [f"  mode: {mode}   [{kind}]"]
    skip = {"configuration_kind", "debug_overrides"}
    flags = [
        f"{k}={'on' if v else 'off'}" if isinstance(v, bool) else f"{k}={v}"
        for k, v in d.items()
        if k not in skip
    ]
    for i in range(0, len(flags), 4):
        lines.append("  " + " ".join(flags[i : i + 4]))
    overrides = list(d.get("debug_overrides") or [])
    lines.append(
        "  debug_overrides: " + (", ".join(str(o) for o in overrides) if overrides else "(none)")
    )
    return lines


def _profile_lines(ctx: Any) -> list[str]:
    snaps = list(getattr(ctx, "profile_snapshots", None) or [])
    if not snaps:
        return ["  profiles: (none selected)"]
    lines = []
    for s in snaps:
        name = getattr(s, "name", "") or "?"
        version = getattr(s, "version", "") or "?"
        source = getattr(s, "source", "") or "?"
        chash = (getattr(s, "content_hash", "") or "")[:12]
        lines.append(f"  profile: {name} v{version} [{source}] hash={chash or '?'}")
    return lines


def _input_lines(ctx: Any) -> list[str]:
    inventory = getattr(ctx, "input_inventory", None)
    docs = list(getattr(inventory, "documents", None) or [])
    if not docs:
        return [
            f"  {int(getattr(ctx, 'file_count', 0) or 0)} file(s), "
            f"{int(getattr(ctx, 'sheet_count', 0) or 0)} sheet(s) "
            "(no input inventory was recorded)"
        ]
    accepted = [d for d in docs if getattr(d, "accepted", False)]
    lines = [
        f"  submitted {len(docs)} file(s): {len(accepted)} accepted "
        f"({sum(int(getattr(d, 'page_count', 0) or 0) for d in accepted)} sheet(s)), "
        f"{len(docs) - len(accepted)} rejected"
    ]
    for d in docs:
        sid = getattr(d, "source_id", "") or "—"
        status = getattr(d, "status", "") or "?"
        name = sanitize_text(getattr(d, "display_name", "") or "?", max_chars=80)
        detail = f"{int(getattr(d, 'page_count', 0) or 0)} page(s)"
        if not getattr(d, "accepted", False):
            detail = sanitize_text(getattr(d, "error", "") or status.lower(), max_chars=160)
            dup = getattr(d, "duplicate_of", "")
            if dup:
                detail += f" (duplicate of {dup})"
        lines.append(f"  {sid:<9} {status:<10} {name} — {detail}")
    return lines


def _sheet_lines(ctx: Any) -> list[str]:
    sheets = list(getattr(ctx, "sheets", None) or [])
    if not sheets:
        return ["  (no sheets)"]
    geoms: dict[Any, Any] = {}
    for g in getattr(ctx, "sheet_geometries", None) or []:
        ref = getattr(g, "ref", None)
        key = getattr(ref, "key", None)
        if key is not None:
            geoms[key] = g
    ok = sum(1 for s in sheets if getattr(s, "ok", False))
    cached = sum(1 for s in sheets if getattr(s, "cached", False))
    drift = sum(1 for s in sheets if getattr(s, "findings_note", ""))
    lines = [
        f"  {len(sheets)} sheet(s): {ok} ok, {len(sheets) - ok} failed, {cached} from cache"
        + (f"; findings-parser drift on {drift} sheet(s)" if drift else "")
    ]
    for s in sheets:
        ref = getattr(s, "ref", None)
        label = sanitize_text(getattr(ref, "display_label", "") or "sheet", max_chars=80)
        error = getattr(s, "error", None)
        # Classified by ``ok`` (error-free AND non-empty), matching the header
        # sums above — an empty error-free digest is a failure, not "ok" (its
        # row would otherwise contradict the summary line).
        if getattr(s, "ok", False):
            status = "ok/cache" if getattr(s, "cached", False) else "ok/fresh"
        else:
            status = "FAILED"
            if not error:
                error = "(empty digest)"
        bits = [f"digest {len(getattr(s, 'text', '') or ''):,} chars"]
        g = geoms.get(getattr(ref, "key", None))
        if g is not None:
            bits.append("raster" if getattr(g, "is_raster", False) else "vector")
            bits.append(f"text layer {len(getattr(g, 'sheet_text', '') or ''):,} chars")
            omitted = getattr(g, "omitted_tile_count", None)
            if omitted is not None:
                bits.append(f"{int(omitted)} blank tile(s) omitted")
        note = getattr(s, "findings_note", "")
        if note:
            bits.append(f"parser: {sanitize_text(note, max_chars=120)}")
        if error:
            bits.append(sanitize_text(error, max_chars=160))
        lines.append(f"  {label:<40} {status:<9} " + " · ".join(bits))
    return lines


def _stage_lines(ctx: Any, journal: "RunJournal | None") -> list[str]:
    results = list(getattr(ctx, "stage_results", None) or [])
    durations = journal.stage_durations() if journal is not None else {}
    header = f"  {'stage':<15}{'status':<15}{'calls':<12}{'items in→out':<14}{'duration':<10}notes"
    lines = [header]
    for sr in results:
        stage = str(getattr(sr, "stage", "?"))
        status = str(getattr(sr, "status", "?"))
        planned = int(getattr(sr, "calls_planned", 0) or 0)
        succeeded = int(getattr(sr, "calls_succeeded", 0) or 0)
        calls = f"{succeeded}/{planned}" if planned else "—"
        items = f"{int(getattr(sr, 'items_in', 0) or 0)}→{int(getattr(sr, 'items_out', 0) or 0)}"
        duration = f"{durations[stage]:.1f}s" if stage in durations else "—"
        notes = list(getattr(sr, "errors", None) or []) + list(getattr(sr, "warnings", None) or [])
        note = sanitize_text(notes[0], max_chars=90) if notes else ""
        if len(notes) > 1:
            note += f" (+{len(notes) - 1} more)"
        lines.append(f"  {stage:<15}{status:<15}{calls:<12}{items:<14}{duration:<10}{note}")
    if not results:
        lines.append("  (no QC stages were requested)")
    return lines


def _usage_lines(ctx: Any) -> list[str]:
    by_family = dict(getattr(ctx, "usage_by_family", None) or {})
    lines = [
        f"  {'family':<12}{'calls':<8}{'cache hits':<12}{'input tok':<12}{'output tok':<12}est. cost"
    ]
    for family, row in by_family.items():
        lines.append(
            f"  {family:<12}{_int(row.get('calls', 0)):<8}{_int(row.get('cache_hits', 0)):<12}"
            f"{_int(row.get('input_tokens', 0)):<12,}{_int(row.get('output_tokens', 0)):<12,}"
            f"{_fmt_cost(row.get('estimated_cost'))}"
        )
    if not by_family:
        lines.append("  (no API usage was recorded)")
    lines.append(
        f"  TOTAL: input {_int(getattr(ctx, 'total_input_tokens', 0) or 0):,} tok · "
        f"output {_int(getattr(ctx, 'total_output_tokens', 0) or 0):,} tok · "
        f"est. cost {_fmt_cost(getattr(ctx, 'total_estimated_cost', None))}"
    )
    lines.append(
        "  (totals are derived sums over the append-only usage ledger, §15.6; "
        "costs are estimates)"
    )
    return lines


def evidence_summary(findings: "list[Any]") -> dict:
    """How many verifier crops were saved, over how many findings (DA-016).

    The one shared counter behind run.log's evidence line and
    ``run_manifest.json``'s evidence block (export.py imports it), so the two
    artifacts in one export can never disagree about the crop count.
    """
    artifacts = 0
    with_evidence = 0
    for f in findings:
        n = len(getattr(getattr(f, "verification", None), "evidence", None) or [])
        artifacts += n
        with_evidence += 1 if n else 0
    return {"artifact_count": artifacts, "findings_with_evidence": with_evidence}


def _ledger_lines(ctx: Any) -> list[str]:
    from .models import receipt_status_counts

    findings = list(getattr(ctx, "findings", None) or [])
    reference = list(getattr(ctx, "reference_findings", None) or [])
    total = len(findings) + len(reference)
    evidence = evidence_summary(findings + reference)["artifact_count"]
    lines = [
        f"  findings: {total} ledger entr{'y' if total == 1 else 'ies'} "
        f"({len(findings)} model/prose, {len(reference)} deterministic) · "
        f"{evidence} saved evidence crop(s)"
    ]
    stats = dict(getattr(ctx, "audit_stats", None) or {})
    if stats:
        lines.append(
            "  deterministic battery: "
            + ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
        )
    coverage = str(getattr(ctx, "coverage_status", "NOT_REQUESTED") or "NOT_REQUESTED")
    markup_run = getattr(ctx, "markup_run", None)
    if markup_run is not None:
        expected = len(getattr(markup_run, "placements", None) or [])
        receipts = receipt_status_counts(getattr(markup_run, "receipts", None))
        terminal = sum(receipts.values())
        lines.append(
            f"  markup placements: {expected} expected · {terminal} receipt(s) "
            f"(WRITTEN {receipts['WRITTEN']}, INDEXED {receipts['INDEXED']}, "
            f"FAILED {receipts['FAILED']})"
        )
    if coverage in ("COMPLETE", "INCOMPLETE"):
        lines.append(f"  markup coverage: {coverage} (receipt-derived, §13.5)")
        tally_line = getattr(ctx, "ledger_tally_line", "") or ""
        if tally_line:
            lines.append(f"  {sanitize_text(tally_line, max_chars=200)}")
    mutated = list(getattr(ctx, "mutated_sources", None) or [])
    if mutated:
        lines.append(
            "  sources changed mid-run (markup skipped): "
            + ", ".join(sanitize_text(m, max_chars=60) for m in mutated)
        )
    return lines


def _prose_lines(ctx: Any) -> list[str]:
    acc = dict(getattr(ctx, "prose_accounting", None) or {})
    if not acc:
        return []
    order = (
        "items", "matched", "structured", "degraded",
        "set_level", "excluded_focus", "skipped", "missing",
    )
    parts = [f"{k.replace('_', ' ')} {_int(acc[k])}" for k in order if k in acc]
    extra = [k for k in acc if k not in order and k != "complete"]
    parts += [f"{k} {acc[k]}" for k in sorted(extra)]
    line = "  " + " · ".join(parts)
    if acc.get("missing"):
        line += "   << unaccounted items — exhaustive QC is incomplete (§14.9)"
    return [line]


def render_run_log(
    ctx: Any,
    *,
    journal: "RunJournal | None" = None,
    outputs: "list[str] | None" = None,
) -> str:
    """Render the §18.2 ``run.log`` document for ``ctx``.

    ``journal`` defaults to ``ctx.run_journal``; a context without one (an
    older cached context, a hand-built test double) still renders — identity
    and the event trace are simply reported as not recorded. Pure and
    I/O-free; :func:`drawing_analyzer.export.write_run_log` owns the file.
    """
    if journal is None:
        journal = getattr(ctx, "run_journal", None)

    lines: list[str] = [
        _HEAVY_RULE,
        "Drawing Analyzer — run log",
        _HEAVY_RULE,
    ]
    if journal is not None:
        lines.append(f"Run ID:      {journal.run_id}")
        lines.append(f"Started:     {_iso(journal.started_at)}")
        if journal.ended_at is not None:
            lines.append(f"Ended:       {_iso(journal.ended_at)}")
    else:
        lines.append("Run ID:      (no run journal was recorded for this context)")
    lines.append(f"Outcome:     {_outcome_line(ctx)}")
    qc_status = str(getattr(ctx, "qc_status", "NOT_REQUESTED") or "NOT_REQUESTED")
    coverage = str(getattr(ctx, "coverage_status", "NOT_REQUESTED") or "NOT_REQUESTED")
    lines.append(f"QC status:   {qc_status} · markup coverage: {coverage}")
    environment = dict(journal.environment) if journal is not None else {}
    if environment:
        pairs = [f"{k}={v}" for k, v in environment.items()]
        lines.append("Environment: " + pairs[0])
        lines.extend(f"             {p}" for p in pairs[1:])

    def section(title: str, *builders: Any) -> None:
        # Each section renders independently and never sinks the log: run.log
        # is an advisory artifact, so a hostile/duck-typed context field costs
        # one section, not the export (I-3 spirit; the §18.4 guarantee is that
        # every export CARRIES the log).
        body: list[str] = []
        for build in builders:
            try:
                body.extend(build(ctx))
            except Exception as exc:  # noqa: BLE001 - render must stay total
                body.append(f"  (section failed to render: {type(exc).__name__})")
        if body:
            lines.extend(["", title, _RULE, *body])

    section("Inputs", _input_lines)
    section("Configuration", _config_lines, _profile_lines)
    section("Sheets", _sheet_lines)
    section("Stages", lambda c: _stage_lines(c, journal))
    section("Usage & estimated cost", _usage_lines)
    section("Findings, ledger & markup coverage", _ledger_lines)
    section("Prose carry-through (§14.9)", _prose_lines)

    if outputs is not None:
        body = [f"  {name}" for name in outputs]
        body.append("  run.log — this file")
        body.append(
            "  run_manifest.json — written after this log (it hashes every artifact"
            " above, run.log included, and excludes only itself; §18.4)"
        )
        section("Outputs", lambda c: body)

    roots = tuple(getattr(journal, "private_roots", ()) or ())
    errors = [
        sanitize_text(e, max_chars=240, private_roots=roots)
        for e in (getattr(ctx, "errors", None) or [])
    ]
    section(
        f"Errors & warnings ({len(errors)})",
        lambda c: [f"  - {e}" for e in errors] or ["  (none)"],
    )

    if journal is not None and journal.events:
        section(
            f"Event trace ({journal.event_count} event(s))",
            lambda c: [f"  {e.line()}" for e in journal.events],
        )

    lines.append("")
    lines.append(_HEAVY_RULE)
    lines.append(f"Final status: {_outcome_line(ctx)}")
    lines.append(_HEAVY_RULE)
    lines.append("")
    return "\n".join(lines)
