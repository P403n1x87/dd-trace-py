from ddtrace._rust.tracer import encoder as re
from ddtrace.span import Span
from tests.tracer.test_encoders import RefMsgpackEncoder
from tests.tracer.test_encoders import decode
from tests.tracer.test_encoders import gen_trace


def test_custom_msgpack_encode():
    def _encode_trace(spans):
        return re.encode([span._ref for span in spans])

    re.encode_trace = _encode_trace
    encoder = re
    refencoder = RefMsgpackEncoder()

    trace = gen_trace(nspans=50)

    # Note that we assert on the decoded versions because the encoded
    # can vary due to non-deterministic map key/value positioning
    assert decode(refencoder.encode_trace(trace)) == decode(encoder.encode_trace(trace))
