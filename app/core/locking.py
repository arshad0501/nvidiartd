"""Nonblocking thread/process writer lock; OS releases locks on process exit."""
from contextlib import contextmanager
import os
import threading
from pathlib import Path
from app.core.config import BusyError

_thread_lock = threading.Lock()


@contextmanager
def writer_lock(database_path):
    if not _thread_lock.acquire(blocking=False):
        raise BusyError("Another update is running. Please retry after it completes.")
    handle, locked = None, False
    try:
        path = Path(str(database_path) + ".writer.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise BusyError("Another update is running. Please retry after it completes.") from exc
        yield
    finally:
        if handle is not None:
            if locked:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        _thread_lock.release()
