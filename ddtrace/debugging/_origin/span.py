from dataclasses import dataclass
from functools import partial as λ
from itertools import count
from pathlib import Path
import sys
from threading import current_thread
from types import FrameType
from types import FunctionType
import typing as t
import uuid

import attr

import ddtrace
from ddtrace import config
from ddtrace._trace.processor import SpanProcessor
from ddtrace.debugging._debugger import Debugger
from ddtrace.debugging._probe.model import DEFAULT_CAPTURE_LIMITS
from ddtrace.debugging._probe.model import LiteralTemplateSegment
from ddtrace.debugging._probe.model import LogFunctionProbe
from ddtrace.debugging._probe.model import LogLineProbe
from ddtrace.debugging._probe.model import ProbeEvaluateTimingForMethod
from ddtrace.debugging._signal.collector import SignalContext
from ddtrace.debugging._signal.snapshot import Snapshot
from ddtrace.ext import EXIT_SPAN_TYPES
from ddtrace.internal import compat
from ddtrace.internal import core
from ddtrace.internal.packages import is_user_code
from ddtrace.internal.safety import _isinstance
from ddtrace.internal.utils.inspection import linenos
from ddtrace.internal.wrapping.context import WrappingContext
from ddtrace.span import Span


def frame_stack(frame: FrameType) -> t.Iterator[FrameType]:
    _frame: t.Optional[FrameType] = frame
    while _frame is not None:
        yield _frame
        _frame = _frame.f_back


@attr.s
class EntrySpanProbe(LogFunctionProbe):
    __span_class__ = "entry"

    @classmethod
    def build(cls, name: str, module: str, function: str) -> "EntrySpanProbe":
        message = f"{cls.__span_class__} span info for {name}, in {module}, in function {function}"

        return cls(
            probe_id=str(uuid.uuid4()),
            version=0,
            tags={},
            module=module,
            func_qname=function,
            evaluate_at=ProbeEvaluateTimingForMethod.ENTER,
            template=message,
            segments=[LiteralTemplateSegment(message)],
            take_snapshot=True,
            limits=DEFAULT_CAPTURE_LIMITS,
            condition=None,
            condition_error_rate=0.0,
            rate=float("inf"),
        )


@attr.s
class ExitSpanProbe(LogLineProbe):
    __span_class__ = "exit"

    @classmethod
    def build(cls, name: str, filename: str, line: int) -> "ExitSpanProbe":
        message = f"{cls.__span_class__} span info for {name}, in {filename}, at {line}"

        return cls(
            probe_id=str(uuid.uuid4()),
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

    @classmethod
    def from_frame(cls, frame: FrameType) -> "ExitSpanProbe":
        code = frame.f_code
        return t.cast(
            ExitSpanProbe,
            cls.build(
                name=code.co_qualname if sys.version_info >= (3, 11) else code.co_name,  # type: ignore[attr-defined]
                filename=str(Path(code.co_filename).resolve()),
                line=frame.f_lineno,
            ),
        )


@dataclass
class EntrySpanLocation:
    name: str
    start_line: int
    end_line: int
    file: str
    module: str
    probe: EntrySpanProbe


class EntrySpanWrappingContext(WrappingContext):
    def __init__(self, f):
        super().__init__(f)

        lines = linenos(f)
        start_line = min(lines)
        filename = str(Path(f.__code__.co_filename).resolve())
        name = f.__qualname__
        module = f.__module__
        self.location = EntrySpanLocation(
            name=name,
            start_line=start_line,
            end_line=max(lines),
            file=filename,
            module=module,
            probe=t.cast(EntrySpanProbe, EntrySpanProbe.build(name=name, module=module, function=name)),
        )

    def __enter__(self):
        super().__enter__()

        root = ddtrace.tracer.current_root_span()
        location = self.location
        if root is None or root.get_tag("_dd.entry_location.file") is not None:
            return

        # Add tags to the local root
        root.set_tag_str("_dd.entry_location.file", location.file)
        root.set_tag_str("_dd.entry_location.start_line", str(location.start_line))
        root.set_tag_str("_dd.entry_location.end_line", str(location.end_line))
        root.set_tag_str("_dd.entry_location.type", location.module)
        root.set_tag_str("_dd.entry_location.method", location.name)

        if config._trace_span_origin_enriched:
            # Create a snapshot
            snapshot = Snapshot(
                probe=location.probe,
                frame=self.__frame__,
                thread=current_thread(),
                trace_context=root,
            )

            # Capture on entry
            context = Debugger.get_collector().attach(snapshot)

            # Correlate the snapshot with the span
            root.set_tag_str("_dd.entry_location.snapshot_id", snapshot.uuid)

            self.set("context", context)
            self.set("start_time", compat.monotonic_ns())

    def _close_context(self, retval=None, exc_info=(None, None, None)):
        try:
            context: SignalContext = self.get("context")
        except KeyError:
            # No snapshot was created
            return

        context.exit(retval, exc_info, compat.monotonic_ns() - self.get("start_time"))

    def __return__(self, retval):
        self._close_context(retval=retval)
        return super().__return__(retval)

    def __exit__(self, exc_type, exc_value, traceback):
        self._close_context(exc_info=(exc_type, exc_value, traceback))
        super().__exit__(exc_type, exc_value, traceback)


@attr.s
class SpanOriginProcessor(SpanProcessor):
    _instance: t.Optional["SpanOriginProcessor"] = None

    def on_span_start(self, span: Span) -> None:
        if span.span_type not in EXIT_SPAN_TYPES:
            return

        # Add call stack information to the exit span. Report only the part of
        # the stack that belongs to user code.
        # TODO: Add a limit to the number of frames to capture
        seq = count(1)
        for frame in frame_stack(sys._getframe(1)):
            frame_origin = Path(frame.f_code.co_filename)

            if is_user_code(frame_origin):
                n = next(seq)
                span.set_tag_str(f"_dd.exit_location.{n}.file", str(frame_origin.resolve()))
                span.set_tag_str(f"_dd.exit_location.{n}.line", str(frame.f_lineno))

                if config._trace_span_origin_enriched:
                    # Create a snapshot
                    snapshot = Snapshot(
                        probe=ExitSpanProbe.from_frame(frame),
                        frame=frame,
                        thread=current_thread(),
                        trace_context=span,
                    )

                    # Capture on entry
                    snapshot.line()

                    # Collect
                    Debugger.get_collector().push(snapshot)

                    # Correlate the snapshot with the span
                    span.set_tag_str("_dd.exit_location.snapshot_id", snapshot.uuid)

    def on_span_finish(self, span: Span) -> None:
        pass

    @classmethod
    def enable(cls):
        if cls._instance is not None:
            return

        @λ(core.on, "service_entrypoint.patch")
        def _(f: t.Callable) -> None:
            if not _isinstance(f, FunctionType):
                return

            if not EntrySpanWrappingContext.is_wrapped(t.cast(FunctionType, f)):
                EntrySpanWrappingContext(f).wrap()

        instance = cls._instance = cls()
        instance.register()

    @classmethod
    def disable(cls):
        if cls._instance is None:
            return

        cls._instance.unregister()
        cls._instance = None

        # TODO: The core event hook is still registered. Currently there is no
        # way to unregister it.
