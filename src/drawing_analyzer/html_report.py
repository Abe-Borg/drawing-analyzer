"""Self-contained, navigable HTML report for a drawing digest.

The raw output of a run is a wall of Markdown — one digest per sheet plus a
cross-sheet synthesis, concatenated. That is *complete* but hard to navigate: an
operator who only wants the coordination items, or the conflicts the model
flagged across the set, has to scroll a massive file. This module renders the
same :class:`~drawing_analyzer.pipeline.DrawingContext` into a single, dependency-free
HTML file that keeps **every** word the model produced while making it
explorable — a sidebar table of contents, a live text search, and category
filters (Coordination, Conflicts, Equipment & Schedules, …) so the operator can
isolate exactly the sections they care about.

Design constraints, mirroring :mod:`drawing_analyzer.export`:

- **Pure & duck-typed.** Reads only the documented attributes off the context
  (``sheets`` / ``synthesis_text`` / ``focus`` / ``focus_report_text`` /
  ``combined_text`` / the run-summary counts / ``errors``); it never imports the
  engine, tkinter, PyMuPDF, or the network, so it unit-tests in isolation. See
  :func:`build_html_report`.
- **Lossless.** The structured view is rendered from each sheet's digest, and the
  exact, verbatim ``combined_text`` is also embedded (collapsed) so the original
  Markdown is always one click / copy away — the rendering can never *drop*
  content, only present it.
- **Self-contained.** All CSS and JavaScript are inlined; the result is one
  ``.html`` file the operator can double-click, search, filter, print, or email
  with no server, build step, or internet access.

In-report Q&A assistant (Ask AI)
--------------------------------
The report embeds a chat widget ("Ask AI") **by default** that answers
questions about the results. It calls the Anthropic Messages API **directly from
the reader's browser** (no server), grounded in the very report text already
embedded in the page (the ``#raw-md`` block), with streaming, adaptive thinking,
and the server-side web search / web fetch tools enabled. The report block is
sent with a prompt-cache breakpoint so follow-up questions re-read the (large)
report at cache prices.

**Key handling.** By default the key is **not** written into the file — even
when the caller has one: the widget asks the reader for a key on first use and
keeps it only in the browser tab's ``sessionStorage`` (the **Forget key**
control clears both the in-memory copy and sessionStorage) — so the file is
safe to share and the key never touches disk. Pass ``embed_api_key=True`` (with
a key) to bake the key into the HTML instead (zero-friction: double-click and
ask) — the file must then never be shared, and the report carries a **red
warning** saying so; a runtime "forget" cannot remove an embedded key, and the
widget says exactly that. Pass ``include_chat=False`` to omit the widget (and
every network reference) entirely. The *Python* module still performs no
network I/O.

**Transcript persistence.** The conversation lives only in the tab's memory
(nothing is written to disk or a server), so a **Save as PDF** control
reformats the already-rendered message DOM for print and hands off to the
browser's native print dialog (no new script, host, or dependency — "Save as
PDF" is just a print destination there). A ``beforeunload`` handler warns
before a refresh, close, or navigation silently drops that history.

**Security boundary.** All model output and every run-derived value (filenames,
titles, errors, quotes…) is treated as hostile — see the trust-boundary note
above the imports: escaped-into-content on the Python side, safe-DOM-built on
the browser side, one https-only URL policy for all links/citations, an inert
JSON config island, and a hash-pinned Content-Security-Policy.

The Markdown→HTML conversion is a small, deliberately-scoped renderer
(:func:`markdown_to_html`) covering exactly the constructs the digests use —
headings, ``**bold**``, ``` `code` ```, bullet/numbered lists, GFM pipe tables
(schedules), block quotes (failed-sheet notices), and horizontal rules. It
escapes all model text, and any line it does not recognize falls through as an
escaped paragraph, so nothing is ever lost.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .core.api_config import CHAT_MODEL_DEFAULT

# --------------------------------------------------------------------------- #
# Report trust boundary (Phase 17, DA-011).
#
# Everything that reaches this document is untrusted: drawing text feeds the
# prompts, so *model output* (digests, findings, assistant answers) can be
# attacker-influenced, and filenames/errors/config values can carry hostile
# markup. The rules, enforced here and in the widget JS:
#
#   - Python side: every untrusted value is html.escape()d into element
#     content, or _esc_attr()'d into attributes; dynamic values never form
#     tag/attribute syntax.
#   - The only dynamic <script> payload is the chat config, emitted as inert
#     type="application/json" through _json_for_script(), which escapes "<"
#     (and the U+2028/U+2029 line separators) so no value — however hostile a
#     filename — can close the script element or form markup.
#   - Browser side: the widget builds DOM via createElement/textContent only
#     (no innerHTML/insertAdjacentHTML/document.write with model data), and
#     every link goes through one URL validator (absolute https only).
#   - Defense in depth: a Content-Security-Policy <meta> allows exactly the
#     two inline scripts by SHA-256 hash, connects only to the Anthropic API
#     (when the assistant is enabled), and forbids objects/base/forms.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Section categories — the spine of the "isolate what I care about" feature.
#
# Every digest section (a bold/heading-led block) is tagged with one category by
# keyword-matching its header, so the report's filter chips can show, e.g., only
# the Coordination and Conflict sections across the whole set. Order is priority:
# a header matching several groups takes the *first* listed, so "Cross-sheet /
# cross-discipline conflicts" classifies as a conflict (the highest-value output)
# rather than mere coordination.
# --------------------------------------------------------------------------- #

CATEGORY_OTHER = "other"

# (id, label, (keyword, ...)) in priority order.
_CATEGORY_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("focus", "Focus",
     ("focus",)),
    ("conflict", "Conflicts",
     ("conflict", "inconsist", "discrepan", "mismatch", "disagree", "contradic",
      "never drawn", "never shown", "but not", "missing")),
    ("coordination", "Coordination",
     ("coordinat", "cross-discipline", "cross discipline", "cross-sheet",
      "cross sheet", "penetration", "shared chase", "another discipline",
      "another trade", "spanning sheets", "tag cross")),
    ("equipment", "Equipment & Schedules",
     ("equipment", "schedule", "fixture")),
    ("dimensions", "Dimensions",
     ("dimension", "elevation", "clearance", "slope", "size", "pipe", "duct",
      "capacity")),
    ("notes", "Notes & Keynotes",
     ("note", "keynote", "callout", "legend", "abbreviation")),
    ("scope", "Scope & Systems",
     ("scope", "system", "plan content", "spaces", "rooms", "set-wide",
      "set wide", "discipline")),
]

# Public id → display label, in chip order.
CATEGORY_LABELS: dict[str, str] = {cid: label for cid, label, _ in _CATEGORY_SPECS}
CATEGORY_LABELS[CATEGORY_OTHER] = "Other"

# The two highest-value categories, surfaced together as a one-click "Issues"
# filter (the coordination items + the conflicts the model flagged).
ISSUE_CATEGORIES: tuple[str, ...] = ("coordination", "conflict")


def classify_section(header: str | None) -> str:
    """Tag a section by its header text — one of :data:`CATEGORY_LABELS`'s ids.

    Matching is case-insensitive substring against the priority-ordered keyword
    groups, so ``"Coordination / cross-discipline items"`` → ``"coordination"``
    and ``"Cross-sheet / cross-discipline conflicts"`` → ``"conflict"`` (conflict
    is listed first, so it wins when a header reads as both). A header with no
    keyword — or no header at all (a digest's lead-in prose) — is ``"other"``.
    """
    if not header:
        return CATEGORY_OTHER
    low = header.lower()
    for cid, _label, keywords in _CATEGORY_SPECS:
        if any(kw in low for kw in keywords):
            return cid
    return CATEGORY_OTHER


# --------------------------------------------------------------------------- #
# Minimal Markdown → HTML. Scoped to exactly what the digests emit; everything
# is HTML-escaped and any unrecognized line degrades to an escaped paragraph, so
# the rendering is lossless (it can only fail to *style* a line, never drop it).
# --------------------------------------------------------------------------- #

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|?\s*$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])")


def _render_inline(text: str) -> str:
    """Escape one line and apply inline Markdown: code, bold, italic.

    Underscores are left literal — technical digests are full of ``file_name`` /
    ``VAV_3``-style tokens, and treating ``_`` as emphasis would mangle them; the
    digests use ``*`` for the rare emphasis. Code spans are extracted to
    placeholders *before* bold/italic so a ``*`` inside backticks is never
    treated as emphasis, then restored.
    """
    escaped = html.escape(text, quote=False)

    codes: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00C{len(codes) - 1}\x00"

    out = _INLINE_CODE_RE.sub(_stash_code, escaped)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _ITALIC_RE.sub(r"<em>\1</em>", out)

    def _restore_code(m: re.Match[str]) -> str:
        return codes[int(m.group(1))]

    return re.sub(r"\x00C(\d+)\x00", _restore_code, out)


def _split_row(row: str) -> list[str]:
    """Split one GFM table row into trimmed cell strings."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _alignments(sep_row: str) -> list[str]:
    aligns: list[str] = []
    for cell in _split_row(sep_row):
        left = cell.startswith(":")
        right = cell.endswith(":")
        aligns.append(
            "center" if left and right else "right" if right else "left" if left else ""
        )
    return aligns


def _cell(tag: str, content: str, align: str) -> str:
    style = f' style="text-align:{align}"' if align else ""
    return f"<{tag}{style}>{_render_inline(content)}</{tag}>"


def _consume_table(lines: list[str], i: int) -> tuple[str, int]:
    """Render a GFM pipe table starting at ``lines[i]`` (header + separator)."""
    header = _split_row(lines[i])
    aligns = _alignments(lines[i + 1])
    j = i + 2
    body: list[list[str]] = []
    while j < len(lines) and "|" in lines[j] and lines[j].strip():
        body.append(_split_row(lines[j]))
        j += 1

    def _align(k: int) -> str:
        return aligns[k] if k < len(aligns) else ""

    parts = ["<table><thead><tr>"]
    parts += [_cell("th", h, _align(k)) for k, h in enumerate(header)]
    parts.append("</tr></thead><tbody>")
    for cells in body:
        parts.append("<tr>")
        parts += [_cell("td", c, _align(k)) for k, c in enumerate(cells)]
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts), j


def _build_list_html(items: list[tuple[int, bool, str]]) -> str:
    """Render a flat ``(indent, ordered, content)`` run as nested HTML lists.

    Stack-based and **loss-proof**: every item is emitted exactly once. A deeper
    indent opens a nested list inside the currently-open ``<li>``; a shallower
    indent closes lists until the item fits. Crucially, an item that dedents to a
    level *between* two open ones is attached to the nearest enclosing list rather
    than dropped — the model does emit irregular indentation, and the earlier
    recursive version silently lost every item below such a dedent (e.g. the
    second top-level bullet after a 4-space → 2-space step), breaking the
    module's lossless guarantee.
    """
    parts: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, tag) of each currently-open list
    for indent, ordered, content in items:
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            parts.append(f"</li></{stack[-1][1]}>")
            stack.pop()
        if not stack or indent > stack[-1][0]:
            parts.append(f"<{tag}>")
            stack.append((indent, tag))
        else:  # same level as the open list — a sibling item
            parts.append("</li>")
        parts.append(f"<li>{_render_inline(content)}")
    while stack:
        parts.append(f"</li></{stack[-1][1]}>")
        stack.pop()
    return "".join(parts)


def _consume_list(lines: list[str], i: int) -> tuple[str, int]:
    items: list[tuple[int, bool, str]] = []
    while i < len(lines):
        m = _LIST_ITEM_RE.match(lines[i])
        if not m:
            break
        indent = len(m.group(1).expandtabs(4))
        ordered = m.group(2) not in ("-", "*", "+")
        items.append((indent, ordered, m.group(3)))
        i += 1
    return _build_list_html(items), i


def _consume_blockquote(lines: list[str], i: int) -> tuple[str, int]:
    inner: list[str] = []
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        inner.append(re.sub(r"^\s*>\s?", "", lines[i]))
        i += 1
    return f"<blockquote>{markdown_to_html(chr(10).join(inner))}</blockquote>", i


def _consume_fence(lines: list[str], i: int) -> tuple[str, int]:
    j = i + 1
    body: list[str] = []
    while j < len(lines) and not lines[j].strip().startswith("```"):
        body.append(lines[j])
        j += 1
    code = html.escape("\n".join(body), quote=False)
    return f"<pre><code>{code}</code></pre>", (j + 1 if j < len(lines) else j)


def markdown_to_html(md: str) -> str:
    """Render the Markdown subset the digests use to a safe HTML fragment.

    Supports headings, horizontal rules, ``>`` block quotes, GFM pipe tables,
    fenced code, nested ordered/unordered lists, and paragraphs with inline
    ``**bold**`` / ``*italic*`` / ``` `code` ```. All text is HTML-escaped; an
    unrecognized line becomes an escaped paragraph (never dropped).
    """
    if not md or not md.strip():
        return ""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            chunk, i = _consume_fence(lines, i)
            out.append(chunk)
            continue
        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue
        m = _HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_render_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue
        if line.lstrip().startswith(">"):
            chunk, i = _consume_blockquote(lines, i)
            out.append(chunk)
            continue
        if (
            "|" in line
            and i + 1 < n
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            chunk, i = _consume_table(lines, i)
            out.append(chunk)
            continue
        if _LIST_ITEM_RE.match(line):
            chunk, i = _consume_list(lines, i)
            out.append(chunk)
            continue

        # Paragraph: gather consecutive "plain" lines.
        para: list[str] = []
        while i < n and lines[i].strip() and not _is_block_start(lines, i):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + "<br>".join(_render_inline(p) for p in para) + "</p>")
    return "".join(out)


def _is_block_start(lines: list[str], i: int) -> bool:
    """True when ``lines[i]`` begins a non-paragraph block (ends a paragraph)."""
    line = lines[i]
    stripped = line.strip()
    if stripped.startswith("```") or stripped.startswith(">"):
        return True
    if _HR_RE.match(line) or _HEADING_RE.match(stripped) or _LIST_ITEM_RE.match(line):
        return True
    return "|" in line and i + 1 < len(lines) and bool(_TABLE_SEP_RE.match(lines[i + 1]))


# --------------------------------------------------------------------------- #
# Section splitting — used both to render and to tag each block for filtering.
# --------------------------------------------------------------------------- #

# A whole-line section header is a *single* bold span covering the line (e.g.
# ``**Coordination / cross-discipline items**``), optionally with a trailing
# colon. The inner part must contain no ``*`` so a normal sentence that merely
# *contains* two bold spans (``**VAV-3** is shown on **M-501**``) is not misread
# as a header and folded into the table of contents.
_WHOLE_LINE_BOLD_RE = re.compile(r"^\*\*[^*]+\*\*:?$")


def _is_section_header(line: str) -> bool:
    s = line.strip()
    return bool(_HEADING_RE.match(s) or _WHOLE_LINE_BOLD_RE.match(s))


def _clean_header(line: str) -> str:
    """Plain header text: strip ``#`` markers, surrounding ``**``, trailing ``:``."""
    s = line.strip()
    s = re.sub(r"^#{1,6}\s*", "", s).strip()
    if s.startswith("**") and s.rstrip(":").endswith("**"):
        s = s.rstrip(":")[2:-2].strip()
    return s.rstrip(":").strip()


def split_into_sections(md: str) -> list[tuple[str | None, str]]:
    """Split a digest into ``(header_or_None, body_markdown)`` sections.

    A section begins at a heading line or a whole-line ``**bold**`` header (how
    the digests label sections); any lead-in prose before the first header is a
    single ``(None, …)`` section. This is what lets the report tag and filter
    each block independently while still rendering the body as Markdown.
    """
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[tuple[str | None, list[str]]] = []
    header: str | None = None
    body: list[str] = []

    def _flush() -> None:
        if header is not None or any(b.strip() for b in body):
            sections.append((header, body))

    for line in lines:
        if _is_section_header(line):
            _flush()
            header = _clean_header(line)
            body = []
        else:
            body.append(line)
    _flush()
    return [(h, "\n".join(b).strip()) for h, b in sections]


# --------------------------------------------------------------------------- #
# HTML assembly.
# --------------------------------------------------------------------------- #


def _ref_of(sheet: Any) -> Any:
    return getattr(sheet, "ref", None)


def _sheet_status(sheet: Any) -> str:
    """One of ``"failed"`` / ``"cached"`` / ``"ok"`` (drives the badge + filter)."""
    if getattr(sheet, "error", None):
        return "failed"
    if getattr(sheet, "cached", False):
        return "cached"
    return "ok"


_STATUS_BADGE = {
    "ok": ("OK", "ok"),
    "cached": ("Cached", "cached"),
    "failed": ("Failed", "failed"),
}


def _esc_attr(text: str) -> str:
    return html.escape(text, quote=True)


def _json_for_script(value: Any) -> str:
    """Serialize ``value`` as JSON that is inert inside a ``<script>`` element.

    HTML escaping and JavaScript-string escaping are different requirements:
    inside a script element the parser only cares about ``</script`` (and
    ``<!--``), which HTML-entity escaping would corrupt. So every ``<`` is
    emitted as the JSON string escape ``\\u003c`` — a byte-level no-op for
    ``JSON.parse`` — making it impossible for any value to close the script
    element or open a comment/tag. ``json.dumps``'s default ``ensure_ascii``
    already escapes the U+2028/U+2029 line separators; the explicit replaces
    keep that guarantee even if ``ensure_ascii`` is ever turned off.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _script_hash(script_source: str) -> str:
    """The CSP hash-source (``sha256-…``) for one inline ``<script>`` body."""
    digest = hashlib.sha256(script_source.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def _csp_meta(*, script_sources: list[str], chat_enabled: bool) -> str:
    """The report's Content-Security-Policy ``<meta>`` tag (defense in depth).

    Scripts are allowed strictly by SHA-256 hash of the exact inline bodies
    this build emits — there are no inline event handlers, so ``script-src``
    is never weakened to make them work. ``connect-src`` admits only the
    Anthropic Messages endpoint the assistant calls (or nothing at all when
    the assistant is omitted). Objects, ``<base>`` rewriting, and form
    submission are forbidden outright. ``img-src`` admits the report's own
    relative evidence crops (``'self'`` when served, ``file:`` when
    double-clicked) and nothing remote, so an injected image can't beacon.
    ``style-src 'unsafe-inline'`` covers the single inline stylesheet and the
    fixed set of generated ``style=`` attributes (table alignment); CSS
    carries no script here. The exact policy is exercised against ``file://``
    in the Phase 17B headless-Chromium suite.
    """
    hashes = " ".join(f"'{_script_hash(source)}'" for source in script_sources)
    connect = "https://api.anthropic.com" if chat_enabled else "'none'"
    policy = (
        "default-src 'none'; "
        f"script-src {hashes}; "
        "style-src 'unsafe-inline'; "
        "img-src 'self' file: data:; "
        f"connect-src {connect}; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "object-src 'none'"
    )
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'


# --------------------------------------------------------------------------- #
# Findings — the QC record, surfaced as a pinned, sortable, filterable table.
# Each finding collapses its anchor + verification outcomes into ONE "display
# status" chip (the five states an operator triages on); the digest prose is
# untouched (I-2) — these come from ctx.findings / ctx.reference_findings.
# --------------------------------------------------------------------------- #

# display status → (chip label, css suffix). Green/blue/amber/red-outline/grey
# are defined in _CSS under .fchip-*.
_FINDING_STATUS_CHIP: dict[str, tuple[str, str]] = {
    "VERIFIED": ("Verified", "verified"),
    "DETERMINISTIC": ("Deterministic", "deterministic"),
    "UNCERTAIN": ("Uncertain", "uncertain"),
    "UNANCHORED": ("Unanchored", "unanchored"),
    "REJECTED": ("Rejected", "rejected"),
}
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
# Column-sort rank for the status chip (higher sorts first descending).
_STATUS_RANK = {
    "VERIFIED": 5, "DETERMINISTIC": 4, "UNCERTAIN": 3, "UNANCHORED": 2, "REJECTED": 1,
}


def _finding_display_status(f: Any) -> str:
    """Blend a finding's anchor + verification outcomes into one triage state.

    Priority: a ``REJECTED`` verdict wins (never clouded), then the trusted
    ``DETERMINISTIC`` auditors, then a model ``VERIFIED``; an unanchored non-empty
    quote surfaces as ``UNANCHORED`` (the hallucination signal); everything else
    anchored-but-unconfirmed (``UNCERTAIN`` / ``SKIPPED``) reads as ``UNCERTAIN``.
    """
    v = getattr(getattr(f, "verification", None), "status", "") or "SKIPPED"
    a = getattr(getattr(f, "anchor", None), "status", "") or "UNANCHORED"
    if v == "REJECTED":
        return "REJECTED"
    if v == "DETERMINISTIC":
        return "DETERMINISTIC"
    if v == "VERIFIED":
        return "VERIFIED"
    if a == "UNANCHORED":
        return "UNANCHORED"
    return "UNCERTAIN"


def _report_findings(ctx: Any) -> list[Any]:
    """Model findings + deterministic reference findings (duck-typed on ctx)."""
    return list(getattr(ctx, "findings", None) or []) + list(
        getattr(ctx, "reference_findings", None) or []
    )


def _sheet_key(ref: Any) -> tuple[str, int]:
    """Full sheet identity — the PDF's *path* + page — so two sheets that share a
    basename but live in different directories never collide (``SheetRef`` carries
    ``pdf_path``; a fake without one falls back to ``source_name``). Used for the
    geometry↔sheet mapping, where both sides carry the path."""
    pdf_path = getattr(ref, "pdf_path", None)
    ident = str(pdf_path) if pdf_path else (getattr(ref, "source_name", "") or "")
    return (ident, int(getattr(ref, "page_index", 0) or 0))


def _finding_sheet_key(ref_or_name: Any, page_index: int) -> tuple[str, int]:
    """Collision-safe finding→sheet-card key (DA-001).

    Uses the host-owned ``source_id`` when present, so a finding from one input
    links to *its* sheet card even when another input shares the basename; falls
    back to the ``source_name`` basename only when no ``source_id`` was assigned.
    Mirrors :func:`models.source_page_key` inline so this module stays
    engine-free / duck-typed."""
    sid = (getattr(ref_or_name, "source_id", "") or "").strip()
    name = getattr(ref_or_name, "source_name", ref_or_name) or ""
    return (sid or name, int(page_index))


def _ambiguous_names(ctx: Any) -> frozenset[str]:
    """Display names shared by two *different* sources (§18.6).

    A name is ambiguous when two sheet refs carry the same ``source_name`` but a
    different identity (``source_id`` or ``pdf_path``) — e.g. two revisions of
    ``M-101.pdf`` pulled from different folders. Labels for such sources get the
    opaque source id suffixed (:func:`_disambiguated`) so the operator can tell
    them apart; a name used by only one source stays clean.
    """
    identities: dict[str, set[tuple[str, str]]] = {}
    for sheet in getattr(ctx, "sheets", None) or []:
        ref = _ref_of(sheet)
        name = getattr(ref, "source_name", "") or ""
        sid = (getattr(ref, "source_id", "") or "").strip()
        path = str(getattr(ref, "pdf_path", "") or "")
        identities.setdefault(name, set()).add((sid, path))
    return frozenset(name for name, ids in identities.items() if len(ids) > 1)


def _disambiguated(label: str, owner: Any, ambiguous: frozenset[str]) -> str:
    """Suffix ``label`` with the opaque source id when the owner's display name
    is ambiguous (§18.6): ``"M-101.pdf (page 1/1) · SRC-0002"``. ``owner`` is
    anything carrying ``source_name`` + ``source_id`` (a ref or a finding); no
    suffix without a host-assigned id — a bare name has nothing truthful to add.
    """
    sid = (getattr(owner, "source_id", "") or "").strip()
    name = getattr(owner, "source_name", "") or ""
    if sid and name in ambiguous:
        return f"{label} · {sid}"
    return label


def _sheet_card_index(sheets: list[Any]) -> dict[tuple[str, int], int]:
    """Map source identity → 1-based sheet-card index (for finding links)."""
    out: dict[tuple[str, int], int] = {}
    for i, sheet in enumerate(sheets, start=1):
        ref = _ref_of(sheet)
        out.setdefault(
            _finding_sheet_key(ref, int(getattr(ref, "page_index", 0) or 0)), i
        )
    return out


def _geometry_index(ctx: Any) -> dict[tuple[str, int], Any]:
    """Map full sheet identity → the sheet's captured geometry."""
    out: dict[tuple[str, int], Any] = {}
    for geom in getattr(ctx, "sheet_geometries", None) or []:
        out.setdefault(_sheet_key(_ref_of(geom)), geom)
    return out


