"""Agentic investigation loop (Phase C): escalate UNCERTAIN verification verdicts.

The verify pass gives every anchored finding exactly one look — a single
high-DPI crop — and ``NOT_VISIBLE`` (→ ``UNCERTAIN``) is an accepted terminal
answer. This stage picks those UNCERTAIN findings up and lets the model
*request* the evidence the one crop lacked, through host-executed tools:

- ``crop_region`` — a different/larger/higher-DPI region of a sheet;
- ``find_text``   — a deterministic, zero-API search of a sheet's vector text
  layer (returns match rectangles the model can then crop);
- ``view_sheet``  — a whole-sheet overview of ANOTHER sheet in the set, for
  "the answer depends on another sheet/schedule" cases.

The host executes every request deterministically and returns the result as a
``tool_result`` block (images inline); the model iterates until it can conclude
CONFIRMED / CONTRADICTED / NOT_VISIBLE, or the evidence budget forces a final
text-only close. The loop only ever *updates* ``finding.verification`` in place
— a legal post-seal mutation, exactly like the verify pass it escalates — and a
budget-capped or garbled outcome stays ``UNCERTAIN``, never ``REJECTED``
(:func:`verify.parse_verdict` is reused verbatim).

Turn discipline (ported from the report chat widget's loop): the assistant
turn is committed to history *before* its tools are answered; every
``tool_use`` id is answered in ONE user turn; when the round budget is
exhausted the budget notice rides that final tool-result turn and later
requests carry no ``tools`` key at all — a run can never terminate on a
dangling tool request.

Evidence discipline (§16.6): every image is saved under the finding's evidence
directory *before* it is sent (continuing the verify pass's directory and
``leg_index`` numbering); an image that cannot be durably saved is not sent.
This module imports no PDF engine (I-5) — rendering goes through
:mod:`render`, and investigations run strictly sequentially (PyMuPDF is not
thread-safe; each investigation interleaves renders with API turns).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .core.api_config import (
    PHASE_INVESTIGATION,
    VERIFICATION_ESCALATION_MODEL,
    apply_effort_config,
    apply_thinking_config,
    phase_output_cap,
    system_prompt_with_cache,
    tools_with_cache,
)
from .diagnostics import get_logger
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    _clean_error,
    _error_status,
    _image_block,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
)
from .models import Finding, Verification, source_page_key
from .verify import (
    _FATAL_STATUSES,
    _reserve_evidence_dir,
    _save_crop,
    _sheet_lookup,
    context_rect,
    parse_verdict,
)

_log = get_logger()

# Bump on any prompt/tool-contract change (rides the cache key in Phase C4).
INVESTIGATE_PROMPT_VERSION = "investigate-v1"

_DEFAULT_MAX_ROUNDS = 6
_DEFAULT_MAX_INVESTIGATIONS = 10
_MAX_PAUSE_RESUMES = 3
_VIEW_SHEET_DPI = 150
_MAX_CROP_DPI = 300
_MIN_CROP_DPI = 72
_MIN_RECT_SPAN_PT = 5.0
_MAX_FIND_TEXT_MATCHES = 20
_MAX_SHEET_INDEX_ENTRIES = 60
_NOTE_CAP = 250

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def investigation_max_rounds() -> int:
    """Evidence rounds per investigation (env-tunable, min 1)."""
    return _env_int("DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS", _DEFAULT_MAX_ROUNDS)


def investigation_max_findings() -> int:
    """Investigations per run (env-tunable, min 1)."""
    return _env_int(
        "DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS", _DEFAULT_MAX_INVESTIGATIONS
    )


def investigation_model() -> str:
    """Model for the investigation loop — the escalation tier by default,
    overridable via ``DRAWING_ANALYZER_INVESTIGATION_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_INVESTIGATION_MODEL")
    if override and override.strip():
        return override.strip()
    return VERIFICATION_ESCALATION_MODEL


INVESTIGATE_SYSTEM_PROMPT = """\
You are a senior design professional doing a back-check before a construction \
drawing set is issued. A first-pass reviewer looked at ONE cropped region and \
could not decide whether a FINDING holds. You may request more evidence with \
the tools provided: a different or larger crop, a text search to locate a \
schedule/note/tag, or an overview of another sheet the answer depends on.

Rules:
- Conclude ONLY from evidence you have actually seen in the images returned \
to you. Never conclude from memory or from what a sheet "should" say.
- You have a limited evidence budget (the host will tell you when it is \
exhausted). Prefer the single most decisive request over broad exploration.
- Remaining uncertain is an acceptable outcome; do not guess.

When you can decide — or when told the budget is exhausted — respond with \
ONLY a JSON object and nothing else:
{"verdict": "CONFIRMED" | "CONTRADICTED" | "NOT_VISIBLE", "note": "<= 25 words \
on what you actually saw"}"""


