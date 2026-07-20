from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from drawing_analyzer.file_upload import (
    ReusableSheetUpload,
    iter_prefetched_sheets,
    retask_uploaded_content,
)


def test_retask_changes_only_final_instruction_without_mutating_digest_content() -> None:
    digest_content = [
        {"type": "text", "text": "framing"},
        {"type": "image", "source": {"type": "file", "file_id": "file-1"}},
        {"type": "text", "text": "digest task"},
    ]

    critique_content = retask_uploaded_content(digest_content, "critique task")

    assert digest_content[-1]["text"] == "digest task"
    assert critique_content[:-1] == digest_content[:-1]
    assert critique_content[-1] == {"type": "text", "text": "critique task"}
    assert critique_content[1]["source"]["file_id"] == "file-1"


def test_reusable_upload_preserves_ids_and_builds_stage_specific_content() -> None:
    upload = ReusableSheetUpload(
        ref="sheet-ref",
        rows=6,
        cols=6,
        content=[{"type": "image", "source": {"file_id": "f"}}],
        file_ids=["f"],
    )

    content = upload.content_for("review this sheet")

    assert content[-1] == {"type": "text", "text": "review this sheet"}
    assert upload.file_ids == ["f"]


def test_reusable_upload_transfers_cleanup_ownership_exactly_once() -> None:
    upload = ReusableSheetUpload(
        ref="sheet-ref",
        rows=6,
        cols=6,
        content=[
            {"type": "image", "source": {"file_id": "f"}},
            {"type": "text", "text": "digest"},
        ],
        file_ids=["f"],
    )

    transferred = upload.transfer("critique")

    assert transferred is not None
    assert transferred.file_ids == ["f"]
    assert transferred.content[-1] == {"type": "text", "text": "critique"}
    assert upload.available is False
    assert upload.transfer("another owner") is None
    assert upload.release_ids() == []


def test_reusable_upload_release_and_transfer_are_thread_safe_and_exclusive() -> None:
    upload = ReusableSheetUpload(
        ref="sheet-ref", rows=6, cols=6,
        content=[{"type": "text", "text": "digest"}],
        file_ids=["f1", "f2"],
    )

    def _claim(index: int) -> list[str]:
        if index % 2:
            transferred = upload.transfer("critique")
            return [] if transferred is None else transferred.file_ids
        return upload.release_ids()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(_claim, range(16)))

    assert [claim for claim in claims if claim] == [["f1", "f2"]]


def test_prefetched_sheets_overlaps_next_render_and_preserves_order() -> None:
    next_requested = threading.Event()
    allow_second = threading.Event()

    def _rendered():
        yield "sheet-0"
        next_requested.set()
        assert allow_second.wait(1)
        yield "sheet-1"
        yield "sheet-2"

    prefetched = iter(iter_prefetched_sheets(_rendered()))
    assert next(prefetched) == "sheet-0"
    assert next_requested.wait(1), "second render did not overlap current-sheet work"
    allow_second.set()
    assert next(prefetched) == "sheet-1"
    assert next(prefetched) == "sheet-2"
    with pytest.raises(StopIteration):
        next(prefetched)


def test_prefetched_sheets_early_close_finalizes_source_on_render_worker() -> None:
    main_thread = threading.get_ident()
    lookahead_started = threading.Event()
    release_lookahead = threading.Event()
    next_threads: list[int] = []
    close_threads: list[int] = []

    class _Source:
        def __init__(self):
            self.position = 0

        def __iter__(self):
            return self

        def __next__(self):
            next_threads.append(threading.get_ident())
            self.position += 1
            if self.position == 1:
                return "sheet-0"
            if self.position == 2:
                lookahead_started.set()
                assert release_lookahead.wait(1)
                return "sheet-1"
            raise AssertionError("cleanup advanced the renderer again")

        def close(self):
            close_threads.append(threading.get_ident())

    prefetched = iter_prefetched_sheets(_Source())
    assert next(prefetched) == "sheet-0"
    assert lookahead_started.wait(1)
    release_lookahead.set()
    prefetched.close()

    assert len(next_threads) == 2
    assert close_threads == [next_threads[0]]
    assert close_threads[0] != main_thread
