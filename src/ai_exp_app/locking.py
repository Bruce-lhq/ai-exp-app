"""Process-scoped single-instance lock on Windows and POSIX."""
import os


class FileLock:
    def __init__(self, path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.stream = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0, 2)
                if self.stream.tell() == 0:
                    self.stream.write(b'\0')
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise BlockingIOError('AI Experiment service already owns this workspace') from exc
        return self

    def __exit__(self, *args):
        if self.stream is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.stream.seek(0)
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream, fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None
