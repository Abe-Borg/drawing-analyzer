"""Live view insight tabs: Story, Thinking, Plan and Findings.

The board (:mod:`~drawing_analyzer.live_scene`) shows *that* a run is moving.
These four views show what it is doing and why, from the same
:class:`~drawing_analyzer.live_view.LiveRunModel`:

* **Story** — the pipeline as a timeline: what each stage does, in plain
  words, its live progress, the model and effort it runs at, where the spend
  goes, and a few computed insights (:func:`insights`).
* **Thinking** — the models' own reasoning summaries, call by call, as they
  arrive (:mod:`~drawing_analyzer.thought_stream`), beside the calls in flight.
* **Plan** — what the set was identified as (disciplines, place, adopted code
  editions) and the review checklist, a person's and the model's, with each
  item's answers filling in sheet by sheet.
* **Findings** — the path from "reported by a read" to "proven on the PDF":
  reported → merged in the ledger → placed on the sheet → re-checked, with
  the findings themselves listed underneath.

Tk-free and pure like the board: each view appends :class:`Prim`s to the frame
for the rectangle it is given. A canvas cannot clip, so a scrolling list emits
only the rows inside its rectangle and fades the ones at its edges. Text is
laid out by the scene's width estimate, never by asking a toolkit.
"""
from __future__ import annotations

import textwrap
from typing import Any

from .live_scene import (
    ACCENT,
    ACCENT_GLOW,
    AMBER,
    BG,
    BUCKET_COLOR,
    CYAN,
    GREEN,
    GREEN_GLOW,
    INK,
    INK_DIM,
    INK_FAINT,
    MONO,
    PANEL,
    PURPLE,
    PURPLE_GLOW,
    RED,
    STATUS_COLOR,
    WHITE,
    fit,
    fmt_duration,
    fmt_money,
    fmt_tokens,
    line,
    mix,
    oval,
    poly,
    pulse,
    rect,
    rounded_rect_points,
    text,
    text_width,
)
from .live_view import (
    ANCHOR_BUCKETS,
    CHECK_STATUSES,
    FINDING_BUCKETS,
    PHASE_IDLE,
    PHASE_RUNNING,
    SHEET_CACHED,
    SHEET_QUEUED,
    SHEET_READING,
    SHEET_TERMINAL,
    SOURCE_LABELS,
    STAGE_ACTIVE,
    STAGE_DONE,
    STAGE_SKIPPED,
    family_label,
)

TAB_BOARD = "board"
TAB_STORY = "story"
TAB_MIND = "mind"
TAB_PLAN = "plan"
TAB_FINDINGS = "findings"
TABS: tuple[tuple[str, str], ...] = (
    (TAB_BOARD, "BOARD"),
    (TAB_STORY, "STORY"),
    (TAB_MIND, "THINKING"),
    (TAB_PLAN, "PLAN"),
    (TAB_FINDINGS, "FINDINGS"),
)
TAB_KEYS = tuple(key for key, _label in TABS)

# What each stage does, in the words a reviewer would use. One sentence each:
# the Story tab shows it under the stage's name.
STAGE_STORY: dict[str, str] = {
    "inventory": "Checks every input: a readable PDF, within the size limits. "
                 "Nothing is sent until the set is known to be sound.",
    "digest": "Reads every sheet whole: an overview image, a grid of high-resolution "
              "tiles and the sheet's exact text layer, in one request per sheet.",
    "identity": "One text-only pass works out what the set is: its disciplines, where "
                "the project sits, its units and the code editions it adopts.",
    "review_plan": "The model writes a review checklist for each discipline it found, "
                   "naming code, section and edition. Every critique must answer each item.",
    "critique": "A second, adversarial read of every sheet, run twice. Its only job is "
                "finding problems; what both reads find is marked reproduced.",
    "cross_qc": "A text-only hunt for conflicts between sheets: a value on one sheet "
                "that disagrees with the same thing on another.",
    "synthesis": "Writes the set overview from the sheet digests.",
    "focus": "Answers your focus question across the whole set.",
    "auditors": "Five offline checkers: references, arithmetic, naming, title blocks and "
                "the sheet index. No model call; the math is done here in exact decimals.",
    "prose_harvest": "Collects the coordination and conflict items written in prose, so "
                     "none is left out of the findings ledger.",
    "edition_audit": "Compares every cited code edition with the editions the set "
                     "adopts. Offline; a stale edition becomes a finding.",
    "anchor": "Pins each finding to its spot on the PDF by finding its quote in the "
              "sheet's text layer. A quote that cannot be found is a warning sign.",
    "absence_check": "For every finding that says something is missing, searches the "
                     "other sheets' text for it before trusting the claim.",
    "verification": "Re-checks each finding against a fresh high-resolution crop of the "
                    "spot it cites: verified, rejected or uncertain.",
    "investigation": "Gives uncertain findings a closer look: the model may ask for more "
                     "crops, a text search or the whole sheet before it decides.",
    "citation": "Looks up each cited code section on the web and checks the drawing's "
                "claim against the source.",
    "markup": "Draws the findings on a copy of the PDF, then reopens the file and proves "
              "every mark is really there.",
}

SEVERITY_COLOR = {"high": RED, "medium": AMBER, "low": ACCENT_GLOW}
CHECK_COLOR = {
    "VIOLATED": RED,
    "UNDETERMINED": AMBER,
    "MET": GREEN,
    "NOT_APPLICABLE": "#4B5B76",
    "UNANSWERED": "#2A3A55",
}
ANCHOR_COLOR = {"exact": GREEN, "fuzzy": CYAN, "tile": AMBER, "unplaced": "#6B5560"}
FAMILY_COLOR = {
    "digest": ACCENT_GLOW,
    "critique": PURPLE_GLOW,
    "verify": GREEN_GLOW,
    "investigate": AMBER,
    "citation": CYAN,
    "cross_qc": "#F9A8D4",
}
BUCKET_TEXT = dict(FINDING_BUCKETS)


# --------------------------------------------------------------------------- #
# Small shared pieces.
# --------------------------------------------------------------------------- #


def short_model(model: str) -> str:
    """``claude-opus-5-5`` → ``opus-5-5`` (the tabs have little room)."""
    model = str(model or "")
    return model[7:] if model.startswith("claude-") else model


def caps_width(value: str, size: float) -> float:
    """Layout width of a bold small-caps label (wider than mixed-case text)."""
    return len(str(value)) * size * 0.72


def edge_fade(y: float, top: float, bottom: float, s: float) -> float:
    """1 in the middle of a scrolling list, falling to 0 at its edges."""
    return max(0.0, min(1.0, (y - top) / (9 * s), (bottom - y) / (9 * s)))


def panel(out: list, key: str, x0, y0, x1, y1, s, *, outline: str = INK_FAINT) -> None:
    out.append(poly(key, rounded_rect_points(x0, y0, x1, y1, 6 * s),
                    fill=PANEL, outline=outline, width=1, smooth=True))


def caption(out: list, key: str, x, y, title: str, note: str, width: float, s) -> None:
    """A section title in small caps with a plain-text note after it."""
    out.append(text(f"{key}_t", x, y, title, fill=INK_DIM, size=9.5 * s, weight="bold"))
    tw = caps_width(title, 9.5 * s) + 10 * s
    out.append(text(f"{key}_n", x + tw, y, fit(note, max(0.0, width - tw), 9.5 * s),
                    fill=INK, size=9.5 * s))


