"""
R2D2 Supervisor — main entry point.

Starts and manages the entire application:
  - Acquires a Redis lock to prevent multiple instances
  - Starts uvicorn (FastAPI) as a subprocess
  - Monitors and manages live trading task processes
  - Handles graceful shutdown on SIGINT / SIGTERM

Usage:
    cd backend && python -m app.main
"""
import os
import sys
import time
import signal
import subprocess
import json
import uuid
import msgpack
from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing import Process
from pathlib import Path
from typing import Dict, Optional, Any, cast

# Ensure backend/ is in sys.path when run directly
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

import redis

from app.core.config import (
    redis_params,
    SUPERVISOR_POLL_INTERVAL,
    SUPERVISOR_MAX_RESTARTS,
    SUPERVISOR_CRASH_INTERVAL,
    SUPERVISOR_FORCE_KILL_TIMEOUT,
    SUPERVISOR_LOCK_KEY,
    SUPERVISOR_PIDS_KEY,
    SUPERVISOR_ERRORS_KEY,
    SUPERVISOR_GLOBAL_CHANNEL,
    REDIS_QUOTE_REQUEST_LIST,
)
from app.core.logger import setup_logging, get_logger
from app.services.tasks.tasks import TradingTaskList
from app.services.trading_worker import worker_trading_task
from app.services.quotes.constants import SUB_ACTION_UNSUBSCRIBE

logger = get_logger(__name__)

# Lock TTL is computed from the poll interval — not a configurable constant
LOCK_TTL = max(int(SUPERVISOR_POLL_INTERVAL * 5), 15)  # Seconds; renewed every poll

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProcessInfo:
    process: Process
    start_time: float                    # time.monotonic() when this process started
    crash_count: int = 0                 # Number of rapid crashes in a row
    stop_requested_at: Optional[float] = None   # When isRunning=False was first detected (alive)
    sigterm_sent_at: Optional[float] = None     # When SIGTERM was sent


# ---------------------------------------------------------------------------
# Supervisor class
# ---------------------------------------------------------------------------

