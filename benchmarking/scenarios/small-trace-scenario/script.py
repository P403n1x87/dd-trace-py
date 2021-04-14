from ddtrace import tracer


def test_trace_simple_trace():
    with tracer.trace("parent"):
        for i in range(5):
            with tracer.trace("child") as c:
                c.set_tag("i", i)


for _ in range(10000):
    test_trace_simple_trace()