def placeholder(out: list, key: str, x0, y0, x1, y1, lines: list[str], s) -> None:
    """Centered explanatory text for a view that has nothing to show yet."""
    cy = (y0 + y1) / 2.0 - (len(lines) - 1) * 8 * s
    for i, ln in enumerate(lines):
        out.append(text(f"{key}_{i}", (x0 + x1) / 2.0, cy + i * 16 * s,
                        fit(ln, x1 - x0 - 16 * s, 10.5 * s),
                        fill=INK_DIM if i == 0 else INK_FAINT, size=10.5 * s, anchor="center"))


def stacked_bar(out: list, key: str, x0, y0, x1, y1, parts: list, *, grow: float = 1.0) -> None:
    """A horizontal bar split by ``parts`` = ``[(part key, count, color)]``."""
    total = sum(n for _k, n, _c in parts)
    out.append(rect(f"{key}_bg", x0, y0, x1, y1, fill="#101D33"))
    cursor = x0
    span = (x1 - x0) * max(0.0, min(1.0, grow))
    for part, n, color in parts:
        w = span * n / total if total else 0.0
        out.append(rect(f"{key}_{part}", cursor, y0, cursor + max(0.0, w - (1 if w > 2 else 0)),
                        y1, fill=color if n else BG))
        cursor += w


def scrollbar(out: list, key: str, x, y0, y1, offset: float, content: float, s) -> None:
    view = y1 - y0
    if content <= view + 1 or view <= 8:
        out.append(rect(key, x, y0, x, y0, fill=BG))
        return
    size = max(14 * s, view * view / content)
    top = y0 + (view - size) * (offset / max(1.0, content - view))
    out.append(rect(key, x - 2.5 * s, top, x, top + size, fill=INK_FAINT))


# --------------------------------------------------------------------------- #
# The tab strip.
# --------------------------------------------------------------------------- #


def tab_badges(model: Any) -> dict:
    """The count each tab shows beside its name (absent: no badge)."""
    badges: dict[str, int] = {}
    if model.thoughts:
        badges[TAB_MIND] = len(model.thoughts)
    items = sum(len(g.items) for g in model.checklist)
    if items:
        badges[TAB_PLAN] = items
    found = model.ledger_total or sum(model.found.values())
    if found:
        badges[TAB_FINDINGS] = found
    return badges


def tab_news(model: Any) -> dict:
    """When each tab's content last changed (the model's animation clock)."""
    return {
        TAB_MIND: model.thoughts_changed_at,
        TAB_PLAN: model.insights_changed_at if (model.identity or model.checklist) else 0.0,
        TAB_FINDINGS: model.insights_changed_at if (model.ledger_total or model.found) else 0.0,
    }


def tab_strip(scene: Any, out: list, model: Any, x0, x1, y, s, t, dt) -> None:
    """The row of tabs under the HUD; records each tab's hit box on the scene."""
    scene._tab_hits = []
    badges, news = tab_badges(model), tab_news(model)
    size = 10 * s
    cx = x0
    active_box = None
    thinking_now = any(th.open for th in model.thoughts)
    for key, label in TABS:
        badge = badges.get(key)
        badge_text = fmt_tokens(badge) if badge else ""
        lw = caps_width(label, size)
        w = lw + (text_width(badge_text, size) + 5 * s if badge_text else 0.0) + 18 * s
        active = key == scene.tab
        hot = scene.hover is not None and cx <= scene.hover[0] <= cx + w \
            and y - 11 * s <= scene.hover[1] <= y + 11 * s
        color = INK if active else (ACCENT_GLOW if hot else INK_DIM)
        out.append(text(f"tab_{key}", cx + 6 * s, y, label, fill=color, size=size,
                        weight="bold" if active else "normal"))
        if badge_text:
            out.append(text(f"tab_{key}_b", cx + 6 * s + lw + 5 * s, y, badge_text,
                            fill=INK_DIM, size=size))
        else:
            out.append(text(f"tab_{key}_b", -100, -100, "", fill=BG, size=size))
        # Something new landed on a tab the user is not looking at: a dot.
        fresh = not active and news.get(key, 0.0) > scene._tab_seen.get(key, 0.0)
        live = key == TAB_MIND and thinking_now and model.phase == PHASE_RUNNING
        if fresh or live:
            # It pulses only while a run is in flight: a finished board rests.
            running = model.phase == PHASE_RUNNING
            glow = pulse(t, 1.1) if running else 0.0
            dot = PURPLE if key == TAB_MIND else ACCENT
            out.append(oval(f"tab_{key}_dot", cx + w - 6 * s, y - 6 * s, (1.6 + 1.0 * glow) * s,
                            fill=mix(dot, WHITE, 0.4 * glow)))
            if running:
                scene.animating = True
        else:
            out.append(oval(f"tab_{key}_dot", -10, -10, 0, fill=BG))
        if active:
            active_box = (cx + 4 * s, cx + w - 10 * s)
            scene._tab_seen[key] = max(scene._tab_seen.get(key, 0.0), t)
        scene._tab_hits.append((cx, y - 11 * s, cx + w, y + 11 * s, key))
        cx += w + 4 * s
    out.append(line("tab_rule", (x0, y + 11 * s, x1, y + 11 * s), fill=INK_FAINT, width=1,
                    capstyle="butt"))
    if active_box is not None:
        ux0 = scene._ease("tab_u0", active_box[0], dt, rate=16.0)
        ux1 = scene._ease("tab_u1", active_box[1], dt, rate=16.0)
        out.append(line("tab_under", (ux0, y + 11 * s, ux1, y + 11 * s), fill=ACCENT,
                        width=2.5 * s, capstyle="butt"))


# --------------------------------------------------------------------------- #
# Story.
# --------------------------------------------------------------------------- #


def stage_now_line(model: Any, st: Any) -> str:
    """What an active stage is doing this moment, as one sentence."""
    sheets = model.sheets
    if st.name == "digest" and sheets:
        counts = model.sheet_counts()
        done = sum(counts.get(k, 0) for k in SHEET_TERMINAL)
        bits = [f"{done} of {len(sheets)} sheets read"]
        if counts.get(SHEET_READING):
            bits.append(f"{counts[SHEET_READING]} streaming now")
        if counts.get(SHEET_QUEUED):
            bits.append(f"{counts[SHEET_QUEUED]} waiting in the batch queue")
        if counts.get(SHEET_CACHED):
            bits.append(f"{counts[SHEET_CACHED]} from cache")
        return " · ".join(bits)
    if st.name == "critique" and sheets:
        done = sum(sh.critique_done for sh in sheets)
        pending = sum(sh.critique_open + sh.critique_queued for sh in sheets)
        return f"{done} critique read(s) back" + (f" · {pending} still out" if pending else "")
    if st.name == "verification" and model.findings_sealed:
        return f"{model.findings_verified} of {model.findings_sealed} findings re-checked"
    total = st.calls_done + st.calls_open + st.calls_queued
    if total:
        bits = [f"{st.calls_done} of {total} request(s) answered"]
        if st.calls_open:
            bits.append(f"{st.calls_open} in flight")
        if st.calls_queued:
            bits.append(f"{st.calls_queued} in the batch queue")
        return " · ".join(bits)
    return "working on this computer (no model call)"


