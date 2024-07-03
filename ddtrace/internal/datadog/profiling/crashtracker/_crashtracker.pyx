# distutils: language = c++
# cython: language_level=3
# Right now, this file lives in the profiling-internal directory even though the interface itself is not specific to
# profiling. This is because the crashtracker code is bundled in the libdatadog Profiling FFI, which saves a
# considerable amount of binary size, # and it's cumbersome to set an RPATH on that dependency from a different location

import os
from functools import wraps

from ..types import StringType
from ..util import ensure_binary_or_empty


def raise_if_unimplementable(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ImportError:
            raise NotImplementedError(f"{func.__name__} is not implemented")
    return wrapper


cdef extern from "<string_view>" namespace "std" nogil:
    cdef cppclass string_view:
        string_view(const char* s, size_t count)

# For now, the crashtracker code is bundled in the libdatadog Profiling FFI.
# This is primarily to reduce binary size.
cdef extern from "crashtracker_interface.hpp":
    void crashtracker_set_url(string_view url)
    void crashtracker_set_service(string_view service)
    void crashtracker_set_env(string_view env)
    void crashtracker_set_version(string_view version)
    void crashtracker_set_runtime(string_view runtime)
    void crashtracker_set_runtime_version(string_view runtime_version)
    void crashtracker_set_library_version(string_view profiler_version)
    void crashtracker_set_stdout_filename(string_view filename)
    void crashtracker_set_stderr_filename(string_view filename)
    void crashtracker_set_alt_stack(bint alt_stack)
    void crashtracker_set_resolve_frames_disable()
    void crashtracker_set_resolve_frames_fast()
    void crashtracker_set_resolve_frames_full()
    void crashtracker_set_resolve_frames_safe()
    bint crashtracker_set_receiver_binary_path(string_view path)
    void crashtracker_profiling_state_sampling_start()
    void crashtracker_profiling_state_sampling_stop()
    void crashtracker_profiling_state_unwinding_start()
    void crashtracker_profiling_state_unwinding_stop()
    void crashtracker_profiling_state_serializing_start()
    void crashtracker_profiling_state_serializing_stop()
    void crashtracker_start()


@raise_if_unimplementable
def set_url(url: StringType) -> None:
    url_bytes = ensure_binary_or_empty(url)
    crashtracker_set_url(string_view(<const char*>url_bytes, len(url_bytes)))


@raise_if_unimplementable
def set_service(service: StringType) -> None:
    service_bytes = ensure_binary_or_empty(service)
    crashtracker_set_service(string_view(<const char*>service_bytes, len(service_bytes)))


@raise_if_unimplementable
def set_env(env: StringType) -> None:
    env_bytes = ensure_binary_or_empty(env)
    crashtracker_set_env(string_view(<const char*>env_bytes, len(env_bytes)))


@raise_if_unimplementable
def set_version(version: StringType) -> None:
    version_bytes = ensure_binary_or_empty(version)
    crashtracker_set_version(string_view(<const char*>version_bytes, len(version_bytes)))


@raise_if_unimplementable
def set_runtime(runtime: StringType) -> None:
    runtime_bytes = ensure_binary_or_empty(runtime)
    crashtracker_set_runtime(string_view(<const char*>runtime_bytes, len(runtime_bytes)))


@raise_if_unimplementable
def set_runtime_version(runtime_version: StringType) -> None:
    runtime_version_bytes = ensure_binary_or_empty(runtime_version)
    crashtracker_set_runtime_version(string_view(<const char*>runtime_version_bytes, len(runtime_version_bytes)))


@raise_if_unimplementable
def set_library_version(library_version: StringType) -> None:
    library_version_bytes = ensure_binary_or_empty(library_version)
    crashtracker_set_library_version(string_view(<const char*>library_version_bytes, len(library_version_bytes)))


@raise_if_unimplementable
def set_stdout_filename(filename: StringType) -> None:
    filename_bytes = ensure_binary_or_empty(filename)
    crashtracker_set_stdout_filename(string_view(<const char*>filename_bytes, len(filename_bytes)))


@raise_if_unimplementable
def set_stderr_filename(filename: StringType) -> None:
    filename_bytes = ensure_binary_or_empty(filename)
    crashtracker_set_stderr_filename(string_view(<const char*>filename_bytes, len(filename_bytes)))


@raise_if_unimplementable
def set_alt_stack(alt_stack: bool) -> None:
    crashtracker_set_alt_stack(alt_stack)


@raise_if_unimplementable
def set_resolve_frames_disable() -> None:
    crashtracker_set_resolve_frames_disable()


@raise_if_unimplementable
def set_resolve_frames_fast() -> None:
    crashtracker_set_resolve_frames_fast()


@raise_if_unimplementable
def set_resolve_frames_full() -> None:
    crashtracker_set_resolve_frames_full()


@raise_if_unimplementable
def set_resolve_frames_safe() -> None:
    crashtracker_set_resolve_frames_safe()


@raise_if_unimplementable
def set_profiling_state_sampling(on: bool) -> None:
    if on:
        crashtracker_profiling_state_sampling_start()
    else:
        crashtracker_profiling_state_sampling_stop()


@raise_if_unimplementable
def set_profiling_state_unwinding(on: bool) -> None:
    if on:
        crashtracker_profiling_state_unwinding_start()
    else:
        crashtracker_profiling_state_unwinding_stop()


@raise_if_unimplementable
def set_profiling_state_serializing(on: bool) -> None:
    if on:
        crashtracker_profiling_state_serializing_start()
    else:
        crashtracker_profiling_state_serializing_stop()


@raise_if_unimplementable
def start() -> bool:
    # The file is "crashtracker_exe" in the same directory as the libdd_wrapper.so
    exe_dir = os.path.dirname(__file__)
    crashtracker_path = os.path.join(exe_dir, "crashtracker_exe")
    crashtracker_path_bytes = ensure_binary_or_empty(crashtracker_path)
    bin_exists = crashtracker_set_receiver_binary_path(
        string_view(<const char*>crashtracker_path_bytes, len(crashtracker_path_bytes))
    )

    # We don't have a good place to report on the failure for now.
    if bin_exists:
        crashtracker_start()
    return bin_exists
