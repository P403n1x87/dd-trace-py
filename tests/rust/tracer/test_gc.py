from time import sleep

from ddtrace._rust.tracer import gc as rgc
from ddtrace._rust.tracer import span as rs


def test_gc_recycle():
    rgc.start()

    span = rs.new()
    rgc.recycle(span)

    # Give time to the Rust GC to recycle the span
    sleep(2)

    try:
        # The reference is now invalid
        rs.get_name(span)
    except:
        pass
    else:
        assert False, "Reference is still valid!"

    rgc.stop()


def test_gc_keep():
    pass
