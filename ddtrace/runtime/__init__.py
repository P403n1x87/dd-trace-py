from typing import Optional

import ddtrace.internal.runtime.runtime_metrics


class RuntimeMetrics(object):
    """
    Runtime metrics service API.

    This is normally started automatically by ``ddtrace-run`` when the
    ``DD_RUNTIME_METRICS_ENABLED`` variable is set.

    To start the service manually, invoke the ``enable`` static method::

        from ddtrace.runtime import RuntimeMetrics
        RuntimeMetrics.enable()
    """

    @staticmethod
    def enable(tracer=None, dogstatsd_url=None, flush_interval=None):
        # type: (Optional[ddtrace.Tracer], Optional[str], Optional[float]) -> None
        """
        Enable the runtime metrics collection service.

        If the service has already been activated before, this method does
        nothing. Use ``disable`` to turn off the runtime metric collection
        service.

        :param tracer: The tracer instance to correlate with.
        :param dogstatsd_url: The DogStatsD URL.
        :param flush_interval: The flush interval.
        """

        ddtrace.internal.runtime.runtime_metrics.RuntimeWorker.enable(  # type: ignore[attr-defined]
            tracer=tracer, dogstatsd_url=dogstatsd_url, flush_interval=flush_interval
        )

    @staticmethod
    def disable():
        # type: () -> None
        """
        Disable the runtime metrics collection service.

        Once disabled, runtime metrics can be re-enabled by calling ``enable``
        again.
        """
        ddtrace.internal.runtime.runtime_metrics.RuntimeWorker.disable()  # type: ignore[attr-defined]


__all__ = ["RuntimeMetrics"]
