from collections import Counter
from collections import OrderedDict
from collections import defaultdict
from collections import deque
import functools
from inspect import iscoroutinefunction
from inspect import isgeneratorfunction
import ipaddress
import os
import platform
import re
import sys
from tempfile import mkdtemp
import threading
from types import BuiltinFunctionType
from types import BuiltinMethodType
from types import FunctionType
from types import MethodType
from types import TracebackType
from typing import Any  # noqa:F401
from typing import AnyStr  # noqa:F401
from typing import Optional  # noqa:F401
from typing import Text  # noqa:F401
from typing import Tuple  # noqa:F401
from typing import Type  # noqa:F401
from typing import Union  # noqa:F401
import warnings

import six

from ddtrace.vendor.wrapt.wrappers import BoundFunctionWrapper
from ddtrace.vendor.wrapt.wrappers import FunctionWrapper


__all__ = [
    "httplib",
    "iteritems",
    "iscoroutinefunction",
    "Queue",
    "stringify",
    "StringIO",
    "urlencode",
    "parse",
    "reraise",
    "maybe_stringify",
]

PYTHON_VERSION_INFO = sys.version_info

# Infos about python passed to the trace agent through the header
PYTHON_VERSION = platform.python_version()
PYTHON_INTERPRETER = platform.python_implementation()

try:
    StringIO = six.moves.cStringIO
except ImportError:
    StringIO = six.StringIO  # type: ignore[misc]

httplib = six.moves.http_client
urlencode = six.moves.urllib.parse.urlencode
parse = six.moves.urllib.parse
Queue = six.moves.queue.Queue
iteritems = six.iteritems
reraise = six.reraise
reload_module = six.moves.reload_module

ensure_text = six.ensure_text
ensure_str = six.ensure_str
ensure_binary = six.ensure_binary
stringify = six.text_type
string_type = six.string_types[0]
text_type = six.text_type
binary_type = six.binary_type
msgpack_type = six.binary_type
# DEV: `six` doesn't have `float` in `integer_types`
numeric_types = six.integer_types + (float,)

# `six.integer_types` cannot be used for typing as we need to define a type
# alias for
# see https://mypy.readthedocs.io/en/latest/common_issues.html#variables-vs-type-aliases
NumericType = Union[int, float]

# Pattern class generated by `re.compile`
pattern_type = re.Pattern

try:
    from inspect import getfullargspec  # noqa:F401

    def is_not_void_function(f, argspec):
        return (
            argspec.args
            or argspec.varargs
            or argspec.varkw
            or argspec.defaults
            or argspec.kwonlyargs
            or argspec.kwonlydefaults
            or isgeneratorfunction(f)
        )

except ImportError:
    from inspect import getargspec as getfullargspec  # type: ignore[assignment]  # noqa: F401

    def is_not_void_function(f, argspec):
        return argspec.args or argspec.varargs or argspec.keywords or argspec.defaults or isgeneratorfunction(f)


def is_integer(obj):
    # type: (Any) -> bool
    """Helper to determine if the provided ``obj`` is an integer type or not"""
    # DEV: We have to make sure it is an integer and not a boolean
    # >>> type(True)
    # <class 'bool'>
    # >>> isinstance(True, int)
    # True
    return isinstance(obj, six.integer_types) and not isinstance(obj, bool)


try:
    from time import time_ns
except ImportError:
    from time import time as _time

    def time_ns():
        # type: () -> int
        return int(_time() * 10e5) * 1000


try:
    from time import monotonic
except ImportError:
    from ddtrace.vendor.monotonic import monotonic


try:
    from time import monotonic_ns
except ImportError:

    def monotonic_ns():
        # type: () -> int
        return int(monotonic() * 1e9)


try:
    from time import process_time_ns
except ImportError:
    from time import clock as _process_time  # type: ignore[attr-defined]

    def process_time_ns():
        # type: () -> int
        return int(_process_time() * 1e9)


main_thread = threading.main_thread()


def make_async_decorator(tracer, coro, *params, **kw_params):
    """
    Decorator factory that creates an asynchronous wrapper that yields
    a coroutine result. This factory is required to handle Python 2
    compatibilities.

    :param object tracer: the tracer instance that is used
    :param function f: the coroutine that must be executed
    :param tuple params: arguments given to the Tracer.trace()
    :param dict kw_params: keyword arguments given to the Tracer.trace()
    """

    @functools.wraps(coro)
    async def func_wrapper(*args, **kwargs):
        with tracer.trace(*params, **kw_params):
            result = await coro(*args, **kwargs)
            return result

    return func_wrapper


# DEV: There is `six.u()` which does something similar, but doesn't have the guard around `hasattr(s, 'decode')`
def to_unicode(s):
    # type: (AnyStr) -> Text
    """Return a unicode string for the given bytes or string instance."""
    # No reason to decode if we already have the unicode compatible object we expect
    # DEV: `six.text_type` will be a `str` for python 3 and `unicode` for python 2
    # DEV: Double decoding a `unicode` can cause a `UnicodeEncodeError`
    #   e.g. `'\xc3\xbf'.decode('utf-8').decode('utf-8')`
    if isinstance(s, six.text_type):
        return s

    # If the object has a `decode` method, then decode into `utf-8`
    #   e.g. Python 2 `str`, Python 2/3 `bytearray`, etc
    if hasattr(s, "decode"):
        return s.decode("utf-8")

    # Always try to coerce the object into the `six.text_type` object we expect
    #   e.g. `to_unicode(1)`, `to_unicode(dict(key='value'))`
    return six.text_type(s)