def investigation_tools() -> list[dict]:
    """The static client-tool schemas (stable → cacheable via tools_with_cache)."""
    return [
        {
            "name": "crop_region",
            "description": (
                "Render a rectangular region of a sheet at high resolution. "
                "Coordinates are PDF points in the same space as the crops you "
                "are shown, origin top-left. Defaults to the finding's own sheet."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "rect": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "[x0, y0, x1, y1] in points",
                    },
                    "sheet_id": {
                        "type": "string",
                        "description": "Optional: another sheet's ID (e.g. M-101).",
                    },
                    "dpi": {"type": "integer", "minimum": 72, "maximum": 300},
                },
                "required": ["rect"],
            },
        },
        {
            "name": "find_text",
            "description": (
                "Search a sheet's vector text layer for a word or phrase. "
                "Returns matched rectangles (points) and line context; follow "
                "with crop_region to view one. Free and instant; raster sheets "
                "have no text layer. Defaults to the finding's own sheet."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 2},
                    "sheet_id": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "view_sheet",
            "description": (
                "A whole-sheet overview of another sheet in the set, identified "
                "by sheet ID or by source file + 1-based page number. Use before "
                "crop_region on that sheet."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "sheet_id": {"type": "string"},
                    "source_name": {"type": "string"},
                    "page_number": {"type": "integer", "minimum": 1},
                },
                "required": [],
            },
        },
    ]


# render_fn contract: (pdf_path, page_index, rect_pts, dpi) -> png bytes | None.
# Injectable so unit tests stay PyMuPDF-free (I-4/I-5).
RenderFn = Callable[[Any, int, list, int], "bytes | None"]


def _default_render_fn(pdf_path: Any, page_index: int, rect: list, dpi: int) -> bytes | None:
    from . import render

    for _key, png in render.iter_region_crops(pdf_path, [(0, page_index, rect, dpi)]):
        return png
    return None


def _norm_id(text: Any) -> str:
    return " ".join(str(text or "").split()).upper()


def _sheet_id_map(findings: Iterable[Finding], sheets: list, lookup: dict) -> dict:
    """``{normalized sheet id: sheet}`` — detected title-block IDs, overlaid by
    the IDs the findings themselves carry (finding-carried IDs win: they are the
    names the model will use). Deterministic iteration order."""
    from .auditors.references import detect_sheet_id

    out: dict[str, Any] = {}
    for sheet in sheets:
        detected = detect_sheet_id(sheet)
        if detected:
            out.setdefault(_norm_id(detected), sheet)
    for f in findings:
        fid = _norm_id(getattr(f, "sheet_id", ""))
        sheet = lookup.get(source_page_key(f))
        if fid and sheet is not None:
            out[fid] = sheet
        for leg in getattr(f, "also_on", None) or []:
            lid = _norm_id(getattr(leg, "sheet_id", ""))
            leg_sheet = lookup.get(source_page_key(leg))
            if lid and leg_sheet is not None:
                out[lid] = leg_sheet
    return out


def _sheet_index_text(sheet_id_map: dict) -> str:
    """A bounded one-line index of the other sheets the tools can reach."""
    entries = []
    for sid, sheet in list(sheet_id_map.items())[:_MAX_SHEET_INDEX_ENTRIES]:
        ref = getattr(sheet, "ref", None)
        name = getattr(ref, "source_name", "") or ""
        page = int(getattr(ref, "page_index", 0) or 0) + 1
        entries.append(f"{sid} ({name} p.{page})" if name else sid)
    if not entries:
        return ""
    more = len(sheet_id_map) - len(entries)
    suffix = f" (+{more} more)" if more > 0 else ""
    return "Sheets in this set reachable by the tools: " + ", ".join(entries) + suffix


def _word_rect(word: Any) -> list[float]:
    return [float(word[0]), float(word[1]), float(word[2]), float(word[3])]


def _rect_union(rects: list) -> list[float]:
    return [
        min(r[0] for r in rects), min(r[1] for r in rects),
        max(r[2] for r in rects), max(r[3] for r in rects),
    ]


