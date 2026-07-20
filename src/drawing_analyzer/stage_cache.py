"""Shared content-addressed cache helpers for post-digest model stages.

The pipeline already owns one opt-in :class:`DigestCache` instance.  Reusing its
small ``get``/``put`` protocol keeps one persistence policy while giving the
text-only stages their own rigor-preserving namespace.  Callers supply every
model-visible input plus the prompt and output-shaping parameters; any change to
that contract produces a miss.

This module deliberately knows nothing about stage result classes.  It stores a
defensive JSON-shaped payload and is therefore also usable by verification (or
future stages) without creating import cycles.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


_STAGE_CACHE_SCHEMA = 1
_STAGE_CACHE_NAMESPACE = "drawing-analyzer-stage-cache"


def stage_cache_key(
    stage: str,
    *,
    model: str,
    prompt: Any,
    inputs: Any,
    params: Any = None,
) -> str:
    """Return a deterministic key for one complete stage request contract.

    ``prompt``, ``inputs``, and ``params`` must be JSON-shaped values.  Keeping
    the serializer strict is intentional: silently stringifying an unsupported
    object could make two materially different requests share a cache entry.
    """
    envelope = {
        "namespace": _STAGE_CACHE_NAMESPACE,
        "schema": _STAGE_CACHE_SCHEMA,
        "stage": str(stage or ""),
        "model": str(model or ""),
        "prompt": prompt,
        "inputs": inputs,
        "params": params,
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"stage:{stage}:{digest}"


def get_stage_cache_entry(cache: Any, key: str, *, stage: str) -> dict | None:
    """Read and validate one stage payload; cache failures degrade to a miss."""
    if cache is None:
        return None
    try:
        entry = cache.get(key)
    except Exception:  # a cache can never sink the actual review
        return None
    if not isinstance(entry, dict):
        return None
    if entry.get("_kind") != _STAGE_CACHE_NAMESPACE:
        return None
    if entry.get("_schema") != _STAGE_CACHE_SCHEMA:
        return None
    if entry.get("stage") != stage:
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    return copy.deepcopy(payload)


def put_stage_cache_entry(
    cache: Any,
    key: str,
    *,
    stage: str,
    payload: dict,
) -> None:
    """Store one successful stage payload; persistence errors are non-fatal."""
    if cache is None or not isinstance(payload, dict):
        return
    try:
        # Validate the persistence contract up front.  A non-JSON value must not
        # become an in-memory-only "hit" that disappears or poisons a later disk
        # flush; round-tripping also detaches every nested object from the caller.
        safe_payload = json.loads(json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ))
    except (TypeError, ValueError):
        return
    entry = {
        "_kind": _STAGE_CACHE_NAMESPACE,
        "_schema": _STAGE_CACHE_SCHEMA,
        "stage": stage,
        "payload": safe_payload,
    }
    try:
        cache.put(key, entry)
    except Exception:  # the computed result is still valid if persistence fails
        return
