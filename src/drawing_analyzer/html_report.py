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
  (``sheets`` / ``synthesis_text`` / ``combined_text`` / the run-summary counts /
  ``errors``); it never imports the engine, tkinter, PyMuPDF, or the network, so
  it unit-tests in isolation. See :func:`build_html_report`.
- **Lossless.** The structured view is rendered from each sheet's digest, and the
  exact, verbatim ``combined_text`` is also embedded (collapsed) so the original
  Markdown is always one click / copy away — the rendering can never *drop*
  content, only present it.
- **Self-contained.** All CSS and JavaScript are inlined; the result is one
  ``.html`` file the operator can double-click, search, filter, print, or email
  with no server, build step, or internet access.

The Markdown→HTML conversion is a small, deliberately-scoped renderer
(:func:`markdown_to_html`) covering exactly the constructs the digests use —
headings, ``**bold**``, ``` `code` ```, bullet/numbered lists, GFM pipe tables
(schedules), block quotes (failed-sheet notices), and horizontal rules. It
escapes all model text, and any line it does not recognize falls through as an
escaped paragraph, so nothing is ever lost.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

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


def _block_html(header: str | None, body_md: str) -> str:
    """Render one digest section as a filterable ``<section>`` with its category."""
    category = classify_section(header)
    head = ""
    if header:
        cat_label = CATEGORY_LABELS.get(category, "")
        tag = (
            f'<span class="cat-tag cat-{category}">{html.escape(cat_label)}</span>'
            if category in ("coordination", "conflict")
            else ""
        )
        head = f'<h4 class="block-title">{_render_inline(header)}{tag}</h4>'
    return (
        f'<section class="block" data-category="{category}">'
        f"{head}{markdown_to_html(body_md)}</section>"
    )


def _render_digest_blocks(text: str) -> str:
    return "".join(_block_html(h, b) for h, b in split_into_sections(text))


def _card(
    *, card_id: str, title_html: str, badges_html: str, status: str, body_html: str
) -> str:
    """A collapsible, filterable card (one sheet, or the set overview)."""
    return (
        f'<article class="card" id="{card_id}" data-status="{_esc_attr(status)}">'
        f'<header class="card-head" role="button" tabindex="0">'
        f'<span class="card-title">{title_html}</span>'
        f'<span class="badges">{badges_html}</span>'
        f'<span class="chevron" aria-hidden="true">▾</span>'
        f"</header>"
        f'<div class="card-body">{body_html}</div>'
        f"</article>"
    )


def _sheet_card(index: int, total: int, sheet: Any) -> str:
    ref = _ref_of(sheet)
    label = getattr(ref, "display_label", None) or f"Sheet {index}/{total}"
    status = _sheet_status(sheet)
    text = (getattr(sheet, "text", "") or "").strip()
    error = getattr(sheet, "error", None)
    in_tok = int(getattr(sheet, "input_tokens", 0) or 0)
    out_tok = int(getattr(sheet, "output_tokens", 0) or 0)

    badge_text, badge_cls = _STATUS_BADGE[status]
    badges = [f'<span class="badge badge-{badge_cls}">{badge_text}</span>']
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


def _toc_html(ctx: Any, sheets: list[Any]) -> str:
    rows = [
        '<a class="toc-item" data-target="overview" href="#overview">'
        '<span class="toc-dot dot-overview"></span>'
        '<span class="toc-label">Drawing Set Overview</span></a>'
    ]
    total = len(sheets)
    for i, sheet in enumerate(sheets, start=1):
        ref = _ref_of(sheet)
        label = getattr(ref, "display_label", None) or f"Sheet {i}/{total}"
        status = _sheet_status(sheet)
        rows.append(
            f'<a class="toc-item" data-target="sheet-{i}" href="#sheet-{i}">'
            f'<span class="toc-dot dot-{status}"></span>'
            f'<span class="toc-seq">{i:02d}</span>'
            f'<span class="toc-label">{html.escape(label)}</span></a>'
        )
    return "".join(rows)


