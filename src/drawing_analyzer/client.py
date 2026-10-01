"""Anthropic client factory for the drawing analyzer.

A small cached wrapper around the Anthropic SDK client. It mirrors the behavior
of the original host app's client factory — read the key from the environment,
cache one client per key — without pulling in any unrelated code. Importing this
module never requires a key; the key is read lazily on first use.

Two callers, one construction (:func:`new_client`):

- a library or script caller passes no client, and each stage that needs one
  calls :func:`get_client`, which reads ``ANTHROPIC_API_KEY`` on every call;
- the GUI builds one client per run from the key it snapshotted at Analyze and
  passes it to ``extract_drawing_context`` (remediation WP-16.2, G2), so no
  stage of a GUI run reads the environment, and the GUI never writes it.
"""
from __future__ import annotations

import os

from anthropic import Anthropic

_cached_client: Anthropic | None = None
_cached_key: str | None = None


def new_client(api_key: str) -> Anthropic:
    """Build an SDK client for ``api_key``: the one construction.

    :func:`get_client` builds its cached client here and the GUI builds each
    run's client here, so a run's client is the one a library caller gets: the
    SDK's default retries and timeouts, and every request path (the refusal
    fallback included) unchanged.
    """
    return Anthropic(api_key=api_key)


def get_client() -> Anthropic:
    """Return a process-wide cached Anthropic client.

    Reads ``ANTHROPIC_API_KEY`` from the environment. Raises ``ValueError`` when
    it is unset so a misconfigured run fails loudly instead of at the API.
    """
    global _cached_client, _cached_key
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    if _cached_client is None or _cached_key != key:
        _cached_client = new_client(key)
        _cached_key = key
    return _cached_client
