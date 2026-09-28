"""The one normalizer and the one shape check for an Anthropic API key (WP-16.1).

A key file saved "UTF-8 with BOM" was loaded with the BOM, because U+FEFF is not
whitespace and ``str.strip()`` keeps it (G3). The value then passed the key
store's verified round-trip, was migrated into the OS keyring, and every call
failed authentication from then on. Every place a key enters the app from a
person (a key file, a keyring entry, the GUI field, :func:`save_api_key`) now
goes through :func:`normalize_api_key` and :func:`looks_like_api_key`.

A leaf module, standard library only: :mod:`drawing_analyzer.diagnostics`
redacts with :data:`ANTHROPIC_KEY_RE`, and importing the key store instead
would pull the optional ``keyring`` package into every module that logs.
"""
from __future__ import annotations

import re
import unicodedata

#: Anthropic key material. The diagnostics redactor replaces every match of it
#: wherever it appears in a line; :func:`looks_like_api_key` accepts a value
#: only when the whole value matches it. One pattern, so what the store accepts
#: and what the log hides cannot drift apart. No length floor (plan WP-16 step
#: 3): a future key must not be refused by a length rule, and the suite's fake
#: keys are short.
ANTHROPIC_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def _is_edge_noise(ch: str) -> bool:
    # Whitespace as str.strip() sees it (NBSP included), and every Unicode
    # format character (category Cf): the BOM, a zero-width space, a word
    # joiner, a soft hyphen, the directional marks. None of them can be part of
    # a key, and none is visible in a text editor.
    return ch.isspace() or unicodedata.category(ch) == "Cf"


def normalize_api_key(value: str | None) -> str:
    """``value`` with whitespace and format characters stripped from both ends.

    Only the ends: a format character inside the value is left where it is, so
    :func:`looks_like_api_key` refuses the value instead of this function
    quietly editing a key (the owner's rule). Idempotent. ``None`` is ``""``.
    """
    text = value or ""
    start, end = 0, len(text)
    while start < end and _is_edge_noise(text[start]):
        start += 1
    while end > start and _is_edge_noise(text[end - 1]):
        end -= 1
    return text[start:end]


def looks_like_api_key(value: str | None) -> bool:
    """Is the whole of ``value`` shaped like an Anthropic API key?

    A local, conservative check (no API call): ``sk-ant-`` followed by one or
    more of ``A-Z a-z 0-9 _ -``. Call it on a normalized value.
    """
    return bool(ANTHROPIC_KEY_RE.fullmatch(value or ""))
