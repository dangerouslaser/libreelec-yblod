//! In-process call-boundary failures for the isolated headless regression build.
//! Absent from ordinary builds; never inject driver faults or mutate the kernel.
#[inline]
pub fn hit(point: &str) -> bool {
    #[cfg(feature = "test-faults")]
    {
        use std::collections::HashMap;
        use std::sync::{Mutex, OnceLock};
        static COUNTS: OnceLock<Mutex<HashMap<String, u64>>> = OnceLock::new();
        let Ok(spec) = std::env::var("DVVK_TEST_FAIL") else {
            return false;
        };
        for item in spec.split(',') {
            let Some((name, at)) = item.split_once(':') else {
                continue;
            };
            if name != point {
                continue;
            }
            let mut counts = COUNTS.get_or_init(Default::default).lock().unwrap();
            let count = counts.entry(item.to_owned()).or_default();
            *count += 1;
            if at == "all" || at.parse::<u64>() == Ok(*count) {
                eprintln!("dvvk test-fault: {point} call {count}");
                return true;
            }
        }
    }
    let _ = point;
    false
}

#[inline]
pub(crate) fn check(point: &str) -> crate::device::Result<()> {
    if hit(point) {
        Err(crate::device::Error::Vk(ash::vk::Result::ERROR_UNKNOWN))
    } else {
        Ok(())
    }
}
