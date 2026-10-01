"""One fallback-aware text join for every reply (remediation WP-01.6, U2; the owner's rules).

A real-time call to a model that declares the server-side refusal fallback
(Opus 5.5, Sonnet 5.5, Opus 5) can be declined part way through a streamed
reply. The API then closes the open text block, marks the boundary with a
``fallback`` content block, and the fallback model **continues from the
partial output** (Anthropic's refusals-and-fallback page: "only the partial
output's ``text`` blocks are passed to the fallback model as context"), so the
text on either side is one text the two models wrote, split anywhere, mid-word
included. A non-streamed reply declined part way omits the partial and answers
from scratch: ``[fallback, text]``.

``digest._message_text`` joined every text block with ``"\\n"``, so ``12`` +
`` inches`` read ``1\\n2 inches``, a boundary inside the digest's findings JSON
lost the finding, and a critique read split that way failed although it was
good. Measured through the real SDK (SDK 1.7.0 and 1.8.0, identical): the plain
namespace parses a ``fallback`` block as a ``TextBlock`` whose ``type`` is
``"fallback"`` (it carries no text), and the beta namespace as a
``BetaFallbackBlock``; so a join must read ``type``, never the class.

The owner's rules:

- **Contiguous across a fallback block**, whatever sits around it (thinking
  blocks included); ``"\\n"`` between any other two text blocks, as before, so
  every reply without a fallback block reads byte-identical (no stored text
  changes). ``between=`` lets WP-12.1 pass ``""`` for citation splits.
- **One helper**, ``core.reply_text.reply_text``: ``digest._message_text`` is
  gone and every module that read it reads this.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import drawing_analyzer
from drawing_analyzer import digest
from drawing_analyzer.core.reply_text import FALLBACK_BLOCK_TYPE, reply_text
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import AnthropicAPIStub

SRC = Path(drawing_analyzer.__file__).resolve().parent

TEXT = 'The pipe is 12 inches.\n```json\n{"findings": [{"text": "VAV-3 missing"}]}\n```'
THINKING = {"type": "thinking", "thinking": "", "signature": "sig"}


def _fb(to: str = "claude-opus-4-8") -> dict:
    return R.fallback_block("claude-opus-5-5", to)


# --------------------------------------------------------------------------- #
# The rule, over plain API JSON
# --------------------------------------------------------------------------- #

# name -> (content, the text it reads as)
_CASES = {
    "one-text": ([R.text("only")], "only"),
    "no-content": ([], ""),
    "fallback-mid-word": ([R.text("The pipe is 1"), _fb(), R.text("2 inches.")],
                          "The pipe is 12 inches."),
    "fallback-keeps-the-boundary-space": ([R.text("12"), _fb(), R.text(" inches")], "12 inches"),
    "fallback-between-thinking": ([THINKING, R.text("VA"), _fb(), THINKING, R.text("V-3")],
                                  "VAV-3"),
    "fallback-first": ([_fb(), R.text("full answer")], "full answer"),
    "two-fallbacks": ([R.text("a"), _fb(), R.text("b"), _fb("claude-opus-5"), R.text("c")],
                      "abc"),
    "fallback-then-empty-text": ([R.text("VA"), _fb(), R.text(""), R.text("V-3")], "VAV-3"),
    "ordinary-blocks-keep-the-newline": ([R.text("Let me search."),
                                          R.server_tool_use(web_search=1),
                                          R.text("Found it.")],
                                         "Let me search.\nFound it."),
    "adjacent-texts-keep-the-newline": ([R.text("NFPA "), R.text("13")], "NFPA \n13"),
    "a-newline-after-the-fallback-only-where-another-block-follows": (
        [R.text("a"), _fb(), R.text("b"), R.text("c")], "ab\nc"),
    "outer-whitespace-stripped": ([R.text("  x"), _fb(), R.text("y \n")], "xy"),
}


@pytest.mark.parametrize("name", sorted(_CASES), ids=sorted(_CASES))
def test_the_join_rule_over_api_json(name):
    content, expected = _CASES[name]

    assert reply_text(R.message(content)) == expected


def test_between_joins_ordinary_blocks_only():
    # WP-12.1 passes "" for citation splits; a fallback boundary is "" anyway.
    msg = R.message([R.text("NFPA "), R.text("13"), _fb(), R.text(" ed.")])

    assert reply_text(msg, between="") == "NFPA 13 ed."
    assert reply_text(msg) == "NFPA \n13 ed."


def test_a_fallback_block_is_named_by_its_type():
    assert FALLBACK_BLOCK_TYPE == "fallback"
    # A fallback block never contributes text of its own, even one that
    # carries a stray "text" key.
    msg = R.message([R.text("a"), dict(_fb(), text="IGNORED"), R.text("b")])
    assert reply_text(msg) == "ab"


def test_a_reply_without_a_fallback_block_is_unchanged():
    """Every reply the suite sends has at most one text block beside the
    ``[text, fallback, text]`` recorded limits (measured over the whole suite:
    3,882 joins, 6 of them multi-block, all fallback-split), so for everything
    else the new join is the old one, byte for byte."""
    for content in ([R.text(TEXT)], [THINKING, R.text(TEXT)],
                    [R.text("a"), R.tool_use("crop_region", {}), R.text("b")]):
        msg = R.message(content)
        old = "\n".join(b["text"] for b in content if b.get("type") == "text" and b["text"]).strip()
        assert reply_text(msg) == old


def test_tolerates_missing_and_odd_shapes():
    assert reply_text(None) == ""
    assert reply_text({}) == ""
    assert reply_text({"content": None}) == ""
    assert reply_text({"content": [{"type": "text", "text": None}, {"type": "text"}]}) == ""


# --------------------------------------------------------------------------- #
# Through the real SDK: both namespaces, create and stream, both 5.5 models
# --------------------------------------------------------------------------- #

_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
_ENTRIES = ("plain.create", "plain.stream", "beta.create", "beta.stream")


def _served(model: str, content: list[dict]) -> dict:
    return R.message(content, model=model)


def _call(client, entry: str, model: str):
    req = dict(model=model, max_tokens=100, messages=[{"role": "user", "content": "x"}])
    namespace, method = entry.split(".")
    if namespace == "beta":
        req.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        messages = client.beta.messages
    else:
        messages = client.messages
    if method == "create":
        return messages.create(**req)
    with messages.stream(**req) as stream:
        return stream.get_final_message()


@pytest.mark.parametrize("entry", _ENTRIES, ids=list(_ENTRIES))
@pytest.mark.parametrize("model", _MODELS, ids=list(_MODELS))
@pytest.mark.parametrize("at", [13, TEXT.index("VAV") + 2], ids=["prose", "findings-json"])
def test_a_fallback_split_reply_reads_as_the_text_the_models_wrote(model, entry, at):
    to = "claude-opus-4-8" if "opus" in model else "claude-sonnet-5"
    reply = R.splice_fallback(_served(model, [R.text(TEXT)]), at, to_model=to)
    message = _call(AnthropicAPIStub(lambda params: reply).client(), entry, model)

    assert [b.type for b in message.content] == ["text", FALLBACK_BLOCK_TYPE, "text"]
    assert reply_text(message) == TEXT


@pytest.mark.parametrize("entry", _ENTRIES, ids=list(_ENTRIES))
def test_the_plain_namespace_parses_a_fallback_block_as_a_text_block(entry):
    """The measured SDK fact the join relies on: on the plain namespace a
    ``fallback`` block comes back as a ``TextBlock`` (``ParsedTextBlock`` from
    a stream) keeping ``type="fallback"``; only ``type`` tells it apart. A
    helper that tested ``isinstance(block, TextBlock)`` would read it as text."""
    reply = R.splice_fallback(_served("claude-opus-5-5", [R.text(TEXT)]), 13,
                              to_model="claude-opus-4-8")
    message = _call(AnthropicAPIStub(lambda params: reply).client(), entry, "claude-opus-5-5")
    block = message.content[1]

    assert block.type == FALLBACK_BLOCK_TYPE
    if entry.startswith("plain"):
        assert type(block).__name__ in {"TextBlock", "ParsedTextBlock"}
    else:
        assert type(block).__name__ == "BetaFallbackBlock"
    assert reply_text(message) == TEXT


# --------------------------------------------------------------------------- #
# One helper: no second join
# --------------------------------------------------------------------------- #

# Every module that read digest._message_text before WP-01.6.
_READERS = ("batch_digest", "citation_check", "critique", "cross_qc", "digest", "focus",
            "investigate", "prose_harvest", "review_planner", "set_identity", "synthesis",
            "verify")


def test_the_old_join_is_gone():
    assert not hasattr(digest, "_message_text")


@pytest.mark.parametrize("module", _READERS, ids=list(_READERS))
def test_every_former_reader_reads_the_shared_join(module):
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}

    assert "reply_text" in names
    assert "_message_text" not in names


def _compares_type_to_text(node: ast.Compare) -> bool:
    """``<x>.type == "text"``, ``_get(b, "type") == "text"`` or
    ``b.get("type") == "text"``: a test of a content block's type."""
    if not any(isinstance(c, ast.Constant) and c.value == "text" for c in node.comparators):
        return False
    left = node.left
    if isinstance(left, ast.Attribute):
        return left.attr == "type"
    if isinstance(left, ast.Call):
        return any(isinstance(a, ast.Constant) and a.value == "type" for a in left.args)
    return False


# Request builders (they build content, not read a reply).
_REQUEST_SIDE = {"file_upload.py"}
# This formatter handles outgoing host tool results, preserving separate
# images/text. Exclude only that function; investigation's reply-reading code
# must remain covered by the structural pin below.
_REQUEST_SIDE_FUNCTIONS = {"investigate.py": {"_tool_source_content"}}


def test_no_module_reads_reply_text_blocks_itself():
    """The structural pin: outside the helper, nothing in the package tests a
    content block for ``type == "text"``, so a second join cannot come back
    (the chat widget's JavaScript renders blocks and sends no ``fallbacks``)."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "core/reply_text.py" or path.name in _REQUEST_SIDE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in _REQUEST_SIDE_FUNCTIONS.get(rel, set())):
                continue
            offenders += [f"{rel}:{n.lineno}" for n in ast.walk(node)
                          if isinstance(n, ast.Compare) and _compares_type_to_text(n)]

    assert offenders == []


def test_the_helper_lives_in_the_stdlib_only_kernel():
    tree = ast.parse((SRC / "core" / "reply_text.py").read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.level == 0}

    assert imported <= {"__future__", "typing"}, imported
