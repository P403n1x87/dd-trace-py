import collections
import itertools
import operator
import typing

import attr
import six

from ddtrace import ext
from ddtrace.internal.encoding import ListStringTable
from ddtrace.profiling import exporter
from ddtrace.profiling.collector import memalloc
from ddtrace.profiling.collector import stack
from ddtrace.profiling.collector import threading
from ddtrace.utils import config


def _protobuf_post_312():
    # type: (...) -> bool
    """Check if protobuf version is post 3.12"""
    import google.protobuf

    from ddtrace.utils.version import parse_version

    v = parse_version(google.protobuf.__version__)
    return v[0] >= 3 and v[1] >= 12


if _protobuf_post_312():
    from ddtrace.profiling.exporter import pprof_pb2
else:
    from ddtrace.profiling.exporter import pprof_pre312_pb2 as pprof_pb2


_ITEMGETTER_ZERO = operator.itemgetter(0)
_ITEMGETTER_ONE = operator.itemgetter(1)
_ATTRGETTER_ID = operator.attrgetter("id")


@attr.s
class _Sequence(object):
    start_at = attr.ib(default=1, type=int)
    next_id = attr.ib(init=False, default=None, type=int)

    def __attrs_post_init__(self) -> None:
        self.next_id = self.start_at

    def generate(self) -> int:
        """Generate a new unique id and return it."""
        generated_id = self.next_id
        self.next_id += 1
        return generated_id


