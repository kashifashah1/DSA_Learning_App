"""Unit tests for CodeEvaluator (Step 5).

These tests use SimpleTestCase on purpose: the evaluator must not touch the database.
"""

import os
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from problems.models import TestCase as ProblemTestCase

from . import evaluator as evaluator_module
from .evaluator import CodeEvaluator, Status, TestRunResult


def case(input_data, expected_output):
    return SimpleNamespace(input_data=input_data, expected_output=expected_output)


def process_exists(pid):
    """True if the process is still running. A dead process that nobody has cleaned up yet
    (a "zombie") does not count: it can no longer run anything."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/status") as status:  # Linux only
            for line in status:
                if line.startswith("State:") and "Z" in line.split()[1]:
                    return False
    except OSError:
        pass
    return True


SUM_CODE = "n = int(input())\nprint(sum(map(int, input().split())))\n"


class NormalRunTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = CodeEvaluator(time_limit_sec=2)

    def test_correct_code_passes(self):
        result = self.evaluator.run_one(SUM_CODE, "3\n1 2 3", "6")
        self.assertEqual(result.status, Status.PASSED)
        self.assertEqual(result.output, "6\n")
        self.assertEqual(result.error_message, "")
        self.assertIsInstance(result.exec_time_ms, int)
        self.assertGreaterEqual(result.exec_time_ms, 0)

    def test_wrong_output_fails(self):
        result = self.evaluator.run_one(SUM_CODE, "3\n1 2 3", "7")
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.output, "6\n")  # what the program really printed
        self.assertEqual(result.error_message, "")

    def test_empty_output_fails_when_something_is_expected(self):
        result = self.evaluator.run_one("pass\n", "", "5")
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.output, "")

    def test_empty_output_passes_when_nothing_is_expected(self):
        self.assertEqual(self.evaluator.run_one("pass\n", "", "").status, Status.PASSED)

    def test_output_is_compared_after_trimming(self):
        code = 'print("  YES  ")\nprint()\n'
        self.assertEqual(self.evaluator.run_one(code, "", "YES").status, Status.PASSED)
        self.assertEqual(self.evaluator.run_one("print('YES')", "", "\n YES \n\n").status, Status.PASSED)

    def test_spaces_inside_the_output_still_matter(self):
        self.assertEqual(self.evaluator.run_one("print('1  2')", "", "1 2").status, Status.FAILED)

    def test_comparison_is_case_sensitive(self):
        self.assertEqual(self.evaluator.run_one("print('yes')", "", "YES").status, Status.FAILED)

    def test_windows_line_endings_are_fine(self):
        # The admin text boxes of a browser send \r\n.
        result = self.evaluator.run_one("print(1)\nprint(2)", "", "1\r\n2\r\n")
        self.assertEqual(result.status, Status.PASSED)
        result = self.evaluator.run_one(SUM_CODE, "3\r\n1 2 3\r\n", "6")
        self.assertEqual(result.status, Status.PASSED)

    def test_code_can_read_all_input_at_once(self):
        code = "import sys\ndata = sys.stdin.read().split()\nprint(len(data))\n"
        self.assertEqual(self.evaluator.run_one(code, "a b\nc", "3").status, Status.PASSED)

    def test_non_english_text_works(self):
        result = self.evaluator.run_one('print("héllo ✓")', "", "héllo ✓")
        self.assertEqual(result.status, Status.PASSED)

    def test_large_input_works(self):
        numbers = " ".join(["7"] * 200_000)
        code = "input()\nprint(sum(map(int, input().split())))\n"
        result = self.evaluator.run_one(code, f"200000\n{numbers}", "1400000")
        self.assertEqual(result.status, Status.PASSED)

    def test_program_that_ignores_big_input_does_not_break_us(self):
        result = self.evaluator.run_one("print(1)", "x" * 5_000_000, "1")
        self.assertEqual(result.status, Status.PASSED)

    def test_without_expected_output_a_clean_run_counts_as_passed(self):
        result = self.evaluator.run_one("print('hi')", "")
        self.assertEqual(result.status, Status.PASSED)
        self.assertEqual(result.output, "hi\n")


class ErrorTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = CodeEvaluator(time_limit_sec=2)

    def test_syntax_error_gives_error_with_message(self):
        result = self.evaluator.run_one("print('oops'\n", "", "oops")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("SyntaxError", result.error_message)
        self.assertIn("solution.py", result.error_message)

    def test_runtime_exception_gives_error_with_message(self):
        result = self.evaluator.run_one("x = 1\nprint(x / 0)\n", "", "1")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("ZeroDivisionError", result.error_message)
        self.assertIn("division by zero", result.error_message)
        self.assertIn("line 2", result.error_message)

    def test_error_after_some_output_keeps_that_output(self):
        result = self.evaluator.run_one("print('first')\nraise ValueError('bad')\n", "", "first")
        self.assertEqual(result.status, Status.ERROR)  # a crash is an error even if the output looks right
        self.assertEqual(result.output, "first\n")
        self.assertIn("ValueError: bad", result.error_message)

    def test_missing_import_is_an_error(self):
        result = self.evaluator.run_one("import no_such_module_xyz\n", "", "")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("ModuleNotFoundError", result.error_message)

    def test_exit_with_error_code_is_an_error(self):
        result = self.evaluator.run_one("import sys\nsys.exit(3)\n", "", "")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("exit code 3", result.error_message)

    def test_exit_with_code_zero_is_fine(self):
        result = self.evaluator.run_one("import sys\nprint('ok')\nsys.exit(0)\n", "", "ok")
        self.assertEqual(result.status, Status.PASSED)

    def test_error_message_does_not_show_our_temp_folder(self):
        result = self.evaluator.run_one("1/0", "", "")
        self.assertNotIn("dsa_run_", result.error_message)

    def test_very_long_error_message_is_cut_to_its_end(self):
        code = "raise ValueError('x' * 10000 + 'THE-END')"
        result = self.evaluator.run_one(code, "", "")
        self.assertLessEqual(len(result.error_message), settings.MAX_ERROR_CHARS)
        self.assertIn("THE-END", result.error_message)

    def test_null_bytes_in_the_code_are_an_error_not_a_crash(self):
        result = self.evaluator.run_one("print(1)\x00", "", "1")
        self.assertEqual(result.status, Status.ERROR)

    def test_empty_code_gives_failed_not_a_crash(self):
        self.assertEqual(self.evaluator.run_one("", "", "5").status, Status.FAILED)


class TimeLimitTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = CodeEvaluator(time_limit_sec=1)

    def test_infinite_loop_is_tle_and_returns_on_time(self):
        started = time.perf_counter()
        result = self.evaluator.run_one("while True:\n    pass\n", "", "x")
        took = time.perf_counter() - started
        self.assertEqual(result.status, Status.TLE)
        self.assertIn("Time limit exceeded", result.error_message)
        self.assertGreaterEqual(result.exec_time_ms, 1000)
        self.assertLess(took, 4)  # we did not hang

    def test_sleeping_forever_is_tle_too(self):
        result = self.evaluator.run_one("import time\ntime.sleep(60)\n", "", "")
        self.assertEqual(result.status, Status.TLE)

    def test_waiting_for_input_that_never_comes_is_tle(self):
        # input() is asked twice, but only one line is given: the program must not hang us.
        result = self.evaluator.run_one("input()\ninput()\n", "one line", "")
        self.assertIn(result.status, (Status.ERROR, Status.TLE))  # EOFError (ERROR) at once, never a hang

    def test_infinite_printing_is_stopped_and_output_is_capped(self):
        result = self.evaluator.run_one("while True:\n    print('x' * 100)\n", "", "")
        self.assertEqual(result.status, Status.TLE)
        self.assertLessEqual(len(result.output), settings.MAX_OUTPUT_BYTES)

    @unittest.skipUnless(os.name == "posix", "needs Linux or Mac")
    def test_killed_process_is_really_gone(self):
        code = "import os\nprint(os.getpid(), flush=True)\nwhile True:\n    pass\n"
        result = self.evaluator.run_one(code, "", "")
        self.assertEqual(result.status, Status.TLE)
        self.assertFalse(process_exists(int(result.output.split()[0])))

    @unittest.skipUnless(os.name == "posix", "needs Linux or Mac")
    def test_processes_started_by_the_code_are_killed_too(self):
        code = (
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "while True:\n    pass\n"
        )
        started = time.perf_counter()
        result = self.evaluator.run_one(code, "", "")
        self.assertEqual(result.status, Status.TLE)
        self.assertLess(time.perf_counter() - started, 4)
        time.sleep(0.2)
        self.assertFalse(process_exists(int(result.output.split()[0])))

    @override_settings(CODE_TIME_LIMIT_SEC=1)
    def test_time_limit_comes_from_settings(self):
        result = CodeEvaluator().run_one("while True: pass", "", "")
        self.assertEqual(result.status, Status.TLE)
        self.assertIn("limit: 1 s", result.error_message)

    def test_own_time_limit_beats_settings(self):
        with override_settings(CODE_TIME_LIMIT_SEC=60):
            result = CodeEvaluator(time_limit_sec=1).run_one("while True: pass", "", "")
        self.assertEqual(result.status, Status.TLE)

    def test_default_limit_is_five_seconds(self):
        self.assertEqual(settings.CODE_TIME_LIMIT_SEC, 5)


class EvaluateAllTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = CodeEvaluator(time_limit_sec=1)

    def test_one_result_per_test_case_in_order(self):
        cases = [case("3\n1 2 3", "6"), case("2\n5 5", "11"), case("1\n9", "9")]
        results = self.evaluator.evaluate(SUM_CODE, cases)
        self.assertEqual([r.status for r in results], [Status.PASSED, Status.FAILED, Status.PASSED])
        self.assertTrue(all(isinstance(r, TestRunResult) for r in results))

    def test_all_test_cases_run_even_after_a_timeout_and_a_crash(self):
        code = (
            "import sys\n"
            "word = sys.stdin.read().strip()\n"
            "if word == 'loop':\n    while True: pass\n"
            "if word == 'crash':\n    raise RuntimeError('boom')\n"
            "print(word)\n"
        )
        cases = [case("ok", "ok"), case("loop", "loop"), case("crash", "crash"), case("last", "last")]
        results = self.evaluator.evaluate(code, cases)
        self.assertEqual(
            [r.status for r in results], [Status.PASSED, Status.TLE, Status.ERROR, Status.PASSED]
        )

    def test_no_test_cases_gives_empty_list(self):
        self.assertEqual(self.evaluator.evaluate(SUM_CODE, []), [])

    def test_works_with_problem_test_case_objects(self):
        cases = [ProblemTestCase(input_data="2\n4 6", expected_output="10")]  # not saved: no database needed
        self.assertEqual(self.evaluator.evaluate(SUM_CODE, cases)[0].status, Status.PASSED)

    def test_each_test_case_runs_in_its_own_process_and_folder(self):
        code = (
            "import os\n"
            "print(os.path.exists('marker.txt'))\n"
            "open('marker.txt', 'w').write('x')\n"
            "x = globals().get('state', 0)\nstate = x + 1\nprint(state)\n"
        )
        results = self.evaluator.evaluate(code, [case("", "False\n1"), case("", "False\n1")])
        self.assertEqual([r.status for r in results], [Status.PASSED, Status.PASSED])


class IsolationBasicsTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = CodeEvaluator(time_limit_sec=2)

    def test_runs_in_a_temporary_folder_that_is_removed_afterwards(self):
        result = self.evaluator.run_one("import os\nprint(os.getcwd())\n", "")
        folder = result.output.strip()
        self.assertIn("dsa_run_", os.path.basename(folder))
        self.assertNotEqual(os.path.realpath(folder), os.path.realpath(settings.BASE_DIR))
        self.assertFalse(os.path.exists(folder))

    def test_runs_in_a_separate_process_with_the_same_python(self):
        code = "import os, sys\nprint(os.getpid())\nprint(sys.executable)\n"
        pid, executable = self.evaluator.run_one(code, "").output.split("\n")[:2]
        self.assertNotEqual(int(pid), os.getpid())
        self.assertEqual(executable, sys.executable)

    def test_secrets_from_our_environment_are_not_visible_to_the_code(self):
        code = "import os\nprint(os.environ.get('DB_PASSWORD'), os.environ.get('SECRET_KEY'))\n"
        with mock.patch.dict(os.environ, {"DB_PASSWORD": "secret123", "SECRET_KEY": "abc"}):
            result = self.evaluator.run_one(code, "", "None None")
        self.assertEqual(result.status, Status.PASSED)


class NeverCrashTests(SimpleTestCase):
    def test_internal_problem_becomes_an_error_result_and_is_logged(self):
        with mock.patch.object(subprocess, "Popen", side_effect=OSError("cannot start")):
            with self.assertLogs("attempts.evaluator", level="ERROR"):
                result = CodeEvaluator().run_one("print(1)", "", "1")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("Internal error", result.error_message)

    def test_evaluate_continues_after_an_internal_problem(self):
        real_popen = subprocess.Popen
        calls = {"count": 0}

        def sometimes_broken(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("first one fails")
            return real_popen(*args, **kwargs)

        with mock.patch.object(subprocess, "Popen", side_effect=sometimes_broken):
            with self.assertLogs("attempts.evaluator", level="ERROR"):
                results = CodeEvaluator(time_limit_sec=2).evaluate("print(1)", [case("", "1"), case("", "1")])
        self.assertEqual([r.status for r in results], [Status.ERROR, Status.PASSED])


class HelperTests(SimpleTestCase):
    def result(self, status):
        return TestRunResult(status, "", 1)

    def test_tests_passed_counts_only_passed(self):
        results = [self.result(s) for s in (Status.PASSED, Status.FAILED, Status.PASSED, Status.TLE, Status.ERROR)]
        self.assertEqual(CodeEvaluator.tests_passed(results), 2)

    def test_is_correct_needs_every_test_case_to_pass(self):
        self.assertTrue(CodeEvaluator.is_correct([self.result(Status.PASSED)] * 3))
        for bad in (Status.FAILED, Status.TLE, Status.ERROR):
            with self.subTest(bad=bad):
                self.assertFalse(CodeEvaluator.is_correct([self.result(Status.PASSED), self.result(bad)]))

    def test_no_test_cases_is_never_correct(self):
        self.assertFalse(CodeEvaluator.is_correct([]))
        self.assertEqual(CodeEvaluator.tests_passed([]), 0)

    def test_helpers_work_on_real_results(self):
        results = CodeEvaluator(time_limit_sec=2).evaluate(SUM_CODE, [case("1\n4", "4"), case("1\n4", "5")])
        self.assertEqual(CodeEvaluator.tests_passed(results), 1)
        self.assertFalse(CodeEvaluator.is_correct(results))


class AdminWarningTests(SimpleTestCase):
    def setUp(self):
        evaluator_module._warned_about_admin = False
        self.addCleanup(setattr, evaluator_module, "_warned_about_admin", False)

    def test_warns_once_when_running_as_admin(self):
        with mock.patch.object(evaluator_module, "_running_as_admin", return_value=True):
            with self.assertLogs("attempts.evaluator", level="WARNING") as logs:
                CodeEvaluator(time_limit_sec=2).run_one("print(1)", "")
                CodeEvaluator(time_limit_sec=2).run_one("print(1)", "")
        self.assertEqual(len(logs.records), 1)
        self.assertIn("normal user", logs.output[0])

    def test_no_warning_for_a_normal_user(self):
        with mock.patch.object(evaluator_module, "_running_as_admin", return_value=False):
            with self.assertNoLogs("attempts.evaluator", level="WARNING"):
                CodeEvaluator(time_limit_sec=2).run_one("print(1)", "")
