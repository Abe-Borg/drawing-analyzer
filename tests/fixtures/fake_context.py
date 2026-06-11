"""Duck-typed fakes of the drawing ``DrawingContext`` shape, for hermetic tests.

The serializers (:mod:`drawing_analyzer.export`, :mod:`drawing_analyzer.html_report`)
are deliberately pure and duck-typed — they read only a handful of attributes off
the context and its sheets, never the engine itself. These fakes expose exactly
that read surface (``ref`` / ``text`` / ``error`` / ``cached`` / token counts on a
sheet; ``sheets`` / ``synthesis_text`` / ``combined_text`` / the run-summary
properties on the context), so both serializer test suites can build a context
without PyMuPDF, the network, or the real dataclasses. Keeping one definition here
means the shared shape can't drift between the two suites.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeRef:
    """Stand-in for :class:`drawing_analyzer.models.SheetRef`."""

    source_name: str
    page_index: int
    page_count: int

    @property
    def display_label(self) -> str:
        return f"{self.source_name} (page {self.page_index + 1}/{self.page_count})"


@dataclass
class FakeSheet:
    """Stand-in for :class:`drawing_analyzer.digest.SheetDigest`."""

    ref: FakeRef
    text: str = ""
    error: str | None = None
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


@dataclass
class FakeContext:
    """Stand-in for :class:`drawing_analyzer.pipeline.DrawingContext`."""

    sheets: list
    synthesis_text: str = ""
    combined_text: str = ""
    file_count: int = 1
    errors: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    focus: str = ""
    focus_report_text: str = ""

    @property
    def sheet_count(self) -> int:
        return len(self.sheets)

    @property
    def ok_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.ok)

    @property
    def cached_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.cached)