@attr.s
class _PprofConverter(object):
    """Convert stacks generated by a Profiler to pprof format."""

    # Those attributes will be serialize in a `pprof_pb2.Profile`
    _functions = attr.ib(init=False, factory=dict)
    _locations = attr.ib(init=False, factory=dict)
    _string_table = attr.ib(init=False, factory=ListStringTable)

    _last_location_id = attr.ib(init=False, factory=_Sequence)
    _last_func_id = attr.ib(init=False, factory=_Sequence)

    # A dict where key is a (Location, [Labels]) and value is a a dict.
    # This dict has sample-type (e.g. "cpu-time") as key and the numeric value.
    _location_values = attr.ib(
        factory=lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: 0)), init=False, repr=False
    )

    def _to_Function(self, filename, funcname):
        try:
            return self._functions[(filename, funcname)]
        except KeyError:
            func = pprof_pb2.Function(
                id=self._last_func_id.generate(),
                name=self._str(funcname),
                filename=self._str(filename),
            )
            self._functions[(filename, funcname)] = func
            return func

    def _to_Location(self, filename, lineno, funcname=None):
        try:
            return self._locations[(filename, lineno, funcname)]
        except KeyError:
            if funcname is None:
                real_funcname = "<unknown function>"
            else:
                real_funcname = funcname
            location = pprof_pb2.Location(
                id=self._last_location_id.generate(),
                line=[
                    pprof_pb2.Line(
                        function_id=self._to_Function(filename, real_funcname).id,
                        line=lineno,
                    ),
                ],
            )
            self._locations[(filename, lineno, funcname)] = location
            return location

    def _str(self, string):
        """Convert a string to an id from the string table."""
        return self._string_table.index(str(string))

    def _to_locations(self, frames, nframes):
        locations = [self._to_Location(filename, lineno, funcname).id for filename, lineno, funcname in frames]

        omitted = nframes - len(frames)
        if omitted:
            locations.append(
                self._to_Location("", 0, "<%d frame%s omitted>" % (omitted, ("s" if omitted > 1 else ""))).id
            )

        return tuple(locations)

    def convert_stack_event(
        self,
        thread_id,  # type: int
        thread_native_id,  # type: int
        thread_name,  # type: str
        task_id,  # type: typing.Optional[int]
        task_name,  # type: str
        trace_id,  # type: int
        span_id,  # type: int
        trace_resource,  # type: str
        trace_type,  # type: str
        frames,
        nframes,  # type: int
        samples,  # type: typing.Iterable[stack.StackSampleEvent]
    ):
        # type: (...) -> None
        location_key = (
            self._to_locations(frames, nframes),
            (
                ("thread id", str(thread_id)),
                ("thread native id", str(thread_native_id)),
                ("thread name", thread_name),
                ("task id", task_id),
                ("task name", task_name),
                ("trace id", trace_id),
                ("span id", span_id),
                ("trace endpoint", trace_resource),
                ("trace type", trace_type),
            ),
        )

        self._location_values[location_key]["cpu-samples"] = len(samples)
        self._location_values[location_key]["cpu-time"] = sum(s.cpu_time_ns for s in samples)
        self._location_values[location_key]["wall-time"] = sum(s.wall_time_ns for s in samples)

    def convert_memalloc_event(self, thread_id, thread_native_id, thread_name, frames, nframes, events):
        location_key = (
            self._to_locations(frames, nframes),
            (
                ("thread id", str(thread_id)),
                ("thread native id", str(thread_native_id)),
                ("thread name", thread_name),
            ),
        )

        nevents = len(events)
        sampling_ratio_avg = sum(event.capture_pct for event in events) / nevents / 100.0
        total_alloc = sum(event.nevents for event in events)
        number_of_alloc = total_alloc * sampling_ratio_avg
        average_alloc_size = sum(event.size for event in events) / float(nevents)

        self._location_values[location_key]["alloc-samples"] = nevents
        self._location_values[location_key]["alloc-space"] = round(number_of_alloc * average_alloc_size)

    def convert_memalloc_heap_event(self, event):
        location_key = (
            self._to_locations(event.frames, event.nframes),
            (
                ("thread id", str(event.thread_id)),
                ("thread native id", str(event.thread_native_id)),
                ("thread name", event.thread_name),
            ),
        )

        self._location_values[location_key]["heap-space"] += event.size

    def convert_lock_acquire_event(
        self,
        lock_name,
        thread_id,
        thread_name,
        trace_id,
        span_id,
        trace_resource,
        trace_type,
        frames,
        nframes,
        events,
        sampling_ratio,
    ):
        location_key = (
            self._to_locations(frames, nframes),
            (
                ("thread id", str(thread_id)),
                ("thread name", thread_name),
                ("trace id", trace_id),
                ("span id", span_id),
                ("trace endpoint", trace_resource),
                ("trace type", trace_type),
                ("lock name", lock_name),
            ),
        )

        self._location_values[location_key]["lock-acquire"] = len(events)
        self._location_values[location_key]["lock-acquire-wait"] = int(
            sum(e.wait_time_ns for e in events) / sampling_ratio
        )

    def convert_lock_release_event(
        self,
        lock_name,
        thread_id,
        thread_name,
        trace_id,
        span_id,
        trace_resource,
        trace_type,
        frames,
        nframes,
        events,
        sampling_ratio,
    ):
        location_key = (
            self._to_locations(frames, nframes),
            (
                ("thread id", str(thread_id)),
                ("thread name", thread_name),
                ("trace id", trace_id),
                ("span id", span_id),
                ("trace endpoint", trace_resource),
                ("trace type", trace_type),
                ("lock name", lock_name),
            ),
        )

        self._location_values[location_key]["lock-release"] = len(events)
        self._location_values[location_key]["lock-release-hold"] = int(
            sum(e.locked_for_ns for e in events) / sampling_ratio
        )

    def convert_stack_exception_event(
        self, thread_id, thread_native_id, thread_name, trace_id, span_id, frames, nframes, exc_type_name, events
    ):
        location_key = (
            self._to_locations(frames, nframes),
            (
                ("thread id", str(thread_id)),
                ("thread native id", str(thread_native_id)),
                ("thread name", thread_name),
                ("trace id", trace_id),
                ("span id", span_id),
                ("exception type", exc_type_name),
            ),
        )

        self._location_values[location_key]["exception-samples"] = len(events)

    def convert_memory_event(self, stats, sampling_ratio):
        location = tuple(self._to_Location(frame.filename, frame.lineno).id for frame in reversed(stats.traceback))
        location_key = (location, tuple())
        self._location_values[location_key]["alloc-samples"] = int(stats.count / sampling_ratio)
        self._location_values[location_key]["alloc-space"] = int(stats.size / sampling_ratio)

    def _build_profile(self, start_time_ns, duration_ns, period, sample_types, program_name) -> pprof_pb2.Profile:
        pprof_sample_type = [
            pprof_pb2.ValueType(type=self._str(type_), unit=self._str(unit)) for type_, unit in sample_types
        ]

        sample = [
            pprof_pb2.Sample(
                location_id=locations,
                value=[values.get(sample_type_name, 0) for sample_type_name, unit in sample_types],
                label=[pprof_pb2.Label(key=self._str(key), str=self._str(s)) for key, s in labels],
            )
            for (locations, labels), values in sorted(six.iteritems(self._location_values), key=_ITEMGETTER_ZERO)
        ]

        period_type = pprof_pb2.ValueType(type=self._str("time"), unit=self._str("nanoseconds"))

        # WARNING: no code should use _str() here as once the _string_table is serialized below,
        # it won't be updated if you call _str later in the code here
        return pprof_pb2.Profile(
            sample_type=pprof_sample_type,
            sample=sample,
            mapping=[
                pprof_pb2.Mapping(
                    id=1,
                    filename=self._str(program_name),
                ),
            ],
            # Sort location and function by id so the output is reproducible
            location=sorted(self._locations.values(), key=_ATTRGETTER_ID),
            function=sorted(self._functions.values(), key=_ATTRGETTER_ID),
            string_table=list(self._string_table),
            time_nanos=start_time_ns,
            duration_nanos=duration_ns,
            period=period,
            period_type=period_type,
        )


