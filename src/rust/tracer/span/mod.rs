use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::collections::{HashMap, VecDeque};

use std::mem;
use std::sync::{Arc, Mutex, Once};

#[macro_export]
macro_rules! span {
    ($reference:ident) => {
        SpanStore::instance()
            .map
            .lock()
            .unwrap()
            .get(&$reference)
            .unwrap()
    };
    ($reference:ident, $getter:ident) => {
        span!($reference).$getter().clone()
    };
    ($reference:ident, $getter:ident, $key:expr) => {
        span!($reference).$getter($key).unwrap().clone()
    };
}

macro_rules! span_mut {
    ($reference:ident, $setter:ident, $value:ident) => {
        let store = SpanStore::instance();
        let mut map = store.map.lock().unwrap();
        let span = map.get_mut(&$reference).unwrap();
        span.$setter($value);
    };
    ($reference:ident, $setter:ident, $key:ident, $value:ident) => {
        let store = SpanStore::instance();
        let mut map = store.map.lock().unwrap();
        let span = map.get_mut(&$reference).unwrap();
        span.$setter($key, $value);
    };
}

// ---- Internal data structures ----

pub struct Span {
    // TODO: Add lock
    pub service: String,
    pub name: String,
    pub resource: String,
    pub trace_id: u64,
    pub span_id: u64,
    pub parent_id: u64,
    pub start: i64,
    pub duration: i64,
    pub error: i32,
    pub meta: HashMap<String, String>,
    pub metrics: HashMap<String, f64>,
    pub span_type: String,
}

impl Span {
    pub fn get_name(&self) -> &String {
        &self.name
    }
    fn set_name(&mut self, name: String) {
        self.name = name;
    }
    pub fn get_span_type(&self) -> &String {
        &self.span_type
    }
    fn set_span_type(&mut self, span_type: String) {
        self.span_type = span_type;
    }
    pub fn get_service(&self) -> &String {
        &self.service
    }
    fn set_service(&mut self, service: String) {
        self.service = service;
    }
    pub fn get_resource(&self) -> &String {
        &self.resource
    }
    fn set_resource(&mut self, resource: String) {
        self.resource = resource;
    }
    fn get_trace_id(&self) -> u64 {
        self.trace_id
    }
    fn set_trace_id(&mut self, trace_id: u64) {
        self.trace_id = trace_id;
    }
    fn get_parent_id(&self) -> u64 {
        self.parent_id
    }
    fn set_parent_id(&mut self, parent_id: u64) {
        self.parent_id = parent_id;
    }
    fn get_span_id(&self) -> u64 {
        self.span_id
    }
    fn set_span_id(&mut self, span_id: u64) {
        self.span_id = span_id;
    }
    fn get_start(&self) -> i64 {
        self.start
    }
    fn set_start(&mut self, start: i64) {
        self.start = start;
    }
    fn get_duration(&self) -> i64 {
        self.duration
    }
    fn set_duration(&mut self, duration: i64) {
        self.duration = duration;
    }
    fn get_error(&self) -> i32 {
        self.error
    }
    fn set_error(&mut self, error: i32) {
        self.error = error;
    }
    fn get_meta(&self, key: &String) -> Option<&String> {
        self.meta.get(key)
    }
    fn set_meta(&mut self, key: String, value: String) {
        self.meta.insert(key, value);
    }
    fn del_meta(&mut self, key: String) {
        self.meta.remove(&key);
    }
    fn get_metrics(&self, key: &String) -> Option<&f64> {
        self.metrics.get(key)
    }
    fn set_metrics(&mut self, key: String, value: f64) {
        self.metrics.insert(key, value);
    }
    fn del_metrics(&mut self, key: String) {
        self.metrics.remove(&key);
    }
}

pub type SpanReference = u32;

#[derive(Clone)]
pub struct SpanStore {
    pub map: Arc<Mutex<HashMap<SpanReference, Span>>>, // TODO: This might not require a lock
    count: Arc<Mutex<SpanReference>>,
    free: Arc<Mutex<VecDeque<SpanReference>>>,
}

