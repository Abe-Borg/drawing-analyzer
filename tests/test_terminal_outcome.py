"""The shared terminal-outcome classifier (D-1, WP-01.2).

``stop_reason`` decides whether a response is finished work before any text or
JSON is looked at. The vocabulary is the installed SDK's, and these tests pin
the classifier to it: an SDK upgrade that adds a stop reason fails here until
someone classifies it (until then the new reason is UNKNOWN, never finished).
"""
from __future__ import annotations

import typing

import pytest

from drawing_analyzer.core.terminal_outcome import (
    CONTINUATION,
    FINISHED,
    KINDS,
    REFUSED,
    STOP_REASON_KINDS,
    TRUNCATED,
    UNFINISHED,
    UNKNOWN,
    TerminalOutcome,
    classify_stop_reason,
)


def _sdk_stop_reasons() -> set[str]:
    from anthropic.types import StopReason
    from anthropic.types.beta import BetaStopReason

    return set(typing.get_args(StopReason)) | set(typing.get_args(BetaStopReason))


def test_every_sdk_stop_reason_is_classified_and_nothing_else_is():
    # Both vocabularies: an Opus 5 call travels the beta namespace for the
    # refusal fallback, so a response can carry BetaStopReason's extra values.
    assert set(STOP_REASON_KINDS) == _sdk_stop_reasons()
    for stop_reason in _sdk_stop_reasons():
        assert classify_stop_reason(stop_reason).kind != UNKNOWN, stop_reason


@pytest.mark.parametrize(
    "stop_reason, kind",
    [
        ("end_turn", FINISHED),
        ("stop_sequence", FINISHED),
        ("max_tokens", TRUNCATED),
        ("model_context_window_exceeded", TRUNCATED),
        ("refusal", REFUSED),
        ("tool_use", CONTINUATION),
        ("pause_turn", CONTINUATION),
        ("compaction", CONTINUATION),
        (None, UNFINISHED),
    ],
)
def test_the_classification(stop_reason, kind):
    outcome = classify_stop_reason(stop_reason)
    assert outcome == TerminalOutcome(kind, stop_reason)
    assert outcome.kind in KINDS
    assert outcome.finished is (kind == FINISHED)


@pytest.mark.parametrize(
    "stop_reason",
    ["a_stop_reason_from_the_future", "", "END_TURN", " end_turn", 0, 1, True, object()],
)
def test_anything_the_sdk_does_not_name_is_unknown_and_never_finished(stop_reason):
    # Strict equality on purpose: a spelling the API never sends is not a
    # promise that the model finished.
    outcome = classify_stop_reason(stop_reason)
    assert outcome.kind == UNKNOWN
    assert not outcome.finished
    assert not outcome.raised_cap_may_finish


def test_only_a_max_tokens_truncation_can_be_finished_by_a_raised_cap():
    # A context-window stop is a truncation too, but the window is the limit,
    # not max_tokens: raising the cap cannot make room.
    may_finish = {
        stop for stop in _sdk_stop_reasons()
        if classify_stop_reason(stop).raised_cap_may_finish
    }
    assert may_finish == {"max_tokens"}
    assert not classify_stop_reason(None).raised_cap_may_finish


def test_only_end_turn_and_stop_sequence_are_finished():
    finished = {
        stop for stop in _sdk_stop_reasons() if classify_stop_reason(stop).finished
    }
    assert finished == {"end_turn", "stop_sequence"}
