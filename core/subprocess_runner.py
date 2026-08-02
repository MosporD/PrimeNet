"""
Stream child process output to logs without buffering entire stdout/stderr in RAM.

The sync scheduler launches long-running pipeline scripts; ``capture_output=True``
keeps the full transcript in the parent process and was a major source of scheduler
RSS growth on production hosts.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SubprocessResult:
    returncode: int
    stdout_tail: str
    stderr_tail: str

    @property
    def stdout(self) -> str:
        return self.stdout_tail

    @property
    def stderr(self) -> str:
        return self.stderr_tail


def _tail_text(lines: Iterable[str]) -> str:
    return '\n'.join(lines)


def _pump_stream(stream, tail: deque[str], log_fn) -> None:
    try:
        for raw in stream:
            line = raw.rstrip('\n\r')
            tail.append(line)
            if line and log_fn:
                log_fn(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_logged_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    logger: logging.Logger | None = None,
    tail_lines: int = 120,
    log_stdout: bool = True,
    log_stderr: bool = True,
) -> SubprocessResult:
    """
    Run ``cmd``, stream lines to ``logger``, retain only the last ``tail_lines``
    from each stream for failure summaries.
    """
    log = logger or logging.getLogger(__name__)
    stdout_tail: deque[str] = deque(maxlen=max(10, int(tail_lines)))
    stderr_tail: deque[str] = deque(maxlen=max(10, int(tail_lines)))

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    threads: list[threading.Thread] = []
    if proc.stdout is not None:
        out_fn = (lambda line: log.info('%s', line)) if log_stdout else None
        threads.append(
            threading.Thread(
                target=_pump_stream,
                args=(proc.stdout, stdout_tail, out_fn),
                daemon=True,
            )
        )
    if proc.stderr is not None:
        err_fn = (lambda line: log.warning('%s', line)) if log_stderr else None
        threads.append(
            threading.Thread(
                target=_pump_stream,
                args=(proc.stderr, stderr_tail, err_fn),
                daemon=True,
            )
        )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    returncode = proc.wait()
    return SubprocessResult(
        returncode=int(returncode),
        stdout_tail=_tail_text(stdout_tail),
        stderr_tail=_tail_text(stderr_tail),
    )
