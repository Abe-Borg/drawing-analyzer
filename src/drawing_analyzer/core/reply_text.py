"""The text of one Messages reply, read as the model wrote it (remediation WP-01.6, U2).

Every stage that reads a reply's text reads it here, so there is one join.

A reply's ``content`` is a list of blocks, and the text is spread over the
``text`` blocks among them. Two kinds of boundary separate them:

* a **fallback boundary**. A real-time call that carries the server-side refusal
  fallback (``core.api_config.call_with_refusal_fallback``) can be declined part
  way through a streamed reply. The API closes the open block, marks the switch
  with a ``fallback`` content block, and the fallback model *continues from the
  partial output* (Anthropic: "only the partial output's ``text`` blocks are
  passed to the fallback model as context"). The text on either side is one
  text two models wrote, and the split can fall anywhere: mid-word, or inside
  the digest's findings JSON. So the two sides are joined with nothing between
  them, whatever else sits in between (a thinking block included). A
  non-streamed reply declined part way omits the partial and starts over
  (``[fallback, text]``), which the same rule reads correctly;
* any **other boundary** (a tool use, a server tool result, two adjacent text
  blocks): joined with ``between``, ``"\\n"`` by default, as the join always
  was. So a reply without a ``fallback`` block reads byte-identical to the
  1.7.0 join, and nothing stored from one changes. A caller whose blocks are
  splits of one text (citations: WP-12.1) passes ``between=""``.

A block is told by its ``type`` and nothing else. Measured through the real SDK
(1.7.0 and 1.8.0): the plain namespace parses a ``fallback`` block as a
``TextBlock`` whose ``type`` is ``"fallback"``, so a test of the class would read
it as text. It carries no text of its own and never contributes any.

Shape-tolerant (an SDK model on either namespace, or a plain dict), stdlib only,
and it never raises on a malformed reply: a missing or ``None`` field reads as
empty. The result is stripped at both ends, as before.
"""
from __future__ import annotations

from typing import Any

#: The ``type`` of the block the API puts where one model's output gives way
#: to the next (the server-side refusal fallback).
FALLBACK_BLOCK_TYPE = "fallback"

_TEXT_BLOCK_TYPE = "text"


def _field(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def reply_text(resp: Any, *, between: str = "\n") -> str:
    """The reply's text: its ``text`` blocks in order, stripped at both ends.

    Two text blocks with a ``fallback`` block anywhere between them are joined
    with nothing (the fallback model continued the partial text); any other
    two are joined with ``between``. Empty text blocks are skipped, and a
    fallback boundary carries over them to the next text.
    """
    parts: list[str] = []
    continues = False
    for block in _field(resp, "content") or ():
        kind = _field(block, "type")
        if kind == FALLBACK_BLOCK_TYPE:
            continues = True
            continue
        if kind != _TEXT_BLOCK_TYPE:
            continue
        text = _field(block, "text")
        if not isinstance(text, str) or not text:
            continue
        if parts:
            parts.append("" if continues else between)
        parts.append(text)
        continues = False
    return "".join(parts).strip()