_stack_event_group_key_T = typing.Tuple[
    int,
    int,
    str,
    typing.Optional[int],
    str,
    str,
    typing.Optional[int],
    typing.Tuple,
    int,
]


@attr.s
class PprofExporter(exporter.Exporter):
    """Export recorder events to pprof format."""

    @staticmethod
    def _none_to_str(
        value,  # type: typing.Optional[typing.Any]
    ):
        # type: (...) -> str
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _get_thread_name(thread_id, thread_name):
        if thread_name is None:
            return "Anonymous Thread %d" % thread_id
        return thread_name

    def _stack_event_group_key(
        self,
        event,  # type: stack.StackSampleEvent
    ):
        # type: (...) -> _stack_event_group_key_T

        if event.trace_type == ext.SpanTypes.WEB.value:
            trace_resource = self._none_to_str(event.trace_resource)
        else:
            # Do not export trace_resource for privacy concerns.
            trace_resource = ""

        return (
            event.thread_id,
            event.thread_native_id,
            self._get_thread_name(event.thread_id, event.thread_name),
            self._none_to_str(event.task_id),
            self._none_to_str(event.task_name),
            self._none_to_str(event.trace_id),
            self._none_to_str(event.span_id),
            trace_resource,
            self._none_to_str(event.trace_type),
            tuple(event.frames),
            event.nframes,
        )

    def _group_stack_events(
        self,
        events,  # type: typing.Iterable[stack.StackSampleEvent]
    ):
        # type: typing.Iterator[typing.Tuple[_stack_event_group_key_T, typing.Iterator[stack.StackSampleEvent]]]
        return itertools.groupby(
            sorted(events, key=self._stack_event_group_key),
            key=self._stack_event_group_key,
        )

    def _lock_event_group_key(
        self, event  # type: lock.LockEventBase
    ):
        if event.trace_type == ext.SpanTypes.WEB.value:
            trace_resource = self._none_to_str(event.trace_resource)
        else:
            # Do not export trace_resource for privacy concerns.
            trace_resource = ""

        return (
            event.lock_name,
            event.thread_id,
            self._get_thread_name(event.thread_id, event.thread_name),
            self._none_to_str(event.trace_id),
            self._none_to_str(event.span_id),
            trace_resource,
            self._none_to_str(event.trace_type),
            tuple(event.frames),
            event.nframes,
        )

    def _group_lock_events(self, events):
        return itertools.groupby(
            sorted(events, key=self._lock_event_group_key),
            key=self._lock_event_group_key,
        )

    def _stack_exception_group_key(self, event):
        exc_type = event.exc_type
        exc_type_name = exc_type.__module__ + "." + exc_type.__name__
        return (
            event.thread_id,
            event.thread_native_id,
            self._get_thread_name(event.thread_id, event.thread_name),
            self._none_to_str(event.trace_id),
            self._none_to_str(event.span_id),
            tuple(event.frames),
            event.nframes,
            exc_type_name,
        )

    def _group_stack_exception_events(self, events):
        return itertools.groupby(
            sorted(events, key=self._stack_exception_group_key),
            key=self._stack_exception_group_key,
        )

    def _exception_group_key(self, event):
        exc_type = event.exc_type
        exc_type_name = exc_type.__module__ + "." + exc_type.__name__
        return (
            event.thread_id,
            self._get_thread_name(event.thread_id, event.thread_name),
            tuple(event.frames),
            event.nframes,
            exc_type_name,
        )

    def _group_exception_events(self, events):
        return itertools.groupby(
            sorted(events, key=self._exception_group_key),
            key=self._exception_group_key,
        )

    @staticmethod
    def min_none(a, b):
        """A min() version that discards None values."""
        if a is None:
            return b
        if b is None:
            return a
        return min(a, b)

    @staticmethod
    def max_none(a, b):
        """A max() version that discards None values."""
        if a is None:
            return b
        if b is None:
            return a
        return max(a, b)

    def export(self, events, start_time_ns, end_time_ns) -> pprof_pb2.Profile:  # type: ignore[valid-type]
        """Convert events to pprof format.

        :param events: The event dictionary from a `ddtrace.profiling.recorder.Recorder`.
        :param start_time_ns: The start time of recording.
        :param end_time_ns: The end time of recording.
        :return: A protobuf Profile object.
        """
        program_name = config.get_application_name()

        sum_period = 0
        nb_event = 0

        converter = _PprofConverter()

        # Handle StackSampleEvent
        stack_events = []
        for event in events.get(stack.StackSampleEvent, []):
            stack_events.append(event)
            sum_period += event.sampling_period
            nb_event += 1

        for (
            (
                thread_id,
                thread_native_id,
                thread_name,
                task_id,
                task_name,
                trace_id,
                span_id,
                trace_resource,
                trace_type,
                frames,
                nframes,
            ),
            stack_events,
        ) in self._group_stack_events(stack_events):
            converter.convert_stack_event(
                thread_id,
                thread_native_id,
                thread_name,
                task_id,
                task_name,
                trace_id,
                span_id,
                trace_resource,
                trace_type,
                frames,
                nframes,
                list(stack_events),
            )

        # Handle Lock events
        for event_class, convert_fn in (
            (threading.LockAcquireEvent, converter.convert_lock_acquire_event),
            (threading.LockReleaseEvent, converter.convert_lock_release_event),
        ):
            lock_events = events.get(event_class, [])
            sampling_sum_pct = sum(event.sampling_pct for event in lock_events)

            if lock_events:
                sampling_ratio_avg = sampling_sum_pct / (len(lock_events) * 100.0)

                for (
                    lock_name,
                    thread_id,
                    thread_name,
                    trace_id,
                    span_id,
                    trace_resource,
                    trace_type,
                    frames,
                    nframes,
                ), l_events in self._group_lock_events(lock_events):
                    convert_fn(
                        lock_name,
                        thread_id,
                        thread_name,
                        trace_id,
                        span_id,
                        trace_resource,
                        trace_type,
                        frames,
                        nframes,
                        list(l_events),
                        sampling_ratio_avg,
                    )

        for (
            (thread_id, thread_native_id, thread_name, trace_id, span_id, frames, nframes, exc_type_name),
            se_events,
        ) in self._group_stack_exception_events(events.get(stack.StackExceptionSampleEvent, [])):
            converter.convert_stack_exception_event(
                thread_id,
                thread_native_id,
                thread_name,
                trace_id,
                span_id,
                frames,
                nframes,
                exc_type_name,
                list(se_events),
            )

        if memalloc._memalloc:
            for (
                (
                    thread_id,
                    thread_native_id,
                    thread_name,
                    task_id,
                    task_name,
                    trace_id,
                    span_id,
                    trace_resource,
                    trace_type,
                    frames,
                    nframes,
                ),
                memalloc_events,
            ) in self._group_stack_events(events.get(memalloc.MemoryAllocSampleEvent, [])):
                converter.convert_memalloc_event(
                    thread_id,
                    thread_native_id,
                    thread_name,
                    frames,
                    nframes,
                    list(memalloc_events),
                )

            for event in events.get(memalloc.MemoryHeapSampleEvent, []):
                converter.convert_memalloc_heap_event(event)

        # Compute some metadata
        if nb_event:
            period = int(sum_period / nb_event)
        else:
            period = None

        duration_ns = end_time_ns - start_time_ns

        sample_types = (
            ("cpu-samples", "count"),
            ("cpu-time", "nanoseconds"),
            ("wall-time", "nanoseconds"),
            ("exception-samples", "count"),
            ("lock-acquire", "count"),
            ("lock-acquire-wait", "nanoseconds"),
            ("lock-release", "count"),
            ("lock-release-hold", "nanoseconds"),
            ("alloc-samples", "count"),
            ("alloc-space", "bytes"),
            ("heap-space", "bytes"),
        )

        return converter._build_profile(
            start_time_ns=start_time_ns,
            duration_ns=duration_ns,
            period=period,
            sample_types=sample_types,
            program_name=program_name,
        )