def _pdf_deep_link(pdf_links: "dict[str, dict] | None", qc_id: str) -> str:
    """The ``<name>.pdf#page=N`` href for a finding's QC-### cell, or ``""``.

    ``#page=N`` is the one PDF-open fragment every browser PDF viewer honors
    (Chrome/pdfium, Firefox/pdf.js, Safari, Acrobat), so the click reliably
    opens the marked-up PDF at the finding's page — where the inked cloud + QC
    tag already sit. Precise zoom-to-rect is delivered inside the PDF's own
    bookmark outline (see :mod:`drawing_analyzer.annotate`) rather than a
    ``#zoom`` fragment, whose coordinate origin is inconsistent across viewers.
    The filename is percent-encoded (spaces etc.) but the ``#page`` fragment is
    not. Returns ``""`` for any finding without a resolvable link.
    """
    if not pdf_links or not qc_id:
        return ""
    link = pdf_links.get(qc_id)
    if not link:
        return ""
    pdf = str(link.get("pdf", "") or "")
    page = link.get("page")
    if not pdf or not isinstance(page, int) or page < 1:
        return ""
    return f"{quote(pdf)}#page={page}"


def _finding_row_html(
    f: Any,
    card_index: int | None,
    *,
    link_evidence: bool,
    ambiguous: frozenset[str] = frozenset(),
    pdf_links: "dict[str, dict] | None" = None,
) -> str:
    status = _finding_display_status(f)
    label, cls = _FINDING_STATUS_CHIP.get(status, ("Uncertain", "uncertain"))
    category = getattr(f, "category", "") or "other"
    severity = (getattr(f, "severity", "") or "").lower()
    sev_rank = _SEVERITY_RANK.get(severity, 0)
    sheet_id = getattr(f, "sheet_id", "") or getattr(f, "source_name", "") or "—"
    sheet_id = _disambiguated(sheet_id, f, ambiguous)
    text = getattr(f, "text", "") or ""
    quote = getattr(f, "source_quote", "") or ""
    qc_id = getattr(f, "qc_id", "") or ""

    sheet_cell = (
        f'<a href="#sheet-{card_index}">{html.escape(sheet_id)}</a>'
        if card_index else html.escape(sheet_id)
    )
    # The QC-### cell deep-links into the marked-up PDF (same export folder) at
    # this finding's page when a reviewed PDF was produced; otherwise plain text.
    pdf_href = _pdf_deep_link(pdf_links, qc_id)
    qc_cell = html.escape(qc_id) or "—"
    if pdf_href and qc_id:
        qc_cell = (
            f'<a class="pdf-link" href="{_esc_attr(pdf_href)}" target="_blank" '
            f'rel="noopener noreferrer" '
            f'title="Open {_esc_attr(qc_id)} in the marked-up PDF">'
            f"{html.escape(qc_id)}</a>"
        )
    quote_cell = (
        f"<code>{html.escape(quote)}</code>" if quote
        else '<span class="muted">—</span>'
    )
    text_cell = _render_inline(text)
    action = (getattr(f, "recommended_action", "") or "").strip()
    if action:
        text_cell += (
            f'<div class="finding-action">Action: {html.escape(action)}</div>'
        )
    sources = getattr(f, "sources", None) or []
    if sources:
        from .ledger import provenance_label

        text_cell += (
            f' <span class="muted provenance-chip">[{html.escape(provenance_label(sources))}]</span>'
        )
    prose_ids = list(getattr(f, "prose_item_ids", None) or [])
    if prose_ids:
        # Phase 22 §14.6: how many enumerated prose items this entry accounts for.
        text_cell += (
            f' <span class="muted provenance-chip">prose×{len(prose_ids)}</span>'
        )
    assessments = list(getattr(f, "citations", None) or [])
    if assessments:
        # Per-reference, claim-complete citation verdicts (§18.6, DA-017) — one
        # span per reference, never collapsed into one ambiguous status. Phase B:
        # a mismatch gets its own warning class (it used to render in the same
        # muted gray as a pass), plus the structured edition provenance and the
        # model-selected evidence link (https-only, enforced at parse AND here).
        for a in assessments:
            a_ref = str(getattr(a, "reference", "") or "")
            a_status = str(getattr(a, "status", "") or "UNCHECKED")
            a_note = (getattr(a, "note", "") or "").strip()
            if len(a_note) > 120:
                a_note = a_note[:119].rstrip() + "…"
            css = "citation-note citation-mismatch" if a_status == "CHECKED_MISMATCH" \
                else "muted citation-note"
            edition_bits = []
            for prov_label, prov_attr in (("adopted", "adopted_edition"),
                                          ("checked", "checked_edition"),
                                          ("current", "current_edition")):
                value = str(getattr(a, prov_attr, "") or "").strip()
                if value:
                    edition_bits.append(f"{prov_label}: {html.escape(value)}")
            detail = f" ({'; '.join(edition_bits)})" if edition_bits else ""
            evidence_url = str(getattr(a, "evidence_url", "") or "").strip()
            link = ""
            if evidence_url.lower().startswith("https://"):
                link = (
                    f' <a class="citation-evidence" href="{html.escape(evidence_url, quote=True)}"'
                    f' target="_blank" rel="noopener noreferrer">evidence</a>'
                )
            text_cell += (
                f' <span class="{css}">[{html.escape(a_ref)}: '
                f"{html.escape(a_status)}"
                + (f" — {html.escape(a_note)}" if a_note else "")
                + detail
                + "]"
                + link
                + "</span>"
            )
    else:
        # Legacy single-verdict summary (a finding from an older cached run).
        citation = getattr(f, "citation", None)
        if citation is not None and getattr(citation, "status", "UNCHECKED") != "UNCHECKED":
            cite_label = "supports" if citation.status == "CHECKED_SUPPORTS" else "mismatch"
            cite_note = (getattr(citation, "note", "") or "").strip()
            css = ("citation-note citation-mismatch"
                   if citation.status == "CHECKED_MISMATCH" else "muted citation-note")
            text_cell += (
                f' <span class="{css}">[citation {html.escape(cite_label)}'
                + (f": {html.escape(cite_note)}" if cite_note else "")
                + "]</span>"
            )
    if link_evidence:
        verification = getattr(f, "verification", None)
        # DA-016: list EVERY saved crop (one per leg of a cross-sheet conflict),
        # not just the first — the report's evidence trail must be complete. Fall
        # back to the legacy single-path alias for a finding loaded from an older
        # cache that predates the artifact list.
        artifacts = list(getattr(verification, "evidence", None) or [])
        rels: list[str] = [
            (getattr(a, "relative_path", "") or "").strip() for a in artifacts
        ]
        if not any(rels):
            legacy = (getattr(verification, "evidence_png", "") or "").strip()
            rels = [legacy] if legacy else []
        for i, rel in enumerate([r for r in rels if r]):
            src = _esc_attr(rel)
            alt = _esc_attr(f"verification evidence crop (leg {i + 1})")
            text_cell += (
                f' <a class="evidence-link" href="{src}" target="_blank" '
                f'rel="noopener noreferrer"><img class="evidence-thumb" src="{src}" '
                f'alt="{alt}" loading="lazy"></a>'
            )
    return (
        f'<tr class="finding-row" data-category="{_esc_attr(category)}" '
        f'data-severity="{sev_rank}" data-status="{status}" '
        f'data-status-rank="{_STATUS_RANK.get(status, 0)}">'
        f'<td class="fcol-qcid">{qc_cell}</td>'
        f'<td class="fcol-sheet">{sheet_cell}</td>'
        f'<td class="fcol-cat">{html.escape(category)}</td>'
        f'<td class="fcol-sev sev-{html.escape(severity or "none")}">'
        f'{html.escape(severity or "—")}</td>'
        f'<td class="fcol-status"><span class="fchip fchip-{cls}">'
        f"{html.escape(label)}</span></td>"
        f'<td class="fcol-text">{text_cell}</td>'
        f'<td class="fcol-quote">{quote_cell}</td>'
        f"</tr>"
    )


