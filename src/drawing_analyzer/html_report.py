"""Self-contained, navigable HTML report for a drawing digest.

The per-sheet Markdown digests (and the cross-sheet synthesis) are faithful but
*long* — a single combined ``.md`` of a large set is a wall of text the operator
has to scroll and ``Ctrl-F`` through. This module renders the same
``DrawingContext`` into ONE self-contained HTML file that is easier to read and,
crucially, lets the operator **isolate the high-value findings** — cross-sheet
conflicts, per-sheet coordination / cross-discipline items, and failed sheets —
without losing any of the original content.

Design goals:

- **Lossless.** Every sheet's exact digest text is preserved verbatim in a
  collapsible *Raw digest (Markdown)* block, so nothing the model returned is
  ever dropped or paraphrased — the rendered view is a convenience layered on
  top, never a replacement.
- **Navigable.** A sticky sidebar table of contents, a live text search, and
  filter chips (``All`` / ``Coordination & conflicts`` / ``Failed`` /
  per-discipline) let the operator jump to or isolate exactly what they want.
- **Coordination-first.** An *Issues & Coordination* panel at the top
  aggregates, across the whole set, the synthesis's conflict findings, every
  per-sheet coordination section, and any failed sheets — each linking back to
  its sheet.
- **Self-contained & offline.** All CSS and JS are inlined; the file opens by
  double-click with no network, server, or external assets.

Like :mod:`drawing_analyzer.export` this module is kept **pure and duck-typed**
on the context (it reads only the attributes listed below) so it unit-tests with
plain fakes — no tkinter, PyMuPDF, or network. It also ships a tiny,
dependency-free Markdown subset renderer (headings, bold/italic, inline code,
bullet/ordered lists, pipe tables, block quotes, rules) sufficient for the digest
format; anything it doesn't recognize still survives in the raw block.

Read surface (duck-typed), identical to :mod:`drawing_analyzer.export`:
- ``ctx.sheets`` — per-sheet digests, each with ``.ref`` (``source_name`` /
  ``page_index`` / ``page_count`` / ``display_label``), ``.text``, ``.error``,
  ``.cached``, ``.input_tokens`` / ``.output_tokens``.
- ``ctx.synthesis_text`` — the cross-sheet overview (may be empty).
- ``ctx.ok_sheet_count`` / ``ctx.sheet_count`` / ``ctx.cached_sheet_count`` /
  ``ctx.total_input_tokens`` / ``ctx.total_output_tokens`` / ``ctx.errors``.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Words that mark a section / finding as a coordination or consistency concern —
# the things the operator most wants to isolate. Matched (case-insensitively)
# against section *titles* only, so it targets the digest's "Coordination /
# cross-discipline items" section and the synthesis's "conflicts" subsection
# rather than firing on every prose mention.
_COORD_RE = re.compile(
    r"coordinat|cross.?disciplin|conflict|discrepan|mismatch|inconsist", re.I
)

# Legibility markers the model is told to emit for unreadable content; surfaced
# as a per-sheet badge so a sheet the model could only partly read is obvious.
_ILLEGIBLE_RE = re.compile(r"\[(?:partially )?illegible\]", re.I)


def _esc(text: str) -> str:
    """Escape text for HTML body content."""
    return _html.escape(text or "", quote=False)


def _esc_attr(text: str) -> str:
    """Escape text for an HTML attribute value (quotes included)."""
    return _html.escape(text or "", quote=True)


# --------------------------------------------------------------------------- #
# Duck-typed accessors (mirror drawing_analyzer.export)
# --------------------------------------------------------------------------- #


def _ref_of(sheet: Any) -> Any:
    return getattr(sheet, "ref", None)


def _sheet_label(index: int, total: int, sheet: Any) -> str:
    ref = _ref_of(sheet)
    return getattr(ref, "display_label", None) or f"Sheet {index}/{total}"


def _status_badge(sheet: Any) -> tuple[str, str]:
    """``(text, css_state)`` for the sheet's status pill."""
    if getattr(sheet, "error", None):
        return "Failed", "failed"
    if getattr(sheet, "cached", False):
        return "Cached", "cached"
    return "OK", "ok"


# --------------------------------------------------------------------------- #
# Tiny Markdown subset renderer
# --------------------------------------------------------------------------- #

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")
_SAFE_URL_RE = re.compile(r"^(?:https?:|mailto:|#|/)", re.I)


