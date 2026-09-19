"""Blocking process locks for persistent lockfiles (standard library only).

Do not unlink or replace a lockfile: waiters must keep sharing the same inode.
Locks are not reentrant. POSIX uses flock for compatibility with existing writers;
Windows reserves byte [0, 1), including on an empty file (locking beyond EOF is
supported). The file's contents are never modified.
"""

from contextlib import contextmanager
import errno
import os
import time

if os.name == "nt":
    import msvcrt
elif os.name == "posix":
    import fcntl
else:
    raise ImportError(f"Unsupported locking platform: {os.name}")


@contextmanager
def exclusive_lock(path, timeout=None):
    """Acquire an exclusive lock, blocking until available; always close/release.

The caller creates the parent directory. Opening does not truncate existing
files. Only contention/interruption is retried; other I/O failures propagate.
"""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    deadline = None if timeout is None else time.monotonic() + max(0, timeout)
    try:
        while True:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    # LK_LOCK has a finite retry limit; retry LK_NBLCK ourselves.
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0))
                acquired = True
                break
            except OSError as error:
                if error.errno == errno.EINTR:
                    continue
                if (os.name == "nt" or deadline is not None) and error.errno in (
                    errno.EACCES, errno.EAGAIN, errno.EDEADLK
                ):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("lock_deadline_exceeded") from None
                    time.sleep(0.01 if deadline is not None else 0.05)
                    continue
                raise
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
