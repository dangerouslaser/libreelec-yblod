//! Rollback for unpublished construction resources only. Runtime ownership and
//! retirement remain explicit in Engine; this is not general GPU-resource RAII.
use crate::device::Device;
use crate::gpu::{DeviceBuffer, HostBuffer, Lut3d, OneShot, Pipeline, SampledImage};
use ash::vk;

type Action = Box<dyn FnOnce(&Device)>;
pub(crate) struct Construction<'a> {
    device: &'a Device,
    actions: Vec<Action>,
    submitted: bool,
}
impl<'a> Construction<'a> {
    pub(crate) fn new(device: &'a Device) -> Self {
        Self { device, actions: Vec::new(), submitted: false }
    }
    pub(crate) fn keep<T: Resource>(&mut self, value: T) -> T {
        self.watch(&value);
        value
    }
    pub(crate) fn watch<T: Resource>(&mut self, value: &T) {
        self.actions.push(value.rollback());
    }
    /// Call before any submission can reference a tracked object.
    pub(crate) fn may_submit(&mut self) {
        self.submitted = true;
    }
    /// Transfer all ownership to the fully constructed object.
    pub(crate) fn commit(mut self) {
        self.actions.clear();
    }
}
impl Drop for Construction<'_> {
    fn drop(&mut self) {
        if self.submitted && !self.actions.is_empty() {
            self.device.require_idle();
        }
        for action in self.actions.drain(..).rev() {
            action(self.device);
        }
    }
}

pub(crate) trait Resource {
    fn rollback(&self) -> Action;
}
// These private snapshots have no Drop and never escape the transaction. Reuse
// the normal destructors so rollback ordering cannot diverge from teardown.
impl Resource for Pipeline {
    fn rollback(&self) -> Action {
        let copy =
            Self { set_layout: self.set_layout, layout: self.layout, pipeline: self.pipeline, bindings: Vec::new() };
        Box::new(move |d| copy.destroy(d))
    }
}
impl Resource for HostBuffer {
    fn rollback(&self) -> Action {
        let copy = Self { buffer: self.buffer, memory: self.memory, ptr: self.ptr, size: self.size };
        Box::new(move |d| copy.destroy(d))
    }
}
impl Resource for DeviceBuffer {
    fn rollback(&self) -> Action {
        let copy = Self { buffer: self.buffer, memory: self.memory, size: self.size };
        Box::new(move |d| copy.destroy(d))
    }
}
impl Resource for SampledImage {
    fn rollback(&self) -> Action {
        let copy = Self { image: self.image, memory: self.memory, view: self.view };
        Box::new(move |d| copy.destroy(d))
    }
}
impl Resource for Lut3d {
    fn rollback(&self) -> Action {
        let copy = Self { image: self.image, memory: self.memory, view: self.view, n: self.n, ready: false };
        Box::new(move |d| copy.destroy(d))
    }
}
impl Resource for OneShot {
    fn rollback(&self) -> Action {
        let copy = Self { pool: self.pool, cmd: self.cmd, fence: self.fence };
        Box::new(move |d| copy.destroy(d))
    }
}
macro_rules! handle {
    ($ty:ty, $destroy:ident) => {
        impl Resource for $ty {
            fn rollback(&self) -> Action {
                let value = *self;
                Box::new(move |d| unsafe { d.device.$destroy(value, None) })
            }
        }
    };
}
handle!(vk::Sampler, destroy_sampler);
handle!(vk::CommandPool, destroy_command_pool);
handle!(vk::Semaphore, destroy_semaphore);
handle!(vk::QueryPool, destroy_query_pool);
