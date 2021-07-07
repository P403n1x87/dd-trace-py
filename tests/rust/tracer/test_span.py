from ddtrace._rust.tracer import span as rs
from ddtrace.internal._rand import rand64bits


def test_span_store():
    span = rs.new()
    rs.set_name(span, "foo")

    rs.remove(span)
    span = rs.new()
    assert rs.get_name(span) != "foo"

    rs.remove(span)


def test_span_attributes():
    span = rs.new()
    rs.set_name(span, "test")
    assert rs.get_name(span) == "test"

    uuid = rand64bits()
    rs.set_trace_id(span, uuid)
    assert rs.get_trace_id(span) == uuid

    rs.set_meta(span, "foo", "bar")
    assert rs.get_meta(span, "foo") == "bar"

    rs.remove(span)


def test_span_invalid_ref():
    try:
        rs.get_name(999)
    except:  # TODO: Need to improve!
        pass
    else:
        assert False