def _filter_chips_html() -> str:
    chips = [
        '<button class="chip chip-active" data-filter="all">All</button>',
        '<button class="chip chip-issues" data-filter="issues">⚠ Issues only</button>',
    ]
    for cid, _label, _kw in _CATEGORY_SPECS:
        chips.append(
            f'<button class="chip" data-filter="{cid}">{html.escape(CATEGORY_LABELS[cid])}</button>'
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
        f'<div class="stats">{cards}</div>'
        f'<details class="sources"><summary>Source files</summary>'
        f"<ul>{sources}</ul></details>"
        f"{errors_html}"
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
    ctx: Any, *, source_names: list[str], now: datetime | None = None
) -> str:
    """Render a :class:`DrawingContext` to one self-contained HTML document.

    Pure and duck-typed (see the module docstring): reads only ``ctx.sheets`` and
    the run-summary attributes, embeds all CSS/JS, and returns the full HTML as a
    string. ``source_names`` is listed in the run summary; ``now`` stamps the
    report (defaults to :func:`datetime.now`).
    """
    now = now or datetime.now()
    sheets = list(getattr(ctx, "sheets", None) or [])
    total = len(sheets)

    title = "Drawing Set Digest"
    if source_names:
        title = f"{Path(source_names[0]).stem} — Drawing Digest"

    cards = [_overview_card(ctx)]
    cards += [_sheet_card(i, total, s) for i, s in enumerate(sheets, start=1)]

    body = f"""<aside class="sidebar">
  <div class="brand">Drawing Digest</div>
  <div class="generated">{html.escape(now.strftime('%Y-%m-%d %H:%M'))}</div>
  <div class="search-wrap">
    <input id="search" type="search" placeholder="Search all sheets…" autocomplete="off">
  </div>
  <div class="chips">{_filter_chips_html()}</div>
  <div class="result-count" id="result-count"></div>
  <nav class="toc" id="toc">{_toc_html(ctx, sheets)}</nav>
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

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        f"</head>\n<body>\n{body}\n<script>{_JS}</script>\n</body>\n</html>\n"
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
.card-title{font-weight:600; flex:1 1 auto; font-size:15px}
.seq{color:var(--muted); font-variant-numeric:tabular-nums; margin-right:4px}
.badges{display:flex; gap:6px; flex-wrap:wrap; align-items:center}
.badge{font-size:11px; padding:3px 8px; border-radius:999px; white-space:nowrap}
.badge-ok{background:#e7f6ee; color:var(--ok)}
.badge-cached{background:#fbf3df; color:var(--cached)}
.badge-failed{background:var(--conflict-soft); color:var(--failed)}
.badge-overview{background:#f1eaff; color:var(--overview)}
.badge-tok{background:#eef1f6; color:var(--muted); font-variant-numeric:tabular-nums}
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
.cat-tag{font-size:10px; font-weight:700; padding:2px 7px; border-radius:999px; text-transform:uppercase; letter-spacing:.4px}
.cat-coordination{background:var(--coord); color:#fff}
.cat-conflict{background:var(--conflict); color:#fff}

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
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var toc = Array.prototype.slice.call(document.querySelectorAll('.toc-item'));
  var resultCount = document.getElementById('result-count');
  var noResults = document.getElementById('no-results');
  var ISSUE = ['coordination','conflict'];
  var activeFilter = 'all';

  function activeCategories(){
    if(activeFilter === 'all') return null;          // null => every category
    if(activeFilter === 'issues') return ISSUE.slice();
    return [activeFilter];
  }

  function tocFor(id){
    for(var i=0;i<toc.length;i++){ if(toc[i].getAttribute('data-target')===id) return toc[i]; }
    return null;
  }

  function apply(){
    var q = (search.value || '').trim().toLowerCase();
    var cats = activeCategories();
    var visibleCards = 0;

    cards.forEach(function(card){
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

    noResults.hidden = visibleCards !== 0;
    var filterLabel = activeFilter === 'all' ? '' :
      ' · filter: ' + (document.querySelector('.chip-active') ? document.querySelector('.chip-active').textContent.trim() : activeFilter);
    resultCount.textContent = visibleCards + ' of ' + cards.length + ' section(s)' + filterLabel;
  }

  chips.forEach(function(chip){
    chip.addEventListener('click', function(){
      chips.forEach(function(c){ c.classList.remove('chip-active'); });
      chip.classList.add('chip-active');
      activeFilter = chip.getAttribute('data-filter');
      apply();
    });
  });

  var timer = null;
  search.addEventListener('input', function(){
    if(timer) clearTimeout(timer);
    timer = setTimeout(apply, 90);
  });

  // Collapse / expand a card by clicking (or keyboard-activating) its header.
  cards.forEach(function(card){
    var head = card.querySelector('.card-head');
    function toggle(){ card.classList.toggle('collapsed'); }
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', function(e){
      if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); toggle(); }
    });
  });
  var ea = document.getElementById('expand-all');
  var ca = document.getElementById('collapse-all');
  if(ea) ea.addEventListener('click', function(){ cards.forEach(function(c){ c.classList.remove('collapsed'); }); });
  if(ca) ca.addEventListener('click', function(){ cards.forEach(function(c){ c.classList.add('collapsed'); }); });

  // TOC click scrolls (native via href) and expands the target if collapsed.
  toc.forEach(function(item){
    item.addEventListener('click', function(){
      var el = document.getElementById(item.getAttribute('data-target'));
      if(el) el.classList.remove('collapsed');
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