def get_connection_response(
    conn,  # type: httplib.HTTPConnection
):
    # type: (...) -> httplib.HTTPResponse
    """Returns the response for a connection.

    If using Python 2 enable buffering.

    Python 2 does not enable buffering by default resulting in many recv
    syscalls.

    See:
    https://bugs.python.org/issue4879
    https://github.com/python/cpython/commit/3c43fcba8b67ea0cec4a443c755ce5f25990a6cf
    """
    return conn.getresponse()


CONTEXTVARS_IS_AVAILABLE = True


try:
    from collections.abc import Iterable  # noqa:F401
except ImportError:
    from collections import Iterable  # type: ignore[no-redef, attr-defined]  # noqa:F401


def maybe_stringify(obj):
    # type: (Any) -> Optional[str]
    if obj is not None:
        return stringify(obj)
    return None


NoneType = type(None)

BUILTIN_SIMPLE_TYPES = frozenset([int, float, str, bytes, bool, NoneType, type, complex])
BUILTIN_MAPPNG_TYPES = frozenset([dict, defaultdict, Counter, OrderedDict])
BUILTIN_SEQUENCE_TYPES = frozenset([list, tuple, set, frozenset, deque])
BUILTIN_CONTAINER_TYPES = BUILTIN_MAPPNG_TYPES | BUILTIN_SEQUENCE_TYPES
BUILTIN_TYPES = BUILTIN_SIMPLE_TYPES | BUILTIN_CONTAINER_TYPES


try:
    from types import MethodWrapperType

except ImportError:
    MethodWrapperType = object().__init__.__class__  # type: ignore[misc]

CALLABLE_TYPES = (
    BuiltinMethodType,
    BuiltinFunctionType,
    FunctionType,
    MethodType,
    MethodWrapperType,
    FunctionWrapper,
    BoundFunctionWrapper,
    property,
    classmethod,
    staticmethod,
)
BUILTIN = "builtins"


try:
    from typing import Collection  # noqa:F401
except ImportError:
    from typing import List  # noqa:F401
    from typing import Set  # noqa:F401
    from typing import Union  # noqa:F401

    Collection = Union[List, Set, Tuple]  # type: ignore[misc,assignment]

ExcInfoType = Union[Tuple[Type[BaseException], BaseException, Optional[TracebackType]], Tuple[None, None, None]]


try:
    from json import JSONDecodeError
except ImportError:
    JSONDecodeError = ValueError  # type: ignore[misc,assignment]


def ip_is_global(ip):
    # type: (str) -> bool
    """
    is_global is Python 3+ only. This could raise a ValueError if the IP is not valid.
    """
    parsed_ip = ipaddress.ip_address(six.text_type(ip))

    return parsed_ip.is_global


# https://stackoverflow.com/a/19299884
class TemporaryDirectory(object):
    """Create and return a temporary directory.  This has the same
    behavior as mkdtemp but can be used as a context manager.  For
    example:

        with TemporaryDirectory() as tmpdir:
            ...

    Upon exiting the context, the directory and everything contained
    in it are removed.
    """

    def __init__(self, suffix="", prefix="tmp", _dir=None):
        self._closed = False
        self.name = None  # Handle mkdtemp raising an exception
        self.name = mkdtemp(suffix, prefix, _dir)

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)

    def __enter__(self):
        return self.name

    def cleanup(self, _warn=False):
        if self.name and not self._closed:
            try:
                self._rmtree(self.name)
            except (TypeError, AttributeError) as ex:
                # Issue #10188: Emit a warning on stderr
                # if the directory could not be cleaned
                # up due to missing globals
                if "None" not in str(ex):
                    raise
                return
            self._closed = True
            if _warn:
                self._warn("Implicitly cleaning up {!r}".format(self), ResourceWarning)

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def __del__(self):
        # Issue a ResourceWarning if implicit cleanup needed
        self.cleanup(_warn=True)

    # XXX (ncoghlan): The following code attempts to make
    # this class tolerant of the module nulling out process
    # that happens during CPython interpreter shutdown
    # Alas, it doesn't actually manage it. See issue #10188
    _listdir = staticmethod(os.listdir)
    _path_join = staticmethod(os.path.join)
    _isdir = staticmethod(os.path.isdir)
    _islink = staticmethod(os.path.islink)
    _remove = staticmethod(os.remove)
    _rmdir = staticmethod(os.rmdir)
    _warn = warnings.warn

    def _rmtree(self, path):
        # Essentially a stripped down version of shutil.rmtree.  We can't
        # use globals because they may be None'ed out at shutdown.
        for name in self._listdir(path):
            fullname = self._path_join(path, name)
            try:
                isdir = self._isdir(fullname) and not self._islink(fullname)
            except OSError:
                isdir = False
            if isdir:
                self._rmtree(fullname)
            else:
                try:
                    self._remove(fullname)
                except OSError:
                    pass
        try:
            self._rmdir(path)
        except OSError:
            pass


try:
    from shlex import quote as shquote
except ImportError:
    import re

    _find_unsafe = re.compile(r"[^\w@%+=:,./-]").search

    def shquote(s):
        # type: (str) -> str
        """Return a shell-escaped version of the string *s*."""
        if not s:
            return "''"
        if _find_unsafe(s) is None:
            return s

        # use single quotes, and put single quotes into double quotes
        # the string $'b is then quoted as '$'"'"'b'
        return "'" + s.replace("'", "'\"'\"'") + "'"


try:
    from shlex import join as shjoin
except ImportError:

    def shjoin(args):  # type: ignore[misc]
        # type: (Iterable[str]) -> str
        """Return a shell-escaped string from *args*."""
        return " ".join(shquote(arg) for arg in args)


try:
    from contextlib import nullcontext
except ImportError:
    from contextlib import contextmanager

    @contextmanager  # type: ignore[no-redef]
    def nullcontext(enter_result=None):
        yield enter_result