class Supervisor:
    def __init__(self) -> None:
        self._params = redis_params()
        self._redis: Optional[redis.Redis] = None
        self._trading_task_list: Optional[TradingTaskList] = None
        self._processes: Dict[int, ProcessInfo] = {}   # task_id → ProcessInfo
        self._api_process: Optional[subprocess.Popen] = None
        self._running = True

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _get_redis(self) -> redis.Redis:
        if self._redis is None or not self._ping_redis():
            self._redis = redis.Redis(
                host=self._params["host"],
                port=self._params["port"],
                db=self._params["db"],
                password=self._params.get("password"),
                decode_responses=True,
                socket_connect_timeout=5,
            )
        return self._redis

    def _ping_redis(self) -> bool:
        if self._redis is None:
            return False
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Instance lock
    # ------------------------------------------------------------------

    def _acquire_lock(self) -> bool:
        """
        Try to acquire the application instance lock.

        Returns True if lock acquired, False if another instance is running.
        Uses SET NX EX to atomically create key with TTL.
        """
        client = self._get_redis()
        pid = str(os.getpid())
        acquired = client.set(SUPERVISOR_LOCK_KEY, pid, nx=True, ex=LOCK_TTL)
        if acquired:
            logger.info(f"Instance lock acquired (PID={pid}, TTL={LOCK_TTL}s)")
            return True

        owner = client.get(SUPERVISOR_LOCK_KEY)
        logger.error(
            f"Another instance is already running (lock owner PID={owner}). "
            "If you are sure no other instance is running, delete the Redis key: "
            f"redis-cli del {SUPERVISOR_LOCK_KEY}"
        )
        return False

    def _renew_lock(self) -> None:
        """Renew lock TTL so it doesn't expire while supervisor is alive."""
        try:
            self._get_redis().expire(SUPERVISOR_LOCK_KEY, LOCK_TTL)
        except Exception as e:
            logger.warning(f"Failed to renew instance lock: {e}")

    def _release_lock(self) -> None:
        """Release the lock on graceful shutdown."""
        try:
            pid = str(os.getpid())
            client = self._get_redis()
            owner = client.get(SUPERVISOR_LOCK_KEY)
            if owner == pid:
                client.delete(SUPERVISOR_LOCK_KEY)
                logger.info("Instance lock released")
        except Exception as e:
            logger.warning(f"Failed to release instance lock: {e}")

    # ------------------------------------------------------------------
    # PID tracking in Redis
    # ------------------------------------------------------------------

    def _save_pid(self, task_id: int, pid: int) -> None:
        try:
            self._get_redis().hset(SUPERVISOR_PIDS_KEY, str(task_id), str(pid))
        except Exception as e:
            logger.warning(f"Failed to save PID for task {task_id}: {e}")

    def _remove_pid(self, task_id: int) -> None:
        try:
            self._get_redis().hdel(SUPERVISOR_PIDS_KEY, [str(task_id)])
        except Exception as e:
            logger.warning(f"Failed to remove PID for task {task_id}: {e}")

    def _cleanup_quotes_subscription(self, task_id: int) -> None:
        """
        Best-effort unsubscribe for QuotesServer after worker death.

        This covers cases where the worker process exits before BrokerLive.cleanup()
        can send the unsubscribe request itself.
        """
        try:
            task = self._get_task_list().load(task_id)
            if task is None:
                return
            if not task.source or not task.symbol or not task.timeframe:
                return

            request = {
                "request_id": str(uuid.uuid4()),
                "action": SUB_ACTION_UNSUBSCRIBE,
                "source": task.source,
                "symbol": task.symbol,
                "timeframe": task.timeframe,
            }
            request_bytes = cast(bytes, msgpack.packb(request, use_bin_type=True))
            self._get_redis().lpush(
                REDIS_QUOTE_REQUEST_LIST,
                request_bytes,
            )
            logger.info(
                "Queued quotes unsubscribe for task %s: %s:%s:%s",
                task_id,
                task.source,
                task.symbol,
                task.timeframe,
            )
        except Exception as e:
            logger.warning(
                "Failed to queue quotes unsubscribe for task %s: %s",
                task_id,
                e,
            )

    def _load_pids(self) -> Dict[int, int]:
        """Load task_id → pid mapping from Redis."""
        try:
            raw = cast(Dict[str, str], self._get_redis().hgetall(SUPERVISOR_PIDS_KEY))
            return {int(k): int(v) for k, v in raw.items()}
        except Exception as e:
            logger.warning(f"Failed to load PIDs from Redis: {e}")
            return {}

    # ------------------------------------------------------------------
    # Supervisor error logging (per trading task)
    # ------------------------------------------------------------------

    def _write_supervisor_error(self, task_id: int, message: str, level: str = "error") -> None:
        """
        Persist a supervisor error for a trading task to Redis.

        Stored as a JSON list at key trading_tasks:supervisor_errors:{task_id}.
        Also publishes to global supervisor:messages channel for real-time frontend updates.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": level,
            "category": "supervisor",
            "message": message,
        }

        key = SUPERVISOR_ERRORS_KEY.format(task_id=task_id)
        try:
            client = self._get_redis()
            client.rpush(key, json.dumps(entry))
        except Exception as e:
            logger.warning(f"Failed to write supervisor error to Redis for task {task_id}: {e}")

        # Publish to global supervisor channel (for frontend real-time updates)
        try:
            global_entry = dict(entry, task_id=task_id)
            self._get_redis().publish(SUPERVISOR_GLOBAL_CHANNEL, json.dumps(global_entry))
        except Exception as e:
            logger.warning(f"Failed to publish supervisor error to global channel for task {task_id}: {e}")

        # Also notify per-task pub/sub channel (best-effort)
        try:
            task_list = self._get_task_list()
            task = task_list.load(task_id)
            if task is not None:
                task.message(f"[Supervisor] {message}", level=level)
        except Exception as e:
            logger.warning(f"Failed to send pub/sub message for task {task_id}: {e}")

    # ------------------------------------------------------------------
    # Task list access
    # ------------------------------------------------------------------

    def _get_task_list(self) -> TradingTaskList:
        if self._trading_task_list is None:
            self._trading_task_list = TradingTaskList(redis_params=self._params)
        return self._trading_task_list

    # ------------------------------------------------------------------
    # uvicorn (FastAPI) subprocess
    # ------------------------------------------------------------------

    def _start_api(self) -> None:
        """Start uvicorn as a subprocess."""
        python_executable = sys.executable
        cmd = [
            python_executable, "-m", "uvicorn",
            "app.main_fastapi:app",
            "--host", "0.0.0.0",
            "--port", "8202",
        ]
        logger.info(f"Starting uvicorn: {' '.join(cmd)}")
        self._api_process = subprocess.Popen(
            cmd,
            cwd=str(_backend_dir),
        )
        logger.info(f"uvicorn started (PID={self._api_process.pid})")

    def _ensure_api_alive(self) -> None:
        """Restart uvicorn if it has died."""
        if self._api_process is None:
            self._start_api()
            return

        ret = self._api_process.poll()
        if ret is not None:
            logger.warning(f"uvicorn exited (code={ret}), restarting...")
            self._start_api()

    def _stop_api(self) -> None:
        """Gracefully stop uvicorn subprocess."""
        if self._api_process is None:
            return
        ret = self._api_process.poll()
        if ret is None:
            logger.info(f"Sending SIGTERM to uvicorn (PID={self._api_process.pid})")
            self._api_process.terminate()
            try:
                self._api_process.wait(timeout=10)
                logger.info("uvicorn stopped")
            except subprocess.TimeoutExpired:
                logger.warning("uvicorn did not stop in time, killing...")
                self._api_process.kill()
                self._api_process.wait()
        self._api_process = None

    # ------------------------------------------------------------------
    # Trading process management
    # ------------------------------------------------------------------

    def _start_trading_process(self, task_id: int, crash_count: int = 0) -> ProcessInfo:
        """Spawn a new worker process for a trading task."""
        process = Process(target=worker_trading_task, args=(task_id,), daemon=False)
        process.start()
        pid = process.pid
        if pid is None:
            raise RuntimeError(f"Failed to start trading process for task {task_id}: PID is None")
        logger.info(f"Started trading process for task {task_id} (PID={pid}, crash_count={crash_count})")
        self._save_pid(task_id, pid)
        return ProcessInfo(
            process=process,
            start_time=time.monotonic(),
            crash_count=crash_count,
        )

    def _restore_tracked_processes(self) -> None:
        """
        On supervisor startup, check Redis for previously tracked PIDs.

        If a process with that PID is still alive, we can't adopt it (it's an
        unmanaged orphan), but we know it's running. We mark the task as
        "untracked but running" by NOT adding to _processes — next poll cycle
        will see isRunning=True + not tracked → will try to start a duplicate.

        To avoid duplicates: check if PID is alive. If yes, log a warning and
        skip starting a new process for that task_id until the old one dies.
        """
        stored = self._load_pids()
        for task_id, pid in stored.items():
            alive = _is_pid_alive(pid)
            if alive:
                logger.warning(
                    f"Task {task_id}: found orphan process PID={pid} from previous supervisor run. "
                    "Will not start a new process until it exits."
                )
                # Create a "sentinel" ProcessInfo with a sentinel Process object
                # We create a Process that wraps the existing PID so we can poll it
                orphan_process = _adopt_process(pid)
                if orphan_process is not None:
                    self._processes[task_id] = ProcessInfo(
                        process=orphan_process,
                        start_time=time.monotonic(),
                        crash_count=0,
                    )
            else:
                logger.info(f"Task {task_id}: orphan PID={pid} is no longer running, clearing")
                self._remove_pid(task_id)

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """
        Single poll cycle: process all trading tasks.
        """
        try:
            task_list = self._get_task_list()
            tasks = task_list.list()
        except Exception as e:
            logger.error(f"Failed to list trading tasks: {e}")
            return

        now = time.monotonic()
        active_task_ids = {t.id for t in tasks}

        # Clean up tracking for deleted tasks
        for task_id in list(self._processes.keys()):
            if task_id not in active_task_ids:
                info = self._processes.pop(task_id)
                _kill_process(info.process, task_id, "task deleted")
                self._remove_pid(task_id)

        for task in tasks:
            task_id = task.id
            is_running_flag = task.isRunning

            info = self._processes.get(task_id)
            proc_alive = info is not None and info.process.is_alive()

            # ----------------------------------------------------------------
            # Case 1: Should be running, not tracked → start
            # ----------------------------------------------------------------
            if is_running_flag and info is None:
                self._processes[task_id] = self._start_trading_process(task_id)
                continue

            # ----------------------------------------------------------------
            # Case 2: Should be running, tracked, alive → all good
            # ----------------------------------------------------------------
            if is_running_flag and proc_alive:
                continue

            # ----------------------------------------------------------------
            # Case 3: Should be running, tracked, DEAD → crash detected
            # ----------------------------------------------------------------
            if is_running_flag and info is not None and not proc_alive:
                elapsed = now - info.start_time
                rapid = elapsed < SUPERVISOR_CRASH_INTERVAL

                if rapid:
                    new_crash_count = info.crash_count + 1
                else:
                    # Ran for a while — reset crash counter
                    new_crash_count = 1

                self._remove_pid(task_id)
                self._cleanup_quotes_subscription(task_id)

                if new_crash_count >= SUPERVISOR_MAX_RESTARTS:
                    # Too many rapid crashes — disable task
                    task_label = f"{task.name} (id={task_id})" if task.name else f"Task {task_id}"
                    msg = (
                        f"{task_label} crashed {new_crash_count} time(s) within "
                        f"{SUPERVISOR_CRASH_INTERVAL}s. Setting isRunning=False."
                    )
                    logger.error(msg)
                    self._write_supervisor_error(task_id, msg, level="error")

                    try:
                        t = task_list.load(task_id)
                        if t is not None:
                            t.isRunning = False
                            t.save()
                    except Exception as e:
                        logger.error(f"Failed to set isRunning=False for task {task_id}: {e}")

                    del self._processes[task_id]
                else:
                    # Restart
                    logger.warning(
                        f"Task {task_id} crashed (rapid={rapid}, crashes={new_crash_count}). "
                        "Restarting..."
                    )
                    self._processes[task_id] = self._start_trading_process(
                        task_id, crash_count=new_crash_count
                    )

                continue

            # ----------------------------------------------------------------
            # Case 4: Should be stopped, not tracked / already dead → nothing
            # ----------------------------------------------------------------
            if not is_running_flag and (info is None or not proc_alive):
                if info is not None:
                    del self._processes[task_id]
                    self._remove_pid(task_id)
                continue

            # ----------------------------------------------------------------
            # Case 5: Should be stopped, tracked, ALIVE → waiting for graceful stop
            # ----------------------------------------------------------------
            if not is_running_flag and info is not None and proc_alive:
                if info.stop_requested_at is None:
                    info.stop_requested_at = now
                    logger.info(
                        f"Task {task_id}: stop requested, waiting for graceful termination "
                        f"(timeout={SUPERVISOR_FORCE_KILL_TIMEOUT}s)"
                    )

                waited = now - info.stop_requested_at

                if waited >= SUPERVISOR_FORCE_KILL_TIMEOUT:
                    # SIGTERM first, then SIGKILL on next cycle if still alive
                    if info.sigterm_sent_at is None:
                        logger.warning(
                            f"Task {task_id}: process did not stop in {SUPERVISOR_FORCE_KILL_TIMEOUT}s, "
                            "sending SIGTERM"
                        )
                        _sigterm_process(info.process, task_id)
                        info.sigterm_sent_at = now
                    else:
                        # Already sent SIGTERM and still alive → SIGKILL
                        msg = (
                            f"Task {task_id}: process did not respond to SIGTERM, "
                            "force-killing with SIGKILL"
                        )
                        logger.error(msg)
                        self._write_supervisor_error(task_id, msg, level="error")
                        _kill_process(info.process, task_id, "force kill after timeout")
                        self._cleanup_quotes_subscription(task_id)
                        del self._processes[task_id]
                        self._remove_pid(task_id)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _handle_signal(self, signum, frame) -> None:
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self._running = False

    def _shutdown(self) -> None:
        """Stop all child processes and perform cleanup."""
        logger.info("Supervisor shutting down...")

        # Stop all trading processes
        for task_id, info in list(self._processes.items()):
            if info.process.is_alive():
                logger.info(f"Stopping trading process for task {task_id}...")
                _sigterm_process(info.process, task_id)
                info.process.join(timeout=10)
                if info.process.is_alive():
                    _kill_process(info.process, task_id, "shutdown")
            self._remove_pid(task_id)
        self._processes.clear()

        # Stop uvicorn
        self._stop_api()

        self._release_lock()
        logger.info("Supervisor shutdown complete")

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main supervisor loop."""
        setup_logging()
        logger.info("R2D2 Supervisor starting...")

        # Check Redis connection and acquire lock
        try:
            self._get_redis().ping()
        except Exception as e:
            logger.critical(f"Cannot connect to Redis: {e}")
            sys.exit(1)

        if not self._acquire_lock():
            sys.exit(1)

        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Restore previously tracked processes (from before a supervisor restart)
        self._restore_tracked_processes()

        # Start uvicorn
        self._start_api()

        logger.info(
            f"Supervisor running. Poll interval={SUPERVISOR_POLL_INTERVAL}s, "
            f"max_restarts={SUPERVISOR_MAX_RESTARTS}, "
            f"crash_interval={SUPERVISOR_CRASH_INTERVAL}s, "
            f"force_kill_timeout={SUPERVISOR_FORCE_KILL_TIMEOUT}s"
        )

        try:
            while self._running:
                self._renew_lock()
                self._ensure_api_alive()
                self._poll()
                time.sleep(SUPERVISOR_POLL_INTERVAL)
        finally:
            self._shutdown()


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _adopt_process(pid: int) -> Optional[Any]:
    """
    Create a lightweight proxy that lets us poll an existing PID.

    We use a sentinel Process object whose is_alive() delegates to os.kill.
    Returns None if the process no longer exists.
    """
    if not _is_pid_alive(pid):
        return None

    class OrphanProcess:
        """Minimal duck-type wrapper around an existing PID."""
        def __init__(self, pid: int):
            self.pid = pid

        def is_alive(self) -> bool:
            return _is_pid_alive(self.pid)

        def join(self, timeout=None):
            pass  # Cannot join a non-child process

    return OrphanProcess()  # type: ignore[return-value]


def _sigterm_process(process, task_id: int) -> None:
    """Send SIGTERM to a process, ignoring errors."""
    try:
        pid = process.pid
        if pid and _is_pid_alive(pid):
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to task {task_id} (PID={pid})")
    except Exception as e:
        logger.warning(f"Failed to send SIGTERM to task {task_id}: {e}")


def _kill_process(process, task_id: int, reason: str) -> None:
    """Send SIGKILL to a process, ignoring errors."""
    try:
        pid = process.pid
        if pid and _is_pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
            logger.warning(f"Sent SIGKILL to task {task_id} (PID={pid}), reason: {reason}")
    except Exception as e:
        logger.warning(f"Failed to send SIGKILL to task {task_id}: {e}")

    # For multiprocessing.Process — clean up zombie
    if hasattr(process, "join"):
        try:
            process.join(timeout=2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    supervisor = Supervisor()
    supervisor.run()