def find_text_matches(sheet: Any, query: str) -> list[dict]:
    """Deterministic, zero-API text search over a sheet's word layer.

    Words are grouped into their extraction lines (``(block, line)`` from the
    PAGE_VIEW_V2 word tuples) and matched case-insensitively as a joined
    phrase, so a query can span words ("ROOM 101"). The match rect is the
    union of the covered words' rects; the context is the whole line. Order is
    the sheet's own word order; capped at ``_MAX_FIND_TEXT_MATCHES``.
    """
    words = list(getattr(sheet, "words", []) or [])
    needle = " ".join(str(query or "").split()).upper()
    if not words or not needle:
        return []
    # Group into lines, tolerating short word tuples (each its own line).
    lines: dict[tuple, list] = {}
    order: list[tuple] = []
    for i, w in enumerate(words):
        key = (w[5], w[6]) if len(w) >= 7 else ("w", i)
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(w)
    matches: list[dict] = []
    for key in order:
        line_words = lines[key]
        texts = [str(w[4]) for w in line_words]
        joined = " ".join(texts)
        hay = joined.upper()
        start = 0
        while True:
            pos = hay.find(needle, start)
            if pos < 0:
                break
            end = pos + len(needle)
            covered, offset = [], 0
            for w, t in zip(line_words, texts):
                w_start, w_end = offset, offset + len(t)
                if w_end > pos and w_start < end:
                    covered.append(w)
                offset = w_end + 1  # the joining space
            if covered:
                matches.append({
                    "rect": [round(v, 2) for v in _rect_union([_word_rect(w) for w in covered])],
                    "line": joined[:120],
                })
            start = end
            if len(matches) > _MAX_FIND_TEXT_MATCHES:
                break
        if len(matches) > _MAX_FIND_TEXT_MATCHES:
            break
    return matches


@dataclass
class _ToolExecutor:
    """Deterministic host-side executor for the investigation tools.

    ``execute`` never raises: an invalid request becomes an ``is_error``
    tool_result the model can react to. Every rendered image is saved to the
    evidence trail *before* being sent (§16.6) and recorded in ``tool_trace``
    so a future warm-cache replay can re-render and verify it byte-for-byte.
    """

    finding: Finding
    sheet: Any                          # the finding's own sheet
    sheet_id_map: dict
    evidence_dir: Path | None
    dir_name: str
    next_leg_index: int
    render_fn: RenderFn
    artifacts: list = field(default_factory=list)
    tool_trace: list = field(default_factory=list)

    def _resolve_sheet(self, tool_input: dict) -> tuple[Any, str]:
        """(sheet, error) — the finding's sheet unless a valid other is named."""
        sid = _norm_id(tool_input.get("sheet_id", ""))
        if not sid:
            source = str(tool_input.get("source_name", "") or "")
            page_number = tool_input.get("page_number")
            if source and page_number is not None:
                for sheet in self.sheet_id_map.values():
                    ref = getattr(sheet, "ref", None)
                    if (getattr(ref, "source_name", "") == source
                            and int(getattr(ref, "page_index", -1)) == int(page_number) - 1):
                        return sheet, ""
                return None, f"no sheet at {source} p.{page_number}"
            return self.sheet, ""
        sheet = self.sheet_id_map.get(sid)
        if sheet is None:
            known = ", ".join(list(self.sheet_id_map)[:_MAX_SHEET_INDEX_ENTRIES])
            return None, f"unknown sheet_id {sid!r}; known sheets: {known or 'none'}"
        return sheet, ""

    def _sheet_label(self, sheet: Any) -> str:
        for sid, s in self.sheet_id_map.items():
            if s is sheet:
                return sid
        return _norm_id(getattr(self.finding, "sheet_id", "")) or "sheet"

    def _render_and_save(
        self, sheet: Any, rect: list, dpi: int, kind: str
    ) -> tuple[list | str, bool, "bytes | None"]:
        """Render, save-before-send (§16.6), trace. Returns (content, is_error, png)."""
        png = None
        try:
            png = self.render_fn(sheet.ref.pdf_path, sheet.ref.page_index, rect, dpi)
        except Exception:  # noqa: BLE001 - a tool failure must never crash the loop
            png = None
        if not png:
            return "the region failed to render", True, None
        artifact = _save_crop(
            self.evidence_dir, self.dir_name, png,
            qc_id=self.finding.qc_id, leg_index=self.next_leg_index,
            sheet_id=self._sheet_label(sheet),
            source_id=str(getattr(getattr(sheet, "ref", None), "source_id", "") or ""),
            source_name=str(getattr(getattr(sheet, "ref", None), "source_name", "") or ""),
            page_index=int(getattr(getattr(sheet, "ref", None), "page_index", 0) or 0),
            anchor_rect=None, crop_rect=list(rect), dpi=int(dpi),
        )
        if self.evidence_dir is not None and artifact is None:
            # §16.6: a verdict may not rest on an image absent from the trail.
            return "evidence could not be saved; the image was not provided", True, None
        if artifact is not None:
            self.artifacts.append(artifact)
        self.next_leg_index += 1
        self.tool_trace.append({
            "kind": kind,
            "source_page_key": list(source_page_key(sheet.ref)),
            "sheet_label": self._sheet_label(sheet),
            # Full precision: a warm-cache replay re-renders this exact rect
            # and sha-compares — any rounding would change the pixels.
            "rect": [float(v) for v in rect],
            "dpi": int(dpi),
            "sha256": artifact.sha256 if artifact is not None else "",
        })
        ref = sheet.ref
        label = (
            f"{kind} of {ref.source_name} p.{int(ref.page_index) + 1} "
            f"rect {[round(float(v), 1) for v in rect]} at {int(dpi)} DPI:"
        )
        return [{"type": "text", "text": label}, _image_block(png)], False, png

    def execute(self, name: str, tool_input: dict) -> tuple[list | str, bool]:
        """Returns ``(tool_result content, is_error)``. Deterministic; never raises."""
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        if name == "crop_region":
            return self._crop_region(tool_input)
        if name == "find_text":
            return self._find_text(tool_input)
        if name == "view_sheet":
            return self._view_sheet(tool_input)
        return f"unknown tool {name!r}", True

    def _crop_region(self, tool_input: dict) -> tuple[list | str, bool]:
        raw = tool_input.get("rect")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return "rect must be [x0, y0, x1, y1] in points", True
        try:
            x0, y0, x1, y1 = (float(v) for v in raw)
        except (TypeError, ValueError):
            return "rect must be [x0, y0, x1, y1] in points", True
        if not all(v == v and abs(v) != float("inf") for v in (x0, y0, x1, y1)):
            return "rect must be finite numbers", True
        sheet, err = self._resolve_sheet(tool_input)
        if sheet is None:
            return err, True
        page_w = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
        page_h = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if page_w > 0:
            x0, x1 = max(0.0, min(x0, page_w)), max(0.0, min(x1, page_w))
        if page_h > 0:
            y0, y1 = max(0.0, min(y0, page_h)), max(0.0, min(y1, page_h))
        if (x1 - x0) < _MIN_RECT_SPAN_PT or (y1 - y0) < _MIN_RECT_SPAN_PT:
            return "rect lies outside the sheet (or is degenerate after clamping)", True
        try:
            dpi = int(tool_input.get("dpi", _MAX_CROP_DPI))
        except (TypeError, ValueError):
            dpi = _MAX_CROP_DPI
        dpi = min(_MAX_CROP_DPI, max(_MIN_CROP_DPI, dpi))
        content, is_error, _png = self._render_and_save(
            sheet, [x0, y0, x1, y1], dpi, "crop_region"
        )
        return content, is_error

    def _find_text(self, tool_input: dict) -> tuple[list | str, bool]:
        query = str(tool_input.get("query", "") or "").strip()
        if len(query) < 2:
            return "query must be at least 2 characters", True
        sheet, err = self._resolve_sheet(tool_input)
        if sheet is None:
            return err, True
        if not (getattr(sheet, "words", None) or []):
            return (
                [{"type": "text", "text": "no text layer (raster sheet); use crop_region"}],
                False,
            )
        matches = find_text_matches(sheet, query)
        shown = matches[:_MAX_FIND_TEXT_MATCHES]
        payload = {"query": query, "matches": shown}
        if len(matches) > len(shown):
            payload["note"] = f"+{len(matches) - len(shown)} more match(es) not shown"
        if not shown:
            payload["note"] = "no matches"
        return [{"type": "text", "text": json.dumps(payload, sort_keys=True)}], False

    def _view_sheet(self, tool_input: dict) -> tuple[list | str, bool]:
        if not _norm_id(tool_input.get("sheet_id", "")) and not tool_input.get("source_name"):
            return "name a sheet_id or a source_name + page_number", True
        sheet, err = self._resolve_sheet(tool_input)
        if sheet is None:
            return err, True
        page_w = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
        page_h = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)
        if page_w <= 0 or page_h <= 0:
            return "sheet has no page geometry", True
        content, is_error, _png = self._render_and_save(
            sheet, [0.0, 0.0, page_w, page_h], _VIEW_SHEET_DPI, "view_sheet"
        )
        return content, is_error


