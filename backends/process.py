"""A backend's worker process, seen from the add-on: start, requests, answers, stop. No bpy.

The worker talks the JSON lines protocol (backends.protocol) on its stdin / stdout. A thread reads its stdout
into a queue, another keeps the end of its stderr for error messages. Nothing blocks: the add-on calls
pump() from a Blender timer, which updates the Jobs. wait() blocks, for scripts and tests.
"""
import collections
import os
import queue
import subprocess
import sys
import threading
import time

from . import protocol

# Job states
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

# Worker states
STARTING = "STARTING"  # launched, no hello yet
READY = "READY"        # running, waiting for requests
STOPPED = "STOPPED"


class WorkerError(Exception):
    pass


class Job:
    """One request sent to the worker, and what came back for it."""

    def __init__(self, request_id, kind):
        self.id = request_id
        self.kind = kind
        self.state = RUNNING
        self.fraction = 0.0
        self.message = ""
        self.error = ""
        self.result = None      # the answer's payload (skeleton dict...)
        self.frames = []        # "frames" messages of a generation
        self.started = time.perf_counter()
        self.finished = None

    @property
    def finished_ok(self):
        return self.state == DONE

    @property
    def active(self):
        return self.state == RUNNING

    @property
    def duration(self):
        return (self.finished or time.perf_counter()) - self.started

    def _finish(self, state, error=""):
        if self.state == RUNNING:
            self.state = state
            self.error = error
            self.finished = time.perf_counter()

    def handle(self, message):
        kind = message["type"]
        if kind == "progress":
            self.fraction = float(message.get("fraction", 0.0))
            self.message = message.get("message", "")
        elif kind == "frames":
            self.frames.append(message)
        elif kind == "error":
            self._finish(CANCELLED if message.get("cancelled") else FAILED, message.get("message", "Unknown error."))
        elif kind == "skeleton":
            self.result = message.get("skeleton")
            self._finish(DONE)
        elif kind in ("ready", "done"):
            self.fraction = 1.0
            self._finish(DONE)


class Worker:
    """A worker process. command: argv list; env: extra environment variables."""

    def __init__(self, command, env=None, hello_timeout=120.0):
        self.command = list(command)
        self.env = dict(env or {})
        self.hello_timeout = hello_timeout
        self.state = STOPPED
        self.backend_id = ""
        self.error = ""
        self.process = None
        self.jobs = {}
        self._next_id = 1
        self._messages = queue.Queue()
        self._stderr = collections.deque(maxlen=60)
        self._started_at = None

    # Lifecycle

    def start(self):
        """Launch the process. Raises WorkerError if it can't be started."""
        if self.alive:
            return
        env = dict(os.environ)
        env.update(self.env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, env=env, creationflags=flags)
        except OSError as e:
            self.state = STOPPED
            raise WorkerError(f"Unable to start the backend: {e}") from e
        self.state = STARTING
        self.error = ""
        self._started_at = time.perf_counter()
        self._messages = queue.Queue()
        self._stderr.clear()
        threading.Thread(target=self._read_stdout, args=(self.process, self._messages), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(self.process,), daemon=True).start()

    def _read_stdout(self, process, messages):
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                messages.put(protocol.loads(line))
            except ValueError:
                self._stderr.append(f"(not a protocol message) {line[:300]}")
        messages.put(None)  # end of stream

    def _read_stderr(self, process):
        for raw in process.stderr:
            self._stderr.append(raw.decode("utf-8", errors="replace").rstrip())

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    @property
    def busy(self):
        return any(job.active for job in self.jobs.values())

    def stderr_tail(self, lines=12):
        return "\n".join(list(self._stderr)[-lines:])

    def stop(self, timeout=5.0):
        """Ask the worker to quit, kill it if it doesn't. Running jobs are cancelled."""
        if self.process is None:
            return
        if self.alive:
            try:
                self._write({"type": "shutdown"})
            except WorkerError:
                pass
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for job in self.jobs.values():
            job._finish(CANCELLED, "The backend was stopped.")
        self._release()
        self.state = STOPPED

    def _release(self):
        """Forget the process, closing its pipes"""
        if self.process is not None:
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        self.process = None

    # Requests

    def _write(self, message):
        try:
            self.process.stdin.write(protocol.dumps(message).encode("utf-8"))
            self.process.stdin.flush()
        except (OSError, ValueError, AttributeError) as e:
            raise WorkerError(f"The backend is not running ({e}).") from e

    def submit(self, kind, **fields):
        """Send a request ("skeleton", "load", "generate"); returns its Job. Starts the worker if needed."""
        if not self.alive:
            self.start()
        job = Job(self._next_id, kind)
        self._next_id += 1
        self.jobs[job.id] = job
        try:
            self._write(dict({"type": kind, "id": job.id}, **fields))
        except WorkerError as e:
            job._finish(FAILED, str(e))
        return job

    def cancel(self, job):
        if job.active and self.alive:
            try:
                self._write({"type": "cancel", "id": job.id})
            except WorkerError:
                job._finish(CANCELLED, "Cancelled.")

    def forget(self, job):
        self.jobs.pop(job.id, None)

    # Answers

    def pump(self):
        """Handle every message received so far (never blocks). Returns True if something changed."""
        changed = False
        while True:
            try:
                message = self._messages.get_nowait()
            except queue.Empty:
                break
            changed = True
            if message is None:
                self._process_ended()
                break
            self._dispatch(message)

        if self.state == STARTING and time.perf_counter() - self._started_at > self.hello_timeout:
            self.error = "The backend didn't answer when started.\n" + self.stderr_tail()
            self.stop(timeout=1.0)
            changed = True
        return changed

    def _dispatch(self, message):
        kind = message["type"]
        if kind == "hello":
            if message.get("protocol") != protocol.PROTOCOL_VERSION:
                self.error = (f"The backend speaks protocol version {message.get('protocol')}, "
                              f"the add-on version {protocol.PROTOCOL_VERSION}.")
                self.stop(timeout=1.0)
                return
            self.backend_id = message.get("backend", "")
            self.state = READY
            return
        job = self.jobs.get(message.get("id"))
        if job is not None:
            job.handle(message)
        elif kind == "error":
            self.error = message.get("message", "")

    def _process_ended(self):
        code = self.process.poll() if self.process is not None else None
        if self.process is not None:
            try:
                code = self.process.wait(2.0)
            except subprocess.TimeoutExpired:
                pass
        tail = self.stderr_tail()
        for job in self.jobs.values():
            job._finish(FAILED, f"The backend stopped (exit code {code}).\n{tail}".strip())
        if self.state != STOPPED:
            self.error = f"The backend stopped (exit code {code}).\n{tail}".strip()
        self._release()
        self.state = STOPPED

    def wait(self, job, timeout=None, poll=0.01):
        """Block until the job is finished (pumping the messages). Raises WorkerError on timeout."""
        start = time.perf_counter()
        while job.active:
            self.pump()
            if not job.active:
                break
            if not self.alive and self._messages.empty():
                self.pump()
                if job.active:
                    job._finish(FAILED, self.error or "The backend stopped.")
                break
            if timeout is not None and time.perf_counter() - start > timeout:
                raise WorkerError(f"The backend didn't finish '{job.kind}' within {timeout:.0f} s.")
            time.sleep(poll)
        return job
