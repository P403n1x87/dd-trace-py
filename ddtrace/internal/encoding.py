import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TYPE_CHECKING
from typing import Tuple
from typing import Type

from ._encoding import MsgpackEncoder
from .logger import get_logger


if TYPE_CHECKING:
    from ..span import Span


log = get_logger(__name__)


class _EncoderBase(object):
    """
    Encoder interface that provides the logic to encode traces and service.
    """

    def encode_traces(self, traces):
        # type: (List[List[Span]]) -> str
        """
        Encodes a list of traces, expecting a list of items where each items
        is a list of spans. Before dump the string in a serialized format all
        traces are normalized, calling the ``to_dict()`` method. The traces
        nesting is not changed.

        :param traces: A list of traces that should be serialized
        """
        normalized_traces = [[span.to_dict() for span in trace] for trace in traces]
        return self.encode(normalized_traces)

    @staticmethod
    def encode(obj):
        """
        Defines the underlying format used during traces or services encoding.
        This method must be implemented and should only be used by the internal functions.
        """
        raise NotImplementedError


class JSONEncoder(_EncoderBase):
    content_type = "application/json"

    @staticmethod
    def encode(obj):
        # type: (Any) -> str
        return json.dumps(obj)


class JSONEncoderV2(JSONEncoder):
    """
    JSONEncoderV2 encodes traces to the new intake API format.
    """

    content_type = "application/json"

    def encode_traces(self, traces):
        # type: (List[List[Span]]) -> str
        normalized_traces = [[JSONEncoderV2._convert_span(span) for span in trace] for trace in traces]
        return self.encode({"traces": normalized_traces})

    @staticmethod
    def _convert_span(span):
        # type: (Span) -> Dict[str, Any]
        sp = span.to_dict()
        sp["trace_id"] = JSONEncoderV2._encode_id_to_hex(sp.get("trace_id"))
        sp["parent_id"] = JSONEncoderV2._encode_id_to_hex(sp.get("parent_id"))
        sp["span_id"] = JSONEncoderV2._encode_id_to_hex(sp.get("span_id"))
        return sp

    @staticmethod
    def _encode_id_to_hex(dd_id):
        # type: (Optional[int]) -> str
        if not dd_id:
            return "0000000000000000"
        return "%0.16X" % int(dd_id)

    @staticmethod
    def _decode_id_to_hex(hex_id):
        # type: (Optional[str]) -> int
        if not hex_id:
            return 0
        return int(hex_id, 16)


Encoder = MsgpackEncoder


_ENCODERS = (
    ("/v0.5/traces", MsgpackEncoder),
    ("/v0.4/traces", MsgpackEncoder),
    ("/v0.3/traces", MsgpackEncoder),
)


def encoder_for_endpoints(endpoints):
    # type: (List[str]) -> Tuple[str, Type[MsgpackEncoder]]
    """
    Returns the encoder for the given endpoint.
    """
    for ep, enc in _ENCODERS:
        if ep in endpoints:
            return (ep, enc)

    raise RuntimeError("No compatible encoders for the currently running version of the agent")