@dataclass
class _InvestigationOutcome:
    outcome: str = "error"        # concluded | budget_capped | not_concluded | error
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fatal: bool = False
    note: str = ""
    tool_trace: list = field(default_factory=list)


def _build_initial_content(
    finding: Finding, crop_png: bytes, sheet_index: str, budget: int
) -> list:
    quote = finding.source_quote.strip()
    header = (
        f"FINDING to investigate (category={finding.category}, "
        f"severity={finding.severity}):\n{finding.text.strip()}"
    )
    if quote:
        header += f'\nText the first reviewer quoted from the sheet: "{quote}"'
    prior = (finding.verification.note if finding.verification is not None else "") or ""
    header += f"\nA first-pass reviewer judged this UNCERTAIN: {prior or 'no note'}"
    legs = [
        _norm_id(getattr(leg, "sheet_id", ""))
        for leg in (getattr(finding, "also_on", None) or [])
        if _norm_id(getattr(leg, "sheet_id", ""))
    ]
    if legs:
        header += "\nThe finding also involves sheet(s): " + ", ".join(legs)
    content: list = [
        {"type": "text", "text": header},
        {"type": "text", "text": "The region the first reviewer saw follows:"},
        _image_block(crop_png),
    ]
    if sheet_index:
        content.append({"type": "text", "text": sheet_index})
    content.append({"type": "text", "text": (
        f"You may make up to {budget} evidence request(s). Use the tools to "
        "gather what you need, then respond with ONLY the JSON verdict object."
    )})
    return content