def stage_recipe(st: Any) -> str:
    """The model, effort and thinking mode a stage's calls were given."""
    if not st.model:
        return ""
    bits = [short_model(st.model)]
    if st.effort:
        bits.append(f"effort {st.effort}")
    if st.thinking and st.thinking not in ("omitted", "?"):
        bits.append(f"{st.thinking} thinking")
    if st.batch:
        bits.append("batch (half price)")
    return " · ".join(bits)


def stage_figures(model: Any, st: Any) -> str:
    """A stage's calls, tokens and spend, as far as they are known."""
    bits = []
    if st.calls_done:
        bits.append(f"{st.calls_done} call(s)")
    tokens = st.tokens_in + st.tokens_out
    if tokens:
        bits.append(f"{fmt_tokens(tokens)} tokens")
    if st.cost:
        bits.append(fmt_money(st.cost, estimate=not model.cost_final))
    return " · ".join(bits)


def insights(model: Any) -> list[tuple[str, str]]:
    """Plain-language observations about the run so far: ``[(level, text)]``.

    Each is derived from figures the board already holds; a figure that is not
    known yet contributes nothing.
    """
    out: list[tuple[str, str]] = []
    n = len(model.sheets)
    if model.phase == PHASE_IDLE:
        if n:
            out.append(("info", f"{n} sheet(s) loaded; {len(model.stages)} stage(s) will run."))
            if not any(st.name == "critique" for st in model.stages):
                out.append(("info", "A standard read. QC Markups adds the plan, the "
                                    "critique reads, the re-checks and the marked-up PDF."))
        return out
    counts = model.sheet_counts()
    cached = counts.get(SHEET_CACHED, 0)
    if cached:
        out.append(("good", f"{cached} of {n} sheet(s) came from the cache: no charge, "
                            "no wait."))
    digest = next((st for st in model.stages if st.name == "digest"), None)
    if digest is not None and digest.calls_done:
        per = (digest.tokens_in + digest.tokens_out) / digest.calls_done
        if per:
            out.append(("info", f"A sheet read takes about {fmt_tokens(per)} tokens, "
                                "nearly all of it the sheet's images."))
    if any(st.batch for st in model.stages):
        out.append(("info", "Batch reads cost half price; their replies arrive together "
                            "when the queue clears."))
    spend = sum(float(st.cost) for st in model.stages)
    if spend > 0:
        top = max(model.stages, key=lambda st: float(st.cost))
        share = float(top.cost) / spend
        if share >= 0.3:
            out.append(("info", f"{top.long_label} is {share:.0%} of the spend so far."))
    if model.thoughts_seen:
        out.append(("info", f"{model.thoughts_with_text} of {model.thoughts_seen} call(s) "
                            "returned a reasoning summary (Thinking tab)."))
    items = [it for g in model.checklist for it in g.items]
    if items:
        flagged = sum(1 for it in items if it.counts.get("VIOLATED"))
        tail = f"; {flagged} flagged on at least one sheet" if flagged else ""
        out.append(("warn" if flagged else "info",
                    f"The review checklist has {len(items)} check(s){tail} (Plan tab)."))
    if model.ledger_total:
        buckets = model.ledger_by.get("bucket", {})
        merged = model.merged_reports()
        text_ = f"{model.ledger_total} finding(s) in the ledger"
        if merged > 0:
            text_ += f" after merging {merged} duplicate report(s)"
        if buckets.get("rejected"):
            text_ += f"; the re-check threw out {buckets['rejected']}"
        out.append(("info", text_ + "."))
    if model.retries:
        out.append(("warn", f"The API pushed back {model.retries} time(s); each request "
                            "waited and was sent again."))
    if model.spend_limit:
        out.append(("bad", "An API spend limit was reached: nothing further is sent."))
    return out


def story(scene: Any, out: list, model: Any, x0, y0, x1, y1, s, t, dt) -> None:
    split = (x1 - x0) >= 620 * s
    left_x1 = x0 + (x1 - x0) * 0.62 if split else x1
    _story_timeline(scene, out, model, x0, y0, left_x1 - (8 * s if split else 0), y1, s, t, dt)
    if split:
        _story_side(scene, out, model, left_x1 + 6 * s, y0, x1, y1, s, t, dt)


def _story_timeline(scene, out, model, x0, y0, x1, y1, s, t, dt) -> None:
    stages = list(model.stages)
    done = sum(1 for st in stages if st.state == STAGE_DONE)
    caption(out, "st_cap", x0, y0 + 6 * s, "PIPELINE",
            f"{done} of {len(stages)} stage(s) finished" if model.phase != PHASE_IDLE
            else f"{len(stages)} stage(s) planned", x1 - x0, s)
    top, bottom = y0 + 16 * s, y1
    if not stages or bottom - top < 24 * s:
        return
    # Row heights: an active stage opens up to show its live line and recipe.
    heights = [(80 if st.state == STAGE_ACTIVE else 34) * s for st in stages]
    content = sum(heights)
    follow = None
    acc = 0.0
    for st, h in zip(stages, heights):
        if st.state == STAGE_ACTIVE:
            # Keep the stage before it in view above, the ones to come below.
            follow = acc - 36 * s
            break
        acc += h
    off = scene.scroll_offset(TAB_STORY, content, bottom - top, dt, follow=follow)
    gx = x0 + 9 * s
    tx = x0 + 24 * s
    # Where each row's node sits, and which rows fit the rectangle.
    node_ys: list[float] = []
    y = top - off
    for h in heights:
        node_ys.append(y + 11 * s)
        y += h
    shown = [ny for ny in node_ys if ny >= top + 4 * s and ny + 15 * s <= bottom]
    if len(shown) > 1:
        out.append(line("st_spine", (gx, shown[0], gx, shown[-1]), fill=INK_FAINT,
                        width=1.5 * s))
    for i, (st, ny) in enumerate(zip(stages, node_ys)):
        visible = ny >= top + 4 * s and ny + 15 * s <= bottom
        k = f"st{i}"
        if visible:
            fade = edge_fade(ny, top - 2 * s, bottom, s)
            active = st.state == STAGE_ACTIVE
            if active:
                color, ink = ACCENT, INK
            elif st.state == STAGE_DONE:
                color, ink = STATUS_COLOR.get(st.status, GREEN), INK
            elif st.state == STAGE_SKIPPED:
                color, ink = INK_FAINT, INK_FAINT
            else:
                color, ink = INK_DIM, INK_DIM
            if active:
                halo = pulse(t, 1.4)
                out.append(oval(f"{k}_h", gx, ny, (5 + 5 * halo) * s,
                                outline=mix(ACCENT_GLOW, BG, halo), width=1.3 * s))
                scene.animating = True
            else:
                out.append(oval(f"{k}_h", gx, ny, 0, outline=BG, width=1))
            filled = st.state in (STAGE_ACTIVE, STAGE_DONE)
            out.append(oval(f"{k}_n", gx, ny, 4.5 * s, fill=mix(BG, color, fade) if filled else BG,
                            outline=mix(BG, color, fade), width=1.5 * s))
            right = _stage_right(model, st)
            rw = text_width(right, 9.5 * s)
            out.append(text(f"{k}_r", x1 - 6 * s, ny, right, fill=mix(BG, color if filled else INK_FAINT, fade),
                            size=9.5 * s, anchor="e"))
            out.append(text(f"{k}_t", tx, ny, fit(st.long_label, x1 - tx - rw - 16 * s, 11.5 * s),
                            fill=mix(BG, ink, fade), size=11.5 * s,
                            weight="bold" if active else "normal"))
            why = st.note if (st.state == STAGE_DONE and st.note) else STAGE_STORY.get(st.name, "")
            why_color = AMBER if (st.state == STAGE_DONE and st.note) else INK_DIM
            if st.state == STAGE_SKIPPED:
                why, why_color = "Did not run.", INK_FAINT
            wy = ny + 15 * s
            width = x1 - tx - 8 * s
            if active:
                cols = max(20, int(width / (9.5 * s * 0.56)))
                wrapped = scene.wrap(("story", st.name, cols), why, cols)[:2]
                for j in range(2):
                    if wy + j * 12.5 * s > bottom - 4 * s:
                        break
                    out.append(text(f"{k}_w{j}", tx, wy + j * 12.5 * s,
                                    wrapped[j] if j < len(wrapped) else "", fill=INK_DIM,
                                    size=9.5 * s))
                ly = wy + 26 * s
                if ly + 13 * s <= bottom - 2 * s:
                    out.append(text(f"{k}_now", tx, ly, fit("▸ " + stage_now_line(model, st), width,
                                                            10 * s),
                                    fill=ACCENT_GLOW, size=10 * s, weight="bold"))
                    recipe = " · ".join(b for b in (stage_recipe(st), stage_figures(model, st)) if b)
                    out.append(text(f"{k}_rec", tx, ly + 13 * s, fit(recipe, width, 9 * s),
                                    fill=INK_DIM, size=9 * s, family=MONO))
            else:
                out.append(text(f"{k}_w0", tx, wy, fit(why, width, 9.5 * s),
                                fill=mix(BG, why_color, fade), size=9.5 * s))
                scene.add_tip(tx, ny - 9 * s, x1, wy + 8 * s, _stage_tip(model, st))
    scrollbar(out, "st_sb", x1, top, bottom, off, content, s)


