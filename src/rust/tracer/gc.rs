use super::span::{SpanReference, SpanStore};
use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::collections::HashSet;

use std::mem;
use std::sync::{Arc, Condvar, Mutex, Once};
use std::time::Duration;

#[derive(Clone)]
pub struct GarbageCollector {
    garbage: Arc<Mutex<HashSet<SpanReference>>>,
    keep: Arc<Mutex<HashSet<SpanReference>>>, // TODO: Lock spans instead
    started: Arc<Mutex<bool>>,
    cvar: Arc<Condvar>,
}

impl GarbageCollector {
    pub fn instance() -> GarbageCollector {
        // https://stackoverflow.com/questions/27791532/how-do-i-create-a-global-mutable-singleton
        static mut SINGLETON: *const GarbageCollector = 0 as *const GarbageCollector;
        static ONCE: Once = Once::new();
        unsafe {
            ONCE.call_once(|| {
                let singleton = GarbageCollector {
                    garbage: Arc::new(Mutex::new(HashSet::new())),
                    keep: Arc::new(Mutex::new(HashSet::new())),
                    started: Arc::new(Mutex::new(false)),
                    cvar: Arc::new(Condvar::new()),
                };
                SINGLETON = mem::transmute(Box::new(singleton));
            });
            (*SINGLETON).clone()
        }
    }

    pub fn keep(&self, span: &SpanReference) {
        self.keep.lock().unwrap().insert(*span);
    }

    pub fn release(&self, span: &SpanReference) {
        self.keep.lock().unwrap().remove(span);
    }

    fn recycle(&self, span: &SpanReference) {
        self.garbage.lock().unwrap().insert(*span);
    }

    fn start(&mut self) {
        let mut started = self.started.lock().unwrap();
        if *started {
            return;
        }

        let pair = (Arc::clone(&self.started), Arc::clone(&self.cvar));
        std::thread::spawn(move || {
            let (lock, cvar) = pair;
            let mut started = lock.lock().unwrap();
            let gc = GarbageCollector::instance();

            loop {
                let result = cvar
                    .wait_timeout(started, Duration::from_millis(1000))
                    .unwrap();
                started = result.0;
                if !*started {
                    break;
                }
                let mut garbage = gc.garbage.lock().unwrap();
                let keep = gc.keep.lock().unwrap();
                let to_remove = garbage.clone();
                for s in to_remove.iter() {
                    if !keep.contains(s) {
                        SpanStore::instance().remove_span(s);
                        garbage.remove(s);
                    }
                }
            }
        });

        *started = true;
    }

    fn stop(&mut self) {
        let mut started = self.started.lock().unwrap();

        if !*started {
            return;
        }

        *started = false;
        self.cvar.notify_one();
    }
}

#[pyfunction]
fn recycle(span: SpanReference) {
    GarbageCollector::instance().recycle(&span);
}

#[pyfunction]
fn start(py: Python) {
    py.allow_threads(|| GarbageCollector::instance().start());
}

#[pyfunction]
fn stop() {
    GarbageCollector::instance().stop();
}

pub fn init_gc(module: &PyModule) -> PyResult<()> {
    // module.add_function(wrap_pyfunction!(keep, module)?)?;
    module.add_function(wrap_pyfunction!(recycle, module)?)?;
    module.add_function(wrap_pyfunction!(start, module)?)?;
    module.add_function(wrap_pyfunction!(stop, module)?)?;

    Ok(())
}
