//! Implicit fences on dmabufs as sync_files, and sync_files as semaphores.

use crate::device::{Device, Error, Result};
use ash::vk;
use std::os::fd::RawFd;

pub const DMA_BUF_SYNC_READ: u32 = 1;
pub const DMA_BUF_SYNC_WRITE: u32 = 2;

#[repr(C)]
struct SyncFileArg {
    flags: u32,
    fd: i32,
}

// _IOWR('b', 2, struct dma_buf_export_sync_file), _IOW('b', 3, struct dma_buf_import_sync_file)
const DMA_BUF_IOCTL_EXPORT_SYNC_FILE: libc::c_ulong = 0xC008_6202;
const DMA_BUF_IOCTL_IMPORT_SYNC_FILE: libc::c_ulong = 0x4008_6203;

/// The fences a reader (`DMA_BUF_SYNC_READ`: the writers') or a writer
/// (`DMA_BUF_SYNC_WRITE`: all) of the dmabuf would wait for, as a sync_file.
pub fn export_sync_file(dmabuf: RawFd, flags: u32) -> Result<RawFd> {
    let mut arg = SyncFileArg { flags, fd: -1 };
    let r = unsafe { libc::ioctl(dmabuf, DMA_BUF_IOCTL_EXPORT_SYNC_FILE, &mut arg) };
    if r != 0 || arg.fd < 0 {
        return Err(Error::Unsupported(format!("DMA_BUF_IOCTL_EXPORT_SYNC_FILE: {}", std::io::Error::last_os_error())));
    }
    Ok(arg.fd)
}

/// Attaches a sync_file to the dmabuf as an implicit fence (a write fence with
/// `DMA_BUF_SYNC_WRITE`), for consumers that only know implicit sync.
pub fn import_sync_file(dmabuf: RawFd, sync_file: RawFd, flags: u32) -> Result<()> {
    let mut arg = SyncFileArg { flags, fd: sync_file };
    let r = unsafe { libc::ioctl(dmabuf, DMA_BUF_IOCTL_IMPORT_SYNC_FILE, &mut arg) };
    if r != 0 {
        return Err(Error::Unsupported(format!("DMA_BUF_IOCTL_IMPORT_SYNC_FILE: {}", std::io::Error::last_os_error())));
    }
    Ok(())
}

/// True if the fence fd (sync_file) has signalled.
pub fn signalled(fd: RawFd) -> bool {
    let mut p = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
    unsafe {
        libc::poll(&mut p, 1, 0) == 1
            && p.revents & libc::POLLIN != 0
            && p.revents & (libc::POLLERR | libc::POLLNVAL | libc::POLLHUP) == 0
    }
}

/// A binary semaphore whose next wait is on `sync_file` (consumed on success).
pub fn semaphore_from_sync_file(d: &Device, semaphore: vk::Semaphore, sync_file: RawFd) -> Result<()> {
    if crate::fault::hit("semaphore-import") {
        return Err(Error::Vk(vk::Result::ERROR_INVALID_EXTERNAL_HANDLE));
    }
    let info = vk::ImportSemaphoreFdInfoKHR::default()
        .semaphore(semaphore)
        .flags(vk::SemaphoreImportFlags::TEMPORARY)
        .handle_type(vk::ExternalSemaphoreHandleTypeFlags::SYNC_FD)
        .fd(sync_file);
    unsafe { d.semaphore_fd.import_semaphore_fd(&info) }?;
    Ok(())
}

/// A sync_file for a binary semaphore's pending signal.
pub fn sync_file_from_semaphore(d: &Device, semaphore: vk::Semaphore) -> Result<RawFd> {
    let info = vk::SemaphoreGetFdInfoKHR::default()
        .semaphore(semaphore)
        .handle_type(vk::ExternalSemaphoreHandleTypeFlags::SYNC_FD);
    Ok(unsafe { d.semaphore_fd.get_semaphore_fd(&info) }?)
}

/// A binary semaphore that can export/import sync_files.
pub fn exportable_semaphore(d: &Device) -> Result<vk::Semaphore> {
    let mut export =
        vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::SYNC_FD);
    let info = vk::SemaphoreCreateInfo::default().push_next(&mut export);
    Ok(unsafe { d.device.create_semaphore(&info, None) }?)
}

/// Wait for a producer whose sync-file could not be imported into Vulkan.
/// Never interpret POLLNVAL/POLLERR/HUP as successful producer completion.
pub fn wait_sync_file(fd: RawFd, timeout_ms: u32) -> Result<()> {
    let timeout_ms = if crate::fault::hit("producer-timeout") { 0 } else { timeout_ms };
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms as u64);
    loop {
        let mut p = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
        let remaining =
            deadline.saturating_duration_since(std::time::Instant::now()).as_millis().min(i32::MAX as u128) as i32;
        let r = unsafe { libc::poll(&mut p, 1, remaining) };
        if r < 0
            && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted
            && std::time::Instant::now() < deadline
        {
            continue;
        }
        if r == 0 {
            return Err(Error::Unsupported("producer sync-file wait timed out".into()));
        }
        if r == 1 && p.revents & libc::POLLIN != 0 && p.revents & (libc::POLLERR | libc::POLLNVAL | libc::POLLHUP) == 0
        {
            return Ok(());
        }
        return Err(Error::Unsupported("producer sync-file wait failed".into()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_fd_is_not_a_completed_producer() {
        // A nonexistent positive fd reports POLLNVAL, not POLLIN.
        let fd = i32::MAX;
        assert!(!signalled(fd));
        assert!(wait_sync_file(fd, 0).is_err());
    }
    #[test]
    fn readable_hung_up_fd_is_not_successful_sync_completion() {
        let mut fds = [0; 2];
        assert_eq!(unsafe { libc::pipe2(fds.as_mut_ptr(), libc::O_CLOEXEC) }, 0);
        let byte = 1u8;
        assert_eq!(unsafe { libc::write(fds[1], (&byte as *const u8).cast(), 1) }, 1);
        unsafe {
            libc::close(fds[1]);
        }
        assert!(!signalled(fds[0]));
        assert!(wait_sync_file(fds[0], 0).is_err());
        unsafe {
            libc::close(fds[0]);
        }
    }
    #[test]
    fn pending_producer_timeout_does_not_authorize_a_read() {
        let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) };
        assert!(fd >= 0);
        assert!(wait_sync_file(fd, 2).is_err());
        assert!(!signalled(fd));
        unsafe {
            libc::close(fd);
        }
    }
    #[test]
    fn pending_and_ready_producers_are_distinguished() {
        let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) };
        assert!(fd >= 0);
        assert!(!signalled(fd));
        let value = 1u64;
        assert_eq!(unsafe { libc::write(fd, (&value as *const u64).cast(), 8) }, 8);
        assert!(signalled(fd));
        assert!(wait_sync_file(fd, 0).is_ok());
        unsafe {
            libc::close(fd);
        }
    }
}
