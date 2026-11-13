"""Read actual media-test process pipes without socket-only Windows select."""
import queue
import threading


class MediaLineReader:
    def __init__(self, stream):
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream):
        try:
            for line in stream:
                self.lines.put(line)
        except (OSError, ValueError) as exc:
            self.lines.put(exc)
        finally:
            self.lines.put('')

    def readline(self, timeout=10):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise AssertionError('actual generated server response timeout') from exc
        if isinstance(line, Exception):
            raise AssertionError('actual generated server pipe read failed') from line
        return line

    def response_line(self, timeout=10):
        line = self.readline(timeout=timeout)
        if not line:
            raise AssertionError('actual generated server closed stdout')
        return line
