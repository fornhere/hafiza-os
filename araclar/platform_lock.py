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
def exclusive_lock(path):
    """Acquire an exclusive lock, blocking until available; always close/release.

The caller creates the parent directory. Opening does not truncate existing
files. Only contention/interruption is retried; other I/O failures propagate.
"""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        while True:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    # LK_LOCK has a finite retry limit; retry LK_NBLCK ourselves.
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                acquired = True
                break
            except OSError as error:
                if error.errno == errno.EINTR:
                    continue
                if os.name == "nt" and error.errno in (
                    errno.EACCES, errno.EAGAIN, errno.EDEADLK
                ):
                    time.sleep(0.05)
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
