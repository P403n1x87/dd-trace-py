IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 9):
    from cpython cimport PyFrameObject
    from cpython.object cimport PyObject
    from cpython.ref cimport Py_XDECREF

    cdef extern from "<Python.h>":
        ctypedef struct PyCodeObject:
            pass
        PyObject* PyTuple_GetItem(PyObject *p, Py_ssize_t pos)
        PyObject* PyDict_GetItem(PyObject *p, PyObject *key)
        PyCodeObject* PyFrame_GetCode(PyFrameObject* frame)
        PyFrameObject* PyFrame_GetBack(PyFrameObject* frame)

        IF PY_MINOR_VERSION >= 11:
            PyObject* PyFrame_GetLocals(PyFrameObject* frame)
            int PyFrame_GetLineNumber(PyFrameObject* frame)
            PyObject* PyCode_GetVarnames(PyCodeObject* co)


cpdef _extract_class_name(frame):
    # type: (...) -> str
    """Extract class name from a frame, if possible.

    :param frame: The frame object.
    """
    # Python 3.11 moved PyFrameObject to internal C API and cannot be directly accessed from tstate
    IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 11):
        code = PyFrame_GetCode(<PyFrameObject*> frame)
        co_varnames = PyCode_GetVarnames(code)
        if co_varnames:
            argname = PyTuple_GetItem(co_varnames, 0)
            try:
                f_locals = PyFrame_GetLocals(<PyFrameObject*>frame)
                value = <object>PyDict_GetItem(f_locals, argname)
                Py_XDECREF(f_locals)
                Py_XDECREF(argname)
                Py_XDECREF(co_varnames)
            except KeyError:
                return ""
    ELSE:
        co_varnames = frame.f_code.co_varnames
        if co_varnames:
            argname = co_varnames[0]
            try:
                value = frame.f_locals[argname]
            except KeyError:
                return ""
    try:
        if <str>argname == "self":
            return object.__getattribute__(type(value), "__name__")  # use type() and object.__getattribute__ to avoid side-effects
        if <str>argname == "cls":
            return object.__getattribute__(value, "__name__")
    except AttributeError:
        return ""
    return ""


cpdef traceback_to_frames(traceback, max_nframes):
    """Serialize a Python traceback object into a list of tuple of (filename, lineno, function_name).

    :param traceback: The traceback object to serialize.
    :param max_nframes: The maximum number of frames to return.
    :return: The serialized frames and the number of frames present in the original traceback.
    """
    tb = traceback
    frames = []
    nframes = 0
    while tb is not None:
        if nframes < max_nframes:
            frame = tb.tb_frame
            # Python 3.11 moved PyFrameObject to internal C API and cannot be directly accessed from tstate
            IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 11):
                code = PyFrame_GetCode(<PyFrameObject*> frame)
                lineno = PyFrame_GetLineNumber(<PyFrameObject*> frame)
                lineno = 0 if lineno is None else lineno
            ELSE:
                code = frame.f_code
                lineno = 0 if frame.f_lineno is None else frame.f_lineno
            frames.insert(0, ((<object>code).co_filename, lineno, (<object>code).co_name, _extract_class_name(frame)))
        nframes += 1
        tb = tb.tb_next
    return frames, nframes


cpdef pyframe_to_frames(frame, max_nframes):
    """Convert a Python frame to a list of frames.

    :param frame: The frame object to serialize.
    :param max_nframes: The maximum number of frames to return.
    :return: The serialized frames and the number of frames present in the original traceback."""
    frames = []
    nframes = 0
    while frame is not None:
        nframes += 1
        # Python 3.11 moved PyFrameObject to internal C API and cannot be directly accessed from tstate
        IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 11):
            if len(frames) < max_nframes:
                code = PyFrame_GetCode(<PyFrameObject*> frame)
                lineno = PyFrame_GetLineNumber(<PyFrameObject*> frame)
                lineno = 0 if lineno is None else lineno
                frames.append(((<object>code).co_filename, lineno, (<object>code).co_name, _extract_class_name(frame)))
            frame = <object>PyFrame_GetBack(<PyFrameObject*> frame)
        ELSE:
            if len(frames) < max_nframes:
                code = frame.f_code
                lineno = 0 if frame.f_lineno is None else frame.f_lineno
                frames.append((code.co_filename, lineno, code.co_name, _extract_class_name(frame)))
            frame = frame.f_back
    return frames, nframes
