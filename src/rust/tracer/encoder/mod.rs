use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::PyBytes;

use super::gc::GarbageCollector;
use super::span::{SpanReference, SpanStore};

use rmp::encode::{write_array_len, write_map_len, write_str, write_u64, write_pfix, write_i64, write_f64, write_nil};

macro_rules! write_string {
    ($buf:ident, $value:expr) => {
        if $value.len() == 0 {
            write_nil($buf).ok();
        }
        else {
            write_str($buf, $value).ok();
        }
    };
}

macro_rules! write_uint64 {
    ($buf:ident, $value:expr) => {
        if $value == 0 {
            write_nil($buf).ok();
        }
        else {
            write_u64($buf, $value).ok();
        }
    };
}

macro_rules! write_int64 {
    ($buf:ident, $value:expr) => {
        if $value == 0 {
            write_nil($buf).ok();
        }
        else if $value > 0 {
            write_u64($buf, $value as u64).ok();
        }
        else {
            write_i64($buf, $value).ok();
        }
    };
}

fn encode_span(buf: &mut Vec<u8>, reference: &SpanReference) {
    let store = SpanStore::instance();
    let map = store.map.lock().unwrap(); // TODO: This lock is not required :(
    let span = map.get(&reference).unwrap();
    
    let len = 9
        + if span.meta.len() > 0 { 1 } else { 0 }
        + if span.metrics.len() > 0 { 1 } else { 0 }
        + if span.span_type.len() > 0 { 1 } else { 0 };

    write_map_len(buf, len).ok();
    
    write_string!(buf, "trace_id");
    write_uint64!(buf, span.trace_id);

    write_string!(buf, "parent_id");
    write_uint64!(buf, span.parent_id);

    write_string!(buf, "span_id");
    write_uint64!(buf, span.span_id);

    write_string!(buf, "service");
    write_string!(buf, span.service.as_str());

    write_string!(buf, "resource");
    write_string!(buf, span.resource.as_str());

    write_string!(buf, "name");
    write_string!(buf, span.name.as_str());

    write_string!(buf, "error");
    write_pfix(buf, if span.error != 0 {1} else {0}).ok();

    write_string!(buf, "start");
    write_int64!(buf, span.start);

    write_string!(buf, "duration");
    write_int64!(buf, span.duration);

    if span.span_type.len() > 0 {
        write_string!(buf, "type");
        write_string!(buf, span.span_type.as_str());
    }

    if span.meta.len() > 0 {
        write_string!(buf, "meta");
        write_map_len(buf, span.meta.len() as u32).ok();
        for (k, v) in &span.meta {
            write_string!(buf, k.as_str());
            write_string!(buf, v.as_str());
        }
    }

    if span.metrics.len() > 0 {
        write_string!(buf, "metrics");
        write_map_len(buf, span.metrics.len() as u32).ok();
        for (k, v) in &span.metrics {
            write_string!(buf, k.as_str());
            write_f64(buf, *v).ok();
        }
    }
}

fn encode_trace(buf: &mut Vec<u8>, trace: &Vec<SpanReference>) {
    write_array_len(buf, trace.len() as u32).ok();
    for span in trace.iter() {
        encode_span(buf, span);
    }
}

#[pyfunction]
fn encode(py: Python, trace: Vec<SpanReference>) -> PyResult<&PyBytes> {
    let gc = GarbageCollector::instance();

    // Prevent spans that are to be encoded from being removed too early.
    // Use the GIL to prevent Python Span objects from calling __del__ while
    // we're still encoding the trace.
    for s in trace.iter() {
        gc.keep(s)
    }

    let mut buf = Vec::new();

    // Do the encoding while allowing Python threads to run
    py.allow_threads(|| {    
        encode_trace(&mut buf, &trace);
    });

    // Release the spans that have just been encoded so that they can be removed
    for s in trace.iter() {
        gc.release(s);
    }

    Ok(PyBytes::new(py, &buf).into())
}

pub fn init_encoder(module: &PyModule) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(encode, module)?)?;

    Ok(())
}