def _stage_right(model: Any, st: Any) -> str:
    if st.state == STAGE_ACTIVE:
        return "running · " + fmt_duration(st.duration(model._wall()))
    if st.state == STAGE_DONE:
        word = {"COMPLETE": "done", "SKIPPED_VALID": "nothing to do", "PARTIAL": "partial",
                "FAILED": "failed", "STOPPED": "stopped"}.get(st.status, st.status.lower() or "done")
        dur = st.duration(model._wall())
        return word + (f" · {fmt_duration(dur)}" if dur is not None and dur >= 1 else "")
    if st.state == STAGE_SKIPPED:
        return "skipped"
    return "planned"


def _stage_tip(model: Any, st: Any) -> list[str]:
    lines = [st.long_label, STAGE_STORY.get(st.name, "")]
    for extra in (stage_recipe(st), stage_figures(model, st), st.note):
        if extra:
            lines.append(extra)
    return [ln for ln in lines if ln]


def _story_side(scene, out, model, x0, y0, x1, y1, s, t, dt) -> None:
    priced = [st for st in model.stages if st.cost]
    use_cost = bool(priced)
    rows = priced or [st for st in model.stages if st.tokens_in + st.tokens_out]
    value = (lambda st: float(st.cost)) if use_cost else (lambda st: float(st.tokens_in + st.tokens_out))
    caption(out, "sp_cap", x0, y0 + 6 * s, "WHERE THE SPEND GOES" if use_cost else "TOKENS BY STAGE",
            "", x1 - x0, s)
    y = y0 + 20 * s
    row_h = 15 * s
    notes = insights(model)
    room = max(0, int(((y1 - y) - min(len(notes), 4) * 26 * s - 22 * s) // row_h))
    rows = sorted(rows, key=value, reverse=True)[:max(0, room)]
    peak = max((value(st) for st in rows), default=0.0)
    label_w = 62 * s
    for i, st in enumerate(rows):
        v = value(st)
        shown = scene._ease(f"sp_{st.name}", v, dt, rate=4.0)
        frac = shown / peak if peak else 0.0
        label = fmt_money(v, estimate=not model.cost_final) if use_cost else fmt_tokens(v)
        vw = text_width(label, 9 * s, mono=True) + 6 * s
        bx0, bx1 = x0 + label_w, x1 - vw
        active = st.state == STAGE_ACTIVE
        out.append(text(f"sp{i}_l", x0, y + row_h / 2, fit(st.label, label_w - 4 * s, 9.5 * s),
                        fill=INK if active else INK_DIM, size=9.5 * s))
        out.append(rect(f"sp{i}_bg", bx0, y + 4 * s, bx1, y + row_h - 4 * s, fill="#101D33"))
        color = mix(ACCENT, ACCENT_GLOW, pulse(t, 1.2)) if active else GREEN
        out.append(rect(f"sp{i}_b", bx0, y + 4 * s, bx0 + max(0.0, (bx1 - bx0) * min(1.0, frac)),
                        y + row_h - 4 * s, fill=color))
        out.append(text(f"sp{i}_v", x1, y + row_h / 2, label, fill=INK, size=9 * s, anchor="e",
                        family=MONO))
        y += row_h
    if not rows:
        out.append(text("sp_none", x0, y + 6 * s,
                        fit("Appears with the first paid reply.", x1 - x0, 9.5 * s),
                        fill=INK_FAINT, size=9.5 * s))
        y += 18 * s
    y += 10 * s
    if y1 - y < 24 * s or not notes:
        return
    caption(out, "in_cap", x0, y, "INSIGHTS", "", x1 - x0, s)
    y += 14 * s
    cols = max(18, int((x1 - x0 - 12 * s) / (9.5 * s * 0.56)))
    slot = 0
    for level, note in notes:
        wrapped = scene.wrap(("ins", note, cols), note, cols)[:3]
        if y + len(wrapped) * 12.5 * s > y1:
            break
        dot = {"good": GREEN, "warn": AMBER, "bad": RED}.get(level, ACCENT_GLOW)
        out.append(oval(f"in{slot}_d", x0 + 3 * s, y + 1 * s, 2.2 * s, fill=dot))
        for j, ln in enumerate(wrapped):
            out.append(text(f"in{slot}_{j}", x0 + 11 * s, y + j * 12.5 * s, ln, fill=INK,
                            size=9.5 * s))
        y += len(wrapped) * 12.5 * s + 5 * s
        slot += 1


# --------------------------------------------------------------------------- #
# Thinking.
# --------------------------------------------------------------------------- #

MIND_LINE = 13.5          # line pitch of the feed, in unscaled pixels
REVEAL_CHARS_PER_SECOND = 700.0


def thought_feed(scene: Any, model: Any, cols: int, t: float) -> list[tuple]:
    """The feed as display lines: ``("head", thought)``, ``("body", str,
    thought)`` and ``("gap",)``, oldest thought first."""
    lines: list[tuple] = []
    for th in model.thoughts:
        body = th.text
        if th.transport != "stream" and body:
            # A summary that arrived whole is typed out rather than dumped.
            age = t - th.started_at
            if 0.0 <= age < len(body) / REVEAL_CHARS_PER_SECOND:
                body = body[: max(1, int(age * REVEAL_CHARS_PER_SECOND))]
                scene.animating = scene.fast = True
        lines.append(("head", th))
        if body:
            # Keyed by the text itself: sequence numbers restart with each run.
            for ln in scene.wrap(("th", cols, body), body, cols):
                lines.append(("body", ln, th))
            if th.truncated and len(body) == len(th.text):
                lines.append(("body", "… (the summary continues; trimmed here)", th))
        elif th.open:
            lines.append(("wait", th))
        lines.append(("gap",))
    if lines:
        lines.pop()
    return lines


def mind(scene: Any, out: list, model: Any, x0, y0, x1, y1, s, t, dt) -> None:
    split = (x1 - x0) >= 600 * s
    feed_x1 = x0 + (x1 - x0) * 0.7 if split else x1
    _mind_feed(scene, out, model, x0, y0, feed_x1 - (8 * s if split else 0), y1, s, t, dt)
    if split:
        _mind_now(scene, out, model, feed_x1 + 6 * s, y0, x1, y1, s, t)


def _mind_empty(model: Any) -> list[str]:
    if model.thoughts_enabled is False:
        return ["Reasoning summaries are switched off for this run.",
                "(DRAWING_ANALYZER_SHOW_THINKING=0)"]
    if model.phase == PHASE_RUNNING:
        lines = ["Waiting for the first reasoning summary…"]
        if model.calls_queued and not model.calls_in_flight:
            lines.append("Batch reads report their reasoning when the batch comes back.")
        elif model.thoughts_seen:
            lines.append(f"{model.thoughts_seen} call(s) so far returned none.")
        return lines
    if model.phase == PHASE_IDLE:
        return ["During a run, the model's own reasoning appears here, call by call.",
                "It is the API's summary of what the model thought through:",
                "shown on this screen only, never saved with the results."]
    return ["No reasoning summaries were returned in this run.",
            "Cached sheets and offline stages make no model call."]


def _mind_feed(scene, out, model, x0, y0, x1, y1, s, t, dt) -> None:
    note = ""
    if model.thoughts_seen:
        note = f"{model.thoughts_with_text} of {model.thoughts_seen} call(s) summarized"
    caption(out, "mi_cap", x0, y0 + 6 * s, "WHAT THE MODEL IS THINKING", note, x1 - x0, s)
    top, bottom = y0 + 16 * s, y1
    panel(out, "mi_frame", x0, top, x1, bottom, s)
    ix0, ix1 = x0 + 10 * s, x1 - 10 * s
    iy0, iy1 = top + 6 * s, bottom - 6 * s
    if not model.thoughts:
        placeholder(out, "mi_empty", ix0, iy0, ix1, iy1, _mind_empty(model), s)
        return
    size = 10 * s
    pitch = MIND_LINE * s
    cols = max(24, int((ix1 - ix0 - 6 * s) / (size * 0.6)))
    lines = thought_feed(scene, model, cols, t)
    content = len(lines) * pitch
    view = iy1 - iy0
    max_off = max(0.0, content - view)
    off = scene.scroll_offset(TAB_MIND, content, view, dt,
                              follow=max_off if scene.follow.get(TAB_MIND, True) else None)
    first = max(0, int(off // pitch))
    slot = 0
    for idx in range(first, len(lines)):
        ly = iy0 + idx * pitch - off + pitch / 2.0
        if ly > iy1 - pitch / 2.0 + 1:
            break
        if ly < iy0 + pitch / 2.0 - 1:
            continue
        entry = lines[idx]
        fade = edge_fade(ly, iy0 - 2 * s, iy1 + 2 * s, s)
        k = f"mi_l{slot}"
        slot += 1
        kind = entry[0]
        if kind == "gap":
            out.append(text(k, ix0, ly, "", fill=PANEL, size=size, family=MONO))
            out.append(text(f"{k}r", ix1, ly, "", fill=PANEL, size=size, anchor="e"))
            continue
        th = entry[-1]
        color = FAMILY_COLOR.get(th.stage, INK_DIM)
        if kind == "head":
            state, state_color = _thought_state(th, t)
            sw = text_width(state, 9 * s) + 10 * s
            head = f"{family_label(th.stage).upper()}  ·  {model.item_label(th.item) or 'whole set'}"
            if th.model:
                head += f"  ·  {short_model(th.model)}"
            out.append(text(k, ix0, ly, fit(head, ix1 - ix0 - sw, 9.5 * s),
                            fill=mix(PANEL, color, fade), size=9.5 * s, weight="bold"))
            out.append(text(f"{k}r", ix1, ly, state, fill=mix(PANEL, state_color, fade),
                            size=9 * s, anchor="e"))
            if th.open:
                scene.animating = True
        elif kind == "wait":
            dots = "." * (1 + int(t * 2.5) % 3)
            msg = (f"writing the answer{dots}" if th.chars_out else f"thinking{dots}")
            out.append(text(k, ix0 + 6 * s, ly, msg, fill=mix(PANEL, INK_DIM, fade), size=size,
                            family=MONO))
            out.append(text(f"{k}r", ix1, ly, "", fill=PANEL, size=size, anchor="e"))
            scene.animating = True
        else:
            body = entry[1]
            last = idx + 1 >= len(lines) or lines[idx + 1][0] != "body"
            if th.open and last and int(t * 2) % 2 == 0:
                body += " ▌"
            ink = INK if (th.open or t - th.updated_at < 4.0) else "#A9B8D0"
            out.append(text(k, ix0 + 6 * s, ly, body, fill=mix(PANEL, ink, fade), size=size,
                            family=MONO))
            out.append(text(f"{k}r", ix1, ly, "", fill=PANEL, size=size, anchor="e"))
    scrollbar(out, "mi_sb", x1 - 3 * s, iy0, iy1, off, content, s)
    if not scene.follow.get(TAB_MIND, True) and max_off - off > pitch:
        out.append(text("mi_more", ix1 - 4 * s, iy1 - 4 * s, "▼ newer below — scroll down",
                        fill=ACCENT_GLOW, size=9 * s, anchor="e"))


def _thought_state(th: Any, t: float) -> tuple[str, str]:
    if th.state == "thinking":
        return "thinking", mix(PURPLE, PURPLE_GLOW, pulse(t, 1.0))
    if th.state == "writing":
        return f"writing · {fmt_tokens(th.chars_out)} chars", mix(CYAN, WHITE, 0.3 * pulse(t, 0.8))
    if th.state == "error":
        return "interrupted", AMBER
    return ("from batch" if th.transport == "batch" else "done"), INK_FAINT


def _mind_now(scene, out, model, x0, y0, x1, y1, s, t) -> None:
    live = [th for th in model.thoughts if th.open]
    caption(out, "mn_cap", x0, y0 + 6 * s, "RIGHT NOW",
            f"{len(live)} call(s) in flight" if live else "", x1 - x0, s)
    y = y0 + 22 * s
    row = 28 * s
    room = max(0, int((y1 - y - 30 * s) // row))
    for i, th in enumerate(live[:room]):
        writing = th.state == "writing"
        glow = pulse(t, 0.9 if writing else 1.5, phase=i * 0.17)
        color = CYAN if writing else PURPLE
        out.append(oval(f"mn{i}_h", x0 + 5 * s, y + 5 * s, (3 + 3.5 * glow) * s,
                        outline=mix(color, BG, glow), width=1.2 * s))
        out.append(oval(f"mn{i}_d", x0 + 5 * s, y + 5 * s, 3 * s, fill=color))
        out.append(text(f"mn{i}_t", x0 + 15 * s, y + 5 * s,
                        fit(model.item_label(th.item) or family_label(th.stage), x1 - x0 - 16 * s,
                            10 * s), fill=INK, size=10 * s))
        sub = f"{family_label(th.stage)} · " + (
            f"writing, {fmt_tokens(th.chars_out)} chars" if writing else "thinking")
        out.append(text(f"mn{i}_s", x0 + 15 * s, y + 17 * s, fit(sub, x1 - x0 - 16 * s, 9 * s),
                        fill=INK_DIM, size=9 * s))
        y += row
    if len(live) > room > 0:
        out.append(text("mn_more", x0 + 15 * s, y + 4 * s, f"+{len(live) - room} more",
                        fill=INK_FAINT, size=9 * s))
        y += 14 * s
    if not live:
        msg = ("Nothing is being asked right now." if model.phase == PHASE_RUNNING
               else "Calls in flight are listed here during a run.")
        out.append(text("mn_none", x0, y + 4 * s, fit(msg, x1 - x0, 9.5 * s), fill=INK_FAINT,
                        size=9.5 * s))
    if model.thoughts_enabled:
        cols = max(18, int((x1 - x0) / (9 * s * 0.56)))
        foot = scene.wrap(("mn_foot", cols),
                          "Summaries of the model's reasoning, shown here only. "
                          "They are never written to the results folder.", cols)[:3]
        fy = y1 - len(foot) * 12 * s + 4 * s
        if fy > y + 20 * s:
            for j, ln in enumerate(foot):
                out.append(text(f"mn_f{j}", x0, fy + j * 12 * s, ln, fill=INK_FAINT, size=9 * s))


# --------------------------------------------------------------------------- #
# Plan.
# --------------------------------------------------------------------------- #


def plan(scene: Any, out: list, model: Any, x0, y0, x1, y1, s, t, dt) -> None:
    split = (x1 - x0) >= 560 * s
    left_x1 = x0 + (x1 - x0) * 0.36 if split else x0
    if split:
        _plan_identity(scene, out, model, x0, y0, left_x1 - 8 * s, y1, s, t)
    _plan_checklist(scene, out, model, left_x1 + (6 * s if split else 0), y0, x1, y1, s, t, dt)


def _plan_identity(scene, out, model, x0, y0, x1, y1, s, t) -> None:
    ident = model.identity
    caption(out, "id_cap", x0, y0 + 6 * s, "THE SET",
            f"confidence {ident.confidence}" if ident is not None and ident.confidence else "",
            x1 - x0, s)
    top = y0 + 16 * s
    panel(out, "id_frame", x0, top, x1, y1, s)
    ix0, ix1 = x0 + 10 * s, x1 - 10 * s
    if ident is None:
        planned = any(st.name == "identity" for st in model.stages)
        lines = (["After the sheets are read, one pass", "works out what kind of set this is."]
                 if planned else
                 ["This run does not identify the set.", "QC Markups adds that step."])
        placeholder(out, "id_empty", ix0, top, ix1, y1, lines, s)
        return
    y = top + 14 * s
    width = ix1 - ix0
    headline = " · ".join(b for b in (ident.project_type, ident.set_type) if b) or "Drawing set"
    out.append(text("id_head", ix0, y, fit(headline, width, 11.5 * s), fill=INK, size=11.5 * s,
                    weight="bold"))
    scene.add_tip(ix0, y - 8 * s, ix1, y + 8 * s, [headline])
    y += 15 * s
    facts = " · ".join(b for b in (ident.place, ident.language, ident.units) if b)
    if facts:
        out.append(text("id_facts", ix0, y, fit(facts, width, 9.5 * s), fill=INK_DIM,
                        size=9.5 * s))
        y += 15 * s
    # Discipline chips, flowed left to right.
    if ident.disciplines and y + 16 * s < y1:
        cx, slot = ix0, 0
        for name in ident.disciplines:
            label = fit(name, width - 14 * s, 9 * s)
            w = text_width(label, 9 * s) + 14 * s
            if cx > ix0 and cx + w > ix1:
                cx, y = ix0, y + 18 * s
            if y + 10 * s > y1:
                break
            out.append(poly(f"id_c{slot}", rounded_rect_points(cx, y - 7.5 * s, cx + w, y + 7.5 * s,
                                                               7 * s),
                            fill="#12284A", outline=ACCENT, width=1, smooth=True))
            out.append(text(f"id_c{slot}_t", cx + 7 * s, y, label, fill=ACCENT_GLOW, size=9 * s))
            cx += w + 5 * s
            slot += 1
        y += 20 * s
    if y + 14 * s >= y1:
        return
    adopted = [c for c in ident.codes if c.adopted]
    out.append(text("id_codes", ix0, y, "CODE EDITIONS IT ADOPTS" if adopted else "CODE EDITIONS",
                    fill=INK_DIM, size=9 * s, weight="bold"))
    y += 14 * s
    shown = 0
    for i, code in enumerate(ident.codes):
        if y + 8 * s > y1:
            break
        tag = {"operator": "set by you", "regex": "mentioned", "model": ""}.get(code.origin, "")
        if not code.adopted:
            tag = "mentioned, not adopted"
        label = code.code + (f"  {code.edition}" if code.edition else "")
        tw = text_width(tag, 8.5 * s) + (8 * s if tag else 0)
        dot = GREEN if code.adopted else INK_FAINT
        if code.origin == "operator":
            dot = AMBER
        out.append(oval(f"id_k{i}_d", ix0 + 3 * s, y, 2.4 * s, fill=dot))
        out.append(text(f"id_k{i}", ix0 + 11 * s, y, fit(label, width - 11 * s - tw, 10 * s),
                        fill=INK if code.adopted else INK_DIM, size=10 * s))
        if tag:
            out.append(text(f"id_k{i}_g", ix1, y, tag, fill=INK_FAINT, size=8.5 * s, anchor="e"))
        scene.add_tip(ix0, y - 7 * s, ix1, y + 7 * s, [label, tag] if tag else [label])
        y += 14.5 * s
        shown += 1
    if not ident.codes:
        out.append(text("id_nocodes", ix0, y, "None stated on the sheets.", fill=INK_FAINT,
                        size=9.5 * s))
    elif shown < len(ident.codes):
        out.append(text("id_morecodes", ix1, y1 - 8 * s, f"+{len(ident.codes) - shown} more",
                        fill=INK_FAINT, size=9 * s, anchor="e"))


def check_summary(item: Any) -> tuple[str, str]:
    """An item's headline answer and its color: violated outranks the rest."""
    counts = item.counts
    answered = sum(counts.values())
    if not answered:
        return "", INK_FAINT
    if counts.get("VIOLATED"):
        return f"{counts['VIOLATED']} flagged", RED
    if counts.get("UNDETERMINED"):
        return f"{counts['UNDETERMINED']} unclear", AMBER
    if counts.get("MET"):
        return f"{counts['MET']} met", GREEN
    if counts.get("NOT_APPLICABLE"):
        return "n/a", INK_DIM
    return "unanswered", INK_FAINT


def _plan_empty(model: Any) -> list[str]:
    names = {st.name for st in model.stages}
    if "critique" not in names:
        return ["A standard run reads every sheet but writes no checklist.",
                "Tick QC Markups to have the model plan a review, discipline by discipline."]
    if model.phase == PHASE_RUNNING:
        return ["The review checklist is written after the sheets are read",
                "and the set is identified. It will appear here."]
    if model.phase == PHASE_IDLE:
        return ["The model writes a review checklist for each discipline it finds.",
                "Your own checklists are added to it. Both appear here, with every answer."]
    return ["No review checklist was produced in this run."]


def _plan_checklist(scene, out, model, x0, y0, x1, y1, s, t, dt) -> None:
    groups = model.checklist
    n_items = sum(len(g.items) for g in groups)
    note = ""
    if n_items:
        note = f"{n_items} check(s) in {len(groups)} checklist(s)"
        if model.checklist_sheets:
            note += f" · answered on {model.checklist_sheets} sheet(s)"
    caption(out, "ck_cap", x0, y0 + 6 * s, "REVIEW CHECKLIST", note, x1 - x0, s)
    top, bottom = y0 + 16 * s, y1
    panel(out, "ck_frame", x0, top, x1, bottom, s)
    ix0, ix1 = x0 + 10 * s, x1 - 12 * s
    iy0, iy1 = top + 6 * s, bottom - 6 * s
    if not n_items:
        placeholder(out, "ck_empty", ix0, iy0, ix1, iy1, _plan_empty(model), s)
        return
    rows: list[tuple] = []
    for g in groups:
        rows.append(("group", g))
        rows.extend(("item", it) for it in g.items)
    pitch = 17 * s
    content = len(rows) * pitch
    view = iy1 - iy0
    off = scene.scroll_offset(TAB_PLAN, content, view, dt)
    first = max(0, int(off // pitch))
    meter_w = 54 * s
    count_w = 62 * s
    id_w = 44 * s
    slot = 0
    for idx in range(first, len(rows)):
        ry = iy0 + idx * pitch - off + pitch / 2.0
        if ry > iy1 - pitch / 2.0 + 1:
            break
        if ry < iy0 + pitch / 2.0 - 1:
            continue
        fade = edge_fade(ry, iy0 - 2 * s, iy1 + 2 * s, s)
        k = f"ck{slot}"
        slot += 1
        kind, obj = rows[idx]
        if kind == "group":
            who = "MODEL'S PLAN" if obj.origin == "model" else "YOUR CHECKLIST"
            color = PURPLE_GLOW if obj.origin == "model" else ACCENT_GLOW
            out.append(text(f"{k}_id", ix0, ry, who, fill=mix(PANEL, color, fade), size=9 * s,
                            weight="bold"))
            ww = caps_width(who, 9 * s) + 8 * s
            out.append(text(f"{k}_t", ix0 + ww, ry, fit(obj.title, ix1 - ix0 - ww, 10 * s),
                            fill=mix(PANEL, INK, fade), size=10 * s, weight="bold"))
            out.append(rect(f"{k}_m_bg", 0, -10, 0, -10, fill=BG))
            for status, _label in CHECK_STATUSES:
                out.append(rect(f"{k}_m_{status}", 0, -10, 0, -10, fill=BG))
            out.append(text(f"{k}_c", -100, -100, "", fill=BG, size=9 * s, anchor="e"))
            continue
        summary, color = check_summary(obj)
        out.append(text(f"{k}_id", ix0, ry, obj.id, fill=mix(PANEL, INK_DIM, fade), size=9 * s,
                        family=MONO))
        tx1 = ix1 - meter_w - count_w - 8 * s
        out.append(text(f"{k}_t", ix0 + id_w, ry, fit(obj.text, tx1 - ix0 - id_w, 10 * s),
                        fill=mix(PANEL, INK, fade), size=10 * s))
        mx0 = ix1 - meter_w - count_w
        parts = [(status, obj.counts.get(status, 0), mix(PANEL, CHECK_COLOR[status], fade))
                 for status, _label in CHECK_STATUSES]
        if sum(n for _s, n, _c in parts):
            stacked_bar(out, f"{k}_m", mx0, ry - 3 * s, mx0 + meter_w, ry + 3 * s, parts)
        else:
            out.append(rect(f"{k}_m_bg", mx0, ry - 3 * s, mx0 + meter_w, ry + 3 * s,
                            fill=mix(PANEL, "#101D33", fade)))
            for status, _label in CHECK_STATUSES:
                out.append(rect(f"{k}_m_{status}", 0, -10, 0, -10, fill=BG))
        out.append(text(f"{k}_c", ix1, ry, summary, fill=mix(PANEL, color, fade), size=9 * s,
                        anchor="e"))
        tip = [f"{obj.id}  {obj.text}"]
        answered = [f"{obj.counts[status]} {label}" for status, label in CHECK_STATUSES
                    if obj.counts.get(status)]
        tip.append("Sheets: " + ", ".join(answered) if answered else "Not answered yet")
        scene.add_tip(ix0, ry - pitch / 2.0, ix1, ry + pitch / 2.0, tip)
    scrollbar(out, "ck_sb", x1 - 3 * s, iy0, iy1, off, content, s)


# --------------------------------------------------------------------------- #
# Findings.
# --------------------------------------------------------------------------- #


def funnel_steps(model: Any) -> list[dict]:
    """The four steps a finding passes, each with whether the run reached it."""
    names = {st.name: st for st in model.stages}
    reported = sum(model.found.values())
    reported_note = " · ".join(
        f"{label} {model.found[key]}" for key, label in SOURCE_LABELS if model.found.get(key)
    )
    in_ledger = model.ledger_total
    merged = model.merged_reports()
    extra = model.ledger_offline
    ledger_note = []
    if in_ledger and merged > 0:
        ledger_note.append(f"{merged} duplicate report(s) merged")
    if extra:
        ledger_note.append(f"{extra} from offline checks")
    anchor = model.ledger_by.get("anchor", {})
    anchor_stage = names.get("anchor")
    placed = bool(in_ledger) and (
        any(anchor.get(k) for k in ("exact", "fuzzy", "tile"))
        or (anchor_stage is not None and anchor_stage.state == STAGE_DONE)
    )
    buckets = model.ledger_by.get("bucket", {})
    verify = names.get("verification")
    checked = bool(in_ledger) and (
        any(buckets.get(k) for k in ("verified", "uncertain", "rejected"))
        or (verify is not None and verify.state in (STAGE_ACTIVE, STAGE_DONE))
    )
    return [
        {"key": "reported", "title": "REPORTED BY THE READS", "value": reported,
         "note": reported_note, "reached": reported > 0, "parts": None},
        {"key": "ledger", "title": "IN THE LEDGER", "value": in_ledger,
         "note": " · ".join(ledger_note) or ("one entry per distinct issue" if in_ledger else ""),
         "reached": in_ledger > 0, "parts": None},
        {"key": "placed", "title": "PLACED ON THE SHEET", "value": None,
         "note": " · ".join(f"{anchor[k]} {label}" for k, label in ANCHOR_BUCKETS
                            if anchor.get(k)) if placed else "after the ledger is sealed",
         "reached": placed,
         "parts": [(k, anchor.get(k, 0), ANCHOR_COLOR[k]) for k, _l in ANCHOR_BUCKETS]},
        {"key": "checked", "title": "RE-CHECKED", "value": None,
         "note": (" · ".join(f"{buckets[k]} {label.lower()}" for k, label in FINDING_BUCKETS
                             if buckets.get(k)) if checked
                  else ("crop re-check" if verify is not None else "not part of this run")),
         "reached": checked,
         "parts": [(k, buckets.get(k, 0), BUCKET_COLOR[k]) for k, _l in FINDING_BUCKETS]},
    ]


def findings(scene: Any, out: list, model: Any, x0, y0, x1, y1, s, t, dt) -> None:
    steps = funnel_steps(model)
    sev = model.ledger_by.get("severity", {})
    sev_note = " · ".join(f"{sev[k]} {k}" for k in ("high", "medium", "low") if sev.get(k))
    caption(out, "fn_cap", x0, y0 + 6 * s, "FROM REPORT TO PROOF", sev_note, x1 - x0, s)
    top = y0 + 16 * s
    band = 50 * s
    if y1 - top < band:
        return
    gap = 14 * s
    w = (x1 - x0 - gap * (len(steps) - 1)) / len(steps)
    age = t - model.insights_changed_at
    for i, step in enumerate(steps):
        bx0 = x0 + i * (w + gap)
        bx1 = bx0 + w
        reached = step["reached"]
        k = f"fn_{step['key']}"
        flash = max(0.0, 1.0 - age / 0.8) if reached else 0.0
        if flash:
            scene.animating = scene.fast = True
        panel(out, f"{k}_p", bx0, top, bx1, top + band, s,
              outline=mix(ACCENT if reached else INK_FAINT, WHITE, 0.5 * flash))
        out.append(text(f"{k}_t", bx0 + 8 * s, top + 10 * s, fit(step["title"], w - 16 * s, 8.5 * s),
                        fill=INK_DIM if reached else INK_FAINT, size=8.5 * s, weight="bold"))
        if step["parts"] is None:
            shown = scene._ease(k, float(step["value"] or 0), dt, rate=6.0)
            out.append(text(f"{k}_v", bx0 + 8 * s, top + 27 * s, f"{shown:,.0f}",
                            fill=INK if reached else INK_FAINT, size=17 * s, weight="bold",
                            family=MONO))
        elif reached:
            grow = scene._ease(f"{k}_g", 1.0, dt, rate=3.0)
            stacked_bar(out, f"{k}_b", bx0 + 8 * s, top + 21 * s, bx1 - 8 * s, top + 32 * s,
                        step["parts"], grow=grow)
        else:
            scene._shown.pop(f"{k}_g", None)
            out.append(rect(f"{k}_b_bg", bx0 + 8 * s, top + 21 * s, bx1 - 8 * s, top + 32 * s,
                            fill="#101D33"))
        out.append(text(f"{k}_n", bx0 + 8 * s, top + 41 * s, fit(step["note"], w - 16 * s, 8.5 * s),
                        fill=INK_DIM if reached else INK_FAINT, size=8.5 * s))
        if step["note"]:
            scene.add_tip(bx0, top, bx1, top + band, [step["title"].capitalize(), step["note"]])
        if i:
            ax = bx0 - gap / 2.0
            ay = top + band / 2.0
            out.append(line(f"{k}_a", (ax - 3 * s, ay - 4 * s, ax + 2 * s, ay, ax - 3 * s, ay + 4 * s),
                            fill=ACCENT if reached else INK_FAINT, width=1.6 * s))
    _findings_list(scene, out, model, x0, top + band + 8 * s, x1, y1, s, t, dt)


def _findings_empty(model: Any) -> list[str]:
    reported = sum(model.found.values())
    if reported:
        return [f"{reported} finding(s) reported so far.",
                "They are merged into one ledger once every read is in, then listed here."]
    if model.phase == PHASE_RUNNING:
        return ["Findings appear here as the reads report them."]
    if model.phase == PHASE_IDLE:
        return ["Every issue a read reports is merged into one ledger, pinned to its spot",
                "on the sheet and re-checked against a fresh crop. You can watch it here."]
    return ["No findings were reported in this run."]


def _findings_list(scene, out, model, x0, y0, x1, y1, s, t, dt) -> None:
    if y1 - y0 < 30 * s:
        return
    panel(out, "fl_frame", x0, y0, x1, y1, s)
    ix0, ix1 = x0 + 10 * s, x1 - 12 * s
    iy0, iy1 = y0 + 5 * s, y1 - 5 * s
    rows = model.ledger_findings
    if not rows:
        placeholder(out, "fl_empty", ix0, iy0, ix1, iy1, _findings_empty(model), s)
        return
    pitch = 16 * s
    content = len(rows) * pitch
    view = iy1 - iy0
    off = scene.scroll_offset(TAB_FINDINGS, content, view, dt)
    first = max(0, int(off // pitch))
    id_w = 54 * s
    sheet_w = min(110 * s, (ix1 - ix0) * 0.2)
    status_w = 78 * s
    slot = 0
    for idx in range(first, len(rows)):
        ry = iy0 + idx * pitch - off + pitch / 2.0
        if ry > iy1 - pitch / 2.0 + 1:
            break
        if ry < iy0 + pitch / 2.0 - 1:
            continue
        f = rows[idx]
        fade = edge_fade(ry, iy0 - 2 * s, iy1 + 2 * s, s)
        k = f"fl{slot}"
        slot += 1
        rejected = f.bucket == "rejected"
        ink = INK_FAINT if rejected else INK
        out.append(oval(f"{k}_d", ix0 + 3 * s, ry, 3 * s,
                        fill=mix(PANEL, SEVERITY_COLOR.get(f.severity, INK_DIM), fade)))
        out.append(text(f"{k}_id", ix0 + 11 * s, ry, f.qc_id or "·", fill=mix(PANEL, INK_DIM, fade),
                        size=9 * s, family=MONO))
        out.append(text(f"{k}_sh", ix0 + 11 * s + id_w, ry, fit(f.sheet, sheet_w - 6 * s, 9.5 * s),
                        fill=mix(PANEL, ACCENT_GLOW if not rejected else INK_FAINT, fade),
                        size=9.5 * s))
        tx0 = ix0 + 11 * s + id_w + sheet_w
        out.append(text(f"{k}_t", tx0, ry, fit(f.text, ix1 - status_w - tx0 - 6 * s, 10 * s),
                        fill=mix(PANEL, ink, fade), size=10 * s))
        status = BUCKET_TEXT.get(f.bucket, f.bucket)
        if f.reproduced and len(f.sources) >= 1 and "critique" in f.sources and not rejected:
            status += " ×2"
        out.append(text(f"{k}_st", ix1, ry, status,
                        fill=mix(PANEL, BUCKET_COLOR.get(f.bucket, INK_DIM), fade), size=9 * s,
                        anchor="e"))
        labels = dict(SOURCE_LABELS)
        tip = [f"{f.qc_id or 'Not numbered yet'} · {f.severity or '?'} · {f.sheet}", f.text,
               "Reported by: " + (", ".join(labels.get(src, src) for src in f.sources) or "—"),
               f"Placement: {dict(ANCHOR_BUCKETS).get(f.anchor, f.anchor)} · "
               f"{BUCKET_TEXT.get(f.bucket, f.bucket)}"]
        scene.add_tip(ix0, ry - pitch / 2.0, ix1, ry + pitch / 2.0, tip)
    if model.ledger_total > len(rows):
        out.append(text("fl_more", ix1, iy1 - 2 * s,
                        f"showing the first {len(rows)} of {model.ledger_total}",
                        fill=INK_FAINT, size=8.5 * s, anchor="e"))
    scrollbar(out, "fl_sb", x1 - 3 * s, iy0, iy1, off, content, s)


VIEWS = {TAB_STORY: story, TAB_MIND: mind, TAB_PLAN: plan, TAB_FINDINGS: findings}


def wrap_text(value: str, cols: int) -> list[str]:
    """``value`` wrapped to ``cols`` characters, paragraph breaks kept."""
    lines: list[str] = []
    for para in str(value or "").split("\n"):
        para = " ".join(para.split())
        if not para:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=max(8, cols), break_long_words=True,
                                   break_on_hyphens=False) or [""])
    while lines and lines[-1] == "":
        lines.pop()
    return lines
