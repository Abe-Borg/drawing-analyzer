"""Regenerate the local, asset-free trust page and the ledger's copy/source map.

Run with the project's installed environment: python scripts/write_trust_docs.py.
Do not import this script from tests: tests compare the actual artifacts instead.
"""
from pathlib import Path

from drawing_analyzer.trust_contract_docs import ledger_copy_map
from drawing_analyzer.trust_dossier import render_html

root = Path(__file__).resolve().parents[1]
ledger = root / "docs/TRUST_CLAIMS.md"
text = ledger.read_text(encoding="utf-8")
marker = "<!-- BEGIN GENERATED TRUST COPY MAP -->"
if marker in text:
    text = text[:text.index(marker)].rstrip()
(root / "docs/TRUST.html").write_text(render_html(), encoding="utf-8")
ledger.write_text(text.rstrip() + "\n\n" + ledger_copy_map() + "\n", encoding="utf-8")