_BUDGET_EXHAUSTED_TEXT = (
    "Evidence budget exhausted — respond now with ONLY the JSON verdict object."
)


def _investigate_one(
    finding: Finding,
    sheet: Any,
    *,
    client: Any,
    model: str,
    tools: list[dict],
    sheet_id_map: dict,
    sheet_index: str,
    evidence_dir: Path | None,
    used_evidence_names: set,
    max_rounds: int,
    max_retries: int,
    sleep: Any,
    render_fn: RenderFn,
) -> _InvestigationOutcome:
    """Run one bounded investigation; mutates ``finding.verification`` on any
    non-error outcome. Never raises."""
    out = _InvestigationOutcome()

    old = finding.verification if finding.verification is not None else Verification()
    # Continue the verify pass's evidence directory and leg numbering.
    dir_name, next_leg = _evidence_continuation(finding, used_evidence_names)

    executor = _ToolExecutor(
        finding=finding, sheet=sheet, sheet_id_map=sheet_id_map,
        evidence_dir=evidence_dir, dir_name=dir_name,
        next_leg_index=next_leg, render_fn=render_fn,
    )

    page_w = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
    page_h = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)
    crop_rect = context_rect(finding.anchor.rect_pdf, page_w, page_h)
    initial, initial_err, crop_png = executor._render_and_save(
        sheet, crop_rect, _MAX_CROP_DPI, "initial_crop"
    )
    if initial_err or crop_png is None:
        out.note = str(initial)
        return out

    messages: list[dict] = [{
        "role": "user",
        "content": _build_initial_content(finding, crop_png, sheet_index, max_rounds),
    }]

    tool_round = 0
    pause_count = 0
    hard_stop = max_rounds + _MAX_PAUSE_RESUMES + 3   # backstop, never hit normally

    for _iteration in range(hard_stop):
        kwargs: dict = {
            "model": model,
            "max_tokens": phase_output_cap(PHASE_INVESTIGATION, model=model),
            "system": system_prompt_with_cache(
                INVESTIGATE_SYSTEM_PROMPT, phase=PHASE_INVESTIGATION
            ),
            "messages": messages,
        }
        if tool_round < max_rounds:
            kwargs["tools"] = tools_with_cache(list(tools), phase=PHASE_INVESTIGATION)
        apply_thinking_config(kwargs, model=model, phase=PHASE_INVESTIGATION)
        apply_effort_config(kwargs, model=model, phase=PHASE_INVESTIGATION)

        attempt = 0
        while True:
            try:
                resp = client.messages.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - degrade, never raise (I-3)
                if _is_transient_error(exc) and attempt < max_retries:
                    sleep(_retry_backoff_seconds(attempt))
                    attempt += 1
                    continue
                out.note = _clean_error(exc)
                out.fatal = _error_status(exc) in _FATAL_STATUSES
                out.rounds = tool_round
                out.tool_trace = executor.tool_trace
                return out

        tin, tout = _message_usage(resp)
        out.input_tokens += tin
        out.output_tokens += tout
        stop = str(getattr(resp, "stop_reason", "") or "")
        content = list(getattr(resp, "content", None) or [])

        if stop == "pause_turn":
            pause_count += 1
            if pause_count > _MAX_PAUSE_RESUMES:
                out.outcome = "not_concluded"
                break
            messages = messages + [{"role": "assistant", "content": content}]
            continue

        if stop == "tool_use":
            requests = [b for b in content if getattr(b, "type", "") == "tool_use"]
            if not requests or tool_round >= max_rounds:
                # No tools were offered (or an empty tool turn): close out.
                out.outcome = "not_concluded"
                break
            # Commit the assistant turn BEFORE answering its tools, then answer
            # every id in one user turn.
            messages = messages + [{"role": "assistant", "content": content}]
            results = []
            for block in requests:
                content_out, is_error = executor.execute(
                    str(getattr(block, "name", "") or ""),
                    getattr(block, "input", None),
                )
                result_block: dict = {
                    "type": "tool_result",
                    "tool_use_id": str(getattr(block, "id", "") or ""),
                    "content": content_out,
                }
                if is_error:
                    result_block["is_error"] = True
                results.append(result_block)
            tool_round += 1
            user_content: list = list(results)
            if tool_round >= max_rounds:
                user_content.append({"type": "text", "text": _BUDGET_EXHAUSTED_TEXT})
            messages = messages + [{"role": "user", "content": user_content}]
            continue

        if stop in ("end_turn", "stop_sequence", ""):
            # A genuine NOT_VISIBLE conclusion and a garbled reply both map to
            # UNCERTAIN through parse_verdict — distinguish them on the raw
            # verdict token so garble is "not_concluded", never a conclusion.
            text = _message_text(resp)
            obj = _tolerant_json_object(text)
            raw = (
                str(obj.get("verdict", "")).strip().upper()
                if isinstance(obj, dict) else ""
            )
            if raw not in ("CONFIRMED", "CONTRADICTED", "NOT_VISIBLE"):
                out.outcome = "not_concluded"
                break
            status, note = parse_verdict(text)
            out.outcome = "concluded"
            out.note = note
            finding.verification = Verification(
                status=status,
                note=("investigated: " + note)[:_NOTE_CAP],
                evidence=list(old.evidence) + list(executor.artifacts),
                computation_method=old.computation_method,
                operand_origin=old.operand_origin,
                investigated=True,
                investigation_rounds=tool_round,
            )
            break

        # max_tokens / refusal / anything unexpected.
        out.outcome = "not_concluded"
        break
    else:
        out.outcome = "not_concluded"

    out.rounds = tool_round
    out.tool_trace = executor.tool_trace
    if out.outcome != "concluded":
        # Budget-capped or garbled: the UNCERTAIN verdict stands; record that
        # the loop tried (and keep the new evidence — the trail is the point).
        out.outcome = "budget_capped" if tool_round >= max_rounds else "not_concluded"
        suffix = f"investigated {tool_round} round(s) without conclusion"
        note = f"{old.note}; {suffix}" if old.note else suffix
        finding.verification = Verification(
            status=old.status,
            note=note[:_NOTE_CAP],
            evidence=list(old.evidence) + list(executor.artifacts),
            computation_method=old.computation_method,
            operand_origin=old.operand_origin,
            investigated=True,
            investigation_rounds=tool_round,
        )
    _write_investigation_json(evidence_dir, dir_name, finding, model, out)
    return out


