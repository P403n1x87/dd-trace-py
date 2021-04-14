from ddtrace import tracer


def test_tracer_large_trace():
    import random

    # generate trace with 1024 spans
    @tracer.wrap()
    def func(tracer, level=0):
        span = tracer.current_span()

        # do some work
        num = random.randint(1, 10)
        span.set_tag("num", num)

        if level < 10:
            func(tracer, level + 1)
            func(tracer, level + 1)

    func(tracer)


for _ in range(20):
    test_tracer_large_trace()
