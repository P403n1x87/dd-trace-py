"""
Module providing async hooks. Do not import this module unless using Python >= 3.6.
"""
from ddtrace.contrib.asgi import span_from_scope

from .. import trace_utils
from ...internal.utils import get_argument_value
from .utils import REQUEST_DEFAULT_RESOURCE
from .utils import _after_request_tags
from .utils import _before_request_tags


@trace_utils.with_traced_module
async def traced_get_response_async(django, pin, func, instance, args, kwargs):
    """Trace django.core.handlers.base.BaseHandler.get_response() (or other implementations).

    This is the main entry point for requests.

    Django requests are handled by a Handler.get_response method (inherited from base.BaseHandler).
    This method invokes the middleware chain and returns the response generated by the chain.
    """
    request = get_argument_value(args, kwargs, 0, "request")
    span = span_from_scope(request.scope)
    if span is None:
        return await func(*args, **kwargs)

    # Reset the span resource so we can know if it was modified during the request or not
    span.resource = REQUEST_DEFAULT_RESOURCE
    _before_request_tags(pin, span, request)
    response = None
    try:
        response = await func(*args, **kwargs)
    finally:
        # DEV: Always set these tags, this is where `span.resource` is set
        _after_request_tags(pin, span, request, response)
    return response
