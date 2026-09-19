"""Bounded, per-vault inference coordination across threads and local processes.

Persistent lock files must never be deleted. Hash stripes bound lockfile growth.
Work shares three provider slots. Timed-out callers return
without releasing a slot still owned by an active transport. No retries.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import queue
import threading
import time
from platform_lock import exclusive_lock

MAX_INFLIGHT = 3
_WAITERS = threading.BoundedSemaphore(16)


def _folder(vault):
    root = Path(vault) / '.cache'
    folder = root / 'jev-runtime'
    if root.is_symlink() or folder.is_symlink():
        raise ValueError('coordination_unavailable')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    return folder


def _path(folder, name):
    path = folder / name
    if path.is_symlink(): raise ValueError('coordination_unavailable')
    return path


def run(vault, digest, timeout, operation):
    """Single-flight includes rechecking the cache and publishing its result.

    Operation executes under a provider slot too: a cache hit holds it briefly,
    but never sends another request. Queue wait counts against the deadline.
    """
    if timeout <= 0: raise ValueError('deadline_exceeded')
    if not _WAITERS.acquire(blocking=False): raise ValueError('capacity_exceeded')
    deadline = time.monotonic() + timeout
    output = queue.Queue(maxsize=1)
    def worker():
        try:
            folder = _folder(vault)
            with exclusive_lock(_path(folder, 'flight-' + digest[:2] + '.lock'),
                                timeout=max(0, deadline-time.monotonic())):
                with ExitStack() as stack:
                    while True:
                        if time.monotonic() >= deadline: raise ValueError('deadline_exceeded')
                        for slot in range(MAX_INFLIGHT):
                            try:
                                stack.enter_context(exclusive_lock(_path(folder, f'slot-{slot}.lock'), timeout=0))
                                break
                            except TimeoutError: continue
                        else:
                            time.sleep(min(.01, max(0,deadline-time.monotonic())))
                            continue
                        break
                    value = operation()
            output.put((True, value))
        except TimeoutError:
            output.put((False, ValueError('deadline_exceeded')))
        except Exception as error:
            output.put((False, error))
        finally:
            _WAITERS.release()
    try:
        thread = threading.Thread(target=worker, daemon=True, name='jev-request')
        thread.start()
    except BaseException:
        _WAITERS.release()
        raise
    try: success, value = output.get(timeout=max(0,deadline-time.monotonic()))
    except queue.Empty: raise ValueError('deadline_exceeded') from None
    if not success: raise value
    return value
