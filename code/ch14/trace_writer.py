"""Async, ordered, backpressure-aware writer for Ch 9 evidence entries.

The agent loop calls ``submit()`` and keeps moving; a single consumer thread
drains a bounded queue into Ch 9's ``EvidenceRouter.emit()``. The ordering and
safety properties are the whole point:

  - ORDER: sequence numbers are assigned under a lock at submit time, and the
    single consumer preserves FIFO order. Entries land in the audit log in
    submission order even under concurrent producers.
  - BACKPRESSURE: the queue is bounded. When it fills, ``submit()`` BLOCKS —
    the agent pauses — rather than dropping evidence. An agent that outruns
    its evidence is an agent whose actions are unverifiable, so slowing the
    agent down is the correct response, not losing the record.
  - NO SILENT LOSS: if the consumer thread dies, ``submit()`` raises
    ``EvidenceWriterDown`` instead of buffering into the void. Evidence loss
    is a safety event, and safety events are loud.
  - FLUSH ON SHUTDOWN: ``close()`` drains the queue before stopping the
    consumer. The context-manager protocol does the same.

``router`` is duck-typed on ``emit(session, event_type, payload)`` — in
production it is Ch 9's EvidenceRouter; the consumer only needs that one
method (cf. Ch 9: the router is the single choke point).
"""

from __future__ import annotations

import queue
import threading
import time


class EvidenceWriterDown(RuntimeError):
    """Raised when the consumer thread has died. The writer is unusable."""


class TraceWriter:
    """Async evidence emitter with backpressure. Submit, don't wait."""

    def __init__(self, router, capacity: int = 10_000,
                 put_timeout: float = 30.0) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._router = router
        self._put_timeout = put_timeout
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self._seq_lock = threading.Lock()
        self._next_seq = 0
        self._submitted = 0
        self._emitted = 0
        self._backpressure_events = 0
        self._stats_lock = threading.Lock()
        self._failed: BaseException | None = None
        self._stopping = threading.Event()
        self._consumer = threading.Thread(
            target=self._drain, name="trace-writer", daemon=True)
        self._consumer.start()

    # -- producer -----------------------------------------------------------
    def submit(self, session, event_type: str, payload: dict) -> int:
        """Queue one evidence entry. Returns the submission sequence number.

        Blocks (pauses the caller) when the queue is full — backpressure.
        Raises EvidenceWriterDown if the consumer thread has died: we refuse
        to accept evidence we cannot emit.
        """
        if self._failed is not None:
            raise EvidenceWriterDown(
                f"consumer thread died: {self._failed!r}")
        with self._seq_lock:
            seq = self._next_seq
            self._next_seq += 1
        # put(block=True) is the backpressure: a full queue pauses the agent.
        try:
            self._queue.put((seq, session, event_type, dict(payload or {})),
                            block=True, timeout=self._put_timeout)
        except queue.Full:
            # A full queue past put_timeout means the consumer is wedged; the
            # agent must not proceed unverified. Loud failure, not silent loss.
            with self._stats_lock:
                self._backpressure_events += 1
            raise EvidenceWriterDown(
                f"evidence queue full for {self._put_timeout}s; refusing to "
                f"run unverified")
        with self._stats_lock:
            self._submitted += 1
        return seq

    # -- consumer -----------------------------------------------------------
    def _drain(self) -> None:
        """Single consumer: preserves submission order into the router."""
        while True:
            item = self._queue.get()
            if item is None:  # the shutdown sentinel
                self._queue.task_done()
                return
            seq, session, event_type, payload = item
            try:
                self._router.emit(session, event_type, payload)
            except BaseException as exc:  # noqa: BLE001 — must not kill the loop silently
                # A poisoned entry (or a dead router) is a safety event.
                # Mark the writer failed so future submits raise loudly;
                # the entries already queued stay queued for inspection.
                self._failed = exc
                self._queue.task_done()
                return
            with self._stats_lock:
                self._emitted += 1
            self._queue.task_done()

    # -- lifecycle ----------------------------------------------------------
    def flush(self, timeout: float = 30.0) -> bool:
        """Block until every submitted entry has been emitted.

        Returns True when drained, False on timeout (entries are still
        queued — nothing was lost, but the caller knows the lag).
        """
        deadline = time.monotonic() + timeout
        while True:
            # The failure check comes FIRST: a dead consumer with an empty
            # queue must still fail loudly, not report a clean drain.
            if self._failed is not None:
                raise EvidenceWriterDown(
                    f"consumer thread died during flush: {self._failed!r}")
            if self._queue.unfinished_tasks == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)

    def close(self) -> None:
        """Flush, then stop the consumer. Evidence is never abandoned."""
        if not self.flush():
            raise EvidenceWriterDown(
                "could not drain the evidence queue on shutdown; "
                "refusing to exit with unverified actions outstanding")
        self._stopping.set()
        self._queue.put(None)  # shutdown sentinel
        self._consumer.join(timeout=10.0)

    def stats(self) -> dict:
        """Operational counters for the SLO dashboard (Ch 14 prose)."""
        with self._stats_lock:
            return {
                "submitted": self._submitted,
                "emitted": self._emitted,
                "backpressure_events": self._backpressure_events,
                "queue_depth": self._queue.qsize(),
                "failed": self._failed is not None,
            }

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
