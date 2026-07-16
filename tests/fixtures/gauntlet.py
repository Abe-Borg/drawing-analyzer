"""The Phase 27 trust-gauntlet fixture set (§19.1) — a synthetic drawing set that
exercises every product guarantee in one deterministic, hermetic end-to-end run.

The **oracle set** (:func:`build_oracle_set`) contains, by construction:

- two *different* PDFs sharing the basename ``M-101.pdf`` (source isolation);
- pages at 0°/90°/180°/270°, one with a non-default CropBox;
- vector, raster (empty text layer), and hybrid (text + graphics) pages;
- a pre-existing reviewer annotation on one source (DA-029);
- several unrelated findings anchored in the same tile;
- repeated source text (``TYP DETAIL 5`` twice) requiring tile disambiguation;
- digest JSON findings, a prose item matching a JSON finding, a prose straggler
  that structures cleanly, and one whose structuring call is forced to fail
  (degraded entry);
- a critique finding reproduced across both reads and a read-1 singleton;
- a numeric claim whose quote carries every operand (deterministic arithmetic
  mismatch, §17.5) and a stale ``SEE DRAWING M-999`` pointer (reference auditor);
- a dual-leg cross-sheet conflict (M-101 ↔ E-201);
- a finding the verifier rejects, and an unanchored sheet-level finding;
- a set-level synthesis conflict naming no in-set sheet (§14.8);
- two materially different claims citing one code reference (DA-017); and
- one corrupt input file (inventory UNREADABLE, non-fatal).

:class:`ScriptedQCClient` answers **every** stage of the exhaustive stack —
digest, critique ×2, synthesis, cross-QC (map/reconcile aware), prose-harvest
structuring, verification (capturing the exact image bytes sent), and citation
(claim-complete, per-claim statuses) — and records what each stage was actually
asked, so acceptance tests can assert on the requests as well as the results.

Routing follows the established suite convention: match ``kw["system"]``
against the stage system prompts (``==`` for verify/harvest, ``startswith``
for the prompts that append task addenda), then discriminate sheets by
distinctive body tokens carried in the request's verbatim sheet-text layer.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drawing_analyzer.citation_check import CITATION_SYSTEM_PROMPT
from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
from drawing_analyzer.cross_qc import (
    CROSS_QC_RECONCILE_SYSTEM_PROMPT,
    CROSS_QC_SYSTEM_PROMPT,
)
from drawing_analyzer.digest import (
    DIGEST_SYSTEM_PROMPT,
    _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER,
)
from drawing_analyzer.prose_harvest import HARVEST_SYSTEM_PROMPT
from drawing_analyzer.review_planner import PLANNER_SYSTEM_PROMPT
from drawing_analyzer.set_identity import IDENTITY_SYSTEM_PROMPT
from drawing_analyzer.synthesis import SYNTHESIS_SYSTEM_PROMPT
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

_PAGE_W, _PAGE_H = 792.0, 612.0


# --------------------------------------------------------------------------- #
# PDF builders
# --------------------------------------------------------------------------- #


def _require_pymupdf():
    import pymupdf  # local import: only the builders need it (I-5 for the suite)

    return pymupdf


def build_vector_sheet(
    path: Path,
    *,
    sheet_id: str,
    lines: list[tuple[float, float, str]],
    rotation: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    graphics: bool = False,
    preexisting_note: str = "",
) -> Path:
    """One vector sheet; the title-block id is placed bottom-right **in view
    space** (via the derotation matrix) so sheet-id learning sees it where a
    title block lives regardless of page rotation."""
    pymupdf = _require_pymupdf()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    for x, y, text in lines:
        page.insert_text((x, y), text)
    if graphics:
        page.draw_rect(pymupdf.Rect(420, 60, 700, 240), color=(0.2, 0.4, 0.8))
        page.draw_line(pymupdf.Point(420, 260), pymupdf.Point(700, 260))
    if preexisting_note:
        annot = page.add_text_annot(pymupdf.Point(700, 60), preexisting_note)
        annot.set_info(title="prior-reviewer")
        annot.update()
    if cropbox is not None:
        page.set_cropbox(pymupdf.Rect(*cropbox))
    if rotation:
        page.set_rotation(rotation)
    # Title-block id at view bottom-right (margins keep it clear of the media
    # edge so no glyph is clipped on rotated pages).
    vw, vh = page.rect.width, page.rect.height
    target = pymupdf.Point(vw - 150, vh - 60)
    page.insert_text(target * page.derotation_matrix, sheet_id, fontsize=12)
    words = {w[4] for w in page.get_text("words")}
    assert sheet_id in words, f"fixture bug: {sheet_id!r} not extracted ({path.name})"
    doc.save(str(path))
    doc.close()
    return path


def build_raster_sheet(path: Path) -> Path:
    """Graphics but no text layer → the pipeline treats it as scanned raster."""
    pymupdf = _require_pymupdf()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.draw_rect(pymupdf.Rect(100, 100, 420, 320), fill=(0.20, 0.42, 0.78))
    page.draw_circle(pymupdf.Point(560, 400), 90, fill=(0.85, 0.30, 0.22))
    doc.save(str(path))
    doc.close()
    return path


def build_corrupt_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7 this is not really a pdf \x00\x01 truncated")
    return path


# --------------------------------------------------------------------------- #
# Oracle-set content constants (importable by the acceptance tests)
# --------------------------------------------------------------------------- #

# Sheet A (a/M-101.pdf, rotation 0, hybrid, pre-existing annotation).
Q_F1 = "VAV-7 CLEARANCE NOT SHOWN"
Q_F2 = "DUCT LINER OMITTED AT RISER"
Q_CQ_PRIMARY = "VAV-7 COOLING 12 KW"
Q_CR1 = "SMOKE DAMPER AT CORRIDOR"
Q_CR2 = "FLEX CONN AT AHU"
Q_ARITH = "TOTAL 100 + 250 = 375"
Q_REPEATED = "TYP DETAIL 5"
STALE_REF_LINE = "SEE DRAWING M-999"
PREEXISTING_NOTE = "prior reviewer note"

# Sheet B (b/M-101.pdf — same basename, different drawing, rotation 90).
Q_F4 = "FIRE PUMP 500 GPM"

# Sheet E (E-201.pdf, rotation 180).
Q_CQ_LEG = "PANEL LP-2 FED FROM MDP"
Q_F5 = "GFCI NOTE"

# Sheet C (C-301.pdf, rotation 270, reduced CropBox).
Q_F6 = "CONC PAD 6 IN"
Q_F7_MISSING = "SUMP PUMP DISCHARGE ROUTE"     # deliberately NOT on the sheet

SHARED_REF = "CMC 310.1"                        # cited by two different claims

F1 = {"sheet_id": "M-101", "category": "code", "severity": "high",
      "text": "VAV-7 has no service clearance shown.", "source_quote": Q_F1,
      "tile_label": "r1c1", "refs": [SHARED_REF]}
F2 = {"sheet_id": "M-101", "category": "coordination", "severity": "medium",
      "text": "Duct liner omitted at the riser.", "source_quote": Q_F2,
      "tile_label": "r1c1", "refs": [SHARED_REF]}
F3 = {"sheet_id": "M-101", "category": "question", "severity": "low",
      "text": "Detail 5 may be superseded.", "source_quote": Q_REPEATED,
      "tile_label": "r2c2"}
F4 = {"sheet_id": "FP-101", "category": "code", "severity": "high",
      "text": "Fire pump rating exceeds the service size.", "source_quote": Q_F4,
      "tile_label": "r1c1"}
F5 = {"sheet_id": "E-201", "category": "code", "severity": "medium",
      "text": "GFCI protection is called out where none is required.",
      "source_quote": Q_F5, "tile_label": "r1c1"}
F6 = {"sheet_id": "C-301", "category": "coordination", "severity": "medium",
      "text": "Concrete pad thickness conflicts with the detail.",
      "source_quote": Q_F6, "tile_label": "r1c1"}
F7 = {"sheet_id": "C-301", "category": "question", "severity": "low",
      "text": "Sump pump discharge route is unclear.",
      "source_quote": Q_F7_MISSING}

CR1 = {"sheet_id": "M-101", "category": "coordination", "severity": "high",
       "text": "Smoke damper at the corridor wall lacks an access panel.",
       "source_quote": Q_CR1, "tile_label": "r1c1"}
CR2 = {"sheet_id": "M-101", "category": "question", "severity": "low",
       "text": "Flexible connector at the AHU may be missing.",
       "source_quote": Q_CR2, "tile_label": "r1c1"}
ARITH_CLAIM = {"sheet_id": "M-101", "quote": Q_ARITH, "kind": "sum",
               "terms": [100, 250], "expected": 375, "note": "column total"}

CROSS_CONFLICT = {
    "sheet_id": "M-101", "category": "conflict", "severity": "high",
    "text": "VAV-7 cooling of 12 KW conflicts with the panel schedule.",
    "source_quote": Q_CQ_PRIMARY, "tile_label": "r1c1",
    "also_on": [{"sheet_id": "E-201", "source_quote": Q_CQ_LEG,
                 "tile_label": "r1c1"}],
}

PROSE_MATCHED = "Duct liner omitted at the riser."
PROSE_STRUCTURED = "Kitchen hood exhaust duct is missing its fire wrap."
PROSE_DEGRADED = "Access panels are not scheduled at the shaft."

PROSE_A = (
    "Sheet M-101 - Mechanical - Plan\n"
    "VAV-7 serves the north zone; duct riser at grid 5.\n\n"
    "**Coordination / cross-discipline items**\n"
    f"- {PROSE_MATCHED}\n"
    f"- {PROSE_STRUCTURED}\n"
    f"- {PROSE_DEGRADED}\n"
)
PROSE_B = "Sheet FP-101 - Fire Protection - Plan\nFire pump room plan and riser."
PROSE_E = "Sheet E-201 - Electrical - Plan\nPanel LP-2 single-line and notes."
PROSE_C = "Sheet C-301 - Civil - Plan\nEquipment pads and site drainage."
PROSE_S = "Sheet - Structural - Scan\nScanned framing plan; no vector text."

SET_LEVEL_CONFLICT_SENTENCE = (
    "The specified fire pump rating conflicts with the equipment schedule "
    "and no single sheet in the set resolves which governs."
)
SYNTHESIS_TEXT = (
    "Drawing Set Overview\n\n"
    "Five readable sheets: mechanical, fire protection, electrical, civil and "
    "one scanned structural sheet.\n\n"
    f"{SET_LEVEL_CONFLICT_SENTENCE}"
)

# The valid structured object returned for the PROSE_STRUCTURED straggler.
_STRUCTURED_OBJ = {
    "sheet_id": "M-101", "category": "coordination", "severity": "medium",
    "text": PROSE_STRUCTURED, "source_quote": "", "tile": None, "refs": [],
}


@dataclass
class OracleSet:
    """Paths of the built oracle inputs, in deterministic submission order."""

    root: Path
    a_m101: Path
    b_m101: Path
    e201: Path
    c301: Path
    s501: Path
    corrupt: Path

    @property
    def inputs(self) -> list[Path]:
        return [self.a_m101, self.b_m101, self.e201, self.c301, self.s501, self.corrupt]

    @property
    def source_names(self) -> list[str]:
        return [p.name for p in self.inputs]


def build_oracle_set(root: Path) -> OracleSet:
    (root / "a").mkdir(parents=True, exist_ok=True)
    (root / "b").mkdir(parents=True, exist_ok=True)
    a = build_vector_sheet(
        root / "a" / "M-101.pdf", sheet_id="M-101",
        lines=[
            (72, 100, Q_F1),
            (72, 128, Q_F2),
            (72, 156, Q_CQ_PRIMARY),
            (72, 184, Q_CR1),
            (72, 212, Q_CR2),
            (72, 240, Q_ARITH),
            (72, 268, STALE_REF_LINE),
            (72, 296, Q_REPEATED),          # first occurrence — tile r1c1
            (500, 400, Q_REPEATED),         # second occurrence — tile r2c2
        ],
        graphics=True,                       # hybrid: vector text + drawn shapes
        preexisting_note=PREEXISTING_NOTE,   # DA-029 seed
    )
    b = build_vector_sheet(
        root / "b" / "M-101.pdf", sheet_id="FP-101", rotation=90,
        lines=[(72, 100, Q_F4), (72, 128, "FIRE PUMP ROOM PLAN")],
    )
    e = build_vector_sheet(
        root / "E-201.pdf", sheet_id="E-201", rotation=180,
        lines=[(72, 100, Q_CQ_LEG), (72, 128, Q_F5)],
    )
    c = build_vector_sheet(
        root / "C-301.pdf", sheet_id="C-301", rotation=270,
        cropbox=(36.0, 24.0, 756.0, 588.0),
        lines=[(72, 100, Q_F6), (72, 128, "SITE DRAINAGE PLAN")],
    )
    s = build_raster_sheet(root / "S-501.pdf")
    corrupt = build_corrupt_pdf(root / "corrupt.pdf")
    return OracleSet(root=root, a_m101=a, b_m101=b, e201=e, c301=c, s501=s,
                     corrupt=corrupt)


# --------------------------------------------------------------------------- #
# The scripted all-stage client
# --------------------------------------------------------------------------- #


def _system_text(system) -> str:
    """Normalize a captured request's ``system`` to a plain string.

    ``digest_system_prompt`` returns a two-block cached-prefix list instead
    of a plain string when project specifications are attached (see
    digest.py), so a bare ``str(kw.get("system", ""))`` would stringify the
    block list itself rather than its text — breaking every
    ``.startswith(...)``-based route below.
    """
    if isinstance(system, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in system
        )
    return str(system or "")


def _joined_text(messages: list) -> str:
    parts: list[str] = []
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


def _image_bytes(messages: list) -> list[bytes]:
    out: list[bytes] = []
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            continue
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "image":
                data = (block.get("source") or {}).get("data", "")
                try:
                    out.append(base64.b64decode(data))
                except Exception:  # noqa: BLE001 — capture helper, never fatal
                    out.append(b"")
    return out


def _fenced(obj: dict) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"


@dataclass
class SheetScript:
    """What the model 'sees' on one sheet: routed by ``token`` in the request."""

    token: str                      # distinctive body text identifying the sheet
    prose: str
    findings: list[dict] = field(default_factory=list)
    read1: tuple[list[dict], list[dict]] = ((), ())   # (findings, claims)
    read2: tuple[list[dict], list[dict]] = ((), ())


class ScriptedQCClient:
    """One fake client answering the entire exhaustive stack, deterministically.

    ``sabotage`` selects a §19.1 failure-injection mode:

    - ``"synthesis"``     — synthesis returns an empty max-tokens response;
    - ``"critique_read2"``— every sheet's second critique read is malformed;
    - ``"cross_qc"``      — the cross-sheet call returns unparseable text;
    - ``"citation_empty"``— citation returns an empty assessments list (DA-017);
    - ``"identity"``      — the set-identity call returns unparseable text (the
      run must degrade to identity-less behavior, never fail);
    - ``"identity_misdetect"`` — identity confidently reports a WRONG
      discipline/jurisdiction (the advisory contract: nothing may be gated or
      suppressed by it, and the misdetection stays visible in the manifest);
    - ``"review_plan_malformed"`` — the planner returns unparseable text (the
      critique must still run with the user profiles only).
    """

    def __init__(
        self,
        sheets: list[SheetScript],
        *,
        synthesis_text: str = "",
        cross_findings: list[dict] | None = None,
        verify_verdicts: tuple[tuple[str, str], ...] = (),
        harvest_garbage_tokens: tuple[str, ...] = (),
        citation_statuses: tuple[tuple[str, str], ...] = (),
        identity_payload: dict | None = None,
        sabotage: str | None = None,
    ) -> None:
        self._sheets = list(sheets)
        self._synthesis_text = synthesis_text
        self._cross_findings = list(cross_findings or [])
        self._verify_verdicts = tuple(verify_verdicts)
        self._harvest_garbage = tuple(harvest_garbage_tokens)
        self._citation_statuses = tuple(citation_statuses)
        self._identity_payload = identity_payload
        self._sabotage = sabotage

        # Captures (assertion surface for the acceptance tests).
        self.digest_calls: dict[str, int] = {}
        self.digest_request_texts: list[str] = []
        self.critique_calls: dict[str, int] = {}
        self.critique_system_prompts: list[str] = []
        self.synth_calls = 0
        self.cross_calls = 0
        self.cross_request_texts: list[str] = []
        self.reconcile_calls = 0
        self.harvest_calls = 0
        self.citation_requests: list[str] = []
        self.verify_calls = 0
        self.verify_requests: list[tuple[str, list[bytes]]] = []
        self.raster_placeholder_seen = False
        self.identity_calls = 0
        self.identity_request_texts: list[str] = []
        self.plan_calls = 0
        self.plan_request_texts: list[str] = []

        outer = self

        class _Msgs:
            def create(_self, **kw):  # noqa: ANN001, ANN202
                return outer._route(kw)

        self.messages = _Msgs()

    # -- routing ----------------------------------------------------------- #

    def _sheet_for(self, text: str) -> SheetScript | None:
        for script in self._sheets:
            if script.token in text:
                return script
        return None

    def _route(self, kw: dict) -> FakeMessage:
        system = _system_text(kw.get("system", ""))
        text = _joined_text(kw.get("messages", []))

        if system == VERIFY_SYSTEM_PROMPT:
            return self._verify(kw, text)
        if system == HARVEST_SYSTEM_PROMPT:
            return self._harvest(text)
        if system.startswith(CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
            self.reconcile_calls += 1
            return _msg(_fenced({"findings": [], "claims": []}), 30, 8)
        if system.startswith(CROSS_QC_SYSTEM_PROMPT):
            return self._cross(text)
        if system.startswith(CRITIQUE_SYSTEM_PROMPT):
            return self._critique(text, system)
        if system.startswith(DIGEST_SYSTEM_PROMPT):
            return self._digest(text)
        if system.startswith(CITATION_SYSTEM_PROMPT):
            return self._citation(text)
        if system.startswith(SYNTHESIS_SYSTEM_PROMPT):
            return self._synthesis()
        if system == IDENTITY_SYSTEM_PROMPT:
            return self._identity(text)
        if system == PLANNER_SYSTEM_PROMPT:
            return self._plan(text)
        return _msg("ok", 1, 1)

    # -- per-stage behaviors ------------------------------------------------ #

    def _digest(self, text: str) -> FakeMessage:
        if _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER in text:
            self.raster_placeholder_seen = True
        self.digest_request_texts.append(text)
        script = self._sheet_for(text)
        key = script.token if script else "<raster>"
        self.digest_calls[key] = self.digest_calls.get(key, 0) + 1
        prose = script.prose if script else PROSE_S
        findings = script.findings if script else []
        return _msg(prose + "\n\n" + _fenced({"findings": findings}), 500, 90)

    def _critique(self, text: str, system: str = "") -> FakeMessage:
        self.critique_system_prompts.append(system)
        script = self._sheet_for(text)
        key = script.token if script else "<raster>"
        n = self.critique_calls.get(key, 0) + 1
        self.critique_calls[key] = n
        if self._sabotage == "critique_read2" and n % 2 == 0:
            return _msg("malformed critique output — no findings object", 200, 20)
        findings, claims = ((), ())
        if script is not None:
            findings, claims = script.read1 if n % 2 == 1 else script.read2
        body = {"findings": list(findings), "claims": list(claims)}
        return _msg(_fenced(body), 400, 60)

    def _synthesis(self) -> FakeMessage:
        self.synth_calls += 1
        if self._sabotage == "synthesis":
            # An empty max-tokens response is the parse-level failure mode.
            return FakeMessage(content=[], stop_reason="max_tokens",
                               usage=FakeUsage(input_tokens=10, output_tokens=0))
        return _msg(self._synthesis_text or "Overview.", 300, 60)

    def _cross(self, text: str = "") -> FakeMessage:
        self.cross_calls += 1
        self.cross_request_texts.append(text)
        if self._sabotage == "cross_qc":
            return _msg("no structured output here at all", 100, 10)
        return _msg(_fenced({"findings": self._cross_findings, "claims": []}), 800, 60)

    def _harvest(self, text: str) -> FakeMessage:
        self.harvest_calls += 1
        if any(tok in text for tok in self._harvest_garbage):
            return _msg("not json", 50, 10)
        return _msg(_fenced(_STRUCTURED_OBJ), 50, 20)

    def _verify(self, kw: dict, text: str) -> FakeMessage:
        self.verify_calls += 1
        self.verify_requests.append((text, _image_bytes(kw.get("messages", []))))
        verdict = "CONFIRMED"
        for token, v in self._verify_verdicts:
            if token in text:
                verdict = v
                break
        return _msg(json.dumps({"verdict": verdict, "note": "checked"}), 40, 8)

    def _identity(self, text: str) -> FakeMessage:
        self.identity_calls += 1
        self.identity_request_texts.append(text)
        if self._sabotage == "identity":
            return _msg("I could not classify this set, sorry.", 100, 10)
        if self._sabotage == "identity_misdetect":
            payload = {
                "disciplines": ["landscape"],
                "jurisdiction": "Reykjavik, Iceland",
                "country": "Iceland",
                "language": "is",
                "units": "metric",
                "adopted_codes": [],
                "confidence": "high",
            }
            return _msg(_fenced(payload), 200, 40)
        payload = self._identity_payload or {
            "disciplines": ["electrical", "fire protection", "mechanical"],
            "sheet_disciplines": [
                {"sheet_id": "M-101", "discipline": "mechanical"},
                {"sheet_id": "E-201", "discipline": "electrical"},
                {"sheet_id": "FP-101", "discipline": "fire protection"},
            ],
            "project_type": "commercial building",
            "set_type": "issued for construction",
            "jurisdiction": "California, United States",
            "country": "United States",
            "region": "California",
            "language": "en",
            "units": "imperial",
            "adopted_codes": [{
                "code": "NFPA 13", "edition": "2016", "amendment_note": "",
                "quote": "NFPA 13 2016", "source_sheet": "FP-101",
            }],
            "confidence": "high",
            "evidence": ["general notes"],
            "notes": "",
        }
        return _msg(_fenced(payload), 200, 40)

    def _plan(self, text: str) -> FakeMessage:
        self.plan_calls += 1
        self.plan_request_texts.append(text)
        if self._sabotage == "review_plan_malformed":
            return _msg("here is a checklist:\n- do good work\n- avoid bad work", 100, 20)
        payload = {
            "plans": [
                {
                    "discipline": "fire protection",
                    "title": "Fire protection — NFPA 13 (2016) sprinkler QC",
                    "items": [
                        {
                            "text": ("Flag any dry or preaction schedule row whose "
                                     "remote design area equals the wet-system base "
                                     "area (no +30% increase applied)."),
                            "severity": "high",
                            "refs": ["NFPA 13 2016 §19.2.3.2.5"],
                        },
                        {
                            "text": ("Expected an inspector's test valve on every dry "
                                     "system; flag when not found on this sheet."),
                            "severity": "medium",
                            "refs": ["NFPA 13 2016"],
                        },
                    ],
                },
                {
                    "discipline": "mechanical",
                    "title": "Mechanical — equipment schedule QC",
                    "items": [
                        {
                            "text": ("Flag a scheduled equipment tag that appears in a "
                                     "schedule but is never drawn on any plan sheet."),
                            "severity": "medium",
                            "refs": [],
                        },
                    ],
                },
            ]
        }
        return _msg(_fenced(payload), 300, 80)

    def _citation(self, text: str) -> FakeMessage:
        self.citation_requests.append(text)
        if self._sabotage == "citation_empty":
            return _msg('{"assessments": []}', 10, 4)
        assessments = []
        for handle, claim_text in re.findall(r"\[(C\d+)\] (.+)", text):
            status = "CHECKED_SUPPORTS"
            for token, st in self._citation_statuses:
                if token in claim_text:
                    status = st
                    break
            assessments.append({"claim": handle, "status": status, "note": "checked"})
        if not assessments:
            # A request shape without [Cn] handles: the back-compat single verdict.
            return _msg("searched...\n" + _fenced(
                {"status": "CHECKED_SUPPORTS", "note": "supports", "edition_notes": "e"}
            ), 20, 8)
        return _msg("searched...\n" + _fenced(
            {"assessments": assessments, "edition_notes": "e"}
        ), 20, 8)


def _msg(text: str, tin: int, tout: int) -> FakeMessage:
    return FakeMessage(content=[FakeTextBlock(text=text)],
                       usage=FakeUsage(input_tokens=tin, output_tokens=tout))


# --------------------------------------------------------------------------- #
# Ready-made clients
# --------------------------------------------------------------------------- #


def oracle_client(sabotage: str | None = None) -> ScriptedQCClient:
    """The full §19.1 script over :func:`build_oracle_set`."""
    sheets = [
        SheetScript(token=Q_F1, prose=PROSE_A, findings=[F1, F2, F3],
                    read1=([CR1, CR2], [ARITH_CLAIM]), read2=([CR1], [ARITH_CLAIM])),
        SheetScript(token=Q_F4, prose=PROSE_B, findings=[F4]),
        SheetScript(token=Q_CQ_LEG, prose=PROSE_E, findings=[F5]),
        SheetScript(token=Q_F6, prose=PROSE_C, findings=[F6, F7]),
    ]
    return ScriptedQCClient(
        sheets,
        synthesis_text=SYNTHESIS_TEXT,
        cross_findings=[CROSS_CONFLICT],
        verify_verdicts=((Q_F5, "CONTRADICTED"),),      # F5 → REJECTED
        harvest_garbage_tokens=("Access panels",),      # PROSE_DEGRADED → degraded
        citation_statuses=(("clearance", "CHECKED_SUPPORTS"),
                           ("liner", "CHECKED_MISMATCH")),
        sabotage=sabotage,
    )


# The mini set: two clean vector sheets, one finding with a citation, one prose
# straggler (so every stage has work to sabotage), and a stale reference.
MINI_F1 = {"sheet_id": "M-101", "category": "code", "severity": "high",
           "text": "VAV-3 has no shown clearance.", "source_quote": "VAV-3",
           "tile_label": "r1c1", "refs": ["CMC 310"]}
MINI_PROSE = (
    "Sheet M-101 - Mechanical - Plan\n"
    "VAV-3 serves Room 120.\n\n"
    "**Coordination / cross-discipline items**\n"
    f"- {PROSE_STRUCTURED}\n"
)


def build_mini_set(root: Path) -> list[Path]:
    a = build_vector_sheet(
        root / "M-101.pdf", sheet_id="M-101",
        lines=[(72, 100, "VAV-3 SERVES ROOM 120"), (72, 128, STALE_REF_LINE)],
    )
    b = build_vector_sheet(
        root / "M-102.pdf", sheet_id="M-102",
        lines=[(72, 100, "EQUIPMENT SCHEDULE SHOWN")],
    )
    return [a, b]


def mini_client(sabotage: str | None = None) -> ScriptedQCClient:
    sheets = [
        SheetScript(token="VAV-3", prose=MINI_PROSE, findings=[MINI_F1],
                    read1=([], []), read2=([], [])),
        SheetScript(token="EQUIPMENT SCHEDULE",
                    prose="Sheet M-102 - Mechanical - Schedules\nEquipment schedule."),
    ]
    return ScriptedQCClient(
        sheets,
        synthesis_text="Drawing Set Overview\n\nThe two sheets are consistent.",
        cross_findings=[],
        sabotage=sabotage,
    )