def _findings_card(
    ctx: Any,
    sheets: list[Any],
    *,
    link_evidence: bool = False,
    ambiguous: frozenset[str] = frozenset(),
    pdf_links: "dict[str, dict] | None" = None,
) -> str:
    """The pinned QC Findings card: a sortable, filterable table (``""`` if none).

    Default order is severity-desc then status-rank-desc; the columns are
    click-sortable in the browser. Rows link to the sheet card they sit on and
    carry ``data-category`` so the filter chips (and ⚠ Issues only) reach them.
    The badge total is static (§18.6 — filters never change underlying counts);
    the ``#findings-shown`` span is the JS-maintained "showing K of N" line.
    """
    findings = _report_findings(ctx)
    if not findings:
        return ""
    index = _sheet_card_index(sheets)

    def _key(f: Any):
        sev = _SEVERITY_RANK.get((getattr(f, "severity", "") or "").lower(), 0)
        return (-sev, -_STATUS_RANK.get(_finding_display_status(f), 0))

    rows = []
    for f in sorted(findings, key=_key):
        ref_key = _finding_sheet_key(f, int(getattr(f, "page_index", 0) or 0))
        rows.append(
            _finding_row_html(
                f, index.get(ref_key), link_evidence=link_evidence, ambiguous=ambiguous,
                pdf_links=pdf_links,
            )
        )

    def _th(key: str, label: str) -> str:
        # tabindex + aria-sort: sortable headers are keyboard-reachable and
        # announce their direction (the JS keeps aria-sort in sync).
        return f'<th data-sort="{key}" tabindex="0" aria-sort="none">{label}</th>'

    table = (
        '<div class="findings-wrap"><table class="findings-table">'
        "<thead><tr>"
        + _th("qcid", "ID")
        + _th("sheet", "Sheet")
        + _th("category", "Category")
        + _th("severity", "Severity")
        + _th("status", "Status")
        + _th("text", "Finding")
        + _th("quote", "Quote")
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    hint = (
        '<p class="findings-hint muted">Click a column header to sort · click a '
        "sheet to jump to it · use the filter chips and search on the left.</p>"
    )
    checks = _audit_checks_line(ctx)
    tally = _ledger_tally_line(ctx)
    return _card(
        card_id="findings",
        title_html='<span class="seq">⚑</span> QC Findings',
        badges_html=(
            '<span id="findings-shown" class="muted" aria-live="polite"></span>'
            f'<span class="badge badge-findings">{len(findings)} finding(s)</span>'
        ),
        status="findings",
        body_html=f'<div class="findings-body">{hint}{tally}{checks}{table}</div>',
    )


def _ledger_tally_line(ctx: Any) -> str:
    """The Part III coverage line — every ledger entry accounted for (§18)."""
    line = (getattr(ctx, "ledger_tally_line", "") or "").strip()
    if not line:
        return ""
    return f'<p class="findings-hint muted ledger-tally">{html.escape(line)}.</p>'


def _audit_checks_line(ctx: Any) -> str:
    """A one-line "checks that passed" note from the deterministic-auditor tally.

    The deterministic battery counts what it *verified clean*, not only what it
    flagged — the balance column of a real review. Currently that's the arithmetic
    auditor's "N numeric relationships checked ✓" (Phase 14); empty when no claims
    were checked, so the line only appears when it has something to say.
    """
    stats = getattr(ctx, "audit_stats", None) or {}
    checked = int(stats.get("arithmetic_checked", 0) or 0)
    if checked <= 0:
        return ""
    matched = int(stats.get("arithmetic_matched", 0) or 0)
    noun = "relationship" if checked == 1 else "relationships"
    return (
        '<p class="findings-hint muted">'
        f"Deterministic checks: {matched} of {checked} numeric {noun} checked out ✓"
        "</p>"
    )


def _block_html(header: str | None, body_md: str, *, category: str | None = None) -> str:
    """Render one digest section as a filterable ``<section>`` with its category.

    ``category`` forces the block's ``data-category`` instead of classifying by
    header keywords. The Focus Report card uses this: its body sections are
    headed however the report is organized (``Room-by-room``, ``Equipment``, …),
    and classifying those by keyword would scatter them across other categories
    — selecting the Focus chip would then hide the report's own body. The
    highlight pill still reflects the keyword classification, so an e.g.
    "Conflicts" section inside the report keeps its informative tag.
    """
    classified = classify_section(header)
    category = category or classified
    head = ""
    if header:
        cat_label = CATEGORY_LABELS.get(classified, "")
        tag = (
            f'<span class="cat-tag cat-{classified}">{html.escape(cat_label)}</span>'
            if classified in ("coordination", "conflict", "focus")
            else ""
        )
        head = f'<h4 class="block-title">{_render_inline(header)}{tag}</h4>'
    return (
        f'<section class="block" data-category="{category}">'
        f"{head}{markdown_to_html(body_md)}</section>"
    )


def _render_digest_blocks(text: str, *, category: str | None = None) -> str:
    return "".join(
        _block_html(h, b, category=category) for h, b in split_into_sections(text)
    )


def _card(
    *, card_id: str, title_html: str, badges_html: str, status: str, body_html: str
) -> str:
    """A collapsible, filterable card (one sheet, or the set overview)."""
    return (
        f'<article class="card" id="{card_id}" data-status="{_esc_attr(status)}">'
        f'<header class="card-head" role="button" tabindex="0" aria-expanded="true">'
        f'<span class="card-title">{title_html}</span>'
        f'<span class="badges">{badges_html}</span>'
        f'<span class="chevron" aria-hidden="true">▾</span>'
        f"</header>"
        f'<div class="card-body">{body_html}</div>'
        f"</article>"
    )


def _rawtext_block(geometry: Any) -> str:
    """A collapsed block carrying the sheet's raw extracted text layer.

    The block is a real ``.block`` so its text feeds the report's full-text
    search — search now runs over what the *sheet* says, not only what the
    digest said about it. A raster sheet (empty text layer) gets a note instead.
    """
    if geometry is None:
        return ""
    raw = (getattr(geometry, "sheet_text", "") or "").strip()
    is_raster = bool(getattr(geometry, "is_raster", False))
    if not raw and not is_raster:
        return ""
    if raw:
        inner = (
            '<details class="rawtext"><summary>Sheet text layer '
            "(raw extracted)</summary>"
            f'<pre class="rawtext-pre">{html.escape(raw, quote=False)}</pre>'
            "</details>"
        )
    else:
        inner = (
            '<p class="muted">Raster sheet — no extractable text layer '
            "(the digest read the imagery only).</p>"
        )
    return f'<section class="block block-rawtext" data-category="other">{inner}</section>'


def _sheet_card(
    index: int,
    total: int,
    sheet: Any,
    geometry: Any = None,
    *,
    ambiguous: frozenset[str] = frozenset(),
) -> str:
    ref = _ref_of(sheet)
    label = getattr(ref, "display_label", None) or f"Sheet {index}/{total}"
    label = _disambiguated(label, ref, ambiguous)
    status = _sheet_status(sheet)
    text = (getattr(sheet, "text", "") or "").strip()
    error = getattr(sheet, "error", None)
    in_tok = int(getattr(sheet, "input_tokens", 0) or 0)
    out_tok = int(getattr(sheet, "output_tokens", 0) or 0)

    badge_text, badge_cls = _STATUS_BADGE[status]
    badges = [f'<span class="badge badge-{badge_cls}">{badge_text}</span>']
    if geometry is not None and getattr(geometry, "is_raster", False):
        badges.append('<span class="badge badge-raster">Raster</span>')
    if in_tok or out_tok:
        badges.append(
            f'<span class="badge badge-tok">{in_tok:,} in / {out_tok:,} out</span>'
        )

    if text:
        body = _render_digest_blocks(text)
    elif error:
        body = (
            f'<section class="block" data-category="other">'
            f'<div class="error-box">This sheet could not be analyzed: '
            f"{html.escape(str(error))}</div></section>"
        )
    else:
        body = (
            '<section class="block" data-category="other">'
            '<p class="muted">(empty digest)</p></section>'
        )
    body += _rawtext_block(geometry)

    title = (
        f'<span class="seq">{index:02d}</span> {html.escape(label)}'
    )
    return _card(
        card_id=f"sheet-{index}",
        title_html=title,
        badges_html="".join(badges),
        status=status,
        body_html=body,
    )


def _focus_value(ctx: Any) -> str:
    return (getattr(ctx, "focus", "") or "").strip()


def _focus_card(ctx: Any) -> str:
    """The pinned Focus Report card (rendered only when a per-run focus was set).

    Quotes the operator's question first so the card is self-describing, then
    the set-level report. A failed/absent report still renders the card with a
    pointer to the run summary — the requested deliverable is never silently
    missing from the page.
    """
    focus = _focus_value(ctx)
    report = (getattr(ctx, "focus_report_text", "") or "").strip()
    ask = (
        '<section class="block" data-category="focus">'
        f'<p class="focus-ask"><strong>Operator focus:</strong> '
        f"{html.escape(focus)}</p></section>"
    )
    if report:
        # Every body block is forced to the "focus" category: the whole card IS
        # the focus deliverable, and it must survive the Focus filter chip no
        # matter how the report's own section headers read (a `## Rooms` header
        # would otherwise classify elsewhere and be hidden by the chip).
        body = ask + _render_digest_blocks(report, category="focus")
    else:
        body = ask + (
            '<section class="block" data-category="focus"><p class="muted">'
            "No focus report was produced for this run — see the run summary "
            "for errors. Any per-sheet <em>Focus findings</em> sections still "
            "appear under their sheets below.</p></section>"
        )
    return _card(
        card_id="focus",
        title_html='<span class="seq">◎</span> Focus Report',
        badges_html='<span class="badge badge-focus">Per-run focus</span>',
        status="focus",
        body_html=body,
    )


def _overview_card(ctx: Any) -> str:
    synthesis = (getattr(ctx, "synthesis_text", "") or "").strip()
    if synthesis:
        body = _render_digest_blocks(synthesis)
    else:
        body = (
            '<section class="block" data-category="other"><p class="muted">'
            "No cross-sheet synthesis was produced. Synthesis is skipped for "
            "fewer than two readable sheets and falls back silently on error — "
            "see the run summary for any errors.</p></section>"
        )
    return _card(
        card_id="overview",
        title_html='<span class="seq">★</span> Drawing Set Overview',
        badges_html='<span class="badge badge-overview">Cross-sheet synthesis</span>',
        status="overview",
        body_html=body,
    )


def _toc_html(
    ctx: Any, sheets: list[Any], *, ambiguous: frozenset[str] = frozenset()
) -> str:
    rows = []
    if _focus_value(ctx):
        rows.append(
            '<a class="toc-item" data-target="focus" href="#focus">'
            '<span class="toc-dot dot-focus"></span>'
            '<span class="toc-label">Focus Report</span></a>'
        )
    if _report_findings(ctx):
        rows.append(
            '<a class="toc-item" data-target="findings" href="#findings">'
            '<span class="toc-dot dot-findings"></span>'
            '<span class="toc-label">QC Findings</span></a>'
        )
    rows.append(
        '<a class="toc-item" data-target="overview" href="#overview">'
        '<span class="toc-dot dot-overview"></span>'
        '<span class="toc-label">Drawing Set Overview</span></a>'
    )
    total = len(sheets)
    for i, sheet in enumerate(sheets, start=1):
        ref = _ref_of(sheet)
        label = getattr(ref, "display_label", None) or f"Sheet {i}/{total}"
        label = _disambiguated(label, ref, ambiguous)
        status = _sheet_status(sheet)
        rows.append(
            f'<a class="toc-item" data-target="sheet-{i}" href="#sheet-{i}">'
            f'<span class="toc-dot dot-{status}"></span>'
            f'<span class="toc-seq">{i:02d}</span>'
            f'<span class="toc-label">{html.escape(label)}</span></a>'
        )
    return "".join(rows)


def _filter_chips_html(*, include_focus: bool = False) -> str:
    """The filter chip row. The Focus chip appears only when the run had a
    per-run focus — otherwise it would be a chip that can never match.

    Category chips are exclusive (``data-filter``, one active at a time);
    ``aria-pressed`` mirrors the active state for assistive tech. The trailing
    ``#sev-high`` button is a standalone toggle (DA-025) that *combines* with
    whichever category chip is active instead of replacing it — it carries no
    ``data-filter`` so the exclusive-chip JS never touches it.
    """
    chips = [
        '<button class="chip chip-active" data-filter="all" aria-pressed="true">All</button>',
        '<button class="chip chip-issues" data-filter="issues" aria-pressed="false">⚠ Issues only</button>',
    ]
    for cid, _label, _kw in _CATEGORY_SPECS:
        if cid == "focus" and not include_focus:
            continue
        chips.append(
            f'<button class="chip" data-filter="{cid}" aria-pressed="false">'
            f"{html.escape(CATEGORY_LABELS[cid])}</button>"
        )
    chips.append(
        '<button class="chip chip-toggle" id="sev-high" aria-pressed="false">'
        "High severity only</button>"
    )
    return "".join(chips)


def _summary_html(ctx: Any, source_names: list[str], now: datetime) -> str:
    ok = int(getattr(ctx, "ok_sheet_count", 0) or 0)
    total = int(getattr(ctx, "sheet_count", 0) or 0)
    cached = int(getattr(ctx, "cached_sheet_count", 0) or 0)
    in_tok = int(getattr(ctx, "total_input_tokens", 0) or 0)
    out_tok = int(getattr(ctx, "total_output_tokens", 0) or 0)
    failed = total - ok

    stats = [
        ("Sheets analyzed", f"{ok}/{total}" + (f" · {cached} cached" if cached else "")),
        ("Source file(s)", str(len(source_names))),
        ("Tokens billed", f"{in_tok:,} in / {out_tok:,} out"),
    ]
    if failed > 0:
        stats.append(("Failed", str(failed)))
    cards = "".join(
        f'<div class="stat"><div class="stat-val">{html.escape(v)}</div>'
        f'<div class="stat-key">{html.escape(k)}</div></div>'
        for k, v in stats
    )

    sources = "".join(
        f"<li>{html.escape(name)}</li>" for name in source_names
    ) or "<li>(none)</li>"

    errors_html = ""
    errors = list(getattr(ctx, "errors", None) or [])
    if errors:
        items = "".join(f"<li>{html.escape(str(e))}</li>" for e in errors)
        errors_html = (
            f'<details class="errors" open><summary>{len(errors)} issue(s) '
            f"this run</summary><ul>{items}</ul></details>"
        )

    return (
        f'<div class="summary">'
        f"{_qc_status_banner_html(ctx)}"
        f"{_coverage_banner_html(ctx)}"
        f"{_stage_table_html(ctx)}"
        f'<div class="stats">{cards}</div>'
        f"{_usage_html(ctx)}"
        f'<details class="sources"><summary>Source files</summary>'
        f"<ul>{sources}</ul></details>"
        f"{_run_record_html(ctx)}"
        f"{errors_html}"
        f"</div>"
    )


# StageResult.status → status-cell css suffix (§18.6). SKIPPED_VALID is a benign
# skip, so it reads muted like NOT_REQUESTED rather than as a warning.
_STAGE_STATUS_CLASS = {
    "COMPLETE": "complete",
    "PARTIAL": "partial",
    "FAILED": "failed",
    "SKIPPED_VALID": "skipped",
    "NOT_REQUESTED": "not-requested",
}


def _stage_table_html(ctx: Any) -> str:
    """The per-stage QC status table (Phase 26B, §18.6).

    One row per typed :class:`StageResult`, in recorded order — the drill-down
    behind the one-line QC status banner. Collapsed by default like the usage
    table, and absent entirely when the run recorded no stage results (a
    standard run). The first error/warning per stage is shown inline so a
    PARTIAL/FAILED row explains itself without opening the export's ``run.log``.
    """
    stages = list(getattr(ctx, "stage_results", None) or [])
    if not stages:
        return ""
    rows = []
    for s in stages:
        status = str(getattr(s, "status", "") or "NOT_REQUESTED").upper()
        cls = _STAGE_STATUS_CLASS.get(status, "not-requested")
        errors = [str(e) for e in (getattr(s, "errors", None) or [])]
        warnings = [str(w) for w in (getattr(s, "warnings", None) or [])]
        note = errors[0] if errors else (warnings[0] if warnings else "")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(getattr(s, 'stage', '') or ''))}</td>"
            f"<td>{'yes' if getattr(s, 'expected', False) else 'no'}</td>"
            f'<td class="st-{cls}">{html.escape(status)}</td>'
            f"<td class='num'>{int(getattr(s, 'calls_succeeded', 0) or 0)}"
            f"/{int(getattr(s, 'calls_planned', 0) or 0)}</td>"
            f"<td class='num'>{int(getattr(s, 'items_in', 0) or 0)} → "
            f"{int(getattr(s, 'items_out', 0) or 0)}</td>"
            f'<td class="muted">{html.escape(note) if note else "—"}</td>'
            "</tr>"
        )
    return (
        '<details class="usage stage-status"><summary>QC stage status</summary>'
        '<div class="usage-scroll"><table class="usage-table stage-table">'
        "<thead><tr><th>Stage</th><th>Expected</th><th>Status</th>"
        "<th class='num'>Calls</th><th class='num'>Items in → out</th>"
        "<th>First issue</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )


def _run_record_html(ctx: Any) -> str:
    """The run-record pointer (Phase 26B, §18.6): the journal's identity plus
    where the full per-run record lives. Duck-typed off ``ctx.run_journal``
    (present on every pipeline run since Phase 26A; a context without one simply
    omits the block). Every value is escaped — the journal sanitizes at emit
    time, but the report never relies on that.
    """
    journal = getattr(ctx, "run_journal", None)
    if journal is None:
        return ""
    run_id = str(getattr(journal, "run_id", "") or "")
    items = [f"<li>Run ID: <code>{html.escape(run_id)}</code></li>"]
    started = getattr(journal, "started_at", None)
    if started is not None:
        items.append(f"<li>Started: {html.escape(str(started))}</li>")
    ended = getattr(journal, "ended_at", None)
    if ended is not None:
        items.append(f"<li>Ended: {html.escape(str(ended))}</li>")
    final = str(getattr(journal, "final_status", "") or "")
    if final:
        items.append(f"<li>Final status: {html.escape(final)}</li>")
    items.append(
        "<li>Full event trace: <code>run.log</code> and "
        "<code>run_manifest.json</code>, written into every export folder.</li>"
    )
    return (
        '<details class="sources run-record"><summary>Run record</summary>'
        f"<ul>{''.join(items)}</ul></details>"
    )


def _usage_html(ctx: Any) -> str:
    """A collapsible per-stage token/cost table from the usage ledger (§15.7).

    Actuals, not an estimate — the same append-only records the run totals are
    derived from, so the grand total here always equals the sum of the rows. A
    fully-cached run still shows its CACHE rows (zero billed tokens, $0.00); the
    table is absent only when no records were produced at all.
    """
    by_family = getattr(ctx, "usage_by_family", None) or {}
    if not by_family:
        return ""
    total_cost = getattr(ctx, "total_estimated_cost", None)
    total_line = (
        f" — est. ${float(total_cost):,.2f}" if total_cost is not None else ""
    )
    rows = []
    for fam in sorted(by_family):
        g = by_family[fam]
        cost = g.get("estimated_cost")
        money = f"${float(cost):,.4f}" if cost is not None else "—"
        hits = f"{g['cache_hits']}" if g.get("cache_hits") else "0"
        rows.append(
            "<tr>"
            f"<td>{html.escape(fam)}</td>"
            f"<td class='num'>{g['calls']}</td>"
            f"<td class='num'>{hits}</td>"
            f"<td class='num'>{g['input_tokens']:,}</td>"
            f"<td class='num'>{g['output_tokens']:,}</td>"
            f"<td class='num'>{money}</td>"
            "</tr>"
        )
    return (
        f'<details class="usage"><summary>Token usage &amp; estimated cost by '
        f"stage{total_line}</summary>"
        '<div class="usage-scroll"><table class="usage-table">'
        "<thead><tr><th>Stage</th><th class='num'>Calls</th>"
        "<th class='num'>Cached</th><th class='num'>Input</th>"
        "<th class='num'>Output</th><th class='num'>Est. cost</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )


def _qc_status_banner_html(ctx: Any) -> str:
    """The run-level QC status banner (Phase 23A, §3.3 / §15.5).

    Only shown when exhaustive QC ran (``qc_status`` other than NOT_REQUESTED). It
    leads with the normalized status so the report header shows the same state as
    the GUI and run log; a ``DEBUG_OVERRIDE`` configuration and any PARTIAL/FAILED
    stages are named. With the completeness gate open (Phase 26B §18.0), a
    PARTIAL with no degraded stage has exactly one cause — an explicit debug
    override — and the detail says so. The per-stage table follows (§18.6).
    """
    status = (getattr(ctx, "qc_status", "") or "NOT_REQUESTED").upper()
    if status not in ("COMPLETE", "PARTIAL", "FAILED"):
        return ""
    label = html.escape(getattr(ctx, "qc_status_label", status))
    stages = list(getattr(ctx, "stage_results", None) or [])
    degraded = [s for s in stages if getattr(s, "status", "") in ("PARTIAL", "FAILED")]
    kind = getattr(ctx, "configuration_kind", "NORMAL")

    if degraded:
        names = ", ".join(
            f"{html.escape(str(s.stage))} ({html.escape(str(s.status))})" for s in degraded
        )
        detail = f"Stages needing attention: {names}."
    elif status == "PARTIAL":
        # Gate open (§18.0): the one no-degraded-stage PARTIAL cause is an
        # explicit debug override — named below; never a vague withholding.
        detail = (
            "Every exhaustive-QC stage completed; the run is PARTIAL because "
            "the configuration deliberately weakened the exhaustive contract."
        )
    else:
        detail = "Every required exhaustive-QC stage completed."
    if kind == "DEBUG_OVERRIDE":
        detail += " Configuration: DEBUG_OVERRIDE (an explicit flag disabled a normally-required stage)."
    return (
        f'<div class="qc-status-banner" data-status="{_esc_attr(status)}">'
        f'<div class="cb-title">QC status: {html.escape(status)} — {label}</div>'
        f'<div class="cb-detail">{detail}</div>'
        f"</div>"
    )


def _coverage_banner_html(ctx: Any) -> str:
    """The run-level markup-coverage banner (Phase 21, §13.6).

    ``COMPLETE`` (green) states every planned markup was found again in the saved
    PDFs; ``INCOMPLETE`` (red) names the honest degradation — some markups are
    missing or failed, or a source changed mid-run — so a partial reviewed set is
    never presented as fully successful. Absent when no markups were requested.
    """
    coverage = (getattr(ctx, "coverage_status", "") or "").upper()
    if coverage not in ("COMPLETE", "INCOMPLETE"):
        return ""
    tally = html.escape((getattr(ctx, "ledger_tally_line", "") or "").strip())
    if coverage == "COMPLETE":
        title = "Markup coverage: COMPLETE"
        detail = "Every planned markup was found again in the saved reviewed PDF(s)."
    else:
        title = "Markup coverage: INCOMPLETE"
        mutated = list(getattr(ctx, "mutated_sources", None) or [])
        detail = (
            "Some planned markups are missing or failed"
            + (
                f" — {len(mutated)} source(s) changed mid-run and were skipped"
                if mutated
                else ""
            )
            + ". See the issues below, the <code>_INCOMPLETE</code> reviewed PDF(s), "
            "and <code>markup_manifest.json</code>. A re-run is recommended."
        )
    tally_html = f'<div class="cb-detail">{tally}.</div>' if tally else ""
    return (
        f'<div class="coverage-banner" data-coverage="{_esc_attr(coverage)}">'
        f'<div class="cb-title">{html.escape(title)}</div>'
        f'<div class="cb-detail">{detail}</div>'
        f"{tally_html}"
        f"</div>"
    )


def _raw_html(ctx: Any) -> str:
    combined = (getattr(ctx, "combined_text", "") or "").strip()
    if not combined:
        return ""
    return (
        '<details class="raw-block"><summary>Complete raw Markdown '
        "(verbatim model output)</summary>"
        '<div class="raw-tools">'
        '<button class="copy-btn" data-copy-target="raw-md">Copy all</button>'
        "</div>"
        f'<pre id="raw-md">{html.escape(combined, quote=False)}</pre>'
        "</details>"
    )


def build_html_report(
    ctx: Any,
    *,
    source_names: list[str],
    now: datetime | None = None,
    api_key: str | None = None,
    embed_api_key: bool = False,
    link_evidence: bool = False,
    include_chat: bool = True,
    pdf_links: "dict[str, dict] | None" = None,
) -> str:
    """Render a :class:`DrawingContext` to one self-contained HTML document.

    Pure and duck-typed (see the module docstring): reads only ``ctx.sheets`` and
    the run-summary attributes, embeds all CSS/JS, and returns the full HTML as a
    string. ``source_names`` is listed in the run summary; ``now`` stamps the
    report (defaults to :func:`datetime.now`).

    ``include_chat`` — the in-page Q&A assistant (Ask AI) is included **by
    default**, whether or not a key is available at build time (Phase 17,
    DA-026): with no embedded key it prompts the reader on first use and keeps
    the key only in the browser tab's ``sessionStorage`` — never in the file.
    Pass ``include_chat=False`` for a report with no assistant and no network
    references at all.

    ``api_key`` / ``embed_api_key`` — **by default no key is ever written into
    the file**, even when ``api_key`` is provided. Pass ``embed_api_key=True``
    (with a key) to bake it in — convenient, but the file must then never be
    shared, and the report carries a red warning saying so.

    ``link_evidence`` — when ``True`` (folder exports, where the evidence crops
    are copied alongside), each finding row links a thumbnail of the crop the
    verifier saw, via the run-relative ``verification.evidence_png`` path. The
    single-file report leaves this off to stay light and self-contained.

    ``pdf_links`` — an optional ``{qc_id: {"pdf": name, "page": 1-based}}`` map
    (built by :func:`~drawing_analyzer.export.build_reviewed_pdf_links` for
    folder exports, where the marked-up PDF sits alongside the report). When a
    finding's ``qc_id`` is present, its QC-### cell becomes a deep link that
    opens that reviewed PDF at the finding's page (``<name>.pdf#page=N``); the
    inked cloud + QC tag already on that page put the reader on the mark. Absent
    (single-file reports, non-markup runs) → the cell renders as today's plain
    text.
    """
    now = now or datetime.now()
    sheets = list(getattr(ctx, "sheets", None) or [])
    total = len(sheets)
    geoms = _geometry_index(ctx)
    ambiguous = _ambiguous_names(ctx)  # §18.6 same-name source disambiguation

    title = "Drawing Set Digest"
    if source_names:
        title = f"{Path(source_names[0]).stem} — Drawing Digest"

    has_focus = bool(_focus_value(ctx))
    cards = [_focus_card(ctx)] if has_focus else []
    findings_card = _findings_card(
        ctx, sheets, link_evidence=link_evidence, ambiguous=ambiguous,
        pdf_links=pdf_links,
    )
    if findings_card:
        cards.append(findings_card)
    cards.append(_overview_card(ctx))
    cards += [
        _sheet_card(i, total, s, geoms.get(_sheet_key(_ref_of(s))), ambiguous=ambiguous)
        for i, s in enumerate(sheets, start=1)
    ]

    body = f"""<aside class="sidebar">
  <div class="brand">Drawing Digest</div>
  <div class="generated">{html.escape(now.strftime('%Y-%m-%d %H:%M'))}</div>
  <div class="search-wrap">
    <input id="search" type="search" placeholder="Search all sheets…" autocomplete="off" aria-label="Search the report">
  </div>
  <div class="chips">{_filter_chips_html(include_focus=has_focus)}</div>
  <div class="result-count" id="result-count" role="status"></div>
  <nav class="toc" id="toc" aria-label="Report contents">{_toc_html(ctx, sheets, ambiguous=ambiguous)}</nav>
</aside>
<main class="content">
  <div class="content-head">
    <h1>{html.escape(title)}</h1>
    <div class="content-actions">
      <button id="expand-all" class="ghost-btn">Expand all</button>
      <button id="collapse-all" class="ghost-btn">Collapse all</button>
    </div>
  </div>
  {_summary_html(ctx, source_names, now)}
  <div id="cards">{''.join(cards)}</div>
  <div class="no-results" id="no-results" hidden>No sections match your filter.</div>
  {_raw_html(ctx)}
  <footer class="foot">Generated by Drawing Analyzer · every section above is the
  verbatim model digest, reorganized for navigation.</footer>
</main>"""

    # The assistant is included by default (DA-026) and prompts the reader for
    # a key on first use; the key is embedded only when embed_api_key is set.
    # include_chat=False yields a report with no assistant and no network
    # references at all.
    key_clean = (api_key or "").strip()
    chat_css = chat_markup = chat_script = ""
    script_sources = [_JS]
    if include_chat:
        chat_css = _CHAT_CSS
        chat_markup = "\n" + _chat_bootstrap_html(
            api_key=key_clean,
            embed_key=embed_api_key,
            title=title,
            generated=now.strftime("%Y-%m-%d %H:%M"),
            source_names=source_names,
        )
        chat_script = f"<script>{_CHAT_JS}</script>\n"
        script_sources.append(_CHAT_JS)
        # Inert (type="application/json") data blocks the assistant's client-side
        # tools read: the structured findings ledger and run summary the prose
        # digest omits. Not executable → excluded from script_sources / CSP hashes,
        # and chat-gated so a no-chat report stays network-reference-free.
        chat_markup += (
            "\n" + _findings_data_block(ctx, sheets, ambiguous=ambiguous, pdf_links=pdf_links)
            + "\n" + _summary_data_block(ctx, source_names, now)
            + "\n" + _starters_data_block(
                ctx, sheets, source_names, ambiguous=ambiguous
            )
        )

    # CSP hashes are computed over the *exact* inline script bodies emitted
    # below — the config block is inert (type="application/json") and needs no
    # execution allowance.
    csp = _csp_meta(script_sources=script_sources, chat_enabled=include_chat)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"{csp}\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}{chat_css}</style>\n"
        f"</head>\n<body>\n{body}{chat_markup}\n<script>{_JS}</script>\n{chat_script}</body>\n</html>\n"
    )


# --------------------------------------------------------------------------- #
# Styling & behavior (inlined so the report is a single portable file).
# --------------------------------------------------------------------------- #

_CSS = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#1c2430; --muted:#6b7686;
  --line:#e3e7ee; --accent:#2f6df0; --accent-soft:#eaf1ff;
  --ok:#1f9d57; --cached:#8a6d1f; --failed:#d23b3b; --overview:#7a3ff0;
  --coord:#b5710d; --coord-soft:#fff5e6; --conflict:#d23b3b; --conflict-soft:#fdecec;
  --focus:#0e8a8a; --focus-soft:#e7f7f6; --findings:#c2410c;
  --radius:10px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink); background:var(--bg); display:flex; min-height:100vh;
}
a{color:var(--accent); text-decoration:none}