impl SpanStore {
    pub fn instance() -> SpanStore {
        // https://stackoverflow.com/questions/27791532/how-do-i-create-a-global-mutable-singleton
        static mut SINGLETON: *const SpanStore = 0 as *const SpanStore;
        static ONCE: Once = Once::new();
        unsafe {
            ONCE.call_once(|| {
                let singleton = SpanStore {
                    map: Arc::new(Mutex::new(HashMap::new())),
                    count: Arc::new(Mutex::new(0)),
                    free: Arc::new(Mutex::new(VecDeque::new())),
                };
                SINGLETON = mem::transmute(Box::new(singleton));
            });
            (*SINGLETON).clone()
        }
    }

    fn new_span(&self) -> SpanReference {
        let reference = match self.free.lock().unwrap().pop_back() {
            Some(n) => n,
            None => {
                let mut count = self.count.lock().unwrap();
                (*count) += 1;
                *count
            }
        };

        let mut map = self.map.lock().unwrap();
        map.insert(
            reference,
            Span {
                service: String::new(),
                name: String::new(),
                resource: String::new(),
                trace_id: 0,
                span_id: 0,
                parent_id: 0,
                start: 0,
                duration: 0,
                error: 0,
                meta: HashMap::new(),
                metrics: HashMap::new(),
                span_type: String::new(),
            },
        );

        reference
    }

    pub fn remove_span(&self, reference: &SpanReference) {
        let mut map = self.map.lock().unwrap();
        if map.contains_key(reference) {
            map.remove(reference).unwrap();
            let mut free = self.free.lock().unwrap();
            free.push_front(*reference);
        }
    }
}

// ---- Python Interface ----

#[pyfunction]
fn new() -> SpanReference {
    SpanStore::instance().new_span()
}

#[pyfunction]
fn remove(reference: i64) -> PyResult<()> {
    SpanStore::instance().remove_span(&(reference as SpanReference));
    Ok(())
}

#[pyfunction]
fn get_name(reference: SpanReference) -> PyResult<String> {
    Ok(span!(reference, get_name))
}

#[pyfunction]
fn set_name(reference: SpanReference, name: String) -> PyResult<()> {
    span_mut!(reference, set_name, name);
    Ok(())
}

#[pyfunction]
fn get_service(reference: SpanReference) -> PyResult<String> {
    Ok(span!(reference, get_service))
}

#[pyfunction]
fn set_service(reference: SpanReference, service: String) -> PyResult<()> {
    span_mut!(reference, set_service, service);
    Ok(())
}

#[pyfunction]
fn get_resource(reference: SpanReference) -> PyResult<String> {
    Ok(span!(reference, get_resource))
}

#[pyfunction]
fn set_resource(reference: SpanReference, resource: String) -> PyResult<()> {
    span_mut!(reference, set_resource, resource);
    Ok(())
}

#[pyfunction]
fn get_trace_id(reference: SpanReference) -> PyResult<u64> {
    Ok(span!(reference, get_trace_id))
}

#[pyfunction]
fn set_trace_id(reference: SpanReference, trace_id: u64) -> PyResult<()> {
    span_mut!(reference, set_trace_id, trace_id);
    Ok(())
}

#[pyfunction]
fn get_parent_id(reference: SpanReference) -> PyResult<u64> {
    Ok(span!(reference, get_parent_id))
}

#[pyfunction]
fn set_parent_id(reference: SpanReference, parent_id: u64) -> PyResult<()> {
    span_mut!(reference, set_parent_id, parent_id);
    Ok(())
}

#[pyfunction]
fn get_span_id(reference: SpanReference) -> PyResult<u64> {
    Ok(span!(reference, get_span_id))
}

#[pyfunction]
fn set_span_id(reference: SpanReference, span_id: u64) -> PyResult<()> {
    span_mut!(reference, set_span_id, span_id);
    Ok(())
}

#[pyfunction]
fn get_start(reference: SpanReference) -> PyResult<i64> {
    Ok(span!(reference, get_start))
}

#[pyfunction]
fn set_start(reference: SpanReference, start: i64) -> PyResult<()> {
    span_mut!(reference, set_start, start);
    Ok(())
}

