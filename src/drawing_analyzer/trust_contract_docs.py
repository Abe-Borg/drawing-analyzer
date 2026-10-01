"""Reproducible copy/source index for the checked-in trust artifacts."""
from __future__ import annotations

from . import trust_dossier as trust
from .help_content import TRUST_SHORT_SOURCES, help_document


def ledger_copy_map() -> str:
    def cell(text):
        return text.replace("|", "\\|").replace("\n", " ")

    lines = ["<!-- BEGIN GENERATED TRUST COPY MAP -->",
             "Every statement below maps to the file/symbol evidence in its inventory rows above. "
             "Verification: `test_runtime_inventory_is_complete`, `test_trust_facts`, "
             "`test_generated_docs_match_content_and_ledger`; non-numerical mechanism claims "
             "also require manual source inspection. Generated with `scripts/write_trust_docs.py`.",
             "", "| Copy ID | Factual copy (including each table row) | Source ledger IDs |",
             "| --- | --- | --- |"]
    short = help_document("why_trust_it")
    lines.append(f"| S00 | {cell(short.intro)} | A06, A11, A13, A16 |")
    for i, section in enumerate(short.sections[:-1], 1):
        key = f"S{i:02d}"
        statement = section.heading + ": " + " ".join(b.text for b in section.blocks)
        lines.append(f"| {key} | {cell(statement)} | {', '.join(TRUST_SHORT_SOURCES[key])} |")
    for section in trust.sections():
        for index, block in enumerate(section.blocks, 1):
            key = f"{section.id}.{index}"
            for part_index, statement in enumerate(trust.plain_blocks(block), 1):
                lines.append(f"| {key}.{part_index} | {cell(statement)} | {', '.join(block.refs)} |")
    lines += ["", "| Interpolated value | Source file and exact symbol | Verification |",
              "| --- | --- | --- |"]
    for source in sorted(trust.FACT_SOURCES):
        module, symbol = source.rsplit(".", 1)
        lines.append(f"| `{cell(str(trust.fact(source)))}` | `src/drawing_analyzer/{module.replace('.', '/')}.py: {symbol}` | `test_trust_facts`; direct source read |")
    lines += ["", "Non-exported literals (`PINNED_FACTS`) are asserted against production "
              "JavaScript, verification function defaults and the installed SDK in "
              "`test_trust_facts`. Disable-switch values, the unused token-count path, "
              "model IDs and hostname routes are tested separately in this file. "
              "Percent/minute notation derives from the source overlap/stall constants. "
              "SHA-256 is the hash algorithm invoked by `hashlib.sha256` in "
              "`source_registry.py`, `run_journal.py`, `verify.py` and `core/updates.py`. "
              "SVG coordinates and document section/card ordinals are presentation, not app limits.",
              "<!-- END GENERATED TRUST COPY MAP -->"]
    return "\n".join(lines)