def _render_inline(text: str) -> str:
    """Inline Markdown -> HTML on a single already-escaped run of text.

    Code spans are stashed first so their literal contents are never touched by
    the emphasis/link passes, then restored last. Link targets are scheme-checked
    so a ``javascript:`` URL degrades to plain text rather than an active link.
    """
    escaped = _esc(text)
    codes: list[str] = []

    def _stash(match: re.Match) -> str:
        codes.append(match.group(1))
        return f"\x00C{len(codes) - 1}\x00"

    escaped = _INLINE_CODE_RE.sub(_stash, escaped)

    def _link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        if not _SAFE_URL_RE.match(url):
            return match.group(0)
        return f'<a href="{_esc_attr(url)}" rel="noopener noreferrer">{label}</a>'

    escaped = _LINK_RE.sub(_link, escaped)
    escaped = _BOLD_RE.sub(
        lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped
    )
    escaped = _ITALIC_RE.sub(
        lambda m: f"<em>{m.group(1) or m.group(2)}</em>", escaped
    )
    escaped = re.sub(r"\x00C(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", escaped)
    return escaped


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if "|" not in s and "-" not in s:
        return False
    body = s.strip("|").strip()
    return bool(body) and bool(re.fullmatch(r"[\s:|-]+", s)) and "-" in s


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _nest_list_items(items: list[tuple[int, bool, str]], idx: int, indent: int) -> tuple[str, int]:
    """Render flat ``(indent, ordered, content)`` items into nested ``<ul>``/``<ol>``."""
    ordered = items[idx][1]
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    while idx < len(items):
        it_indent, it_ordered, content = items[idx]
        if it_indent < indent:
            break
        if it_indent > indent:
            sub, idx = _nest_list_items(items, idx, it_indent)
            if len(out) > 1 and out[-1].endswith("</li>"):
                out[-1] = out[-1][:-5] + sub + "</li>"
            else:
                out.append(sub)
            continue
        if it_ordered != ordered:
            break
        out.append(f"<li>{_render_inline(content)}</li>")
        idx += 1
    out.append(f"</{tag}>")
    return "".join(out), idx


