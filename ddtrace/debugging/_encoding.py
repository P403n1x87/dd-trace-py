import abc
from dataclasses import dataclass
import json
import os
import sys
from threading import Thread
from types import FrameType
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import Union

import six

from ddtrace.debugging._config import di_config
from ddtrace.debugging._signal.model import LogSignal
from ddtrace.debugging._signal.snapshot import Snapshot
from ddtrace.internal import forksafe
from ddtrace.internal._encoding import BufferFull
from ddtrace.internal.logger import get_logger
from ddtrace.internal.utils.cache import cachedmethod


log = get_logger(__name__)


class JsonBuffer(object):
    def __init__(self, max_size=None):
        self.max_size = max_size
        self._reset()

    def put(self, item: bytes) -> int:
        if self._flushed:
            self._reset()

        size = len(item)
        if self.size + size > self.max_size:
            raise BufferFull(self.size, size)

        if self.size > 2:
            self.size += 1
            self._buffer += b","
        self._buffer += item
        self.size += size
        return size

    def _reset(self):
        self.size = 2
        self._buffer = bytearray(b"[")
        self._flushed = False

    def flush(self):
        self._buffer += b"]"
        try:
            return self._buffer
        finally:
            self._flushed = True


class Encoder(six.with_metaclass(abc.ABCMeta)):
    @abc.abstractmethod
    def encode(self, item: Any) -> bytes:
        """Encode the given snapshot."""


class BufferedEncoder(six.with_metaclass(abc.ABCMeta)):
    count = 0

    @abc.abstractmethod
    def put(self, item: Any) -> int:
        """Enqueue the given item and returns its encoded size."""

    @abc.abstractmethod
    def encode(self) -> Optional[bytes]:
        """Encode the given item."""


def _logs_track_logger_details(thread: Thread, frame: FrameType) -> Dict[str, Any]:
    code = frame.f_code

    return {
        "name": code.co_filename,
        "method": code.co_name,
        "thread_name": "%s;pid:%d" % (thread.name, os.getpid()),
        "thread_id": thread.ident,
        "version": 2,
    }


def add_tags(payload):
    if not di_config._tags_in_qs and di_config.tags:
        payload["ddtags"] = di_config.tags


def _build_log_track_payload(
    service: str,
    signal: LogSignal,
    host: Optional[str],
) -> Dict[str, Any]:
    context = signal.trace_context

    payload = {
        "service": service,
        "debugger.snapshot": signal.snapshot,
        "host": host,
        "logger": _logs_track_logger_details(signal.thread, signal.frame),
        "dd.trace_id": context.trace_id if context else None,
        "dd.span_id": context.span_id if context else None,
        "ddsource": "dd_debugger",
        "message": signal.message,
        "timestamp": int(signal.timestamp * 1e3),  # milliseconds,
    }
    add_tags(payload)
    return payload


class JSONTree:
    @dataclass
    class Node:
        # name: str
        start: int
        end: int
        level: int
        children: List["JSONTree.Node"]

        def __len__(self):
            return self.end - self.start

        @property
        def leaves(self):
            if not self.children:
                yield self
            else:
                for child in self.children:
                    yield from child.leaves

    def __init__(self, data):
        self._iter = enumerate(data)
        self._stack = []  # TODO: deque
        self.root = None
        self.level = 0

        self._state = self._object

        self._parse()

    def _escape(self, i, c):
        self._state = self._string

    def _string(self, i, c):
        if c == '"':
            self._state = self._object

        elif c == "\\":
            self._state = self._escape

    def _object(self, i, c):
        if c == "}":
            o = self._stack.pop()
            o.end = i + 1
            self.level -= 1
            if not self._stack:
                self.root = o

        elif c == '"':
            self._state = self._string

        elif c == "{":
            o = self.Node(i, 0, self.level, [])
            self.level += 1
            if self._stack:
                self._stack[-1].children.append(o)
            self._stack.append(o)

    def _parse(self):
        for i, c in self._iter:
            self._state(i, c)
            if self.root is not None:
                return

    @property
    def leaves(self):
        return list(self.root.leaves)


class LogSignalJsonEncoder(Encoder):
    MAX_SIGNAL_SIZE = (1 << 20) - 2

    def __init__(self, service: str, host: Optional[str] = None) -> None:
        self._service = service
        self._host = host

    def encode(self, log_signal: LogSignal) -> bytes:
        return self.pruned(json.dumps(_build_log_track_payload(self._service, log_signal, self._host))).encode("utf-8")

    def pruned(self, log_signal_json: str) -> str:
        if len(log_signal_json) <= self.MAX_SIGNAL_SIZE:
            return log_signal_json

        tree = JSONTree(log_signal_json)

        delta = len(tree.root) - self.MAX_SIGNAL_SIZE
        nodes, s = [], 0
        for m in sorted(tree.leaves, key=lambda n: (n.level, len(n)), reverse=True):
            if s > delta:
                break
            nodes.append(m)
            s += len(m) - 2  # We are keeping "{" and "}"

        nodes = sorted(nodes, key=lambda n: n.start)  # Leaf nodes don't overlap

        segments = [log_signal_json[: nodes[0].start + 1]]
        for n, m in zip(nodes, nodes[1:]):
            segments.append(log_signal_json[n.end - 1 : m.start + 1])
        segments.append(log_signal_json[nodes[-1].end - 1 :])

        return "".join(segments)


class BatchJsonEncoder(BufferedEncoder):
    def __init__(
        self,
        item_encoders: Dict[Type, Union[Encoder, Type]],
        buffer_size: int = 4 * (1 << 20),
        on_full: Optional[Callable[[Any, bytes], None]] = None,
    ) -> None:
        self._encoders = item_encoders
        self._buffer = JsonBuffer(buffer_size)
        self._lock = forksafe.Lock()
        self._on_full = on_full
        self.count = 0
        self.max_size = buffer_size - self._buffer.size

    @cachedmethod()
    def _lookup_encoder(self, item_class: Type[Any]) -> Optional[Union[Encoder, Type]]:
        for ic, encoder in self._encoders.items():
            if issubclass(item_class, ic):
                return encoder
        return None

    def put(self, item: Union[Snapshot, str]) -> int:
        encoder = self._lookup_encoder(type(item))
        if encoder is None:
            raise ValueError("No encoder for item type: %r" % type(item))

        return self.put_encoded(item, encoder.encode(item))

    def put_encoded(self, item: Union[Snapshot, str], encoded: bytes) -> int:
        try:
            with self._lock:
                size = self._buffer.put(encoded)
                self.count += 1
                return size
        except BufferFull:
            if self._on_full is not None:
                self._on_full(item, encoded)
            six.reraise(*sys.exc_info())

    def encode(self) -> Optional[bytes]:
        with self._lock:
            if self.count == 0:
                # Reclaim memory
                self._buffer._reset()
                return None

            encoded = self._buffer.flush()
            self.count = 0
            return encoded