#[pyfunction]
fn get_duration(reference: SpanReference) -> PyResult<i64> {
    Ok(span!(reference, get_duration))
}

#[pyfunction]
fn set_duration(reference: SpanReference, duration: i64) -> PyResult<()> {
    span_mut!(reference, set_duration, duration);
    Ok(())
}

#[pyfunction]
fn get_error(reference: SpanReference) -> PyResult<i32> {
    Ok(span!(reference, get_error))
}

#[pyfunction]
fn set_error(reference: SpanReference, error: i32) -> PyResult<()> {
    span_mut!(reference, set_error, error);
    Ok(())
}

#[pyfunction]
fn get_meta(reference: SpanReference, key: String) -> PyResult<String> {
    Ok(span!(reference, get_meta, &key))
}

#[pyfunction]
fn set_meta(reference: SpanReference, key: String, value: String) {
    span_mut!(reference, set_meta, key, value);
}

#[pyfunction]
fn del_meta(reference: SpanReference, key: String) {
    span_mut!(reference, del_meta, key);
}

#[pyfunction]
fn get_metrics(reference: SpanReference, key: String) -> PyResult<f64> {
    Ok(span!(reference, get_metrics, &key))
}

#[pyfunction]
fn set_metrics(reference: SpanReference, key: String, value: f64) {
    span_mut!(reference, set_metrics, key, value);
}

#[pyfunction]
fn del_metrics(reference: SpanReference, key: String) {
    span_mut!(reference, del_metrics, key);
}

#[pyfunction]
fn get_span_type(reference: SpanReference) -> PyResult<String> {
    Ok(span!(reference, get_span_type))
}

#[pyfunction]
fn set_span_type(reference: SpanReference, span_type: String) -> PyResult<()> {
    span_mut!(reference, set_span_type, span_type);
    Ok(())
}

// ---- Submodule configuration ----

pub fn init_span(module: &PyModule) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(new, module)?)?;
    module.add_function(wrap_pyfunction!(remove, module)?)?;

    module.add_function(wrap_pyfunction!(get_name, module)?)?;
    module.add_function(wrap_pyfunction!(set_name, module)?)?;
    module.add_function(wrap_pyfunction!(get_service, module)?)?;
    module.add_function(wrap_pyfunction!(set_service, module)?)?;
    module.add_function(wrap_pyfunction!(get_resource, module)?)?;
    module.add_function(wrap_pyfunction!(set_resource, module)?)?;

    module.add_function(wrap_pyfunction!(get_trace_id, module)?)?;
    module.add_function(wrap_pyfunction!(set_trace_id, module)?)?;
    module.add_function(wrap_pyfunction!(get_parent_id, module)?)?;
    module.add_function(wrap_pyfunction!(set_parent_id, module)?)?;
    module.add_function(wrap_pyfunction!(get_span_id, module)?)?;
    module.add_function(wrap_pyfunction!(set_span_id, module)?)?;
    module.add_function(wrap_pyfunction!(get_start, module)?)?;
    module.add_function(wrap_pyfunction!(set_start, module)?)?;
    module.add_function(wrap_pyfunction!(get_duration, module)?)?;
    module.add_function(wrap_pyfunction!(set_duration, module)?)?;

    module.add_function(wrap_pyfunction!(get_error, module)?)?;
    module.add_function(wrap_pyfunction!(set_error, module)?)?;

    module.add_function(wrap_pyfunction!(get_meta, module)?)?;
    module.add_function(wrap_pyfunction!(set_meta, module)?)?;
    module.add_function(wrap_pyfunction!(del_meta, module)?)?;
    module.add_function(wrap_pyfunction!(get_metrics, module)?)?;
    module.add_function(wrap_pyfunction!(set_metrics, module)?)?;
    module.add_function(wrap_pyfunction!(del_metrics, module)?)?;

    module.add_function(wrap_pyfunction!(get_span_type, module)?)?;
    module.add_function(wrap_pyfunction!(set_span_type, module)?)?;

    Ok(())
}
