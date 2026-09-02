"""QProcess ライフサイクル管理 + ステップキュー"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import traceback
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import TextIO

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, QTimer, Signal, Slot

from core.app_job import APP_JOB_WORKFLOW, AppJob, run_app_job
from core.cancellation import AppJobCancelled
from core.colmap_cli import colmap_batch_qprocess_native_arguments
from gui.common.runner_types import StepCommand, StepCommandPhase, StepCommandQueue

_WORKFLOW_JOB_MODULE = "core.workflow_job_cli"


class _SignalWriter:
    def __init__(self, emit_line: Callable[[str], None]) -> None:
        self._emit_line = emit_line
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += str(text).replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._emit_line(line)
        return len(text)

    def flush(self) -> None:
        tail = self._buffer.strip()
        if tail:
            self._emit_line(tail)
        self._buffer = ""


class _InternalJobWorker(QObject):
    line_received = Signal(str)
    finished = Signal(int)

    def __init__(self, job: AppJob, cancel_event: Event) -> None:
        super().__init__()
        self._job = job
        self._cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        writer = _SignalWriter(self.line_received.emit)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                run_app_job(self._job, cancel_event=self._cancel_event)
            writer.flush()
        except AppJobCancelled as exc:
            writer.flush()
            message = str(exc).strip() or "Canceled."
            self.line_received.emit(message)
            self.finished.emit(1)
            return
        except Exception:
            writer.flush()
            for line in traceback.format_exc().splitlines():
                self.line_received.emit(line)
            self.finished.emit(1)
            return
        self.finished.emit(0)


def _external_command_for_app_job(job: AppJob) -> list[str] | None:
    if job.job_type == APP_JOB_WORKFLOW and job.job_path is not None:
        return [sys.executable, "-m", _WORKFLOW_JOB_MODULE, "--job", str(job.job_path)]
    return None


class ProcessRunner(QObject):
    """複数ステップの外部コマンドまたは内部AppJobを順番に実行する共通ランナー。

    シグナル:
        line_received(str)  -- stdout の1行
        phase_started(str)  -- フェーズ名
        phase_log_started(str, str)  -- フェーズ名, ログファイルパス
        phase_finished(str, int, bool)  -- フェーズ名, exit_code, was_canceled
        queue_finished(bool)  -- 全フェーズが成功したか
    """

    line_received = Signal(str)
    phase_started = Signal(str)
    phase_log_started = Signal(str, str)
    phase_finished = Signal(str, int, bool)
    queue_finished = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._current_phase = ""
        self._buffer = ""
        self._pending: list[StepCommandPhase] = []
        self._cancel_requested = False
        self._all_ok = True
        self._running = False
        self._log_dir: Path | None = None
        self._log_file: TextIO | None = None
        self._current_log_path: Path | None = None
        self._run_log_stamp = ""
        self._phase_index = 0
        self._queue_total = 0
        self._internal_thread: QThread | None = None
        self._internal_worker: _InternalJobWorker | None = None
        self._internal_cancel_event: Event | None = None
        self._internal_exit_code: int | None = None

    # -- public API --

    def is_running(self) -> bool:
        return self._running

    def is_internal_job_running(self) -> bool:
        return self._internal_thread is not None

    @property
    def current_phase(self) -> str:
        return self._current_phase

    @property
    def phase_index(self) -> int:
        return self._phase_index

    @property
    def queue_total(self) -> int:
        return self._queue_total

    def start_single(self, cmd: StepCommand, phase: str = "run", log_dir: str | Path | None = None) -> None:
        self.start_queue([(phase, cmd)], log_dir=log_dir)

    def start_queue(self, steps: StepCommandQueue, log_dir: str | Path | None = None) -> None:
        if self.is_running():
            return
        self._cancel_requested = False
        self._all_ok = True
        self._pending = list(steps)
        self._running = bool(self._pending)
        self._phase_index = 0
        self._queue_total = len(self._pending)
        self._run_log_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._log_dir = Path(log_dir) if log_dir is not None else None
        if self._log_dir is not None:
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.line_received.emit(f"[log] Could not create process log directory: {exc}")
                self._log_dir = None
        self._run_next()

    def cancel(self) -> None:
        if not self.is_running():
            return
        self._cancel_requested = True
        self._pending.clear()
        if self._proc is not None:
            self._terminate_gracefully(self._proc, self._current_phase)
        elif self._internal_thread is not None:
            if self._internal_cancel_event is not None:
                self._internal_cancel_event.set()
            self._emit_line(f"[{self._current_phase}] キャンセル中...")

    # -- internal --

    def _run_next(self) -> None:
        if not self._pending:
            self._running = False
            self.queue_finished.emit(self._all_ok)
            return

        phase, cmd = self._pending.pop(0)
        self._current_phase = phase
        self._buffer = ""
        self._phase_index += 1
        self._open_phase_log(phase)
        display_cmd = cmd.display_command() if isinstance(cmd, AppJob) else cmd
        self._emit_line("$ " + " ".join(display_cmd))
        if self._current_log_path is not None:
            self._emit_line(f"[{phase}] log: {self._current_log_path}")
        self.phase_started.emit(phase)

        if isinstance(cmd, AppJob):
            external_cmd = _external_command_for_app_job(cmd)
            if external_cmd is not None:
                self._run_process(external_cmd)
                return
            self._run_internal_job(cmd)
            return

        self._run_process(cmd)

    def _run_process(self, cmd: list[str]) -> None:
        proc = QProcess(self)
        proc.setProgram(cmd[0])
        native_arguments = colmap_batch_qprocess_native_arguments(cmd)
        if native_arguments is None:
            proc.setArguments(cmd[1:])
        else:
            proc.setNativeArguments(native_arguments)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.errorOccurred.connect(self._on_error)
        proc.finished.connect(self._on_finished)
        self._proc = proc
        proc.start()

    def _run_internal_job(self, job: AppJob) -> None:
        thread = QThread(self)
        cancel_event = Event()
        worker = _InternalJobWorker(job, cancel_event)
        worker.moveToThread(thread)
        worker.line_received.connect(self._emit_line)
        worker.finished.connect(self._on_internal_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_internal_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self._internal_thread = thread
        self._internal_worker = worker
        self._internal_cancel_event = cancel_event
        self._internal_exit_code = None
        thread.start()

    def _on_internal_finished(self, exit_code: int) -> None:
        self._internal_exit_code = exit_code
        self._internal_cancel_event = None

    def _on_internal_thread_finished(self) -> None:
        exit_code = self._internal_exit_code if self._internal_exit_code is not None else 1
        self._internal_thread = None
        self._internal_worker = None
        self._internal_cancel_event = None
        self._internal_exit_code = None
        self._finish_phase(exit_code)

    def _on_output(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        data = data.replace("\r", "\n")
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._emit_line(line)

    def _on_error(self, _error: QProcess.ProcessError) -> None:
        if self._proc is None:
            return
        self._emit_line(f"[{self._current_phase}] プロセスエラーが発生しました")

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        if self._buffer:
            tail = self._buffer.replace("\r", "\n").strip()
            for line in tail.splitlines():
                self._emit_line(line)
            self._buffer = ""

        self._proc = None
        self._finish_phase(exit_code)

    def _finish_phase(self, exit_code: int) -> None:
        phase = self._current_phase
        was_canceled = self._cancel_requested
        self._cancel_requested = False
        self._emit_line(f"[{phase}] exit_code={exit_code} canceled={int(was_canceled)}")
        self._close_phase_log()

        if was_canceled:
            self._running = False
            self._all_ok = False
            self._pending.clear()
            self.phase_finished.emit(phase, exit_code, True)
            self.queue_finished.emit(False)
        elif exit_code == 0:
            self.phase_finished.emit(phase, 0, False)
            self._run_next()
        else:
            self._running = False
            self._all_ok = False
            self._pending.clear()
            self.phase_finished.emit(phase, exit_code, False)
            self.queue_finished.emit(False)

    def _terminate_gracefully(self, proc: QProcess, phase: str, timeout_ms: int = 3000) -> None:
        if proc.state() == QProcess.NotRunning:
            return
        self._emit_line(f"[{phase}] キャンセル中...")
        proc.terminate()
        QTimer.singleShot(timeout_ms, lambda p=proc, ph=phase: self._force_kill(p, ph))

    def _force_kill(self, proc: QProcess, phase: str) -> None:
        if proc.state() == QProcess.NotRunning:
            return
        self._emit_line(f"[{phase}] タイムアウト; プロセスを強制終了")
        self._kill_process_tree(proc)
        proc.kill()

    def _kill_process_tree(self, proc: QProcess) -> None:
        if os.name != "nt":
            return
        pid = int(proc.processId())
        if pid <= 0:
            return
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 5,
        }
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], **kwargs)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _open_phase_log(self, phase: str) -> None:
        self._close_phase_log()
        self._current_log_path = None
        if self._log_dir is None:
            return
        safe_phase = re.sub(r"[^A-Za-z0-9_.-]+", "_", phase).strip("._") or "phase"
        path = self._log_dir / f"{self._run_log_stamp}_{self._phase_index:02d}_{safe_phase}.log"
        try:
            self._log_file = path.open("w", encoding="utf-8", newline="\n")
        except OSError as exc:
            self.line_received.emit(f"[log] Could not open process log file: {exc}")
            self._log_file = None
            return
        self._current_log_path = path
        self.phase_log_started.emit(phase, str(path))

    def _close_phase_log(self) -> None:
        if self._log_file is None:
            return
        self._log_file.close()
        self._log_file = None

    def _emit_line(self, line: str) -> None:
        if self._log_file is not None:
            self._log_file.write(line + "\n")
            self._log_file.flush()
        self.line_received.emit(line)
