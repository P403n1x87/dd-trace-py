use pyo3::prelude::*;

mod encoder;
mod gc;
mod span;

#[pymodule]
fn tracer(py: Python, module: &PyModule) -> PyResult<()> {
    let encoder_module = PyModule::new(py, "encoder")?;
    let gc_module = PyModule::new(py, "gc")?;
    let span_module = PyModule::new(py, "span")?;

    encoder::init_encoder(encoder_module)?;
    gc::init_gc(gc_module)?;
    span::init_span(span_module)?;

    module.add_submodule(encoder_module)?;
    module.add_submodule(gc_module)?;
    module.add_submodule(span_module)?;
    Ok(())
}
