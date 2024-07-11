from collections import deque
from itertools import count
from pathlib import Path
from threading import current_thread
from types import FrameType
from types import TracebackType
import typing as t
import uuid

import attr

from ddtrace._trace.span import Span
from ddtrace.debugging._probe.model import LiteralTemplateSegment
from ddtrace.debugging._probe.model import LogLineProbe
from ddtrace.debugging._signal.collector import SignalCollector
from ddtrace.debugging._signal.snapshot import DEFAULT_CAPTURE_LIMITS
from ddtrace.debugging._signal.snapshot import Snapshot
from ddtrace.internal import core
from ddtrace.internal.logger import get_logger
from ddtrace.internal.packages import is_user_code
from ddtrace.internal.rate_limiter import BudgetRateLimiterWithJitter as RateLimiter
from ddtrace.internal.rate_limiter import RateLimitExceeded


log = get_logger(__name__)

GLOBAL_RATE_LIMITER = RateLimiter(
    limit_rate=1,  # one trace per second
    raise_on_exceed=False,
)

# used to store a snapshot on the frame locals
SNAPSHOT_KEY = "_dd_exception_replay_snapshot_id"

# used to mark that the span have debug info captured, visible to users
DEBUG_INFO_TAG = "error.debug_info_captured"

# used to rate limit decision on the entire local trace (stored at the root span)
CAPTURE_TRACE_TAG = "_dd.debug.error.trace_captured"

# unique exception id
EXCEPTION_ID_TAG = "_dd.debug.error.exception_id"

# link to matching snapshot for every frame in the traceback
FRAME_SNAPSHOT_ID_TAG = "_dd.debug.error.%d.snapshot_id"
FRAME_FUNCTION_TAG = "_dd.debug.error.%d.function"
FRAME_FILE_TAG = "_dd.debug.error.%d.file"
FRAME_LINE_TAG = "_dd.debug.error.%d.line"


def unwind_exception_chain(
    exc: t.Optional[BaseException],
    tb: t.Optional[TracebackType],
) -> t.Tuple[t.Deque[t.Tuple[BaseException, t.Optional[TracebackType]]], t.Optional[uuid.UUID]]:
    """Unwind the exception chain and assign it an ID."""
    chain: t.Deque[t.Tuple[BaseException, t.Optional[TracebackType]]] = deque()

    while exc is not None:
        chain.append((exc, tb))

        if exc.__cause__ is not None:
            exc = exc.__cause__
        elif exc.__context__ is not None and not exc.__suppress_context__:
            exc = exc.__context__
        else:
            exc = None

        tb = getattr(exc, "__traceback__", None)

    exc_id = None
    if chain:
        # If the chain is not trivial we generate an ID for the whole chain and
        # store it on the outermost exception, if not already generated.
        exc, _ = chain[-1]
        try:
            exc_id = exc._dd_exc_id  # type: ignore[attr-defined]
        except AttributeError:
            exc._dd_exc_id = exc_id = uuid.uuid4()  # type: ignore[attr-defined]

    return chain, exc_id


@attr.s
class SpanExceptionProbe(LogLineProbe):
    @classmethod
    def build(cls, exc_id: uuid.UUID, frame: FrameType) -> "SpanExceptionProbe":
        _exc_id = str(exc_id)
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        name = frame.f_code.co_name
        message = f"exception info for {name}, in {filename}, line {line} (exception ID {_exc_id})"

        return cls(
            probe_id=_exc_id,
            version=0,
            tags={},
            source_file=filename,
            line=line,
            template=message,
            segments=[LiteralTemplateSegment(message)],
            take_snapshot=True,
            limits=DEFAULT_CAPTURE_LIMITS,
            condition=None,
            condition_error_rate=0.0,
            rate=float("inf"),
        )


@attr.s
class SpanExceptionSnapshot(Snapshot):
    exc_id = attr.ib(type=t.Optional[uuid.UUID], default=None)

    @property
    def data(self) -> t.Dict[str, t.Any]:
        data = super().data

        data.update({"exception-id": str(self.exc_id)})

        return data


def can_capture(span: Span) -> bool:
    # We determine if we should capture the exception information from the span
    # by looking at its local root. If we have budget to capture, we mark the
    # root as "info captured" and return True. If we don't have budget, we mark
    # the root as "info not captured" and return False. If the root is already
    # marked, we return the mark.
    root = span._local_root
    if root is None:
        return False

    info_captured = root.get_tag(CAPTURE_TRACE_TAG)

    if info_captured == "false":
        return False

    if info_captured == "true":
        return True

    if info_captured is None:
        result = GLOBAL_RATE_LIMITER.limit() is not RateLimitExceeded
        root.set_tag_str(CAPTURE_TRACE_TAG, str(result).lower())
        return result

    msg = f"unexpected value for {CAPTURE_TRACE_TAG}: {info_captured}"
    raise ValueError(msg)


@attr.s
class SpanExceptionHandler:
    collector = attr.ib(type=SignalCollector)

    def install(self) -> None:
        core.on("span.exception", self.on_span_exception, name=__name__)

    def on_span_exception(
        self, span: Span, _exc_type: t.Type[BaseException], exc: BaseException, _tb: t.Optional[TracebackType]
    ) -> None:
        if span.get_tag(DEBUG_INFO_TAG) == "true" or not can_capture(span):
            # Debug info for span already captured or no budget to capture
            return

        chain, exc_id = unwind_exception_chain(exc, _tb)
        if not chain or exc_id is None:
            # No exceptions to capture
            return

        seq = count(1)  # 1-based sequence number

        while chain:
            exc, _tb = chain.pop()  # LIFO: reverse the chain

            if _tb is None or _tb.tb_frame is None:
                # If we don't have a traceback there isn't much we can do
                continue

            # DEV: We go from the handler up to the root exception
            while _tb and _tb.tb_frame:
                frame = _tb.tb_frame
                code = frame.f_code
                seq_nr = next(seq)

                if is_user_code(Path(frame.f_code.co_filename)):
                    snapshot_id = frame.f_locals.get(SNAPSHOT_KEY, None)
                    if snapshot_id is None:
                        # We don't have a snapshot for the frame so we create one
                        snapshot = SpanExceptionSnapshot(
                            probe=SpanExceptionProbe.build(exc_id, frame),
                            frame=frame,
                            thread=current_thread(),
                            trace_context=span,
                            exc_id=exc_id,
                        )

                        # Capture
                        snapshot.line()

                        # Collect
                        self.collector.push(snapshot)

                        # Memoize
                        frame.f_locals[SNAPSHOT_KEY] = snapshot_id = snapshot.uuid

                    # Add correlation tags on the span
                    span.set_tag_str(FRAME_SNAPSHOT_ID_TAG % seq_nr, snapshot_id)
                    span.set_tag_str(FRAME_FUNCTION_TAG % seq_nr, code.co_name)
                    span.set_tag_str(FRAME_FILE_TAG % seq_nr, code.co_filename)
                    span.set_tag_str(FRAME_LINE_TAG % seq_nr, str(_tb.tb_lineno))

                # Move up the stack
                _tb = _tb.tb_next

            span.set_tag_str(DEBUG_INFO_TAG, "true")
            span.set_tag_str(EXCEPTION_ID_TAG, str(exc_id))


def capture_exception() -> None:
    import sys

    from ddtrace import tracer

    try:
        span = tracer.current_span()
        if span is not None and not span.error:
            span.set_exc_info(*sys.exc_info())
    except Exception:
        log.exception("error capturing exception")