def render_markdown(md: str, *, base_level: int = 3) -> str:
    """Render the Markdown subset used by the digests into safe HTML.

    Supports ATX headings, ``**bold**`` / ``*italic*``, ``` `code` ```, bullet
    and ordered lists (nested by indentation), GitHub pipe tables, block quotes,
    horizontal rules, and paragraphs. ``base_level`` offsets heading levels so a
    sheet body's own ``#`` headings nest *under* the report's structure (a body
    ``#`` becomes ``<h{base_level}>``) instead of competing with it. Everything
    is HTML-escaped before formatting, so digest content can never inject markup.
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Fenced code block.
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith(marker):
                buf.append(lines[i])
                i += 1
            i += 1  # consume closing fence (if present)
            out.append(f"<pre class=\"code\"><code>{_esc(chr(10).join(buf))}</code></pre>")
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)) + base_level - 1, 6)
            out.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        # Pipe table: a header row followed by a separator row.
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            header = _split_row(line)
            i += 2
            body_rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body_rows.append(_split_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{_render_inline(c)}</th>" for c in header)
            trows = []
            for row in body_rows:
                cells = "".join(f"<td>{_render_inline(c)}</td>" for c in row)
                trows.append(f"<tr>{cells}</tr>")
            out.append(
                f"<div class=\"table-wrap\"><table><thead><tr>{thead}</tr></thead>"
                f"<tbody>{''.join(trows)}</tbody></table></div>"
            )
            continue

        # Block quote (one or more consecutive '>' lines).
        if _QUOTE_RE.match(line):
            buf = []
            while i < n and _QUOTE_RE.match(lines[i]):
                buf.append(_QUOTE_RE.match(lines[i]).group(1))
                i += 1
            out.append(f"<blockquote>{render_markdown(chr(10).join(buf), base_level=base_level)}</blockquote>")
            continue

        # List (bullet or ordered), possibly nested by indentation.
        if _LIST_RE.match(line):
            items: list[tuple[int, bool, str]] = []
            while i < n:
                m = _LIST_RE.match(lines[i])
                if m:
                    indent = len(m.group(1).expandtabs(4))
                    ordered = m.group(2)[:1] not in "-*+"
                    items.append((indent, ordered, m.group(3)))
                    i += 1
                    continue
                if lines[i].strip() == "" and i + 1 < n and _LIST_RE.match(lines[i + 1]):
                    i += 1
                    continue
                break
            base = min(it[0] for it in items)
            rendered, _ = _nest_list_items(items, 0, base)
            out.append(rendered)
            continue

        # Paragraph: gather consecutive lines until a blank or a new block start.
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines, i):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{_render_inline(' '.join(s.strip() for s in buf))}</p>")

    return "".join(out)


def _starts_block(lines: list[str], i: int) -> bool:
    """True when ``lines[i]`` begins a non-paragraph block (ends a paragraph)."""
    line = lines[i]
    if (
        _HEADING_RE.match(line)
        or _HR_RE.match(line)
        or _LIST_RE.match(line)
        or _QUOTE_RE.match(line)
        or _FENCE_RE.match(line)
    ):
        return True
    return "|" in line and i + 1 < len(lines) and _is_table_sep(lines[i + 1])


# --------------------------------------------------------------------------- #
# Section splitting & coordination extraction
# --------------------------------------------------------------------------- #

_BOLD_LINE_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
_BULLET_LABEL_RE = re.compile(r"^\s*[-*+]\s+\*\*(.+?)\*\*\s*:\s*(.*)$")


def _section_header(line: str) -> tuple[str, str] | None:
    """Recognize a digest *section* start, return ``(title, inline_body)`` or ``None``.

    Handles the three shapes the model emits its sections in: an ATX heading
    (``### Coordination …``), a whole-line bold label (``**Coordination …**``),
    and a bold-led bullet (``- **Coordination …:** text``) whose trailing text
    becomes the first line of the section body.
    """
    heading = _HEADING_RE.match(line)
    if heading and heading.group(2).strip():
        return heading.group(2).strip(), ""
    bullet = _BULLET_LABEL_RE.match(line)
    if bullet:
        return bullet.group(1).strip(), bullet.group(2).strip()
    bold = _BOLD_LINE_RE.match(line)
    if bold:
        return bold.group(1).strip(), ""
    return None


def split_sections(md: str) -> list[tuple[str, str]]:
    """Split digest Markdown into ``(title, body)`` sections (preamble title ``""``).

    Used to *find* and extract coordination findings for the Issues panel; the
    in-body renderer uses the stricter :func:`_iter_strong_sections` so it never
    over-segments equipment bullets.
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[tuple[str, list[str]]] = []
    title, body = "", []
    for line in lines:
        header = _section_header(line)
        if header is not None:
            sections.append((title, body))
            title, body = header[0], ([header[1]] if header[1] else [])
        else:
            body.append(line)
    sections.append((title, body))
    return [(t, "\n".join(b).strip()) for t, b in sections if t or "\n".join(b).strip()]


def coordination_sections(md: str) -> list[tuple[str, str]]:
    """The ``(title, body)`` sections whose *title* reads as a coordination concern."""
    return [(t, b) for t, b in split_sections(md) if t and _COORD_RE.search(t) and b]


def _iter_strong_sections(md: str):
    """Yield ``(title_or_None, chunk_md)`` split only on headings / whole-line bold.

    Deliberately ignores bold-led *bullets* so prose, lists, and tables render
    naturally; used to wrap a strong-signal coordination section in a call-out
    inside the sheet body without chopping equipment lists into sub-cards.
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title: str | None = None
    buf: list[str] = []
    for line in lines:
        header = None
        heading = _HEADING_RE.match(line)
        if heading and heading.group(2).strip():
            header = heading.group(2).strip()
        else:
            bold = _BOLD_LINE_RE.match(line)
            if bold:
                header = bold.group(1).strip()
        if header is not None:
            if title is not None or "".join(buf).strip():
                yield title, "\n".join(buf).strip()
            title, buf = header, []
        else:
            buf.append(line)
    if title is not None or "".join(buf).strip():
        yield title, "\n".join(buf).strip()


def parse_header(text: str) -> dict[str, str]:
    """Parse the leading ``Sheet <number> - <discipline> - <title>`` header line.

    Returns ``{"number", "discipline", "title"}`` (any field may be ``""``).
    Splits only on space-delimited dashes so a discipline like ``Plumbing-Fire``
    or a number like ``M-101`` keeps its internal hyphen.
    """
    out = {"number": "", "discipline": "", "title": ""}
    first = ""
    for raw in (text or "").replace("\r", "\n").split("\n"):
        if raw.strip():
            first = raw.strip()
            break
    first = re.sub(r"^#{1,6}\s*", "", first).strip().strip("*").strip()
    if not re.match(r"(?i)^sheet\b", first):
        return out
    parts = re.split(r"\s+[-–—]\s+", first, maxsplit=2)
    num = re.sub(r"(?i)^sheet\s*", "", parts[0]).strip().strip(":").strip()
    out["number"] = num
    if len(parts) > 1:
        out["discipline"] = parts[1].strip().strip("*").strip()
    if len(parts) > 2:
        out["title"] = parts[2].strip().strip("*").strip()
    return out


# --------------------------------------------------------------------------- #
# HTML assembly
# --------------------------------------------------------------------------- #


def _render_sheet_body(text: str) -> str:
    """Render a sheet digest, wrapping strong-signal coordination sections in call-outs."""
    parts: list[str] = []
    for title, chunk in _iter_strong_sections(text):
        if title is None:
            parts.append(render_markdown(chunk, base_level=4))
            continue
        inner = (
            f"<h4 class=\"sec-h\">{_render_inline(title)}</h4>"
            f"{render_markdown(chunk, base_level=4)}"
        )
        if _COORD_RE.search(title):
            parts.append(
                f"<div class=\"callout coord\"><span class=\"callout-tag\">"
                f"⚠ Coordination / cross-discipline</span>{inner}</div>"
            )
        else:
            parts.append(f"<div class=\"sec\">{inner}</div>")
    return "".join(parts) or "<p class=\"muted\">(empty digest)</p>"


def _sheet_meta(index: int, total: int, sheet: Any) -> dict[str, Any]:
    """Everything the TOC, filters, and card need about one sheet."""
    ref = _ref_of(sheet)
    text = (getattr(sheet, "text", "") or "").strip()
    error = getattr(sheet, "error", None)
    header = parse_header(text)
    status_text, status_state = _status_badge(sheet)
    coord = coordination_sections(text)
    return {
        "anchor": f"sheet-{index}",
        "index": index,
        "label": _sheet_label(index, total, sheet),
        "number": header["number"],
        "discipline": header["discipline"],
        "title": header["title"],
        "text": text,
        "error": error,
        "status_text": status_text,
        "status_state": status_state,
        "in_tok": int(getattr(sheet, "input_tokens", 0) or 0),
        "out_tok": int(getattr(sheet, "output_tokens", 0) or 0),
        "coord": coord,
        "illegible": len(_ILLEGIBLE_RE.findall(text)),
        "page": int(getattr(ref, "page_index", index - 1) or 0) + 1,
        "source": getattr(ref, "source_name", "") or "",
    }


def _badges_html(meta: dict[str, Any]) -> str:
    badges = [
        f"<span class=\"badge {meta['status_state']}\">{_esc(meta['status_text'])}</span>"
    ]
    if meta["discipline"]:
        badges.append(f"<span class=\"badge disc\">{_esc(meta['discipline'])}</span>")
    if meta["coord"]:
        badges.append("<span class=\"badge coordb\">⚠ Coordination</span>")
    if meta["illegible"]:
        badges.append(
            f"<span class=\"badge warnb\">{meta['illegible']} illegible</span>"
        )
    if meta["in_tok"] or meta["out_tok"]:
        badges.append(
            f"<span class=\"badge tok\">{meta['in_tok']:,} in / {meta['out_tok']:,} out</span>"
        )
    return "".join(badges)


def _sheet_card_html(meta: dict[str, Any]) -> str:
    title_bits = [f"<span class=\"sheet-num\">{_esc(meta['number'] or meta['label'])}</span>"]
    if meta["number"] and meta["title"]:
        title_bits.append(f"<span class=\"sheet-title\">{_esc(meta['title'])}</span>")
    head = (
        f"<div class=\"sheet-head\"><h3>{''.join(title_bits)}</h3>"
        f"<div class=\"badges\">{_badges_html(meta)}</div>"
        f"<div class=\"sheet-sub\">{_esc(meta['label'])}</div></div>"
    )
    if meta["error"]:
        body = (
            f"<div class=\"callout failedc\"><span class=\"callout-tag\">"
            f"✕ Sheet analysis failed</span><p>{_esc(meta['error'])}</p></div>"
        )
    else:
        body = f"<div class=\"sheet-body\">{_render_sheet_body(meta['text'])}</div>"
    raw = ""
    if meta["text"]:
        raw = (
            "<details class=\"raw\"><summary>Raw digest (Markdown)</summary>"
            f"<pre>{_esc(meta['text'])}</pre></details>"
        )
    return (
        f"<section id=\"{meta['anchor']}\" class=\"sheet card\" "
        f"data-discipline=\"{_esc_attr(meta['discipline'])}\" "
        f"data-failed=\"{1 if meta['error'] else 0}\" "
        f"data-coord=\"{1 if meta['coord'] else 0}\">"
        f"{head}{body}{raw}</section>"
    )


def _issues_panel_html(metas: list[dict[str, Any]], synthesis_text: str) -> str:
    """Aggregate failed sheets, set-wide conflicts, and per-sheet coordination."""
    blocks: list[str] = []

    failed = [m for m in metas if m["error"]]
    if failed:
        items = "".join(
            f"<li><a href=\"#{m['anchor']}\">{_esc(m['number'] or m['label'])}</a>"
            f" — {_esc(m['error'])}</li>"
            for m in failed
        )
        blocks.append(
            f"<div class=\"issue-card\" data-kind=\"failed\">"
            f"<h3>✕ Failed sheets ({len(failed)})</h3><ul>{items}</ul></div>"
        )

    conflicts = coordination_sections(synthesis_text)
    if conflicts:
        rendered = "".join(
            f"<h4 class=\"sec-h\">{_render_inline(t)}</h4>{render_markdown(b, base_level=4)}"
            for t, b in conflicts
        )
        blocks.append(
            f"<div class=\"issue-card\" data-kind=\"coord\">"
            f"<h3>⚠ Set-wide conflicts &amp; cross-references</h3>"
            f"<p class=\"muted\">From the cross-sheet synthesis.</p>{rendered}</div>"
        )

    coord_sheets = [m for m in metas if m["coord"]]
    if coord_sheets:
        cards = []
        for m in coord_sheets:
            rendered = "".join(
                f"<h4 class=\"sec-h\">{_render_inline(t)}</h4>{render_markdown(b, base_level=4)}"
                for t, b in m["coord"]
            )
            cards.append(
                f"<div class=\"issue-card\" data-kind=\"coord\" data-discipline=\""
                f"{_esc_attr(m['discipline'])}\">"
                f"<h3><a href=\"#{m['anchor']}\">{_esc(m['number'] or m['label'])}</a>"
                + (f" <span class=\"badge disc\">{_esc(m['discipline'])}</span>" if m["discipline"] else "")
                + f"</h3>{rendered}</div>"
            )
        blocks.append(
            "<h3 class=\"issues-sub\">Per-sheet coordination items</h3>"
            + "".join(cards)
        )

    if not blocks:
        return (
            "<section id=\"issues\" class=\"panel\"><h2>⚠ Issues &amp; Coordination</h2>"
            "<p class=\"muted\">No failed sheets, cross-sheet conflicts, or "
            "coordination items were flagged in this set.</p></section>"
        )

    return (
        "<section id=\"issues\" class=\"panel issues\"><h2>⚠ Issues &amp; Coordination</h2>"
        "<p class=\"muted\">The highest-value findings, pulled together from across "
        "the set. Each links back to its sheet.</p>" + "".join(blocks) + "</section>"
    )


def _summary_html(ctx: Any, source_names: list[str], now: datetime, total: int) -> str:
    ok = int(getattr(ctx, "ok_sheet_count", 0) or 0)
    cached = int(getattr(ctx, "cached_sheet_count", 0) or 0)
    in_tok = int(getattr(ctx, "total_input_tokens", 0) or 0)
    out_tok = int(getattr(ctx, "total_output_tokens", 0) or 0)
    files = "".join(f"<li>{_esc(name)}</li>" for name in source_names)
    cached_note = f" ({cached} from cache)" if cached else ""
    stats = (
        f"<div class=\"stat\"><span class=\"k\">{ok}/{total}</span>"
        f"<span class=\"v\">sheets analyzed{_esc(cached_note)}</span></div>"
        f"<div class=\"stat\"><span class=\"k\">{in_tok:,}</span>"
        f"<span class=\"v\">input tokens</span></div>"
        f"<div class=\"stat\"><span class=\"k\">{out_tok:,}</span>"
        f"<span class=\"v\">output tokens</span></div>"
    )
    return (
        "<section id=\"summary\" class=\"panel\">"
        f"<div class=\"stats\">{stats}</div>"
        f"<details class=\"sources\"><summary>{len(source_names)} source file(s)</summary>"
        f"<ul>{files}</ul></details></section>"
    )


def _toc_html(metas: list[dict[str, Any]], has_synthesis: bool) -> str:
    items = ["<li><a href=\"#issues\" class=\"toc-top\">⚠ Issues &amp; Coordination</a></li>"]
    if has_synthesis:
        items.append("<li><a href=\"#overview\" class=\"toc-top\">Set Overview</a></li>")
    for m in metas:
        dot = m["status_state"]
        sub = _esc(m["discipline"] or m["source"])
        flag = " <span class=\"toc-flag\">⚠</span>" if m["coord"] else ""
        items.append(
            f"<li class=\"toc-sheet\" data-key=\"{m['anchor']}\" "
            f"data-discipline=\"{_esc_attr(m['discipline'])}\" "
            f"data-failed=\"{1 if m['error'] else 0}\" "
            f"data-coord=\"{1 if m['coord'] else 0}\">"
            f"<a href=\"#{m['anchor']}\"><span class=\"dot {dot}\"></span>"
            f"<span class=\"toc-name\">{_esc(m['number'] or m['label'])}{flag}</span>"
            f"<span class=\"toc-sub\">{sub}</span></a></li>"
        )
    return "<ul class=\"toc\">" + "".join(items) + "</ul>"


def _discipline_chips(metas: list[dict[str, Any]]) -> str:
    disciplines = sorted({m["discipline"] for m in metas if m["discipline"]})
    chips = [
        "<button class=\"chip active\" data-filter=\"all\">All</button>",
        "<button class=\"chip\" data-filter=\"coord\">⚠ Coordination &amp; conflicts</button>",
        "<button class=\"chip\" data-filter=\"failed\">Failed</button>",
    ]
    for disc in disciplines:
        chips.append(
            f"<button class=\"chip\" data-filter=\"disc\" data-value=\"{_esc_attr(disc)}\">"
            f"{_esc(disc)}</button>"
        )
    return "".join(chips)


def build_html_report(ctx: Any, *, source_names: list[str], now: datetime | None = None) -> str:
    """Render a ``DrawingContext`` into one self-contained, navigable HTML string.

    Pure and duck-typed (see module docstring); does no I/O, so it is the
    unit-testable core of :func:`write_html_report` and the GUI's HTML save. The
    returned document inlines all CSS/JS and embeds every sheet's raw digest, so
    it is both fully offline and lossless.
    """
    now = now or datetime.now()
    sheets = list(getattr(ctx, "sheets", None) or [])
    total = len(sheets)
    metas = [_sheet_meta(i, total, s) for i, s in enumerate(sheets, start=1)]
    synthesis_text = (getattr(ctx, "synthesis_text", "") or "").strip()
    has_synthesis = bool(synthesis_text)

    stem = Path(source_names[0]).stem if source_names else "drawings"
    doc_title = f"{stem} — Drawing Analysis"
    generated = now.strftime("%Y-%m-%d %H:%M:%S")

    overview = ""
    if has_synthesis:
        overview = (
            "<section id=\"overview\" class=\"panel\"><h2>Set Overview</h2>"
            "<p class=\"muted\">Cross-sheet synthesis reconciling tags, systems, "
            f"and conflicts across the set.</p>{render_markdown(synthesis_text, base_level=3)}</section>"
        )

    sheets_html = "".join(_sheet_card_html(m) for m in metas)

    return _HTML_TEMPLATE.format(
        title=_esc(doc_title),
        styles=_STYLES,
        script=_SCRIPT,
        brand=_esc(doc_title),
        generated=_esc(generated),
        sheet_count=total,
        chips=_discipline_chips(metas),
        toc=_toc_html(metas, has_synthesis),
        summary=_summary_html(ctx, source_names, now, total),
        issues=_issues_panel_html(metas, synthesis_text),
        overview=overview,
        sheets=sheets_html,
    )


def write_html_report(
    ctx: Any, path: Any, *, source_names: list[str], now: datetime | None = None
) -> Path:
    """Render and write the HTML report to ``path``; returns the written ``Path``."""
    out = Path(path)
    out.write_text(build_html_report(ctx, source_names=source_names, now=now), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Static assets (inlined so the report is a single offline file)
# --------------------------------------------------------------------------- #

_STYLES = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#1c2530; --muted:#5b6775; --line:#e3e7ec;
  --accent:#2563eb; --accent-soft:#eef3ff; --ok:#15a36e; --cached:#6b7280;
  --failed:#dc2626; --coord:#d97706; --coord-soft:#fff7ed; --failed-soft:#fef2f2;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3,h4{line-height:1.25;margin:0 0 .4em}
.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:16px;
  padding:12px 20px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap}
.topbar .brand{font-weight:700;font-size:17px}
.topbar .meta{color:var(--muted);font-size:13px}
.topbar .search{margin-left:auto;min-width:240px;flex:1;max-width:420px;padding:8px 12px;
  border:1px solid var(--line);border-radius:8px;font-size:14px;background:#fff}
.layout{display:flex;align-items:flex-start;max-width:1400px;margin:0 auto;gap:24px;padding:20px}
.sidebar{position:sticky;top:64px;width:300px;flex:0 0 300px;max-height:calc(100vh - 84px);
  overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.chip{cursor:pointer;border:1px solid var(--line);background:#fff;color:var(--muted);
  padding:5px 10px;border-radius:999px;font-size:12px;font-weight:600}
.chip:hover{border-color:var(--accent);color:var(--accent)}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
.toc{list-style:none;margin:0;padding:0}
.toc>li{margin:1px 0}
.toc a{display:block;padding:6px 8px;border-radius:7px;color:var(--ink)}
.toc a:hover{background:var(--accent-soft);text-decoration:none}
.toc .toc-top{font-weight:600}
.toc-sheet a{display:flex;align-items:center;gap:8px}
.toc-name{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toc-sub{margin-left:auto;color:var(--muted);font-size:11px;white-space:nowrap}
.toc-flag{color:var(--coord)}
.dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px;background:var(--cached)}
.dot.ok{background:var(--ok)} .dot.failed{background:var(--failed)} .dot.cached{background:var(--cached)}
.content{flex:1;min-width:0}
.panel,.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:20px 22px;margin:0 0 18px}
.panel h2{font-size:19px}
.muted{color:var(--muted)}
.stats{display:flex;gap:28px;flex-wrap:wrap}
.stat{display:flex;flex-direction:column}
.stat .k{font-size:24px;font-weight:700}
.stat .v{color:var(--muted);font-size:13px}
.sources{margin-top:14px;font-size:13px}
.sources ul{margin:8px 0 0;padding-left:18px;color:var(--muted)}
.sheets-h{margin:8px 4px 14px;font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.sheet-head{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:14px}
.sheet-head h3{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;font-size:18px;margin:0}
.sheet-num{font-weight:700}
.sheet-title{font-weight:500;color:var(--muted);font-size:15px}
.sheet-sub{color:var(--muted);font-size:12px;margin-top:6px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.badge{font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:#eef1f5;color:var(--muted)}
.badge.ok{background:#e7f7f0;color:var(--ok)}
.badge.cached{background:#eef1f5;color:var(--cached)}
.badge.failed{background:var(--failed-soft);color:var(--failed)}
.badge.disc{background:var(--accent-soft);color:var(--accent)}
.badge.coordb{background:var(--coord-soft);color:var(--coord)}
.badge.warnb{background:#fef9c3;color:#92600a}
.badge.tok{background:#f1f3f7;color:var(--muted);font-weight:500}
.sheet-body :is(h3,h4,h5,h6){margin-top:1.2em}
.sheet-body table,.panel table{border-collapse:collapse;width:100%;font-size:13.5px;margin:.4em 0}
.table-wrap{overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
thead th{background:#f3f5f8}
code{background:#f1f3f7;padding:.1em .35em;border-radius:4px;font-size:.92em}
pre.code{background:#0f172a;color:#e2e8f0;padding:12px 14px;border-radius:8px;overflow:auto}
pre.code code{background:none;color:inherit;padding:0}
blockquote{margin:.6em 0;padding:.3em 0 .3em 14px;border-left:3px solid var(--line);color:var(--muted)}
.sec-h{font-size:14.5px;margin:1.1em 0 .3em}
.callout{border-radius:10px;padding:12px 16px;margin:14px 0;border:1px solid}
.callout-tag{display:inline-block;font-size:11.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.04em;margin-bottom:4px}
.callout.coord{background:var(--coord-soft);border-color:#fed7aa}
.callout.coord .callout-tag{color:var(--coord)}
.callout.failedc{background:var(--failed-soft);border-color:#fecaca}
.callout.failedc .callout-tag{color:var(--failed)}
.issues{border-color:#fed7aa;background:linear-gradient(180deg,var(--coord-soft),#fff 120px)}
.issue-card{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0;background:#fff}
.issue-card h3{font-size:15px}
.issues-sub{margin:18px 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.raw{margin-top:14px;border-top:1px dashed var(--line);padding-top:10px}
.raw summary{cursor:pointer;color:var(--muted);font-size:12.5px;font-weight:600}
.raw pre{white-space:pre-wrap;word-wrap:break-word;background:#f8fafc;border:1px solid var(--line);
  border-radius:8px;padding:12px 14px;font-size:12.5px;margin-top:10px}
.hidden{display:none!important}
.empty-note{padding:30px;text-align:center;color:var(--muted)}
@media(max-width:900px){
  .layout{flex-direction:column}
  .sidebar{position:static;width:100%;flex:1;max-height:none}
}
@media print{
  .topbar,.sidebar,.filters,.raw{display:none!important}
  .layout{display:block;padding:0}
  .panel,.card{break-inside:avoid;border-color:#ccc}
}
"""

_SCRIPT = """
(function(){
  var q=document.getElementById('q');
  var chips=Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var sheets=Array.prototype.slice.call(document.querySelectorAll('.sheet'));
  var tocSheets=Array.prototype.slice.call(document.querySelectorAll('.toc-sheet'));
  var issueCards=Array.prototype.slice.call(document.querySelectorAll('.issue-card'));
  var filter={mode:'all',value:''};

  function matchesFilter(el){
    if(filter.mode==='all') return true;
    if(filter.mode==='coord') return el.getAttribute('data-coord')==='1';
    if(filter.mode==='failed') return el.getAttribute('data-failed')==='1';
    if(filter.mode==='disc') return el.getAttribute('data-discipline')===filter.value;
    return true;
  }
  function matchesQuery(el,text){
    if(!text) return true;
    return (el.textContent||'').toLowerCase().indexOf(text)>=0;
  }
  function apply(){
    var text=(q.value||'').trim().toLowerCase();
    sheets.forEach(function(s){
      var show=matchesFilter(s)&&matchesQuery(s,text);
      s.classList.toggle('hidden',!show);
      var toc=document.querySelector('.toc-sheet[data-key="'+s.id+'"]');
      if(toc) toc.classList.toggle('hidden',!show);
    });
    issueCards.forEach(function(c){
      var ok=true;
      if(filter.mode==='failed') ok=c.getAttribute('data-kind')==='failed';
      else if(filter.mode==='coord') ok=c.getAttribute('data-kind')==='coord';
      else if(filter.mode==='disc') ok=c.getAttribute('data-discipline')===filter.value;
      c.classList.toggle('hidden',!(ok&&matchesQuery(c,text)));
    });
  }
  chips.forEach(function(ch){
    ch.addEventListener('click',function(){
      chips.forEach(function(c){c.classList.remove('active')});
      ch.classList.add('active');
      filter.mode=ch.getAttribute('data-filter');
      filter.value=ch.getAttribute('data-value')||'';
      apply();
    });
  });
  if(q) q.addEventListener('input',apply);

  // Highlight the section currently in view in the sidebar.
  var byId={};
  tocSheets.forEach(function(t){byId[t.getAttribute('data-key')]=t});
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        var t=byId[e.target.id];
        if(t) t.classList.toggle('current',e.isIntersecting);
      });
    },{rootMargin:'-40% 0px -55% 0px'});
    sheets.forEach(function(s){io.observe(s)});
  }
})();
"""

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{styles}</style>
</head>
<body>
<header class="topbar">
  <div class="brand">{brand}</div>
  <div class="meta">Generated {generated} · {sheet_count} sheet(s)</div>
  <input id="q" class="search" type="search" placeholder="Search sheets, tags, notes…" aria-label="Search">
</header>
<div class="layout">
  <nav class="sidebar">
    <div class="filters">{chips}</div>
    {toc}
  </nav>
  <main class="content">
    {summary}
    {issues}
    {overview}
    <div class="sheets-h">Sheets</div>
    {sheets}
  </main>
</div>
<script>{script}</script>
</body>
</html>
"""