def _write_investigation_json(
    evidence_dir: Path | None, dir_name: str, finding: Finding,
    model: str, out: _InvestigationOutcome,
) -> None:
    """``evidence/<dir>/investigation.json`` — the ordered tool trace + verdict.
    Best-effort; no key, no absolute paths."""
    if evidence_dir is None:
        return
    v = finding.verification
    payload = {
        "qc_id": finding.qc_id,
        "finding_id": finding.id,
        "model": model,
        "prompt_version": INVESTIGATE_PROMPT_VERSION,
        "outcome": out.outcome,
        "rounds": out.rounds,
        "verdict": v.status if v is not None else "",
        "note": v.note if v is not None else "",
        "tool_trace": out.tool_trace,
    }
    try:
        (evidence_dir / dir_name / "investigation.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError:
        _log.warning("could not write investigation.json for %s", finding.qc_id or dir_name)


def set_content_fingerprint(documents: Iterable[Any]) -> str:
    """One sha256 over the sorted ``(source_id, content_sha256)`` pairs.

    The whole set is an investigation's input — the tools can roam every
    sheet — so any source edit must invalidate every cached verdict. Returns
    ``""`` (caching off, the safe default) when any document's content hash is
    unknown.
    """
    pairs = sorted(
        (str(getattr(d, "source_id", "") or ""),
         str(getattr(d, "content_sha256", "") or ""))
        for d in documents or []
    )
    if not pairs or any(not sha for _sid, sha in pairs):
        return ""
    h = hashlib.sha256()
    for sid, sha in pairs:
        h.update(sid.encode("utf-8"))
        h.update(b"\x1f")
        h.update(sha.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _payload_hash(finding: Finding, set_fingerprint: str) -> str:
    """The investigated finding's identity for the cache key (Phase C4)."""
    rect = finding.anchor.rect_pdf if finding.anchor is not None else None
    rect_part = ",".join(f"{float(v):.2f}" for v in rect) if rect else ""
    prior = finding.verification.note if finding.verification is not None else ""
    h = hashlib.sha256()
    for part in (
        finding.id or "", finding.text or "", finding.source_quote or "",
        finding.category or "", finding.severity or "", rect_part,
        prior or "", set_fingerprint or "",
    ):
        h.update(str(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _evidence_continuation(finding: Finding, used: set) -> tuple[str, int]:
    """(dir_name, next_leg_index) continuing the verify pass's evidence trail."""
    old = finding.verification if finding.verification is not None else Verification()
    dir_name = ""
    for artifact in old.evidence:
        parts = str(getattr(artifact, "relative_path", "") or "").split("/")
        if len(parts) >= 3 and parts[0] == "evidence":
            dir_name = parts[1]
            break
    if not dir_name:
        dir_name = _reserve_evidence_dir(finding, used)
    next_leg = max((int(a.leg_index) for a in old.evidence), default=-1) + 1
    return dir_name, next_leg


def _replay_cached(
    finding: Finding,
    entry: dict,
    *,
    lookup: dict,
    evidence_dir: Path | None,
    used_evidence_names: set,
    render_fn: RenderFn,
    model: str,
) -> bool:
    """Deterministically replay a cached conclusion (§16.6 + I-7).

    Re-renders every step of the stored tool trace and sha-compares against
    the recorded bytes; the verdict is applied ONLY on a full byte-for-byte
    match, with the evidence re-created on disk exactly as the cold run left
    it. Any mismatch (a drifted render, a missing sheet, a save failure)
    returns ``False`` and the caller runs the investigation live.
    """
    status = str(entry.get("status", "") or "")
    trace = entry.get("tool_trace")
    if status not in ("VERIFIED", "REJECTED", "UNCERTAIN"):
        return False
    if not isinstance(trace, list) or not trace:
        return False
    # Verify every render BEFORE saving anything.
    rendered: list[tuple[dict, Any, bytes]] = []
    for step in trace:
        if not isinstance(step, dict) or not step.get("sha256"):
            return False
        sheet = lookup.get(tuple(step.get("source_page_key") or ()))
        if sheet is None:
            return False
        try:
            png = render_fn(
                sheet.ref.pdf_path, sheet.ref.page_index,
                [float(v) for v in step.get("rect") or []], int(step.get("dpi", 0)),
            )
        except Exception:  # noqa: BLE001 - a replay failure is just a miss
            return False
        if not png or hashlib.sha256(png).hexdigest() != step["sha256"]:
            return False
        rendered.append((step, sheet, png))

    old = finding.verification if finding.verification is not None else Verification()
    dir_name, next_leg = _evidence_continuation(finding, used_evidence_names)
    artifacts = []
    for step, sheet, png in rendered:
        artifact = _save_crop(
            evidence_dir, dir_name, png,
            qc_id=finding.qc_id, leg_index=next_leg,
            sheet_id=str(step.get("sheet_label", "") or finding.sheet_id or "sheet"),
            source_id=str(getattr(getattr(sheet, "ref", None), "source_id", "") or ""),
            source_name=str(getattr(getattr(sheet, "ref", None), "source_name", "") or ""),
            page_index=int(getattr(getattr(sheet, "ref", None), "page_index", 0) or 0),
            anchor_rect=None, crop_rect=[float(v) for v in step.get("rect") or []],
            dpi=int(step.get("dpi", 0)),
        )
        if evidence_dir is not None and artifact is None:
            return False
        if artifact is not None:
            artifacts.append(artifact)
        next_leg += 1

    rounds = int(entry.get("rounds", 0) or 0)
    finding.verification = Verification(
        status=status,
        note=str(entry.get("note", "") or "")[:_NOTE_CAP],
        evidence=list(old.evidence) + artifacts,
        computation_method=old.computation_method,
        operand_origin=old.operand_origin,
        investigated=True,
        investigation_rounds=rounds,
    )
    out = _InvestigationOutcome(outcome="concluded", rounds=rounds, tool_trace=list(trace))
    _write_investigation_json(evidence_dir, dir_name, finding, model, out)
    return True


@dataclass
class InvestigationRecord:
    """One investigation's accounting (feeds the per-instance usage records)."""

    qc_id: str = ""
    outcome: str = ""
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


@dataclass
class InvestigateResult:
    investigated: int = 0
    verified: int = 0
    rejected: int = 0
    still_uncertain: int = 0
    budget_capped: int = 0
    cache_hits: int = 0
    skipped_over_budget: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fatal: bool = False
    errors: list = field(default_factory=list)
    per_finding: list = field(default_factory=list)


def _candidates(findings: Iterable[Finding]) -> list[Finding]:
    picked = [
        f for f in findings
        if f.verification is not None
        and f.verification.status == "UNCERTAIN"
        and f.anchor is not None and f.anchor.rect_pdf is not None
    ]
    picked.sort(key=lambda f: (
        _SEVERITY_RANK.get(str(f.severity).lower(), 3), f.qc_id or "", f.id or "",
    ))
    return picked


def investigate_findings(
    findings: Iterable[Finding],
    sheets: Iterable[Any],
    *,
    client: Any = None,
    model: str | None = None,
    evidence_dir: Path | None = None,
    max_rounds: int | None = None,
    max_investigations: int | None = None,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
    cache: Any = None,
    set_fingerprint: str = "",
    render_fn: RenderFn | None = None,
) -> InvestigateResult:
    """Escalate every UNCERTAIN, anchored finding through the investigation loop.

    Mutates ``finding.verification`` in place (legal post-seal). Strictly
    sequential (PyMuPDF renders interleave with API turns). Never raises: a
    client that cannot be constructed, or a fatal auth failure mid-pass, leaves
    the remaining findings' existing UNCERTAIN verdicts untouched (they are
    already valid) and reports the reason in ``result.errors`` (I-3).
    """
    findings = list(findings)
    sheets = list(sheets)
    result = InvestigateResult()
    model = model or investigation_model()
    max_rounds = max_rounds if max_rounds is not None else investigation_max_rounds()
    max_investigations = (
        max_investigations if max_investigations is not None
        else investigation_max_findings()
    )
    render_fn = render_fn or _default_render_fn

    picked = _candidates(findings)
    if not picked:
        return result
    if len(picked) > max_investigations:
        result.skipped_over_budget = len(picked) - max_investigations
        picked = picked[:max_investigations]

    lookup, ambiguous = _sheet_lookup(sheets)
    sheet_id_map = _sheet_id_map(findings, sheets, lookup)
    sheet_index = _sheet_index_text(sheet_id_map)

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - the UNCERTAIN verdicts stand
            note = _clean_error(exc)
            result.errors.append(f"investigation skipped (client unavailable): {note}")
            _log.warning("investigation skipped (client unavailable): %s", note)
            return result

    tools = investigation_tools()
    used_evidence_names: set = set()
    total = len(picked)
    # Phase C4: the verdict cache is keyed on the finding + the whole-set
    # content fingerprint; an empty fingerprint disables it (safe default).
    use_cache = cache is not None and bool(set_fingerprint)

    for i, finding in enumerate(picked):
        if progress is not None:
            progress(i, total, f"Investigating finding {i + 1}/{total}")
        key = source_page_key(finding)
        sheet = None if key in ambiguous else lookup.get(key)
        if sheet is None:
            result.errors.append(
                f"{finding.qc_id or finding.id}: sheet not available for investigation"
            )
            continue
        cache_key = None
        if use_cache:
            from .digest_cache import investigation_cache_key

            cache_key = investigation_cache_key(
                _payload_hash(finding, set_fingerprint),
                model=model, prompt_version=INVESTIGATE_PROMPT_VERSION,
                max_rounds=max_rounds,
            )
            entry = cache.get(cache_key)
            if entry is not None and _replay_cached(
                finding, entry, lookup=lookup, evidence_dir=evidence_dir,
                used_evidence_names=used_evidence_names, render_fn=render_fn,
                model=model,
            ):
                result.investigated += 1
                result.cache_hits += 1
                status = finding.verification.status
                if status == "VERIFIED":
                    result.verified += 1
                elif status == "REJECTED":
                    result.rejected += 1
                else:
                    result.still_uncertain += 1
                result.per_finding.append(InvestigationRecord(
                    qc_id=finding.qc_id or "", outcome="concluded",
                    rounds=int(entry.get("rounds", 0) or 0), cached=True,
                ))
                continue
        result.investigated += 1
        outcome = _investigate_one(
            finding, sheet, client=client, model=model, tools=tools,
            sheet_id_map=sheet_id_map, sheet_index=sheet_index,
            evidence_dir=evidence_dir, used_evidence_names=used_evidence_names,
            max_rounds=max_rounds, max_retries=max_retries, sleep=sleep,
            render_fn=render_fn,
        )
        result.input_tokens += outcome.input_tokens
        result.output_tokens += outcome.output_tokens
        record = InvestigationRecord(
            qc_id=finding.qc_id or "", outcome=outcome.outcome,
            rounds=outcome.rounds, input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
        )
        result.per_finding.append(record)
        if outcome.outcome == "concluded":
            status = finding.verification.status
            if status == "VERIFIED":
                result.verified += 1
            elif status == "REJECTED":
                result.rejected += 1
            else:
                result.still_uncertain += 1
            # Complete-only admission (Phase C4): cache ONLY a clean conclusion
            # whose every rendered step carries an evidence sha the warm replay
            # can verify — never a budget-capped, garbled, or errored outcome.
            if (
                cache_key is not None
                and outcome.tool_trace
                and all(step.get("sha256") for step in outcome.tool_trace)
            ):
                cache.put(cache_key, {
                    "status": status,
                    "note": finding.verification.note,
                    "rounds": outcome.rounds,
                    "tool_trace": list(outcome.tool_trace),
                })
        elif outcome.outcome == "budget_capped":
            result.budget_capped += 1
            result.still_uncertain += 1
        elif outcome.outcome == "error":
            result.errors.append(
                f"{finding.qc_id or finding.id}: {outcome.note or 'investigation failed'}"
            )
            if outcome.fatal:
                result.fatal = True
                result.errors.append(
                    "investigation stopped early (fatal auth failure); remaining "
                    "findings keep their existing verdicts"
                )
                break
        else:
            result.still_uncertain += 1
    if progress is not None:
        progress(total, total, "Investigation complete")
    return result
