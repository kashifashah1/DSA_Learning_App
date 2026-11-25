"""CodeEvaluator: runs a student's Python solution against test cases.

For EVERY test case the evaluator:
  1. writes the code to solution.py inside a new temporary folder,
  2. starts a SEPARATE Python process (same interpreter as the server) with that
     folder as working directory, the test input on standard input, and a time limit,
  3. kills the process if the time limit is over (status TLE),
  4. compares the trimmed output with the expected output.

An infinite loop, a crash or a huge output can therefore never hang or crash the
web application: everything happens in the separate process, which is killed on timeout.

IMPORTANT: this is NOT full isolation. Submitted code still runs with the rights of
the user who started the server. It is meant for trusted users only (see the README).
This class does not use the database.
"""

import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

from django.conf import settings

from .models import TestCaseResult

logger = logging.getLogger(__name__)

Status = TestCaseResult.Status  # PASSED / FAILED / TLE / ERROR (same words as the database)


@dataclass(frozen=True)
class TestRunResult:
    """What happened when one test case was run."""

    status: str  # Status.PASSED, FAILED (wrong output), TLE (timeout) or ERROR (crash)
    output: str  # what the program printed
    exec_time_ms: int  # how long the run took, in milliseconds
    error_message: str = ""  # the error text for ERROR, a short note for TLE


_warned_about_admin = False


def _running_as_admin():
    """True if the server runs as root (Linux/Mac) or as administrator (Windows)."""
    try:
        if os.name == "nt":
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _warn_once_if_admin():
    global _warned_about_admin
    if not _warned_about_admin and _running_as_admin():
        _warned_about_admin = True
        logger.warning(
            "The server is running as administrator/root, so submitted code would too. "
            "Run the server as a normal user."
        )


def _normal_newlines(text):
    """Windows and browsers use \\r\\n; compare everything with \\n."""
    return text.replace("\r\n", "\n")


class CodeEvaluator:
    def __init__(self, time_limit_sec=None):
        # None means: use CODE_TIME_LIMIT_SEC from settings (read at run time).
        self.time_limit_sec = time_limit_sec

    # ------------------------------------------------------------------ main API
    def evaluate(self, source_code, test_cases):
        """Run the code on ALL test cases (never stops early). One result per test case, same order.

        test_cases: any objects that have .input_data and .expected_output
        (for example problems.TestCase rows).
        """
        return [
            self.run_one(source_code, case.input_data, case.expected_output)
            for case in test_cases
        ]

    def run_one(self, source_code, input_data, expected_output=None):
        """Run the code once. Never raises: problems become an ERROR result.

        With expected_output the status is PASSED or FAILED (output compared after trimming).
        Without it there is nothing to compare, so a run that finishes without error is PASSED.
        """
        _warn_once_if_admin()
        started = time.perf_counter()
        try:
            return self._run(source_code, input_data, expected_output)
        except Exception:
            # Our own problem (for example the process could not be started). Log it, keep going.
            logger.exception("CodeEvaluator could not run a submission")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return TestRunResult(
                Status.ERROR, "", elapsed_ms, "Internal error: the code could not be run. Please try again."
            )

    # ------------------------------------------------------------------- helpers
    @staticmethod
    def tests_passed(results):
        """How many test cases have status PASSED."""
        return sum(1 for result in results if result.status == Status.PASSED)

    @staticmethod
    def is_correct(results):
        """True only if there is at least one test case and ALL of them PASSED."""
        return len(results) > 0 and all(result.status == Status.PASSED for result in results)

    # ------------------------------------------------------------------ internals
    def _limit(self):
        return self.time_limit_sec if self.time_limit_sec is not None else settings.CODE_TIME_LIMIT_SEC

    def _run(self, source_code, input_data, expected_output):
        limit = self._limit()
        input_bytes = _normal_newlines(input_data).encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="dsa_run_", ignore_cleanup_errors=True) as folder:
            script_path = os.path.join(folder, "solution.py")
            with open(script_path, "w", encoding="utf-8", newline="\n") as script:
                script.write(source_code)
            out_path = os.path.join(folder, "stdout.txt")
            err_path = os.path.join(folder, "stderr.txt")

            timed_out = False
            started = time.perf_counter()
            # Output goes to files (not pipes), so a program that prints forever cannot fill our memory.
            with open(out_path, "wb") as out_file, open(err_path, "wb") as err_file:
                process = subprocess.Popen(
                    # -I: ignore environment variables and user site folders, -X utf8: same text encoding everywhere
                    [sys.executable, "-I", "-X", "utf8", script_path],
                    stdin=subprocess.PIPE,
                    stdout=out_file,
                    stderr=err_file,
                    cwd=folder,
                    env=self._clean_environment(folder),
                    # Linux/Mac: own process group, so child processes of the code can be killed too.
                    start_new_session=(os.name == "posix"),
                )
                try:
                    process.communicate(input=input_bytes, timeout=limit)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill(process)
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            stdout = _normal_newlines(self._read_start(out_path))
            stderr = _normal_newlines(self._read_start(err_path))
            return_code = process.returncode

        if timed_out:
            return TestRunResult(Status.TLE, stdout, elapsed_ms, f"Time limit exceeded (limit: {limit:g} s).")

        if return_code != 0:
            message = self._clean_error(stderr, folder) or f"The program stopped with exit code {return_code}."
            return TestRunResult(Status.ERROR, stdout, elapsed_ms, message)

        if expected_output is None:
            return TestRunResult(Status.PASSED, stdout, elapsed_ms)
        same = stdout.strip() == _normal_newlines(expected_output).strip()
        return TestRunResult(Status.PASSED if same else Status.FAILED, stdout, elapsed_ms)

    @staticmethod
    def _clean_environment(folder):
        """Give the code almost nothing from our environment (it holds secrets such as DB_PASSWORD)."""
        keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "LANG", "LC_ALL")  # Windows needs SYSTEMROOT to start Python
        env = {name: os.environ[name] for name in keep if name in os.environ}
        env["TMPDIR"] = env["TEMP"] = env["TMP"] = folder
        return env

    @staticmethod
    def _kill(process):
        """Stop the process (and, on Linux/Mac, everything it started)."""
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logger.error("A submitted program could not be stopped (pid %s)", process.pid)

    @staticmethod
    def _read_start(path):
        """Read at most MAX_OUTPUT_BYTES from a file, as text."""
        with open(path, "rb") as file:
            data = file.read(settings.MAX_OUTPUT_BYTES)
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _clean_error(stderr, folder):
        """Error text for the student: no temp folder path, and only the end if it is very long."""
        text = stderr.replace(folder + os.sep, "").replace(folder, "").strip()
        return text[-settings.MAX_ERROR_CHARS:]