/* Sidebar */
.sidebar{
  width:310px; flex:0 0 310px; background:var(--panel); border-right:1px solid var(--line);
  padding:18px 16px; position:sticky; top:0; height:100vh; overflow-y:auto;
}
.brand{font-weight:700; font-size:16px; letter-spacing:.2px}
.generated{color:var(--muted); font-size:12px; margin-top:2px}
.search-wrap{margin:16px 0 10px}
#search{
  width:100%; padding:9px 12px; border:1px solid var(--line); border-radius:8px;
  font-size:14px; background:#fbfcfe; color:var(--ink);
}
#search:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft)}
.chips{display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px}
.chip{
  border:1px solid var(--line); background:#fff; color:var(--ink); font-size:12px;
  padding:5px 10px; border-radius:999px; cursor:pointer; transition:.12s;
}
.chip:hover{border-color:var(--accent)}
.chip-active{background:var(--accent); border-color:var(--accent); color:#fff}
.chip-issues{font-weight:600}
.chip-issues.chip-active{background:var(--conflict); border-color:var(--conflict)}
.result-count{font-size:12px; color:var(--muted); min-height:16px; margin-bottom:8px}
.toc{display:flex; flex-direction:column; gap:1px; border-top:1px solid var(--line); padding-top:8px}
.toc-item{
  display:flex; align-items:center; gap:8px; padding:7px 8px; border-radius:7px;
  color:var(--ink); font-size:13px;
}
.toc-item:hover{background:var(--accent-soft)}
.toc-item.active{background:var(--accent-soft); font-weight:600}
.toc-seq{color:var(--muted); font-variant-numeric:tabular-nums; font-size:11px}
.toc-label{overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.toc-dot{width:8px; height:8px; border-radius:50%; flex:0 0 8px}
.dot-ok{background:var(--ok)} .dot-cached{background:var(--cached)}
.dot-failed{background:var(--failed)} .dot-overview{background:var(--overview)}
.dot-focus{background:var(--focus)} .dot-findings{background:var(--findings)}

/* Content */
.content{flex:1 1 auto; padding:26px 34px; max-width:1000px; margin:0 auto; width:100%}
.content-head{display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap}
.content h1{font-size:23px; margin:0 0 4px}
.content-actions{display:flex; gap:8px}
.ghost-btn,.copy-btn{
  border:1px solid var(--line); background:#fff; color:var(--ink); font-size:12px;
  padding:6px 11px; border-radius:7px; cursor:pointer;
}
.ghost-btn:hover,.copy-btn:hover{border-color:var(--accent); color:var(--accent)}

/* Summary */
.summary{margin:18px 0 24px}
.stats{display:flex; flex-wrap:wrap; gap:12px}
.stat{
  background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
  padding:12px 16px; min-width:150px;
}
.stat-val{font-size:18px; font-weight:700}
.stat-key{font-size:12px; color:var(--muted); margin-top:2px}
.sources,.errors{margin-top:12px; font-size:13px}
.sources summary,.errors summary{cursor:pointer; color:var(--muted)}
.errors{border:1px solid var(--conflict); background:var(--conflict-soft); border-radius:8px; padding:8px 12px}
.errors summary{color:var(--conflict); font-weight:600}
.errors ul,.sources ul{margin:8px 0 4px; padding-left:20px}
.coverage-banner{margin:0 0 14px; padding:10px 14px; border-radius:8px; font-size:13.5px;
  border:1px solid var(--line)}
.coverage-banner .cb-title{font-weight:700}
.coverage-banner .cb-detail{color:var(--muted); margin-top:2px}
.coverage-banner[data-coverage="COMPLETE"]{border-color:var(--ok); background:#e7f6ee}
.coverage-banner[data-coverage="COMPLETE"] .cb-title{color:var(--ok)}
.coverage-banner[data-coverage="INCOMPLETE"]{border-color:var(--failed); background:var(--conflict-soft)}
.coverage-banner[data-coverage="INCOMPLETE"] .cb-title{color:var(--failed)}
.qc-status-banner{margin:0 0 14px; padding:10px 14px; border-radius:8px; font-size:13.5px;
  border:1px solid var(--line)}
.qc-status-banner .cb-title{font-weight:700}
.qc-status-banner .cb-detail{color:var(--muted); margin-top:2px}
.qc-status-banner[data-status="COMPLETE"]{border-color:var(--ok); background:#e7f6ee}
.qc-status-banner[data-status="COMPLETE"] .cb-title{color:var(--ok)}
.qc-status-banner[data-status="PARTIAL"]{border-color:var(--coord); background:var(--coord-soft)}
.qc-status-banner[data-status="PARTIAL"] .cb-title{color:var(--coord)}
.qc-status-banner[data-status="FAILED"]{border-color:var(--failed); background:var(--conflict-soft)}
.qc-status-banner[data-status="FAILED"] .cb-title{color:var(--failed)}
.usage{margin-top:12px; font-size:13px}
.usage summary{cursor:pointer; color:var(--muted)}
.usage-scroll{overflow-x:auto; margin-top:8px}
.usage-table{border-collapse:collapse; width:100%; font-size:12.5px}
.usage-table th,.usage-table td{border-bottom:1px solid var(--line); padding:4px 10px; text-align:left}
.usage-table th.num,.usage-table td.num{text-align:right; font-variant-numeric:tabular-nums}
.usage-table thead th{color:var(--muted); font-weight:600}
/* Per-stage QC table (§18.6) — status-cell colors match the banner palette. */
.stage-table td.st-complete{color:var(--ok); font-weight:600}
.stage-table td.st-partial{color:var(--coord); font-weight:600}
.stage-table td.st-failed{color:var(--failed); font-weight:600}
.stage-table td.st-skipped,.stage-table td.st-not-requested{color:var(--muted)}

/* Cards */
.card{
  background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
  margin-bottom:14px; overflow:hidden; scroll-margin-top:14px;
}
.card-head{
  display:flex; align-items:center; gap:12px; padding:13px 16px; cursor:pointer;
  user-select:none; border-left:4px solid transparent;
}
.card-head:hover{background:#fafbfd}
.card[data-status="ok"] .card-head{border-left-color:var(--ok)}
.card[data-status="cached"] .card-head{border-left-color:var(--cached)}
.card[data-status="failed"] .card-head{border-left-color:var(--failed)}
.card[data-status="overview"] .card-head{border-left-color:var(--overview)}
.card[data-status="focus"] .card-head{border-left-color:var(--focus)}
.card[data-status="findings"] .card-head{border-left-color:var(--findings)}
.card-title{font-weight:600; flex:1 1 auto; font-size:15px}
.seq{color:var(--muted); font-variant-numeric:tabular-nums; margin-right:4px}
.badges{display:flex; gap:6px; flex-wrap:wrap; align-items:center}
.badge{font-size:11px; padding:3px 8px; border-radius:999px; white-space:nowrap}
.badge-ok{background:#e7f6ee; color:var(--ok)}
.badge-cached{background:#fbf3df; color:var(--cached)}
.badge-failed{background:var(--conflict-soft); color:var(--failed)}
.badge-overview{background:#f1eaff; color:var(--overview)}
.badge-focus{background:var(--focus-soft); color:var(--focus)}
.badge-findings{background:#fdeaea; color:var(--findings)}
.badge-raster{background:#efe7fb; color:#6b3fb0}
.badge-tok{background:#eef1f6; color:var(--muted); font-variant-numeric:tabular-nums}
#findings-shown{font-size:11px; white-space:nowrap}
.chevron{color:var(--muted); transition:transform .15s}
.card.collapsed .chevron{transform:rotate(-90deg)}
.card.collapsed .card-body{display:none}
.card-body{padding:4px 18px 16px; border-top:1px solid var(--line)}

/* Blocks (digest sections) */
.block{padding:10px 0; border-bottom:1px dashed var(--line)}
.block:last-child{border-bottom:none}
.block-title{
  font-size:14px; margin:6px 0 8px; display:flex; align-items:center; gap:8px; flex-wrap:wrap;
}
.block[data-category="coordination"]{
  background:var(--coord-soft); border-left:3px solid var(--coord);
  padding-left:12px; border-radius:6px; border-bottom:none; margin:8px 0;
}
.block[data-category="conflict"]{
  background:var(--conflict-soft); border-left:3px solid var(--conflict);
  padding-left:12px; border-radius:6px; border-bottom:none; margin:8px 0;
}
.block[data-category="focus"]{
  background:var(--focus-soft); border-left:3px solid var(--focus);
  padding-left:12px; border-radius:6px; border-bottom:none; margin:8px 0;
}
.cat-tag{font-size:10px; font-weight:700; padding:2px 7px; border-radius:999px; text-transform:uppercase; letter-spacing:.4px}
.cat-coordination{background:var(--coord); color:#fff}
.cat-conflict{background:var(--conflict); color:#fff}
.cat-focus{background:var(--focus); color:#fff}
.focus-ask{color:var(--ink)}

/* Markdown body */
.block h1,.block h2,.block h3,.block h4,.block h5,.block h6{margin:10px 0 6px; line-height:1.3}
.block h1{font-size:18px} .block h2{font-size:16px} .block h3{font-size:15px}
.block p{margin:7px 0}
.block ul,.block ol{margin:7px 0; padding-left:22px}
.block li{margin:3px 0}
.block code{
  background:#eef1f6; padding:1px 5px; border-radius:4px; font-size:.9em;
  font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;
}
.block blockquote{
  margin:8px 0; padding:6px 14px; border-left:3px solid var(--line);
  color:var(--muted); background:#fafbfd;
}
.block table{border-collapse:collapse; width:100%; margin:10px 0; font-size:13px}
.block th,.block td{border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top}
.block th{background:#f3f5f9; font-weight:600}
.block tr:nth-child(even) td{background:#fafbfd}
.error-box{
  background:var(--conflict-soft); border:1px solid var(--conflict); color:#8d2020;
  padding:10px 14px; border-radius:8px;
}
.muted{color:var(--muted)}
/* Phase B: a citation MISMATCH must read as a warning, not blend into the
   muted pass styling — distinct color + weight. The evidence link is the
   model-selected best https source for that verdict. */
.citation-mismatch{color:#a04a00; font-weight:600}
.citation-evidence{font-size:12px; margin-left:2px}

/* Raw + misc */
.raw-block{margin:22px 0; border:1px solid var(--line); border-radius:var(--radius); background:var(--panel); padding:10px 14px}
.raw-block summary{cursor:pointer; font-weight:600}
.raw-tools{margin:8px 0}
.raw-block pre{
  background:#0f1622; color:#d6e2f5; padding:14px; border-radius:8px; overflow:auto;
  font-size:12.5px; line-height:1.5; max-height:60vh; white-space:pre-wrap; word-break:break-word;
}
.no-results{color:var(--muted); padding:24px; text-align:center; border:1px dashed var(--line); border-radius:var(--radius)}
.foot{margin:30px 0 10px; color:var(--muted); font-size:12px}
.hidden{display:none !important}
mark{background:#ffe9a8; color:inherit; padding:0 1px; border-radius:2px}

/* QC Findings table */
.findings-hint{font-size:12px; margin:2px 0 10px}
.findings-wrap{overflow-x:auto}
.findings-table{border-collapse:collapse; width:100%; font-size:13px}
.findings-table th,.findings-table td{
  border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top;
}
.findings-table thead th{
  background:#f3f5f9; font-weight:600; cursor:pointer; user-select:none;
  white-space:nowrap; position:relative;
}
.findings-table thead th:hover{background:#e9edf4}
.findings-table thead th.sort-asc::after{content:" ▲"; color:var(--muted); font-size:10px}
.findings-table thead th.sort-desc::after{content:" ▼"; color:var(--muted); font-size:10px}
.findings-table tbody tr:nth-child(even) td{background:#fafbfd}
.findings-table .fcol-qcid{white-space:nowrap; font-weight:600; color:var(--muted)}
.findings-table .fcol-qcid a.pdf-link{color:var(--accent); font-weight:600}
.findings-table .fcol-qcid a.pdf-link:hover{text-decoration:underline}
.findings-table .fcol-qcid a.pdf-link::after{content:" \2197"; font-size:10px; color:var(--muted)}
.findings-table .fcol-sheet{white-space:nowrap}
.findings-table .fcol-cat{text-transform:capitalize; color:var(--muted)}
.findings-table .fcol-sev{text-transform:capitalize; font-weight:600}
.findings-table .sev-high{color:var(--conflict)}
.findings-table .sev-medium{color:var(--coord)}
.findings-table .sev-low{color:var(--muted)}
.findings-table code{
  background:#eef1f6; padding:1px 5px; border-radius:4px; font-size:.9em;
  font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;
}
.evidence-thumb{
  height:34px; width:auto; border:1px solid var(--line); border-radius:4px;
  vertical-align:middle; margin-left:4px;
}
.finding-action{margin-top:3px; font-weight:600; color:#2f5fd0}
/* Finding status chips */
.fchip{
  display:inline-block; font-size:11px; font-weight:600; padding:2px 8px;
  border-radius:999px; white-space:nowrap;
}
.fchip-verified{background:#e7f6ee; color:var(--ok)}
.fchip-deterministic{background:#e7eefb; color:#2f5fd0}
.fchip-uncertain{background:#fbf3df; color:var(--coord)}
.fchip-unanchored{background:#fff; color:var(--conflict); border:1px solid var(--conflict)}
.fchip-rejected{background:#eef0f3; color:var(--muted); text-decoration:line-through}

/* Per-sheet raw text layer */
.block-rawtext .rawtext summary{cursor:pointer; color:var(--muted); font-size:13px}
.rawtext-pre{
  background:#0f1622; color:#d6e2f5; padding:12px; border-radius:8px; overflow:auto;
  font-size:12px; line-height:1.5; max-height:44vh; white-space:pre-wrap; word-break:break-word;
  margin-top:8px;
}

@media (max-width:820px){
  body{flex-direction:column}
  .sidebar{width:100%; flex-basis:auto; height:auto; position:static; border-right:none; border-bottom:1px solid var(--line)}
  .content{padding:18px}
}
@media print{
  .sidebar,.content-actions,.raw-tools{display:none !important}
  body{display:block}
  .card,.card-body{break-inside:avoid}
  .card.collapsed .card-body{display:block !important}
}
"""

_JS = r"""
(function(){
  var search = document.getElementById('search');
  // Only data-filter chips are exclusive; #sev-high is a standalone toggle.
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip[data-filter]'));
  var sevHigh = document.getElementById('sev-high');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var toc = Array.prototype.slice.call(document.querySelectorAll('.toc-item'));
  var resultCount = document.getElementById('result-count');
  var noResults = document.getElementById('no-results');
  var findingsCard = document.getElementById('findings');
  var findingRows = findingsCard ?
    Array.prototype.slice.call(findingsCard.querySelectorAll('.finding-row')) : [];
  var findingsShown = document.getElementById('findings-shown');
  var ISSUE = ['coordination','conflict'];
  var activeFilter = 'all';
  var highOnly = false;   // DA-025: severity toggle, independent of the chips

  function activeCategories(){
    if(activeFilter === 'all') return null;          // null => every category
    if(activeFilter === 'issues') return ISSUE.slice();
    return [activeFilter];
  }

  function tocFor(id){
    for(var i=0;i<toc.length;i++){ if(toc[i].getAttribute('data-target')===id) return toc[i]; }
    return null;
  }

  // The findings table filters by row, not by .block: every finding is itself an
  // issue, so ⚠ Issues only keeps them all; a specific category chip narrows to
  // matching rows; search matches row text. Returns 1 if the card stays visible.
  function applyFindings(q){
    if(!findingsCard) return 0;
    var shown = 0;
    findingRows.forEach(function(row){
      var cat = row.getAttribute('data-category');
      var catOk = (activeFilter === 'all' || activeFilter === 'issues') || (cat === activeFilter);
      var textOk = q === '' || row.textContent.toLowerCase().indexOf(q) !== -1;
      // DA-025: data-severity is the numeric rank (3=high, 2, 1, 0).
      var sevOk = !highOnly || row.getAttribute('data-severity') === '3';
      var show = catOk && textOk && sevOk;
      row.classList.toggle('hidden', !show);
      if(show) shown++;
    });
    // §18.6: filters never change the static totals — the badge keeps the full
    // count; this live line only says what the current filters are showing.
    if(findingsShown){
      findingsShown.textContent = shown === findingRows.length ? '' :
        'showing ' + shown + ' of ' + findingRows.length;
    }
    var cardShow = shown > 0;
    findingsCard.classList.toggle('hidden', !cardShow);
    var t = tocFor('findings'); if(t) t.classList.toggle('hidden', !cardShow);
    return cardShow ? 1 : 0;
  }

  function apply(){
    var q = (search.value || '').trim().toLowerCase();
    var cats = activeCategories();
    var visibleCards = 0;

    cards.forEach(function(card){
      if(card === findingsCard) return;   // handled by applyFindings below
      var blocks = Array.prototype.slice.call(card.querySelectorAll('.block'));
      var anyBlock = false;
      var titleEl = card.querySelector('.card-title');
      var titleMatch = q === '' || (titleEl && titleEl.textContent.toLowerCase().indexOf(q) !== -1);

      blocks.forEach(function(b){
        var catOk = !cats || cats.indexOf(b.getAttribute('data-category')) !== -1;
        var textOk = q === '' || b.textContent.toLowerCase().indexOf(q) !== -1 || titleMatch;
        var show = catOk && textOk;
        b.classList.toggle('hidden', !show);
        if(show) anyBlock = true;
      });

      // A card shows when it has a surviving block, or (no category filter) its
      // title matches the search and it simply has no sub-blocks.
      var cardShow = anyBlock || (!cats && titleMatch && blocks.length === 0);
      card.classList.toggle('hidden', !cardShow);
      var t = tocFor(card.id);
      if(t) t.classList.toggle('hidden', !cardShow);
      if(cardShow) visibleCards++;
    });

    visibleCards += applyFindings(q);

    noResults.hidden = visibleCards !== 0;
    var filterLabel = activeFilter === 'all' ? '' :
      ' · filter: ' + (document.querySelector('.chip-active') ? document.querySelector('.chip-active').textContent.trim() : activeFilter);
    resultCount.textContent = visibleCards + ' of ' + cards.length + ' section(s)' + filterLabel;
  }

  chips.forEach(function(chip){
    chip.addEventListener('click', function(){
      chips.forEach(function(c){ c.classList.remove('chip-active'); c.setAttribute('aria-pressed','false'); });
      chip.classList.add('chip-active');
      chip.setAttribute('aria-pressed','true');
      activeFilter = chip.getAttribute('data-filter');
      apply();
    });
  });

  // DA-025: "High severity only" toggles on top of the exclusive chips.
  if(sevHigh){
    sevHigh.addEventListener('click', function(){
      highOnly = !highOnly;
      sevHigh.classList.toggle('chip-active', highOnly);
      sevHigh.setAttribute('aria-pressed', highOnly ? 'true' : 'false');
      apply();
    });
  }

  var timer = null;
  search.addEventListener('input', function(){
    if(timer) clearTimeout(timer);
    timer = setTimeout(apply, 90);
  });

  // Collapse / expand a card by clicking (or keyboard-activating) its header;
  // aria-expanded on the header tracks the state for assistive tech.
  function setExpanded(card, expanded){
    card.classList.toggle('collapsed', !expanded);
    var head = card.querySelector('.card-head');
    if(head) head.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }
  cards.forEach(function(card){
    var head = card.querySelector('.card-head');
    function toggle(){ setExpanded(card, card.classList.contains('collapsed')); }
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', function(e){
      if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); toggle(); }
    });
  });
  var ea = document.getElementById('expand-all');
  var ca = document.getElementById('collapse-all');
  if(ea) ea.addEventListener('click', function(){ cards.forEach(function(c){ setExpanded(c, true); }); });
  if(ca) ca.addEventListener('click', function(){ cards.forEach(function(c){ setExpanded(c, false); }); });

  // Findings table — click a column header to sort; re-clicking a column flips
  // the direction. Severity and status sort by their numeric ranks (high→low,
  // most-actionable→least), the rest lexically by the cell text.
  if(findingsCard){
    var ftable = findingsCard.querySelector('.findings-table');
    var ftbody = ftable ? ftable.querySelector('tbody') : null;
    var fths = ftable ? Array.prototype.slice.call(ftable.querySelectorAll('th[data-sort]')) : [];
    var COLS = {qcid:0, sheet:1, category:2, severity:3, status:4, text:5, quote:6};
    var fsort = {key:null, dir:1};
    function fval(row, key){
      if(key === 'severity') return parseInt(row.getAttribute('data-severity') || '0', 10);
      if(key === 'status') return parseInt(row.getAttribute('data-status-rank') || '0', 10);
      var cell = row.children[COLS[key]];
      return cell ? cell.textContent.trim().toLowerCase() : '';
    }
    fths.forEach(function(th){
      function sortBy(){
        if(!ftbody) return;
        var key = th.getAttribute('data-sort');
        if(fsort.key === key) fsort.dir = -fsort.dir; else { fsort.key = key; fsort.dir = 1; }
        var rows = Array.prototype.slice.call(ftbody.querySelectorAll('.finding-row'));
        rows.sort(function(a, b){
          var va = fval(a, key), vb = fval(b, key);
          if(va < vb) return -fsort.dir;
          if(va > vb) return fsort.dir;
          return 0;
        });
        rows.forEach(function(r){ ftbody.appendChild(r); });
        fths.forEach(function(t){ t.classList.remove('sort-asc','sort-desc'); t.setAttribute('aria-sort','none'); });
        th.classList.add(fsort.dir === 1 ? 'sort-asc' : 'sort-desc');
        th.setAttribute('aria-sort', fsort.dir === 1 ? 'ascending' : 'descending');
      }
      th.addEventListener('click', sortBy);
      th.addEventListener('keydown', function(e){
        if(e.key === 'Enter'){ e.preventDefault(); sortBy(); }
      });
    });
  }

  // TOC click scrolls (native via href) and expands the target if collapsed.
  toc.forEach(function(item){
    item.addEventListener('click', function(){
      var el = document.getElementById(item.getAttribute('data-target'));
      if(el) setExpanded(el, true);
    });
  });

  // Highlight the TOC entry for whatever card is currently in view.
  if('IntersectionObserver' in window){
    var obs = new IntersectionObserver(function(entries){
      entries.forEach(function(en){
        if(en.isIntersecting){
          toc.forEach(function(t){ t.classList.remove('active'); });
          var t = tocFor(en.target.id);
          if(t) t.classList.add('active');
        }
      });
    }, {rootMargin:'-10% 0px -80% 0px', threshold:0});
    cards.forEach(function(c){ obs.observe(c); });
  }

  // Copy-to-clipboard for the raw Markdown.
  document.querySelectorAll('.copy-btn').forEach(function(btn){
    btn.addEventListener('click', function(){
      var el = document.getElementById(btn.getAttribute('data-copy-target'));
      if(!el) return;
      var text = el.textContent;
      var done = function(){ var o = btn.textContent; btn.textContent = 'Copied!'; setTimeout(function(){ btn.textContent = o; }, 1400); };
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
        ta.select(); try{ document.execCommand('copy'); }catch(e){} document.body.removeChild(ta); done();
      }
    });
  });

  apply();
})();
"""


# --------------------------------------------------------------------------- #
# In-report Q&A assistant ("Ask AI").
#
# Everything below is emitted by default (omit with include_chat=False). The
# widget is deliberately self-sufficient: it reads its grounding context out of
# the page's own #raw-md block (the verbatim combined digest) so the large
# report text is never duplicated into the file, resolves its key at runtime
# (prompted on first use and cached in sessionStorage, or embedded via the
# explicit opt-in), and it talks to the Anthropic Messages API straight from
# the browser (the API's CORS opt-in header
# `anthropic-dangerous-direct-browser-access` makes that possible).
# Request shape: streaming, adaptive thinking with summarized display, the
# server-side web_search/web_fetch tools, and a prompt-cache breakpoint on the
# report block so every question after the first re-reads the report at cache
# prices.
# --------------------------------------------------------------------------- #


def _citation_summary(f: Any) -> dict[str, Any] | None:
    """Compact, chat-facing citation state for a finding, or ``None`` when it
    carries no citation check.

    Folds the derived overall :class:`Citation` (``status``/``note``) together
    with the per-reference :class:`CitationAssessment` verdicts so the assistant
    can answer "do the cited code sections check out?" from ``#da-findings``
    without guessing. All values ride the shared :func:`_json_for_script`
    escaping applied to the whole block.
    """
    out: dict[str, Any] = {}
    cit = getattr(f, "citation", None)
    if cit is not None:
        status = (getattr(cit, "status", "") or "").strip()
        if status:
            out["status"] = status
        note = (getattr(cit, "note", "") or "").strip()
        if note:
            out["note"] = note
    per: list[dict[str, str]] = []
    for a in getattr(f, "citations", None) or []:
        ref = (getattr(a, "reference", "") or "").strip()
        st = (getattr(a, "status", "") or "").strip()
        if ref or st:
            per.append({"reference": ref, "status": st})
    if per:
        out["assessments"] = per
    return out or None


def _findings_data_block(
    ctx: Any,
    sheets: list[Any],
    *,
    ambiguous: frozenset[str] = frozenset(),
    pdf_links: "dict[str, dict] | None" = None,
) -> str:
    """An inert ``#da-findings`` JSON block: the structured QC findings the chat
    assistant can query (fields the prose digest deliberately omits).

    Beyond the table's columns, each row carries the cross-sheet ``also_on`` legs
    and any cited ``refs`` / ``citation`` verdict (see :func:`_citation_summary`),
    so the cross-sheet and cited-code starter prompts are answerable from the
    structured data rather than only the prose digest.

    Mirrors :func:`_findings_card`'s per-finding derivation (same ledger entries,
    same sort, same sheet-card linking and §18.6 name disambiguation) so the
    ``query_findings`` tool sees exactly what the table shows. Emitted through
    :func:`_json_for_script` (every ``<`` escaped), so however adversarial a
    finding's text/quote is, it cannot close the script element. Returns ``""``
    when the run produced no findings (the tool then reports an empty ledger).
    """
    findings = _report_findings(ctx)
    if not findings:
        return ""
    index = _sheet_card_index(sheets)

    def _key(f: Any):
        sev = _SEVERITY_RANK.get((getattr(f, "severity", "") or "").lower(), 0)
        return (-sev, -_STATUS_RANK.get(_finding_display_status(f), 0))

    items: list[dict[str, Any]] = []
    for f in sorted(findings, key=_key):
        card_index = index.get(
            _finding_sheet_key(f, int(getattr(f, "page_index", 0) or 0))
        )
        sheet_id = getattr(f, "sheet_id", "") or getattr(f, "source_name", "") or "—"
        row: dict[str, Any] = {
            "id": getattr(f, "qc_id", "") or "",
            "sheet": _disambiguated(sheet_id, f, ambiguous),
            "target": f"sheet-{card_index}" if card_index else "",
            # The marked-up-PDF deep link mirrored from the table, so the
            # assistant can cite the same jump-to-page target the reader sees.
            "pdf": _pdf_deep_link(pdf_links, getattr(f, "qc_id", "") or ""),
            "category": getattr(f, "category", "") or "other",
            "severity": (getattr(f, "severity", "") or "").lower(),
            "status": _finding_display_status(f),
            "text": getattr(f, "text", "") or "",
            "quote": getattr(f, "source_quote", "") or "",
        }
        # Cross-sheet legs (DA-016): the *other* sheet ids this one finding
        # touches. Serialized so the "which issues span more than one sheet?"
        # starter can be answered for a merged finding whose counterpart lives
        # only in ``also_on`` (invisible in the single ``sheet`` field otherwise).
        legs = [
            (getattr(leg, "sheet_id", "") or "").strip()
            for leg in (getattr(f, "also_on", None) or [])
        ]
        legs = [s for s in legs if s]
        if legs:
            row["also_on"] = legs
        # Cited code sections + the web-search citation verdict, so the "do the
        # cited code sections check out?" starter has the actual section numbers
        # and their checked status rather than guessing from the prose.
        refs = [
            str(r).strip()
            for r in (getattr(f, "refs", None) or [])
            if str(r).strip()
        ]
        if refs:
            row["refs"] = refs
        citation = _citation_summary(f)
        if citation:
            row["citation"] = citation
        items.append(row)
    return (
        f'<script id="da-findings" type="application/json">'
        f"{_json_for_script(items)}</script>"
    )


def _summary_data_block(
    ctx: Any, source_names: list[str], now: datetime
) -> str:
    """An inert ``#da-summary`` JSON block: the run metadata the prose digest
    lacks (sheet tally, QC/coverage status, tokens, est. cost, sources).

    Reads exactly the fields :func:`_summary_html` already surfaces, so the
    ``get_report_summary`` tool answers "what did this run cost / how many sheets
    failed / is coverage complete" without the model guessing. Serialized through
    :func:`_json_for_script` (inert). Always emitted with chat (there is always a
    run to describe); finding *counts* are derived client-side from
    ``#da-findings`` so the two blocks never disagree.
    """
    ok = int(getattr(ctx, "ok_sheet_count", 0) or 0)
    total = int(getattr(ctx, "sheet_count", 0) or 0)
    cached = int(getattr(ctx, "cached_sheet_count", 0) or 0)
    cost = getattr(ctx, "total_estimated_cost", None)
    summary: dict[str, Any] = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "sheets": {
            "ok": ok,
            "total": total,
            "cached": cached,
            "failed": max(0, total - ok),
        },
        "qc_status": (getattr(ctx, "qc_status", "") or "NOT_REQUESTED").upper(),
        "coverage_status": (getattr(ctx, "coverage_status", "") or "").upper()
        or "NOT_REQUESTED",
        "tokens": {
            "input": int(getattr(ctx, "total_input_tokens", 0) or 0),
            "output": int(getattr(ctx, "total_output_tokens", 0) or 0),
        },
        "estimated_cost_usd": (round(float(cost), 4) if cost is not None else None),
        "errors": len(list(getattr(ctx, "errors", None) or [])),
        "sources": list(source_names),
    }
    return (
        f'<script id="da-summary" type="application/json">'
        f"{_json_for_script(summary)}</script>"
    )


# Human-facing phrasing for the finding categories, used to build "Summarize the
# {…}" starter prompts from whatever the set actually contains (never an invented
# discipline). Keys are the FINDING_CATEGORIES the ledger assigns.
_CATEGORY_PHRASE = {
    "conflict": "conflicts",
    "coordination": "coordination items",
    "code": "code-compliance items",
    "reference": "cross-reference issues",
    "question": "open questions",
}
# Singular noun for the single most-severe finding's prompt.
_CATEGORY_NOUN = {
    "conflict": "conflict",
    "coordination": "coordination item",
    "code": "code item",
    "reference": "reference issue",
    "question": "open question",
}
# Fixed tie-break order when two categories are equally common (determinism, I-7).
_CATEGORY_ORDER = ("conflict", "coordination", "code", "reference", "question")


def _starter_prompts(
    ctx: Any,
    sheets: list[Any],
    source_names: list[str],
    *,
    ambiguous: frozenset[str] = frozenset(),
) -> list[str]:
    """Up to five click-to-send starter questions, tailored to *this* run.

    Deterministic (I-7): every candidate is gated on real data drawn from the
    same ledger the report shows (:func:`_report_findings`, sorted by the
    :func:`_findings_card` severity/status key), appended in a fixed priority
    order, deduped, and capped at five. It never invents an equipment tag or a
    discipline the set does not contain — a clean, findings-free run still yields
    set-aware prompts built from the real sheet count and source names, not
    generic filler.
    """
    findings = _report_findings(ctx)
    prompts: list[str] = []

    def add(text: str) -> None:
        t = (text or "").strip()
        if t and t not in prompts:
            prompts.append(t)

    if findings:
        def _key(f: Any):
            sev = _SEVERITY_RANK.get((getattr(f, "severity", "") or "").lower(), 0)
            return (-sev, -_STATUS_RANK.get(_finding_display_status(f), 0))

        ordered = sorted(findings, key=_key)

        # 1. The single most-severe finding, named by its real sheet + subject.
        top = ordered[0]
        top_sheet = _disambiguated(
            getattr(top, "sheet_id", "") or getattr(top, "source_name", "") or "",
            top,
            ambiguous,
        )
        if top_sheet:
            top_sev = (getattr(top, "severity", "") or "").lower()
            noun = _CATEGORY_NOUN.get(
                (getattr(top, "category", "") or "").lower(), "issue"
            )
            sev_prefix = f"{top_sev}-severity " if top_sev else ""
            add(f"What's driving the {sev_prefix}{noun} on {top_sheet}?")

        # 2. Critical conflicts / coordination clashes across the set.
        if any(
            (getattr(f, "severity", "") or "").lower() == "high"
            and (getattr(f, "category", "") or "").lower() in ("conflict", "coordination")
            for f in findings
        ):
            add("What are the most critical conflicts across these sheets?")

        # 3. Cross-sheet issues (a finding carrying also_on legs, DA-016).
        if any(getattr(f, "also_on", None) for f in findings):
            add("Which issues span more than one sheet?")

        # 4. Summarize the category the set actually has the most of.
        counts: dict[str, int] = {}
        for f in findings:
            c = (getattr(f, "category", "") or "").lower()
            if c in _CATEGORY_PHRASE:
                counts[c] = counts.get(c, 0) + 1
        if counts:
            best = max(
                counts, key=lambda c: (counts[c], -_CATEGORY_ORDER.index(c))
            )
            add(f"Summarize the {_CATEGORY_PHRASE[best]}.")

        # 5. Cited code sections (any finding carrying refs or a citation check).
        if any(
            getattr(f, "refs", None)
            or getattr(f, "citations", None)
            or getattr(f, "citation", None)
            for f in findings
        ):
            add("Do the cited code sections check out?")

        # 6. Unverified / unanchored findings — the hallucination signal.
        if any(
            _finding_display_status(f) in ("UNANCHORED", "UNCERTAIN")
            for f in findings
        ):
            add("Which findings could not be verified against the drawings?")

    # Set-aware fallbacks — always eligible, lowest priority. They guarantee a
    # non-empty, relevant list for a clean run and only reach the final list when
    # the finding-driven prompts above did not already fill all five slots.
    total = int(getattr(ctx, "sheet_count", 0) or 0) or len(list(sheets) or [])
    if total > 1:
        add(f"Give me an executive summary of this {total}-sheet set.")
    else:
        add("Give me an executive summary of this drawing set.")
    if len(source_names) == 1:
        add(f"What are the key takeaways from {source_names[0]}?")
    else:
        add("What equipment and systems are documented across these sheets?")

    return prompts[:5]


def _starters_data_block(
    ctx: Any,
    sheets: list[Any],
    source_names: list[str],
    *,
    ambiguous: frozenset[str] = frozenset(),
) -> str:
    """An inert ``#da-starters`` JSON block: up to five run-tailored, click-to-send
    starter prompts (see :func:`_starter_prompts`).

    Serialized through :func:`_json_for_script` (every ``<`` escaped), so however
    adversarial a source filename or finding subject is, a prompt string cannot
    close the script element. Returns ``""`` only if no prompts are produced (the
    widget then just shows its static hint text with no chips).
    """
    prompts = _starter_prompts(ctx, sheets, source_names, ambiguous=ambiguous)
    if not prompts:
        return ""
    return (
        f'<script id="da-starters" type="application/json">'
        f"{_json_for_script(prompts)}</script>"
    )


def _chat_bootstrap_html(
    *, api_key: str, embed_key: bool, title: str, generated: str,
    source_names: list[str],
) -> str:
    """The chat widget's markup + its JSON config block (model, run info, key).

    The config is embedded as an inert ``type="application/json"`` script and
    parsed by the widget at startup. It is serialized through
    :func:`_json_for_script`, which escapes every ``<`` (and U+2028/U+2029) as
    a JSON string escape, so no value — however adversarial a source filename
    or title — can close the script element or form markup.

    The key is written into the config **only** when ``embed_key`` is set and a
    key is present; otherwise it is left out and the widget asks the reader for
    one at first use (kept in ``sessionStorage``, never in the file). The footer
    reflects which mode is active — a red warning when the key is embedded —
    and carries the **Forget key** control (clears the tab's stored key in
    prompt mode; in embedded mode it truthfully explains that the credential
    lives in the file itself and only regenerating/deleting the file removes
    it).
    """
    embedding = bool(embed_key and api_key)
    config: dict[str, Any] = {
        "model": CHAT_MODEL_DEFAULT,
        "title": title,
        "generated": generated,
        "sources": list(source_names),
    }
    if embedding:
        config["apiKey"] = api_key
    config_json = _json_for_script(config)
    if embedding:
        foot = (
            "AI-generated answers — verify against the drawings. "
            '<span class="da-key-warn">This file embeds your API key in clear '
            "text; don't share it. Removing the key requires regenerating (or "
            "deleting) the file.</span>"
        )
    else:
        foot = (
            "AI-generated answers — verify against the drawings. Enter your "
            "Anthropic API key in the field above; it is kept only in this "
            "browser tab (sessionStorage) and is never saved into this file."
        )
    return (
        f'<script id="da-chat-config" type="application/json">{config_json}</script>'
        + _CHAT_HTML.replace("__CHAT_FOOT__", foot)
    )


_CHAT_HTML = """
<button id="da-chat-fab" type="button" title="Ask questions about this report">✦ Ask AI</button>
<section id="da-chat-panel" hidden aria-label="Report Q&amp;A">
  <div class="da-rz da-rz-tl" aria-hidden="true"></div>
  <div class="da-rz da-rz-tr" aria-hidden="true"></div>
  <div class="da-rz da-rz-bl" aria-hidden="true"></div>
  <div class="da-rz da-rz-br" aria-hidden="true"></div>
  <div class="da-rz da-rz-t" aria-hidden="true"></div>
  <div class="da-rz da-rz-b" aria-hidden="true"></div>
  <div class="da-rz da-rz-l" aria-hidden="true"></div>
  <div class="da-rz da-rz-r" aria-hidden="true"></div>
  <header class="da-chat-head">
    <span class="da-chat-title">Report Q&amp;A</span>
    <span class="da-chat-model" id="da-chat-model"></span>
    <button id="da-chat-export" type="button" class="ghost-btn" title="Save this conversation as a PDF via your browser's print dialog">Save as PDF</button>
    <button id="da-chat-clear" type="button" class="ghost-btn">New chat</button>
    <button id="da-chat-close" type="button" aria-label="Close">×</button>
  </header>
  <div id="da-chat-print-head"></div>
  <div id="da-chat-msgs">
    <div class="da-msg da-hint">Ask anything about this drawing set. Answers are grounded in
    this report; the assistant can also search the web for codes, standards, and product data.
    <div class="da-starters" id="da-starters-row" aria-label="Suggested questions"></div></div>
  </div>
  <div id="da-chat-key">
    <div id="da-chat-key-form">
      <div class="da-key-row">
        <input id="da-chat-key-input" type="password" placeholder="sk-ant-…" autocomplete="off" spellcheck="false" autocapitalize="off" autocorrect="off" aria-label="Anthropic API key">
        <button id="da-chat-key-toggle" type="button" class="ghost-btn" aria-pressed="false" title="Show or hide the key">Show</button>
        <button id="da-chat-key-save" type="button">Save key</button>
      </div>
    </div>
    <div id="da-chat-key-set" hidden>
      <span class="da-key-set-label">API key set for this browser tab.</span>
      <button id="da-chat-key-change" type="button" class="ghost-btn">Change key</button>
    </div>
    <div id="da-chat-key-status" class="da-key-status" aria-live="polite"></div>
  </div>
  <div class="da-chat-compose">
    <textarea id="da-chat-input" rows="2" placeholder="Ask about this report…"></textarea>
    <button id="da-chat-send" type="button">Send</button>
    <button id="da-chat-stop" type="button" hidden>Stop</button>
  </div>
  <div class="da-chat-foot" id="da-chat-foot"><span>__CHAT_FOOT__</span>
    <button id="da-chat-forget" type="button" title="Remove the API key stored in this browser tab">Forget key</button></div>
</section>
"""

_CHAT_CSS = """
/* ---- In-report Q&A assistant ---- */
#da-chat-fab{
  position:fixed; right:22px; bottom:22px; z-index:60;
  background:var(--accent); color:#fff; border:none; border-radius:999px;
  padding:12px 18px; font-size:14px; font-weight:600; cursor:pointer;
  box-shadow:0 4px 16px rgba(31,60,120,.28);
}
#da-chat-fab:hover{filter:brightness(1.08)}
#da-chat-panel{
  position:fixed; right:22px; bottom:22px; z-index:61;
  width:430px; max-width:calc(100vw - 44px); height:72vh; min-height:420px;
  display:flex; flex-direction:column; background:var(--panel);
  border:1px solid var(--line); border-radius:14px; overflow:hidden;
  box-shadow:0 12px 40px rgba(15,25,45,.25);
}
#da-chat-panel[hidden]{display:none}
.da-chat-head{
  display:flex; align-items:center; gap:8px; padding:10px 12px;
  border-bottom:1px solid var(--line); background:#fbfcfe;
}
.da-chat-title{font-weight:700; font-size:14px}
.da-chat-model{
  font-size:11px; color:var(--muted); flex:1 1 auto; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap;
}
#da-chat-close{
  border:none; background:none; font-size:20px; line-height:1; cursor:pointer;
  color:var(--muted); padding:2px 6px;
}
#da-chat-close:hover{color:var(--ink)}
#da-chat-msgs{flex:1 1 auto; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px}
.da-msg{border-radius:10px; padding:9px 12px; font-size:13.5px; line-height:1.5; max-width:100%; overflow-wrap:break-word}
.da-hint{background:var(--accent-soft); color:var(--ink)}
.da-starters{display:flex; flex-wrap:wrap; gap:6px; margin-top:9px}
.da-starters:empty{display:none}
.da-starter{
  text-align:left; border:1px solid var(--accent); background:#fff; color:var(--accent);
  border-radius:999px; padding:5px 11px; font:12.5px/1.35 inherit; font-family:inherit;
  cursor:pointer; max-width:100%; overflow-wrap:break-word;
}
.da-starter:hover{background:var(--accent); color:#fff}
.da-starter:disabled{opacity:.5; cursor:default}
.da-user{background:var(--accent); color:#fff; align-self:flex-end; max-width:88%; white-space:pre-wrap}
.da-ai{background:#f4f6fa; border:1px solid var(--line); align-self:stretch}
.da-err{background:var(--conflict-soft); border:1px solid var(--conflict); color:#8d2020}
.da-note{color:var(--muted); font-size:12px; font-style:italic; margin-top:6px}
.da-think{margin:2px 0 8px; font-size:12px}
.da-think summary{cursor:pointer; color:var(--muted)}
.da-think-body{
  color:var(--muted); white-space:pre-wrap; border-left:2px solid var(--line);
  padding:4px 10px; margin-top:4px; max-height:180px; overflow-y:auto;
}
.da-tool{
  display:flex; align-items:center; gap:7px; font-size:12px; color:var(--muted);
  background:#eef1f6; border-radius:7px; padding:5px 9px; margin:5px 0;
}
.da-tool.da-tool-done{color:#3c4655}
.da-tool.da-tool-err{background:var(--conflict-soft); color:#8d2020}
.da-cites{margin-left:2px}
.da-cites a{
  font-size:10px; background:var(--accent-soft); border-radius:4px; padding:1px 4px;
  margin-left:2px; vertical-align:super;
}
/* markdown inside answers reuses .block's look, scoped smaller */
.da-md p{margin:6px 0}
.da-md ul,.da-md ol{margin:6px 0; padding-left:20px}
.da-md li{margin:2px 0}
.da-md h1,.da-md h2,.da-md h3,.da-md h4{margin:8px 0 5px; line-height:1.3; font-size:14px}
.da-md h1{font-size:16px}.da-md h2{font-size:15px}
.da-md code{background:#e8ecf3; padding:1px 4px; border-radius:4px; font-size:.9em;
  font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace}
.da-md pre{background:#0f1622; color:#d6e2f5; padding:10px; border-radius:7px; overflow:auto; font-size:12px}
.da-md pre code{background:none; color:inherit; padding:0}
.da-md table{border-collapse:collapse; width:100%; margin:8px 0; font-size:12.5px}
.da-md th,.da-md td{border:1px solid var(--line); padding:4px 7px; text-align:left; vertical-align:top}
.da-md th{background:#f3f5f9; font-weight:600}
.da-md blockquote{margin:6px 0; padding:4px 10px; border-left:3px solid var(--line); color:var(--muted)}
.da-md a{text-decoration:underline}
.da-chat-compose{
  display:flex; gap:8px; padding:10px 12px; border-top:1px solid var(--line);
  background:#fbfcfe; align-items:flex-end;
}
#da-chat-input{
  flex:1 1 auto; resize:none; border:1px solid var(--line); border-radius:8px;
  padding:8px 10px; font:13.5px/1.4 inherit; color:var(--ink); background:#fff;
  font-family:inherit;
}
#da-chat-input:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft)}
#da-chat-send,#da-chat-stop{
  border:none; border-radius:8px; padding:9px 15px; font-size:13px; font-weight:600;
  cursor:pointer; color:#fff; background:var(--accent);
}
#da-chat-send:disabled{opacity:.5; cursor:default}
#da-chat-stop{background:var(--conflict)}
.da-chat-foot{
  font-size:10.5px; color:var(--muted); padding:6px 12px 9px; background:#fbfcfe;
  border-top:1px solid var(--line);
}
.da-key-warn{color:var(--conflict); font-weight:700}
#da-chat-forget{
  border:1px solid var(--line); background:#fff; color:var(--muted);
  font-size:10px; border-radius:6px; padding:2px 7px; margin-left:6px;
  cursor:pointer; vertical-align:baseline; white-space:nowrap;
}
#da-chat-forget:hover{color:var(--conflict); border-color:var(--conflict)}
/* ---- reader-supplied API-key entry ---- */
#da-chat-key{
  padding:9px 12px; border-top:1px solid var(--line); background:#fbfcfe;
  display:flex; flex-direction:column; gap:6px;
}
#da-chat-key[hidden],#da-chat-key-form[hidden],#da-chat-key-set[hidden]{display:none}
.da-key-row{display:flex; gap:6px; align-items:center}
#da-chat-key-input{
  flex:1 1 auto; min-width:0; border:1px solid var(--line); border-radius:8px;
  padding:7px 10px; font-size:13px; font-family:inherit; background:#fff; color:var(--ink);
}
#da-chat-key-input:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft)}
#da-chat-key-toggle,#da-chat-key-change{white-space:nowrap; flex:0 0 auto}
#da-chat-key-save{
  border:none; border-radius:8px; padding:7px 13px; font-size:12.5px; font-weight:600;
  cursor:pointer; color:#fff; background:var(--accent); white-space:nowrap; flex:0 0 auto;
}
#da-chat-key-save:hover{filter:brightness(1.08)}
#da-chat-key-set{display:flex; align-items:center; gap:8px}
.da-key-set-label{font-size:12px; color:var(--muted); flex:1 1 auto}
.da-key-status{font-size:11px; color:var(--muted); line-height:1.4}
.da-key-status:empty{display:none}
/* ---- resize handles + drag ---- */
.da-rz{position:absolute; z-index:3; touch-action:none}
.da-rz-t{top:0; left:8px; right:8px; height:6px; cursor:ns-resize}
.da-rz-b{bottom:0; left:8px; right:8px; height:6px; cursor:ns-resize}
.da-rz-l{left:0; top:8px; bottom:8px; width:6px; cursor:ew-resize}
.da-rz-r{right:0; top:8px; bottom:8px; width:6px; cursor:ew-resize}
.da-rz-tl{top:0; left:0; width:14px; height:14px; cursor:nwse-resize; z-index:4}
.da-rz-br{bottom:0; right:0; width:14px; height:14px; cursor:nwse-resize; z-index:4}
.da-rz-tr{top:0; right:0; width:14px; height:14px; cursor:nesw-resize; z-index:4}
.da-rz-bl{bottom:0; left:0; width:14px; height:14px; cursor:nesw-resize; z-index:4}
.da-chat-head{cursor:grab}
body.da-dragging, body.da-dragging *{user-select:none !important}
/* ---- highlight-to-ask: selection popover + pending-excerpt chip ---- */
#da-sel-pop{
  position:fixed; z-index:62; background:var(--accent); color:#fff; border:none;
  border-radius:8px; padding:6px 12px; font-size:12.5px; font-weight:600; cursor:pointer;
  box-shadow:0 4px 14px rgba(31,60,120,.3);
}
#da-sel-pop:hover{filter:brightness(1.08)}
#da-sel-chip{
  display:flex; align-items:center; gap:8px; margin:0 12px; padding:6px 10px;
  background:var(--accent-soft); border:1px solid var(--line); border-radius:8px;
  font-size:12px; color:var(--ink);
}
.da-sel-chip-text{flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.da-sel-chip-x{
  border:none; background:none; cursor:pointer; font-size:16px; line-height:1;
  color:var(--muted); padding:0 2px;
}
.da-sel-chip-x:hover{color:var(--conflict)}
.da-userctx{margin-top:6px; font-size:12px}
.da-userctx summary{cursor:pointer; opacity:.85}
.da-userctx div{white-space:pre-wrap; margin-top:4px; opacity:.9; max-height:160px; overflow-y:auto}
::highlight(da-sel){background-color:#ffe9a8; color:inherit}
::highlight(da-term){background-color:#bfe3ff; color:inherit}
/* ---- report-navigation flash (scroll_to_report / query targets) ---- */
@keyframes daFlash{0%{background:#fff6d6}100%{background:transparent}}
.da-flash{animation:daFlash 1.6s ease-out}
@media (max-width:600px){
  #da-chat-panel{right:0; bottom:0; width:100vw; max-width:100vw; height:92vh; border-radius:14px 14px 0 0}
  .da-rz{display:none}
}
#da-chat-print-head{display:none}
@media print{
  #da-chat-fab,#da-chat-panel{display:none !important}
  /* ---- Ask AI transcript export (Save as PDF → browser print dialog) ---- */
  body.da-print-chat > *:not(#da-chat-panel){display:none !important}
  body.da-print-chat #da-chat-panel{
    display:block !important; position:static !important; z-index:auto !important;
    width:auto !important; max-width:none !important; height:auto !important;
    min-height:0 !important; border:none !important; box-shadow:none !important;
    border-radius:0 !important;
  }
  body.da-print-chat .da-rz{display:none !important}
  body.da-print-chat #da-chat-export,
  body.da-print-chat #da-chat-clear,
  body.da-print-chat #da-chat-close,
  body.da-print-chat #da-chat-forget,
  body.da-print-chat #da-chat-key,
  body.da-print-chat .da-chat-compose{display:none !important}
  body.da-print-chat .da-chat-head{cursor:default}
  body.da-print-chat #da-chat-print-head{
    display:block; font-size:11px; color:#555; padding:0 0 10px; margin-bottom:8px;
    border-bottom:1px solid #ccc;
  }
  body.da-print-chat #da-chat-msgs{
    display:block !important; overflow:visible !important; height:auto !important; padding:0;
  }
  body.da-print-chat .da-msg{page-break-inside:avoid; max-width:100% !important; margin-bottom:8px}
  body.da-print-chat .da-user{background:#eef2fb !important; color:#000 !important}
  body.da-print-chat .da-ai{background:#fff !important}
  body.da-print-chat .da-chat-foot{display:none !important}
}
"""

_CHAT_JS = r"""
(function(){
  'use strict';
  var cfgEl = document.getElementById('da-chat-config');
  if(!cfgEl) return;
  var CFG;
  try { CFG = JSON.parse(cfgEl.textContent); } catch(e){ return; }
  if(!CFG) return;

  var API_URL = 'https://api.anthropic.com/v1/messages';
  var MAX_CONTINUATIONS = 8;   // pause_turn auto-resumes (server tool loops)
  var MAX_TOOL_ROUNDS = 10;    // client tool_use rounds before forced text close
  var rawEl = document.getElementById('raw-md');
  var REPORT = rawEl ? rawEl.textContent : '';
  var KEY_STORE = 'da-api-key';

  // Key resolution: an embedded key (opt-in) wins; otherwise the reader enters
  // one in the in-panel field (renderKeyUi / revealKeyForm / saveKeyFromInput,
  // below) and the value is kept only in this tab's sessionStorage — never
  // written back into the file and never persisted to disk (no localStorage).
  // ensureKey() is a pure lookup now (no window.prompt); a missing key surfaces
  // the field. forgetKey() drops a stored/rejected key (but keeps an embedded
  // one) and re-opens the field.
  function storedKey(){
    try { var k = sessionStorage.getItem(KEY_STORE); return (k && k.trim()) ? k.trim() : null; }
    catch(e){ return null; }
  }
  var apiKey = (CFG.apiKey || '').trim() || null;
  function haveKey(){ return !!(apiKey || storedKey()); }
  function ensureKey(){
    if(apiKey) return apiKey;
    var k = storedKey();
    if(k){ apiKey = k; return apiKey; }
    return null;
  }
  function forgetKey(){
    if(CFG.apiKey){ apiKey = CFG.apiKey.trim() || null; return; }
    apiKey = null;
    try { sessionStorage.removeItem(KEY_STORE); } catch(e){}
    renderKeyUi();
  }

  // ----------------------------------------------------------- secret hygiene
  // Displayed errors can echo request/response fragments; make sure key
  // material never lands in the DOM even then.
  function scrubSecrets(s){
    return String(s == null ? '' : s).replace(/sk-ant-[\w-]+/g, 'sk-ant-[redacted]');
  }

  // ---------------------------------------------------------------- markdown
  // Safe-DOM renderer (Phase 17, DA-011). The assistant's output is untrusted:
  // drawing content feeds the prompts, so model text can be attacker-
  // influenced. Nothing model-controlled is ever parsed as HTML — every node
  // is built with createElement and filled through textContent, and the ONLY
  // way a link is created is the single URL validator below. Covers the same
  // small subset as before: headings, hr, blockquotes, pipe tables, fenced
  // code, nested lists, bold/italic/code spans, and [text](url) links.

  // Sole URL policy (markdown links AND citation chips): absolute https only;
  // rejects credentials, control chars / whitespace (raw or %-encoded), and any
  // relative/protocol-relative (URL() throws without a base). javascript:,
  // data:, file:, and blob: all fail the protocol check.
  function safeUrl(candidate){
    if(typeof candidate !== 'string' || /[\u0000-\u0020\u007f]/.test(candidate)) return null;
    var u;
    try { u = new URL(candidate); } catch(e){ return null; }
    if(u.protocol !== 'https:') return null;
    if(u.username || u.password) return null;
    if(/%(0[0-9a-fA-F]|1[0-9a-fA-F]|7[fF])/.test(u.href)) return null;
    return u.href;
  }
  // The only anchor factory: DOM-property assignment (never attribute
  // strings), label as textContent, rel=noopener noreferrer. Returns null for
  // any URL the policy rejects so callers degrade to inert text.
  function linkEl(url, label, title){
    var safe = safeUrl(url);
    if(!safe) return null;
    var a = document.createElement('a');
    a.href = safe;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = label;
    if(title) a.title = title;
    return a;
  }

  var CODE_RE = /`([^`]+)`/;
  var LINK_RE = /\[([^\]]+)\]\(([^\s)]+)\)/;
  var BOLD_RE = /\*\*(.+?)\*\*/;
  var EM_RE = /(^|[^\w*])\*([^\s*](?:[^*]*[^\s*])?)\*(?![\w*])/;

  function appendText(parent, s){
    if(s) parent.appendChild(document.createTextNode(s));
  }
  function appendEm(parent, s){
    var m;
    while((m = s.match(EM_RE))){
      appendText(parent, s.slice(0, m.index) + m[1]);
      var em = document.createElement('em');
      em.textContent = m[2];
      parent.appendChild(em);
      s = s.slice(m.index + m[0].length);
    }
    appendText(parent, s);
  }
  function appendBold(parent, s){
    var m;
    while((m = s.match(BOLD_RE))){
      appendEm(parent, s.slice(0, m.index));
      var b = document.createElement('strong');
      appendEm(b, m[1]);
      parent.appendChild(b);
      s = s.slice(m.index + m[0].length);
    }
    appendEm(parent, s);
  }
  function appendLinks(parent, s){
    var m;
    while((m = s.match(LINK_RE))){
      appendBold(parent, s.slice(0, m.index));
      var a = linkEl(m[2], m[1]);
      // A rejected URL (non-https, credentials, controls) degrades to the raw
      // markdown as visible inert text — never a live link, never markup.
      if(a) parent.appendChild(a);
      else appendText(parent, m[0]);
      s = s.slice(m.index + m[0].length);
    }
    appendBold(parent, s);
  }
  function appendInline(parent, s){
    var m;
    while((m = s.match(CODE_RE))){
      appendLinks(parent, s.slice(0, m.index));
      var code = document.createElement('code');
      code.textContent = m[1];   // attack strings inside backticks stay inert
      parent.appendChild(code);
      s = s.slice(m.index + m[0].length);
    }
    appendLinks(parent, s);
  }

  var HR_RE = /^\s*([-*_])(?:\s*\1){2,}\s*$/;
  var LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  var TABLE_SEP_RE = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$/;
  function isBlockStart(lines, i){
    var line = lines[i], st = line.trim();
    if(st.indexOf('```') === 0 || st.charAt(0) === '>') return true;
    if(HR_RE.test(line) || /^#{1,6}\s+/.test(st) || LIST_RE.test(line)) return true;
    return line.indexOf('|') !== -1 && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1]);
  }
  function child(parent, tag){
    var node = document.createElement(tag);
    parent.appendChild(node);
    return node;
  }
  function renderMdInto(container, md, depth){
    depth = depth || 0;
    if(!md || !md.trim()) return;
    var lines = md.replace(/\r\n?/g, '\n').split('\n');
    var i = 0, n = lines.length;
    while(i < n){
      var line = lines[i], st = line.trim();
      if(!st){ i++; continue; }
      if(st.indexOf('```') === 0){
        var body = []; i++;
        while(i < n && lines[i].trim().indexOf('```') !== 0){ body.push(lines[i]); i++; }
        if(i < n) i++;
        child(child(container, 'pre'), 'code').textContent = body.join('\n');
        continue;
      }
      if(HR_RE.test(line)){ child(container, 'hr'); i++; continue; }
      var h = st.match(/^(#{1,6})\s+(.*)$/);
      if(h){
        var lvl = Math.min(h[1].length + 2, 6); // demote: h1 -> h3 inside a bubble
        appendInline(child(container, 'h' + lvl), h[2].trim());
        i++; continue;
      }
      if(st.charAt(0) === '>' && depth < 3){
        var quote = [];
        while(i < n && lines[i].trim().charAt(0) === '>'){
          quote.push(lines[i].replace(/^\s*>\s?/, '')); i++;
        }
        renderMdInto(child(container, 'blockquote'), quote.join('\n'), depth + 1);
        continue;
      }
      if(line.indexOf('|') !== -1 && i + 1 < n && TABLE_SEP_RE.test(lines[i + 1])){
        var cells = function(row){
          return row.trim().replace(/^\||\|$/g, '').split('|').map(function(c){ return c.trim(); });
        };
        var table = child(container, 'table');
        var headRow = child(child(table, 'thead'), 'tr');
        cells(line).forEach(function(c){ appendInline(child(headRow, 'th'), c); });
        var tbody = child(table, 'tbody');
        i += 2;
        while(i < n && lines[i].indexOf('|') !== -1 && lines[i].trim()){
          var tr = child(tbody, 'tr');
          cells(lines[i]).forEach(function(c){ appendInline(child(tr, 'td'), c); });
          i++;
        }
        continue;
      }
      if(LIST_RE.test(line)){
        // Stack-based nesting (port of the Python renderer's loss-proof list
        // builder): a between-levels dedent attaches to the nearest enclosing
        // list rather than dropping the item.
        var stack = [];   // {indent, listEl} of each currently-open list
        while(i < n){
          var m = lines[i].match(LIST_RE);
          if(!m) break;
          var indent = m[1].replace(/\t/g, '    ').length;
          var tag = (m[2] === '-' || m[2] === '*' || m[2] === '+') ? 'ul' : 'ol';
          while(stack.length && indent < stack[stack.length - 1].indent) stack.pop();
          if(!stack.length || indent > stack[stack.length - 1].indent){
            var host = container;
            if(stack.length){
              var parentList = stack[stack.length - 1].listEl;
              host = parentList.lastElementChild || parentList;
            }
            stack.push({indent: indent, listEl: child(host, tag)});
          }
          appendInline(child(stack[stack.length - 1].listEl, 'li'), m[3]);
          i++;
        }
        continue;
      }
      var para = [];
      while(i < n && lines[i].trim() && !isBlockStart(lines, i)){
        para.push(lines[i].trim()); i++;
      }
      var p = child(container, 'p');
      para.forEach(function(text, k){
        if(k) child(p, 'br');
        appendInline(p, text);
      });
    }
  }
  // Re-render `md` into `target`, replacing previous content. The streaming
  // path calls this repeatedly; the final render happens at block stop.
  function renderMdReplace(target, md){
    while(target.firstChild) target.removeChild(target.firstChild);
    renderMdInto(target, md, 0);
  }

  // ------------------------------------------------------------------ request
  function systemBlocks(){
    var preamble =
      'You are the built-in Q&A assistant of a Drawing Analyzer report — an ' +
      'AI-generated analysis of a set of construction drawings.\n\n' +
      'Report: ' + CFG.title + '\nGenerated: ' + CFG.generated +
      '\nSource file(s): ' + (CFG.sources && CFG.sources.length ? CFG.sources.join(', ') : '(unknown)') +
      '\n\nThe next system block is the complete report text, verbatim. Ground your answers in it:\n' +
      '- Answer from the report first, and name the sheet labels / section headers you used ' +
      '(e.g. "M-501", "Coordination items") so the reader can find them in the page above this chat.\n' +
      '- You can see only this report, not the drawings themselves. If the report does not contain ' +
      'the answer, say so plainly — never invent drawing content.\n' +
      '- Use web_search / web_fetch for outside knowledge (codes, standards, manufacturer or product ' +
      'data, definitions) or when the user asks you to — not for questions the report already answers.\n' +
      '- Write for a construction / MEP engineering reader: concise, specific, markdown formatting, ' +
      'tables for enumerable facts.';
    return [
      {type: 'text', text: preamble},
      // The report is byte-identical on every request, so this breakpoint lets
      // every question after the first read it from the prompt cache.
      {type: 'text',
       text: '=== FULL REPORT (verbatim) ===\n\n' + (REPORT || '(no report text was embedded)'),
       cache_control: {type: 'ephemeral'}}
    ];
  }
  var history = [];   // alternating {role, content}; assistant content = raw API blocks

  // Custom tools are executed *in this browser* by the dispatch table below
  // (unlike web_search/web_fetch, which are Anthropic server tools). When
  // noTools is set — the final forced-closure turn once the tool-round budget
  // is spent — every tool is withdrawn and tool_choice:'none' makes the model
  // answer in text, so a run can never end on a dangling tool_use.
  function buildRequest(noTools){
    var req = {
      model: CFG.model,
      max_tokens: 16000,
      system: systemBlocks(),
      thinking: {type: 'adaptive', display: 'summarized'},
      messages: history,
      stream: true
    };
    if(noTools){ req.tool_choice = {type: 'none'}; return req; }
    req.tools = [
      {type: 'web_search_20260209', name: 'web_search', max_uses: 15},
      {type: 'web_fetch_20260209', name: 'web_fetch', max_uses: 15},
      {name: 'scroll_to_report',
       description: 'Scroll the on-page report to a section, sheet, or QC finding and briefly ' +
         'highlight it for the reader. Use this to point the user at something specific in the ' +
         'report they are looking at.',
       input_schema: {type: 'object', properties: {
         target: {type: 'string', description: 'A card id ("overview", "findings", "focus", ' +
           'or "sheet-3"), a sheet label ("M-501"), or a QC finding id ("QC-014").'}
       }, required: ['target']}},
      {name: 'query_findings',
       description: 'Search the structured QC findings ledger — the machine-checked findings ' +
         'with their id, sheet, category, severity, status (VERIFIED/DETERMINISTIC/UNCERTAIN/' +
         'UNANCHORED/REJECTED) and source quote. A cross-sheet finding also carries "also_on" ' +
         '(the other sheet ids it spans); a code finding may carry "refs" (the cited section ' +
         'numbers) and "citation" (the web-search check status/verdict). The prose report does ' +
         'NOT contain this structured data, so use this for questions about specific findings, ' +
         'which issues span multiple sheets, whether cited code sections check out, their status, ' +
         'severities, or counts. Filter by any combination of fields; omit all to list every finding.',
       input_schema: {type: 'object', properties: {
         category: {type: 'string'},
         severity: {type: 'string', enum: ['high', 'medium', 'low']},
         status: {type: 'string', description: 'e.g. VERIFIED, UNANCHORED, REJECTED (substring match).'},
         sheet: {type: 'string', description: 'Sheet label substring, e.g. "M-501".'},
         text: {type: 'string', description: 'Substring to match in the finding text or quote.'},
         limit: {type: 'integer', description: 'Max findings to return (default 50, cap 100).'}
       }}},
      {name: 'filter_report',
       description: 'Change what the report shows on the page by driving its search box, the ' +
         'exclusive category filter chips, and the "High severity only" toggle. Use to focus the ' +
         "reader's view (e.g. show only conflicts, or search a term). Returns the resulting count.",
       input_schema: {type: 'object', properties: {
         search: {type: 'string', description: 'Text to type into the report search box ("" clears it).'},
         category: {type: 'string', description: 'One of: all, issues, conflict, coordination, ' +
           'equipment, dimensions, notes, scope, focus (only categories that exist in this report).'},
         high_only: {type: 'boolean', description: 'Set the "High severity only" toggle.'}
       }}},
      {name: 'get_report_summary',
       description: 'Get run-level metadata the prose does not state: sheets analyzed vs failed, ' +
         'QC and coverage status, token usage, estimated cost, source files, and finding counts ' +
         'by severity and status. Takes no arguments.',
       input_schema: {type: 'object', properties: {}}},
      {name: 'highlight_term',
       description: 'Visually highlight every occurrence of a term across the whole report on the ' +
         'page so the reader can see where it appears. Returns how many matches were highlighted. ' +
         'Call with an empty term to clear the highlight.',
       input_schema: {type: 'object', properties: {
         term: {type: 'string', description: 'The text to highlight everywhere in the report.'}
       }, required: ['term']}},
      {name: 'calculate',
       description: 'Evaluate an exact arithmetic expression (+, -, *, /, parentheses, decimals). ' +
         'Use this for ANY calculation instead of computing in your head, so the arithmetic is ' +
         'guaranteed correct. Example: "(12.5 + 3.25) * 2".',
       input_schema: {type: 'object', properties: {
         expression: {type: 'string', description: 'The arithmetic expression to evaluate.'}
       }, required: ['expression']}}
    ];
    return req;
  }

  // ------------------------------------------------------ client-side tools
  // These run IN THIS BROWSER (unlike the server web_search/web_fetch): each
  // reads or drives the report DOM / the inert #da-findings & #da-summary data
  // blocks and returns a short text result. No network, no eval. runTool always
  // returns a tool_result (is_error on failure) so no tool_use id is left
  // unanswered.
  var TOOL_LABEL = {
    scroll_to_report: '⚙ Navigating the report…',
    query_findings: '⚙ Looking up findings…',
    filter_report: '⚙ Filtering the report…',
    get_report_summary: '⚙ Reading the run summary…',
    highlight_term: '⚙ Highlighting…',
    calculate: '⚙ Calculating…'
  };
  function readJsonBlock(id){
    var el = document.getElementById(id);
    if(!el) return null;
    try { return JSON.parse(el.textContent); } catch(e){ return null; }
  }
  var FINDINGS = readJsonBlock('da-findings') || [];
  var SUMMARY = readJsonBlock('da-summary');
  var reportContent = document.querySelector('main.content');

  function flash(el){
    if(!el) return;
    el.classList.remove('da-flash');   // restart the animation if re-fired
    void el.offsetWidth;
    el.classList.add('da-flash');
    setTimeout(function(){ el.classList.remove('da-flash'); }, 1700);
  }
  function expandCard(card){
    if(!card) return;
    card.classList.remove('collapsed');
    card.classList.remove('hidden');
    var h = card.querySelector('.card-head');
    if(h) h.setAttribute('aria-expanded', 'true');
  }

  function toolScroll(input){
    var target = String((input && input.target) || '').trim();
    if(!target) return 'No target was given.';
    var el = /^(overview|findings|focus|sheet-\d+)$/.test(target)
      ? document.getElementById(target) : null;
    var qc = (target.match(/QC[-\s]?\d+/i) || [null])[0];
    if(!el && qc){
      qc = qc.toUpperCase().replace(/\s+/, '-');
      var rows = Array.prototype.slice.call(document.querySelectorAll('.finding-row'));
      for(var i = 0; i < rows.length; i++){
        var c = rows[i].querySelector('.fcol-qcid');
        if(c && c.textContent.trim().toUpperCase() === qc){ el = rows[i]; break; }
      }
      if(el){ expandCard(document.getElementById('findings')); }
    }
    if(!el){
      var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
      for(var j = 0; j < cards.length; j++){
        var t = cards[j].querySelector('.card-title');
        if(t && t.textContent.toLowerCase().indexOf(target.toLowerCase()) !== -1){ el = cards[j]; break; }
      }
    }
    if(!el) return 'No matching section, sheet, or finding for "' + target + '".';
    var card = el.closest ? el.closest('.card') : null;
    // Capture the pre-reveal hidden state (of the target and its card) before we
    // clear it, so the returned message is truthful.
    var wasHidden = !!(card && card.classList.contains('hidden')) || el.classList.contains('hidden');
    expandCard(card || el);
    el.classList.remove('hidden');
    if(card && el === card){
      // A search/category filter also hides the card's inner blocks — reveal
      // them so a card-level jump doesn't land on a visible-but-empty card.
      Array.prototype.slice.call(card.querySelectorAll('.block.hidden'))
        .forEach(function(n){ n.classList.remove('hidden'); });
    }
    el.scrollIntoView({behavior: 'smooth', block: 'start'});
    flash(el);
    return 'Scrolled the report to "' + target + '".' +
      (wasHidden ? ' (It was hidden by an active filter; I revealed it.)' : '');
  }

  function toolQuery(input){
    input = input || {};
    function lc(s){ return String(s == null ? '' : s).toLowerCase(); }
    var out = FINDINGS.filter(function(f){
      if(input.category && lc(f.category) !== lc(input.category)) return false;
      if(input.severity && lc(f.severity) !== lc(input.severity)) return false;
      if(input.status && lc(f.status).indexOf(lc(input.status)) === -1) return false;
      if(input.sheet && lc(f.sheet).indexOf(lc(input.sheet)) === -1) return false;
      if(input.text && (lc(f.text) + ' ' + lc(f.quote)).indexOf(lc(input.text)) === -1) return false;
      return true;
    });
    var cap = Math.max(1, Math.min(input.limit || 50, 100));
    return JSON.stringify({total: out.length, returned: Math.min(out.length, cap),
      findings: out.slice(0, cap)});
  }

  function toolFilter(input){
    input = input || {};
    var acted = [];
    if(typeof input.search === 'string'){
      var s = document.getElementById('search');
      if(s){
        s.value = input.search;
        s.dispatchEvent(new Event('input', {bubbles: true}));
        acted.push('search="' + input.search + '"');
      }
    }
    if(input.category){
      var cat = String(input.category).toLowerCase().replace(/["\\\]]/g, '');
      var chip = document.querySelector('.chip[data-filter="' + cat + '"]');
      if(chip){ chip.click(); acted.push('category=' + cat); }
      else {
        var avail = Array.prototype.slice.call(document.querySelectorAll('.chip[data-filter]'))
          .map(function(c){ return c.getAttribute('data-filter'); }).join(', ');
        return 'This report has no "' + input.category + '" filter. Available: ' + avail + '.';
      }
    }
    if(input.high_only !== undefined){
      var sev = document.getElementById('sev-high');
      if(sev){
        var on = sev.classList.contains('chip-active');
        if(!!input.high_only !== on) sev.click();
        acted.push('high_only=' + (!!input.high_only));
      }
    }
    if(!acted.length) return 'No filter change was requested.';
    // The report debounces apply() ~90ms after a synthetic search 'input' (chip
    // and severity clicks apply synchronously), so wait it out before reading
    // #result-count — otherwise the model gets the pre-filter count.
    var searched = typeof input.search === 'string';
    return new Promise(function(resolve){
      setTimeout(function(){
        var rc = document.getElementById('result-count');
        resolve('Applied filter (' + acted.join(', ') + ').' +
          (rc && rc.textContent ? ' Now showing: ' + rc.textContent + '.' : ''));
      }, searched ? 130 : 0);
    });
  }

  function toolSummary(){
    var s = SUMMARY || {};
    var bySev = {}, byStatus = {};
    FINDINGS.forEach(function(f){
      var sv = f.severity || 'none'; bySev[sv] = (bySev[sv] || 0) + 1;
      var stt = f.status || 'UNKNOWN'; byStatus[stt] = (byStatus[stt] || 0) + 1;
    });
    return JSON.stringify({
      generated: s.generated, sheets: s.sheets, qc_status: s.qc_status,
      coverage_status: s.coverage_status, tokens: s.tokens,
      estimated_cost_usd: s.estimated_cost_usd, run_errors: s.errors,
      sources: s.sources, findings_total: FINDINGS.length,
      findings_by_severity: bySev, findings_by_status: byStatus
    });
  }

  function clearTermHighlight(){
    try { if(window.CSS && CSS.highlights) CSS.highlights.delete('da-term'); } catch(e){}
  }
  function toolHighlightTerm(input){
    var term = String((input && input.term) || '').trim();
    clearTermHighlight();
    if(!term) return 'Cleared the term highlight.';
    if(!reportContent) return 'There is no report content to search.';
    if(!(window.Highlight && window.CSS && CSS.highlights)){
      return 'This browser cannot paint highlights, but "' + term + '" can still be searched manually.';
    }
    var needle = term.toLowerCase(), ranges = [], CAP = 5000;
    var walker = document.createTreeWalker(reportContent, NodeFilter.SHOW_TEXT, null);
    var node;
    while((node = walker.nextNode())){
      var hay = node.nodeValue.toLowerCase(), from = 0, at;
      while((at = hay.indexOf(needle, from)) !== -1){
        var r = document.createRange();
        r.setStart(node, at); r.setEnd(node, at + needle.length);
        ranges.push(r); from = at + needle.length;
        if(ranges.length >= CAP) break;
      }
      if(ranges.length >= CAP) break;
    }
    if(!ranges.length) return 'No occurrences of "' + term + '" were found in the report.';
    try {
      var hl = new Highlight();
      ranges.forEach(function(rg){ hl.add(rg); });
      CSS.highlights.set('da-term', hl);
    } catch(e){ return ranges.length + ' occurrence(s) found, but the highlight paint failed.'; }
    return 'Highlighted ' + ranges.length + ' occurrence(s) of "' + term + '" in the report.';
  }

  // A tiny SAFE arithmetic evaluator (recursive descent) — never eval/Function.
  // Grammar: expr = term (('+'|'-') term)*; term = factor (('*'|'/') factor)*;
  //          factor = ('+'|'-') factor | '(' expr ')' | number
  function evalArith(src){
    var s = String(src).replace(/\s+/g, '');
    if(s === '') throw new Error('empty expression');
    if(!/^[0-9.eE+\-*/()]+$/.test(s)) throw new Error('only numbers and + - * / ( ) are allowed');
    var pos = 0;
    function expr(){
      var v = term();
      while(pos < s.length && (s[pos] === '+' || s[pos] === '-')){
        var op = s[pos++]; var rhs = term();
        v = op === '+' ? v + rhs : v - rhs;
      }
      return v;
    }
    function term(){
      var v = factor();
      while(pos < s.length && (s[pos] === '*' || s[pos] === '/')){
        var op = s[pos++]; var rhs = factor();
        v = op === '*' ? v * rhs : v / rhs;
      }
      return v;
    }
    function factor(){
      if(pos >= s.length) throw new Error('unexpected end of expression');
      var ch = s[pos];
      if(ch === '+'){ pos++; return factor(); }
      if(ch === '-'){ pos++; return -factor(); }
      if(ch === '('){
        pos++; var v = expr();
        if(s[pos] !== ')') throw new Error('missing ")"');
        pos++; return v;
      }
      return number();
    }
    function number(){
      var start = pos;
      while(pos < s.length){
        var c = s[pos];
        if((c === 'e' || c === 'E') && (s[pos + 1] === '+' || s[pos + 1] === '-')){ pos += 2; continue; }
        if(/[0-9.eE]/.test(c)){ pos++; continue; }
        break;
      }
      var num = s.slice(start, pos);
      var n = parseFloat(num);
      if(isNaN(n)) throw new Error('invalid number "' + num + '"');
      return n;
    }
    var result = expr();
    if(pos !== s.length) throw new Error('unexpected "' + s[pos] + '"');
    return result;
  }
  function toolCalculate(input){
    var e = String((input && input.expression) || '').trim();
    if(!e) return 'No expression was given.';
    try {
      var result = evalArith(e);
      if(!isFinite(result)) return 'The expression "' + e + '" does not evaluate to a finite number.';
      // Trim float64 rounding noise (e.g. 0.1+0.2) WITHOUT corrupting exactly
      // representable integers: every integer below 1e15 has ≤15 significant
      // digits, so toPrecision(15) preserves it while dropping the tail noise
      // that only appears past the 15th digit.
      var out = (Math.abs(result) < 1e15) ? parseFloat(result.toPrecision(15)) : result;
      return e + ' = ' + out;
    } catch(err){
      return 'Could not evaluate "' + e + '": ' + (err && err.message || 'invalid expression') + '.';
    }
  }

  var TOOLS = {
    scroll_to_report: toolScroll,
    query_findings: toolQuery,
    filter_report: toolFilter,
    get_report_summary: toolSummary,
    highlight_term: toolHighlightTerm,
    calculate: toolCalculate
  };
  // Always resolves (never rejects) to {content, is_error} — a handler may return
  // a value OR a Promise (filter_report waits out the report's search debounce),
  // and a throw/rejection still yields an is_error tool_result so no tool_use id
  // is ever left unanswered.
  function runTool(name, inp){
    var fn = TOOLS[name];
    if(!fn) return Promise.resolve({content: 'Unknown tool: ' + name, is_error: true});
    return Promise.resolve().then(function(){ return fn(inp); }).then(function(r){
      return {content: (r == null || r === '') ? '(no result)' : String(r), is_error: false};
    }, function(e){
      return {content: 'Tool "' + name + '" failed: ' + (e && e.message || e), is_error: true};
    });
  }
  function markToolChip(st, id, isErr){
    var chip = st.toolChips[id];
    if(chip) chip.className = isErr ? 'da-tool da-tool-err' : 'da-tool da-tool-done';
  }

  // ---------------------------------------------------------------------- UI
  var fab = document.getElementById('da-chat-fab');
  var panel = document.getElementById('da-chat-panel');
  var msgs = document.getElementById('da-chat-msgs');
  var input = document.getElementById('da-chat-input');
  var sendBtn = document.getElementById('da-chat-send');
  var stopBtn = document.getElementById('da-chat-stop');
  var closeBtn = document.getElementById('da-chat-close');
  var clearBtn = document.getElementById('da-chat-clear');
  var exportBtn = document.getElementById('da-chat-export');
  var printHead = document.getElementById('da-chat-print-head');
  var forgetBtn = document.getElementById('da-chat-forget');
  var startersRow = document.getElementById('da-starters-row');
  var keyRow = document.getElementById('da-chat-key');
  var keyForm = document.getElementById('da-chat-key-form');
  var keySet = document.getElementById('da-chat-key-set');
  var keyInput = document.getElementById('da-chat-key-input');
  var keyToggle = document.getElementById('da-chat-key-toggle');
  var keySave = document.getElementById('da-chat-key-save');
  var keyChange = document.getElementById('da-chat-key-change');
  var keyStatus = document.getElementById('da-chat-key-status');
  document.getElementById('da-chat-model').textContent = CFG.model + ' · web search · thinking';

  fab.addEventListener('click', function(){ panel.hidden = false; fab.hidden = true; applyGeom(); input.focus(); });
  closeBtn.addEventListener('click', function(){ panel.hidden = true; fab.hidden = false; });
  clearBtn.addEventListener('click', function(){
    if(aborter) aborter.abort();
    history = [];
    clearPendingSelection();   // drop any pending excerpt + its highlight
    clearTermHighlight();      // and any highlight_term paint
    while(msgs.children.length > 1) msgs.removeChild(msgs.lastChild); // keep the hint
    if(startersRow) startersRow.style.display = '';  // bring the chips back
  });

  // "Save as PDF": the transcript never leaves the browser or touches a server —
  // this reformats the panel for print (see the body.da-print-chat rules) and
  // hands off to the browser's native print dialog, where "Save as PDF" is a
  // print destination. That keeps the CSP untouched (no new script/host) and
  // reuses the already-rendered, already-sanitized message DOM verbatim.
  if(exportBtn) exportBtn.addEventListener('click', function(){
    if(!msgs.querySelector('.da-user, .da-ai')){
      addMsg('da-hint', 'Nothing to export yet — ask a question first.');
      return;
    }
    if(printHead){
      var parts = ['Report Q&A transcript', '"' + CFG.title + '"'];
      if(CFG.generated) parts.push('report generated ' + CFG.generated);
      parts.push('exported ' + new Date().toLocaleString());
      printHead.textContent = parts.join(' — ');
    }
    document.body.classList.add('da-print-chat');
    window.print();
  });
  window.addEventListener('afterprint', function(){
    document.body.classList.remove('da-print-chat');
  });

  // Refresh/close/navigate would silently drop the whole conversation (it
  // lives only in this tab's memory — see `history` below), so warn once
  // there is anything to lose. Browsers ignore custom text here and show
  // their own generic confirmation; that's a platform restriction, not a bug.
  window.addEventListener('beforeunload', function(e){
    if(!msgs.querySelector('.da-user, .da-ai')) return;
    e.preventDefault();
    e.returnValue = '';
  });

  // ------------------------------------------------------- reader key entry UI
  // The reader supplies their own key in the in-panel field (this replaces the
  // old window.prompt). renderKeyUi() settles the row to its resting state; in
  // embedded mode the whole row is hidden — the embedded key is authoritative
  // and mutually exclusive with manual entry (mirrors the CFG.apiKey guards).
  function setKeyStatus(msg){ if(keyStatus) keyStatus.textContent = msg || ''; }
  function renderKeyUi(){
    if(!keyRow) return;
    if(CFG.apiKey){ keyRow.hidden = true; return; }   // embedded: no manual entry
    keyRow.hidden = false;
    var have = haveKey();
    if(keyForm) keyForm.hidden = have;
    if(keySet) keySet.hidden = !have;
  }
  // Force the entry form open (the replacement for window.prompt): used when a
  // send is attempted with no key and when a key is rejected (401).
  function revealKeyForm(reason){
    if(!keyRow || CFG.apiKey) return;
    keyRow.hidden = false;
    if(keySet) keySet.hidden = true;
    if(keyForm) keyForm.hidden = false;
    setKeyStatus(reason || '');
    if(keyInput){ try { keyInput.focus(); } catch(e){} }
  }
  function saveKeyFromInput(){
    if(!keyInput) return;
    var v = (keyInput.value || '').trim();
    if(!v){ setKeyStatus('Enter your Anthropic API key to use the assistant.'); keyInput.focus(); return; }
    apiKey = v;
    try { sessionStorage.setItem(KEY_STORE, v); } catch(e){}
    keyInput.value = '';                        // never keep the secret in the DOM
    if(keyInput.type !== 'password'){           // re-mask if it had been revealed
      keyInput.type = 'password';
      if(keyToggle){ keyToggle.textContent = 'Show'; keyToggle.setAttribute('aria-pressed', 'false'); }
    }
    renderKeyUi();
    setKeyStatus(/^sk-ant-/.test(v)
      ? 'Key saved — kept only in this browser tab (sessionStorage).'
      : 'Key saved. Note: that does not look like an Anthropic key (they usually start with "sk-ant-").');
    if(input){ try { input.focus(); } catch(e){} }
  }
  if(keySave) keySave.addEventListener('click', saveKeyFromInput);
  if(keyInput) keyInput.addEventListener('keydown', function(e){
    if(e.key === 'Enter'){ e.preventDefault(); saveKeyFromInput(); }
  });
  if(keyToggle) keyToggle.addEventListener('click', function(){
    if(!keyInput) return;
    var reveal = keyInput.type === 'password';
    keyInput.type = reveal ? 'text' : 'password';
    keyToggle.textContent = reveal ? 'Hide' : 'Show';
    keyToggle.setAttribute('aria-pressed', reveal ? 'true' : 'false');
    keyInput.focus();
  });
  if(keyChange) keyChange.addEventListener('click', function(){ revealKeyForm(''); });
  renderKeyUi();

  // "Forget key": clears BOTH the in-memory copy and the tab's sessionStorage,
  // then re-opens the entry field. In embedded mode there is nothing a runtime
  // action can truthfully delete — the credential is part of the HTML file — so
  // say exactly that instead of pretending.
  if(forgetBtn) forgetBtn.addEventListener('click', function(){
    if(CFG.apiKey){
      addMsg('da-err',
        'This report was generated with the API key embedded in the HTML file itself. ' +
        'A runtime clear cannot remove it from the file — regenerate the report without ' +
        'the embed option (or delete this file) to withdraw the credential.');
      return;
    }
    forgetKey();                                // drops memory + sessionStorage, re-opens the field
    setKeyStatus('Key removed from this tab. Enter a key above to ask another question.');
    addMsg('da-hint', 'API key forgotten — removed from this browser tab (memory and sessionStorage). ' +
      'Enter a key in the field above to ask another question.');
  });

  function nearBottom(){ return msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 60; }
  function scrollDown(force){ if(force || nearBottom()) msgs.scrollTop = msgs.scrollHeight; }
  function addMsg(cls, text){
    var div = document.createElement('div');
    div.className = 'da-msg ' + cls;
    if(text !== undefined) div.textContent = text;
    msgs.appendChild(div);
    scrollDown(true);
    return div;
  }
  function note(parent, text){
    var d = document.createElement('div');
    d.className = 'da-note';
    d.textContent = text;
    parent.appendChild(d);
    scrollDown();
  }

  // ------------------------------------------------------------- SSE plumbing
  function sseEvents(text, state, onEvent){
    state.buf += text;
    var idx;
    while((idx = state.buf.indexOf('\n\n')) !== -1){
      var frame = state.buf.slice(0, idx);
      state.buf = state.buf.slice(idx + 2);
      var data = '';
      frame.split('\n').forEach(function(l){
        if(l.lastIndexOf('data:', 0) === 0) data += l.slice(5).trim();
      });
      if(data){
        var ev = null;
        try { ev = JSON.parse(data); } catch(e){ /* partial/garbled frame */ }
        if(ev) onEvent(ev);
      }
    }
  }

  var streaming = false, aborter = null;

  // One POST + SSE read. Appends UI into `bubble`, returns {blocks, stopReason}.
  function streamOnce(bubble, noTools){
    aborter = new AbortController();
    return fetch(API_URL, {
      method: 'POST',
      signal: aborter.signal,
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true'
      },
      body: JSON.stringify(buildRequest(noTools))
    }).then(function(resp){
      if(!resp.ok){
        return resp.json().catch(function(){ return {}; }).then(function(body){
          var msg = (body && body.error && body.error.message) || ('HTTP ' + resp.status);
          if(resp.status === 401){
            forgetKey();
            if(CFG.apiKey){
              msg = 'The API key embedded in this report was rejected (401). Regenerate the report with a valid key.';
            } else {
              msg = 'That API key was rejected (401). Enter a different key above and resend.';
              revealKeyForm('That API key was rejected (401). Enter a different key and resend.');
            }
          }
          if(resp.status === 429) msg = 'Rate limited by the API (429) — wait a moment and try again. ' + msg;
          throw new Error(msg);
        });
      }
      var st = {
        buf: '', blocks: [], partial: {}, stopReason: null,
        els: {}, think: null, mdDirty: {}, mdTimers: {}, toolChips: {}, citeUrls: {}, citeCount: 0
      };
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      function pump(){
        return reader.read().then(function(r){
          if(r.done){
            sseEvents(decoder.decode(), st, function(ev){ handleEvent(ev, st, bubble); });
            return st;
          }
          sseEvents(decoder.decode(r.value, {stream: true}), st, function(ev){ handleEvent(ev, st, bubble); });
          return pump();
        });
      }
      return pump();
    });
  }

  function handleEvent(ev, st, bubble){
    if(ev.type === 'content_block_start'){
      st.blocks[ev.index] = JSON.parse(JSON.stringify(ev.content_block));
      startBlockUI(st, ev.index, bubble);
    } else if(ev.type === 'content_block_delta'){
      var b = st.blocks[ev.index], d = ev.delta;
      if(!b || !d) return;
      if(d.type === 'text_delta'){
        b.text = (b.text || '') + d.text;
        touchText(st, ev.index);
      } else if(d.type === 'thinking_delta'){
        b.thinking = (b.thinking || '') + d.thinking;
        touchThinking(st, ev.index, bubble, b.thinking);
      } else if(d.type === 'input_json_delta'){
        st.partial[ev.index] = (st.partial[ev.index] || '') + d.partial_json;
      } else if(d.type === 'signature_delta'){
        b.signature = d.signature;
      } else if(d.type === 'citations_delta' && d.citation){
        (b.citations = b.citations || []).push(d.citation);
      }
    } else if(ev.type === 'content_block_stop'){
      finishBlock(st, ev.index, bubble);
    } else if(ev.type === 'message_delta'){
      if(ev.delta && ev.delta.stop_reason) st.stopReason = ev.delta.stop_reason;
    } else if(ev.type === 'error'){
      var err = new Error((ev.error && ev.error.message) || 'stream error');
      err.mid_stream = true;
      throw err;
    }
  }

  function startBlockUI(st, index, bubble){
    var b = st.blocks[index];
    if(b.type === 'text'){
      var div = document.createElement('div');
      div.className = 'da-md';
      bubble.appendChild(div);
      st.els[index] = div;
    } else if(b.type === 'server_tool_use'){
      var chip = document.createElement('div');
      chip.className = 'da-tool';
      chip.textContent = b.name === 'web_fetch' ? '🌐 Reading a page…' : '🔍 Searching the web…';
      bubble.appendChild(chip);
      st.els[index] = chip;
      st.toolChips[b.id] = chip;
    } else if(b.type === 'tool_use'){
      // A client (in-browser) tool call. Its chip is flipped done/err by
      // markToolChip() after runTool executes — there is no *_tool_result SSE
      // block for client tools the way there is for the server tools above.
      var cchip = document.createElement('div');
      cchip.className = 'da-tool';
      cchip.textContent = TOOL_LABEL[b.name] || '⚙ Working…';
      bubble.appendChild(cchip);
      st.els[index] = cchip;
      st.toolChips[b.id] = cchip;
    }
    // thinking gets its element lazily (first non-empty delta), so the
    // display:"omitted" fallback never shows an empty box.
    scrollDown();
  }

  function touchThinking(st, index, bubble, textNow){
    var el = st.els[index];
    if(!el){
      var wrap = document.createElement('details');
      wrap.className = 'da-think';
      var summary = document.createElement('summary');
      summary.textContent = 'Thinking…';
      wrap.appendChild(summary);
      var body = document.createElement('div');
      body.className = 'da-think-body';
      wrap.appendChild(body);
      bubble.appendChild(wrap);
      el = st.els[index] = body;
    }
    el.textContent = textNow;
    scrollDown();
  }

  function touchText(st, index){
    if(st.mdDirty[index]) return;
    st.mdDirty[index] = true;
    st.mdTimers[index] = setTimeout(function(){
      st.mdDirty[index] = false;
      delete st.mdTimers[index];
      var b = st.blocks[index], el = st.els[index];
      if(b && el){ renderMdReplace(el, b.text || ''); scrollDown(); }
    }, 90);
  }

  function finishBlock(st, index, bubble){
    var b = st.blocks[index];
    if(!b) return;
    if(st.partial[index] !== undefined){
      try { b.input = JSON.parse(st.partial[index] || '{}'); } catch(e){ b.input = {}; }
      delete st.partial[index];
    }
    // Cancel any pending debounced render for this block: finishBlock's render
    // is authoritative, and a trailing touchText would otherwise wipe the
    // citation chips appended just below (a real streamed-answer race).
    if(st.mdTimers[index]){ clearTimeout(st.mdTimers[index]); delete st.mdTimers[index]; }
    st.mdDirty[index] = false;
    var el = st.els[index];
    if(b.type === 'text' && el){
      renderMdReplace(el, b.text || '');
      if(b.citations && b.citations.length){
        var span = document.createElement('span');
        span.className = 'da-cites';
        b.citations.forEach(function(c){
          if(!c || !c.url || st.citeUrls[c.url]) return;
          // Citations go through the SAME URL policy as markdown links; a
          // rejected URL gets no chip (and no number) at all.
          var a = linkEl(c.url, '', c.title || c.url);
          if(!a) return;
          st.citeUrls[c.url] = ++st.citeCount;
          a.textContent = '[' + st.citeUrls[c.url] + ']';
          span.appendChild(a);
        });
        if(span.children.length) el.appendChild(span);
      }
    } else if(b.type === 'server_tool_use' && el){
      var q = b.input && (b.input.query || b.input.url);
      if(q){
        try { if(b.input.url) q = new URL(b.input.url).hostname; } catch(e){}
        el.textContent = (b.name === 'web_fetch' ? '🌐 Reading ' : '🔍 Searching: ') + '“' + q + '”';
      }
    } else if(b.type === 'tool_use' && el){
      // Relabel the pending chip with the concrete call (model input → textContent, inert).
      var inp = b.input || {};
      if(b.name === 'query_findings'){
        var parts = [];
        ['category', 'severity', 'status', 'sheet', 'text'].forEach(function(k){
          if(inp[k]) parts.push(k + ':' + inp[k]);
        });
        el.textContent = '⚙ Findings query' + (parts.length ? ' (' + parts.join(', ') + ')' : ' (all)');
      } else if(b.name === 'scroll_to_report'){
        el.textContent = '⚙ Go to ' + (inp.target || 'report');
      } else if(b.name === 'filter_report'){
        var fp = [];
        if(inp.search !== undefined) fp.push('search:“' + inp.search + '”');
        if(inp.category) fp.push(inp.category);
        if(inp.high_only !== undefined) fp.push('high only:' + (inp.high_only ? 'on' : 'off'));
        el.textContent = '⚙ Filter report' + (fp.length ? ' (' + fp.join(', ') + ')' : '');
      } else if(b.name === 'highlight_term'){
        el.textContent = '⚙ Highlight “' + (inp.term || '') + '”';
      } else if(b.name === 'calculate'){
        el.textContent = '⚙ Calculate ' + (inp.expression || '');
      }
    } else if(b.type === 'web_search_tool_result' || b.type === 'web_fetch_tool_result'){
      var chip = st.toolChips[b.tool_use_id];
      if(chip){
        if(Array.isArray(b.content)){
          chip.textContent = '🔍 ' + chip.textContent.replace(/^..\s*/, '') + ' — ' + b.content.length + ' result(s)';
          chip.className = 'da-tool da-tool-done';
        } else if(b.content && b.content.error_code){
          chip.textContent = '⚠ ' + (b.type === 'web_fetch_tool_result' ? 'Fetch' : 'Search') + ' failed: ' + b.content.error_code;
          chip.className = 'da-tool da-tool-err';
        } else {
          chip.className = 'da-tool da-tool-done';
        }
      }
    }
    scrollDown();
  }

  // ------------------------------------------------------------ turn driver
  function setStreaming(on){
    streaming = on;
    sendBtn.disabled = on;
    stopBtn.hidden = !on;
    if(!on) aborter = null;
  }

  // apiContent : string|array  — pushed to history as the user turn's content
  // displayText: string        — shown in the da-user bubble (textContent)
  // opts       : {retryValue, excerpt, onCommit}
  function runTurn(apiContent, displayText, opts){
    opts = opts || {};
    if(startersRow) startersRow.style.display = 'none';  // chips give way to the thread
    history.push({role: 'user', content: apiContent});
    var userBubble = addMsg('da-user', displayText);
    if(opts.excerpt){
      // The selected excerpt as a collapsible disclosure under the typed
      // question (textContent — never HTML): the transcript stays readable while
      // the model still receives the full excerpt in apiContent.
      var d = document.createElement('details');
      d.className = 'da-userctx';
      var sm = document.createElement('summary');
      sm.textContent = '↳ about selected excerpt';
      var bd = document.createElement('div');
      bd.textContent = opts.excerpt;
      d.appendChild(sm); d.appendChild(bd);
      userBubble.appendChild(d);
    }
    var bubble = addMsg('da-ai');
    setStreaming(true);
    var pushed = false; // any assistant content committed to history yet?

    // Two independent budgets: `round` = server-tool pause_turn resumes;
    // `toolRound` = client tool_use rounds. Once the tool budget is spent we
    // re-request with tools disabled (noTools) so the model must answer in text
    // — a run can never terminate on a dangling tool_use.
    function step(round, toolRound){
      var noTools = toolRound > MAX_TOOL_ROUNDS;
      return streamOnce(bubble, noTools).then(function(st){
        var blocks = st.blocks.filter(function(b){ return !!b; });
        // Commit the assistant turn (incl. any tool_use blocks) BEFORE answering
        // tools, so history is always assistant(tool_use) → user(tool_result).
        if(blocks.length){ history.push({role: 'assistant', content: blocks}); pushed = true; }
        if(st.stopReason === 'pause_turn' && round < MAX_CONTINUATIONS){
          return step(round + 1, toolRound); // server tool loop paused — resume
        }
        if(st.stopReason === 'tool_use'){
          var uses = blocks.filter(function(b){ return b.type === 'tool_use'; });
          if(uses.length){
            // Execute every client tool locally and answer EACH id in one user
            // turn (handlers may be async; a throwing one still returns an
            // is_error tool_result).
            return Promise.all(uses.map(function(b){
              return runTool(b.name, b.input || {}).then(function(r){
                markToolChip(st, b.id, r.is_error);
                var tr = {type: 'tool_result', tool_use_id: b.id, content: r.content};
                if(r.is_error) tr.is_error = true;
                return tr;
              });
            })).then(function(results){
              history.push({role: 'user', content: results});
              return step(round, toolRound + 1);
            });
          }
        }
        if(st.stopReason === 'refusal') note(bubble, 'The model declined to answer this request.');
        else if(st.stopReason === 'max_tokens') note(bubble, '(Answer truncated — output limit reached.)');
        else if(!st.stopReason) throw new Error('The stream ended unexpectedly — check your connection and try again.');
      });
    }

    step(0, 0).catch(function(err){
      var aborted = err && (err.name === 'AbortError' || err.code === 20);
      if(!pushed){
        history.pop();               // keep history consistent for the next question
        if(!aborted) input.value = (opts.retryValue !== undefined ? opts.retryValue : displayText);
      }
      if(aborted){
        note(bubble, '⏹ Stopped.');
      } else {
        var msg = (err && err.message) || 'Request failed.';
        if(err instanceof TypeError) msg = 'Could not reach api.anthropic.com — the assistant needs an internet connection.';
        addMsg('da-err', scrubSecrets(msg));
      }
    }).then(function(){
      if(!bubble.childNodes.length) bubble.remove(); // nothing ever rendered
      if(pushed && opts.onCommit) opts.onCommit();   // e.g. clear the pending selection
      setStreaming(false);
      scrollDown(true);
    });
  }

  function send(){
    var typed = input.value.trim();
    var hasSel = !!(pendingSel && pendingSel.text);
    if((!typed && !hasSel) || streaming) return;
    if(!ensureKey()){
      revealKeyForm('An Anthropic API key is required to use the assistant. Enter yours above.');
      return;
    }
    input.value = '';
    if(hasSel){
      var ex = pendingSel.text;
      var api = 'The user selected this excerpt from the report:\n<excerpt>\n' + ex + '\n</excerpt>\n\n' +
        'Question: ' + (typed || '(no question typed — explain or comment on this excerpt)');
      runTurn(api, typed || '(about the selected excerpt)', {
        retryValue: typed, excerpt: ex, onCommit: clearPendingSelection
      });
    } else {
      runTurn(typed, typed, {retryValue: typed});
    }
  }
  sendBtn.addEventListener('click', send);
  stopBtn.addEventListener('click', function(){ if(aborter) aborter.abort(); });
  input.addEventListener('keydown', function(e){
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
  });

  // Starter prompts: deterministic, run-tailored questions from the inert
  // #da-starters block (built server-side by _starter_prompts). Each chip fills
  // the box and sends immediately — the same path as a typed question, so the
  // key prompt, streaming, and tools all apply. Rendered as textContent, never
  // HTML, so an adversarial prompt string can inject nothing.
  (function(){
    if(!startersRow) return;
    var starters = readJsonBlock('da-starters');
    if(!starters || !starters.length) return;
    starters.slice(0, 5).forEach(function(q){
      if(!q || typeof q !== 'string') return;
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'da-starter';
      b.textContent = q;
      b.addEventListener('click', function(){
        if(streaming) return;
        input.value = q;
        send();
      });
      startersRow.appendChild(b);
    });
  })();

  // -------------------------------------------------- panel resize + drag
  // Stay CSS-anchored (bottom-right) until the first gesture, then snapshot the
  // rect into explicit left/top/width/height and own all geometry. On mobile
  // (<=600px) the bottom-sheet media query governs and inline geometry is
  // stripped. Persisted in localStorage; double-click the header to reset.
  var GEO_KEY = 'da-chat-geo', MARGIN = 12, MIN_W = 320, MIN_H = 360;
  // Which edges each resize mode moves; the opposite edge stays pinned.
  var RZ_EDGES = {
    l:{l:1}, r:{r:1}, t:{t:1}, b:{b:1},
    tl:{t:1,l:1}, tr:{t:1,r:1}, bl:{b:1,l:1}, br:{b:1,r:1}
  };
  function isMobile(){ return window.innerWidth <= 600; }
  function loadGeo(){ try { return JSON.parse(localStorage.getItem(GEO_KEY) || 'null'); } catch(e){ return null; } }
  function saveGeo(g){ try { localStorage.setItem(GEO_KEY, JSON.stringify(g)); } catch(e){} }
  function clearGeo(){ try { localStorage.removeItem(GEO_KEY); } catch(e){} }

  var customGeom = false;
  function enterCustom(){
    var r = panel.getBoundingClientRect();
    panel.style.left = r.left + 'px'; panel.style.top = r.top + 'px';
    panel.style.width = r.width + 'px'; panel.style.height = r.height + 'px';
    panel.style.right = 'auto'; panel.style.bottom = 'auto';
    panel.style.minHeight = '0px'; panel.style.maxWidth = 'none';  // defeat CSS floor/ceiling
    customGeom = true;
  }
  function stripInline(){
    ['left', 'top', 'width', 'height', 'right', 'bottom', 'minHeight', 'maxWidth']
      .forEach(function(p){ panel.style[p] = ''; });
    customGeom = false;
  }
  function clampGeo(g){
    var vw = window.innerWidth, vh = window.innerHeight;
    var maxW = vw - 2 * MARGIN, maxH = vh - 2 * MARGIN;
    var minW = Math.min(MIN_W, maxW), minH = Math.min(MIN_H, maxH);
    g.w = Math.max(minW, Math.min(g.w, maxW));
    g.h = Math.max(minH, Math.min(g.h, maxH));
    g.left = Math.max(MARGIN, Math.min(g.left, vw - g.w - MARGIN));
    g.top = Math.max(MARGIN, Math.min(g.top, vh - g.h - MARGIN));
    return g;
  }
  function writeGeo(g){
    panel.style.left = g.left + 'px'; panel.style.top = g.top + 'px';
    panel.style.width = g.w + 'px'; panel.style.height = g.h + 'px';
  }
  function applyGeom(){
    if(isMobile()){ stripInline(); return; }   // media query owns the bottom sheet
    var g = loadGeo();
    if(!g){ stripInline(); return; }            // never moved → CSS default
    enterCustom(); var c = clampGeo(g); writeGeo(c); saveGeo(c);
  }

  function startGesture(e, mode){
    if(isMobile()) return;
    if(mode === 'move' && e.target && e.target.closest && e.target.closest('button')) return;
    var el = e.currentTarget;
    var sx = e.clientX, sy = e.clientY, began = false, base = null;
    function onMove(ev){
      var dx = ev.clientX - sx, dy = ev.clientY - sy;
      if(!began){
        if(Math.abs(dx) + Math.abs(dy) < 4) return;  // threshold → lets dblclick fire
        began = true;
        if(!customGeom) enterCustom();
        var r = panel.getBoundingClientRect();
        base = {left: r.left, top: r.top, w: r.width, h: r.height, right: r.right, bottom: r.bottom};
        document.body.classList.add('da-dragging');
      }
      ev.preventDefault();
      var g;
      if(mode === 'move'){
        g = {left: base.left + dx, top: base.top + dy, w: base.w, h: base.h};
      } else {
        var m = RZ_EDGES[mode] || {};
        g = {left: base.left, top: base.top, w: base.w, h: base.h};
        // A left/top drag moves that edge and pins the far edge; a right/bottom
        // drag keeps the near edge fixed and grows width/height.
        if(m.l){ g.left = base.left + dx; g.w = base.right - g.left; }
        else if(m.r){ g.w = base.w + dx; }
        if(m.t){ g.top = base.top + dy; g.h = base.bottom - g.top; }
        else if(m.b){ g.h = base.h + dy; }
        // enforce mins against the FIXED far edge so the anchored edge holds
        var minW = Math.min(MIN_W, window.innerWidth - 2 * MARGIN);
        var minH = Math.min(MIN_H, window.innerHeight - 2 * MARGIN);
        if(g.w < minW){ if(m.l) g.left = base.right - minW; g.w = minW; }
        if(g.h < minH){ if(m.t) g.top = base.bottom - minH; g.h = minH; }
      }
      g = clampGeo(g); writeGeo(g); saveGeo(g);
    }
    function onUp(ev){
      try { el.releasePointerCapture(ev.pointerId); } catch(x){}
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('pointercancel', onUp);
      document.body.classList.remove('da-dragging');
    }
    try { el.setPointerCapture(e.pointerId); } catch(x){}
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
  }

  var headEl = panel.querySelector('.da-chat-head');
  if(headEl){
    headEl.addEventListener('pointerdown', function(e){ startGesture(e, 'move'); });
    headEl.addEventListener('dblclick', function(){ if(!isMobile()){ clearGeo(); stripInline(); } });
  }
  Array.prototype.slice.call(panel.querySelectorAll('.da-rz')).forEach(function(h){
    var mode = ['tl','tr','bl','br','t','b','l','r'].filter(function(k){
      return h.classList.contains('da-rz-' + k);
    })[0] || 'l';
    h.addEventListener('pointerdown', function(e){ startGesture(e, mode); });
  });
  window.addEventListener('resize', applyGeom);
  applyGeom();

  // ------------------------------------------------ highlight → ask about it
  // Select text anywhere in the report → a floating "Ask AI about this" button →
  // the excerpt rides into the chat as a dismissible chip and into the model's
  // question, while the transcript shows only what the user typed.
  var reportEl = reportContent || document.querySelector('main.content');
  var selPop = null, pendingSelDraft = null, pendingSel = null;

  function inReport(node){
    if(!node || !reportEl) return false;
    var el = node.nodeType === 1 ? node : node.parentNode;
    return !!(el && reportEl.contains(el) && !panel.contains(el));
  }
  function hideSelPop(){ if(selPop){ selPop.remove(); selPop = null; } }
  function showSelPop(){
    var sel = window.getSelection();
    if(!sel || sel.isCollapsed || !sel.rangeCount){ hideSelPop(); return; }
    var rng = sel.getRangeAt(0);
    if(!inReport(rng.commonAncestorContainer)){ hideSelPop(); return; }
    var text = sel.toString().replace(/\s+/g, ' ').trim();
    if(text.length < 2){ hideSelPop(); return; }
    var CAP = 4000, truncated = false;
    if(text.length > CAP){ text = text.slice(0, CAP); truncated = true; }
    // Capture at SHOW time (clicking the button collapses the native selection).
    pendingSelDraft = {text: text + (truncated ? ' …(excerpt truncated)' : ''), range: rng.cloneRange()};
    var rect = rng.getBoundingClientRect();
    if(!selPop){
      selPop = document.createElement('button');
      selPop.type = 'button';
      selPop.id = 'da-sel-pop';
      selPop.textContent = '✦ Ask AI about this';
      selPop.addEventListener('mousedown', function(e){ e.preventDefault(); }); // keep selection alive
      selPop.addEventListener('click', onAskSelection);
      document.body.appendChild(selPop);
    }
    var pw = 170, ph = 34;
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - pw - 8));
    var top = rect.top - ph; if(top < 8) top = rect.bottom + 8;
    selPop.style.left = left + 'px';
    selPop.style.top = top + 'px';
  }
  function onAskSelection(){
    if(!pendingSelDraft) return;
    setPendingSelection(pendingSelDraft);
    pendingSelDraft = null;
    hideSelPop();
    panel.hidden = false; fab.hidden = true;
    applyGeom();
    input.focus();
  }

  function paintSelHighlight(range){
    if(window.Highlight && window.CSS && CSS.highlights){
      try { CSS.highlights.set('da-sel', new Highlight(range)); } catch(e){}
    }
  }
  function clearSelHighlight(){ try { if(window.CSS && CSS.highlights) CSS.highlights.delete('da-sel'); } catch(e){} }

  function setPendingSelection(sd){
    pendingSel = {text: sd.text, range: sd.range};
    paintSelHighlight(sd.range);
    var compose = document.querySelector('.da-chat-compose');
    var chip = document.getElementById('da-sel-chip');
    if(!chip && compose){
      chip = document.createElement('div');
      chip.id = 'da-sel-chip';
      var label = document.createElement('span');
      label.className = 'da-sel-chip-text';
      var x = document.createElement('button');
      x.type = 'button'; x.className = 'da-sel-chip-x';
      x.setAttribute('aria-label', 'Clear excerpt');
      x.textContent = '×';
      x.addEventListener('click', clearPendingSelection);
      chip.appendChild(label); chip.appendChild(x);
      compose.parentNode.insertBefore(chip, compose);
    }
    if(chip){
      var preview = sd.text.length > 140 ? sd.text.slice(0, 140) + '…' : sd.text;
      chip.querySelector('.da-sel-chip-text').textContent = '“' + preview + '”';
    }
  }
  function clearPendingSelection(){
    pendingSel = null;
    clearSelHighlight();
    var chip = document.getElementById('da-sel-chip');
    if(chip) chip.remove();
  }

  if(reportEl){
    reportEl.addEventListener('mouseup', function(){ setTimeout(showSelPop, 0); });
  }
  document.addEventListener('selectionchange', function(){
    var s = window.getSelection();
    if(!s || s.isCollapsed) hideSelPop();
  });
  window.addEventListener('scroll', hideSelPop, true);   // fixed popover would go stale
  window.addEventListener('resize', hideSelPop);
})();
"""
