# Requirements traceability (REQ-1 to REQ-46)

The original REQ list is not part of the project files. The wording below is **rebuilt from the
prompt pack** (the "Covers REQ-..." line of every step and the audit list in Part C). If your
SRS words a REQ differently, change only the first two columns; the file and test columns stay valid.

How to check everything: `python manage.py test` (all tests), or one file, for example
`python manage.py test analytics.test_ml`.

| REQ | Requirement | Implemented in | Checked by (tests) |
|---|---|---|---|
| 1 | Registration with name, e-mail, password | `users/models.py`, `users/forms.py` (RegistrationForm), `users/views.py` | `users/tests.py` RegistrationTests |
| 2 | Registration rejects empty fields, bad e-mail, duplicate e-mail, weak password and says which | `users/forms.py` (clean methods, Django password validators) | `users/tests.py` RegistrationTests |
| 3 | Login by e-mail; ONE general error for a wrong combination; forgot password | `users/forms.py` (EmailLoginForm), `users/views.py`, `templates/users/login.html`, `users/email_backend.py` | `users/tests.py` LoginTests, `users/test_password_reset.py`, `web/test_end_to_end.py` test_forgot_password_journey |
| 4 | Logout; view and edit profile (name, e-mail) | `users/views.py`, `templates/users/profile.html` | `users/tests.py` LogoutTests, ProfileTests |
| 5 | Every page except login/registration needs login; admin is staff-only | `LoginRequiredMiddleware` in `settings.py`, `@login_not_required` only on public views | `users/tests.py` LoginRequiredTests, `web/test_hardening.py` AccessControlTests |
| 6 | Problem catalogue: Topic, Subtopic, Problem, TestCase | `problems/models.py` | `problems/tests.py` TopicTests, SubtopicTests, ProblemTests, TestCaseModelTests |
| 7 | Roadmap: topics and subtopics in order with the student's mastery level | `web/services.py` RoadmapService, `templates/web/roadmap.html` | `web/test_services.py` RoadmapServiceTests, `web/test_roadmap_levels.py` |
| 8 | Problem list with topic, subtopic and difficulty filters | `web/forms.py` ProblemFilterForm, `web/services.py` ProblemListService | `web/test_services.py` ProblemListFilterTests, `web/test_pages.py` ProblemListPageTests |
| 9 | Each problem marked not attempted / attempted / solved; message when nothing matches | `problems/models.py` is_attempted_by / is_solved_by, `ProblemListService`, `templates/web/problem_list.html` | `attempts/tests.py` ProblemStatusMethodTests, `web/test_services.py` ProblemStatusTests |
| 10 | Administrator adds, edits, deletes topics, problems and test cases | `problems/admin.py` (TestCase inline), `problems/management/commands/seed_problems.py` | `problems/tests.py` AdminTests, SeedCommandTests |
| 11 | Problem page: statement and sample input/output only | `web/views.py` problem_detail, `templates/web/problem_detail.html` | `web/test_problem_page.py` ProblemPageContentTests |
| 12 | Python code only, plain code area, Submit button | `templates/web/problem_detail.html`, `web/forms.py` | `web/test_problem_page.py` ProblemPageContentTests |
| 13 | Code runs once per test case in a separate process with a time limit | `attempts/evaluator.py` CodeEvaluator | `attempts/test_evaluator.py` NormalRunTests, TimeLimitTests, EvaluateAllTests |
| 14 | Each test case gives PASSED, FAILED, TLE or ERROR (with message) | `attempts/evaluator.py` TestRunResult | `attempts/test_evaluator.py` ErrorTests, TimeLimitTests |
| 15 | An attempt is correct only if ALL test cases pass; result shown per test case | `CodeEvaluator.is_correct`, `web/submission.py`, `templates/web/problem_detail.html` | `web/test_submission_service.py` CorrectOrIncorrectTests, `web/test_problem_page.py` ResultSectionTests |
| 16 | Empty submission is rejected with a message | `web/submission.py` SubmissionService._check_code | `web/test_submission_service.py` RejectedSubmissionTests, `web/test_problem_page.py` EmptySubmissionTests |
| 17 | A crash or an endless loop never stops the app | `attempts/evaluator.py` (timeout, kill, clean environment) | `attempts/test_evaluator.py` NeverCrashTests, `web/test_end_to_end.py` test_a_crashing_and_an_endless_solution_do_not_stop_the_app |
| 18 | Every attempt is stored with its fields (difficulty copy, tests passed, attempt number, time, ...) | `attempts/models.py`, `web/submission.py` | `attempts/tests.py` AttemptModelTests, `web/test_submission_service.py` SavingTests, AttemptNumberTests |
| 19 | Solving time is measured from opening the page to submitting | `web/submission.py` SolveTimer, `SubmissionService._seconds_between` | `web/test_submission_service.py` TimeTakenTests, SolveTimerTests, `web/test_problem_page.py` OpeningTimeTests |
| 20 | Attempts are insert-only: no edit, no delete | `attempts/models.py` (save/delete blocked), `attempts/admin.py` (read-only) | `attempts/test_insert_only.py` AttemptCannotBeChangedTests, AttemptAdminTests |
| 21 | A student sees only their own attempts | `attempts/models.py` for_student, `web/views.py` attempt_history | `attempts/test_insert_only.py` ForStudentHelperTests, `web/test_attempt_history.py`, `web/test_problem_page.py` OwnAttemptsOnlyTests |
| 22 | Accuracy, average time, average attempts, difficulty-wise accuracy | `analytics/services.py` PerformanceAnalyzer (`topic_stats`, `difficulty_accuracy`, `attempts_dataframe`), stored in `analytics/models.py` TopicPerformance | `analytics/tests.py` TopicStatsTests, `analytics/test_performance.py` UpdateTopicPerformanceTests, DerivedNumbersTests |
| 23 | Mastery score 0-100, weighted, same data gives the same score | `analytics/services.py` MasteryCalculator.mastery_score, weights in `settings.py` | `analytics/tests.py` MasteryTests, `analytics/test_performance.py` test_same_attempts_always_give_the_same_scores |
| 24 | Learning level Beginner / Intermediate / Advanced | `MasteryCalculator.learning_level`, LEVEL_RANGES | `analytics/tests.py` MasteryTests |
| 25 | Weak topics and strong topics (and overall skill) | `PerformanceAnalyzer.weak_topics`, `strong_topics`, `overall_skill`, `templates/web/dashboard.html` | `analytics/test_performance.py` WeakAndStrongTopicsTests, DerivedNumbersTests, `web/test_analytics.py` DashboardSkillTests |
| 26 | Recent attempts count more (recent accuracy over the last RECENT_WINDOW) | `PerformanceAnalyzer._stats`, MASTERY_WEIGHTS | `analytics/tests.py` RecentAndSubtopicTests, `analytics/test_performance.py` test_a_recent_decline_is_visible_in_the_stored_row |
| 27 | "Not enough data" below MIN_ATTEMPTS_PER_TOPIC | `MasteryCalculator` | `analytics/tests.py` MasteryTests, `analytics/test_performance.py` test_fewer_than_the_minimum_attempts_means_no_mastery |
| 28 | Scikit-learn success model on past attempts (features known before the attempt) | `analytics/services.py` build_training_data, `analytics/ml.py` SuccessPredictor | `analytics/test_training_data.py` FeaturesUseOnlyThePastTests, `analytics/test_ml.py` TrainingTests |
| 29 | Logistic Regression and Decision Tree compared (accuracy, F1); the better one is kept | `analytics/ml.py` train, choose_best | `analytics/test_ml.py` ChooseBestTests, TrainingTests |
| 30 | Model saved and loaded with Joblib from a path in settings | `analytics/ml.py` (`_save`, `load`), MODEL_PATH | `analytics/test_ml.py` LoadingAndAvailabilityTests |
| 31 | Model used only with at least MIN_ATTEMPTS_FOR_MODEL attempts | `SuccessPredictor.is_available`, `train_model` refusal | `analytics/test_ml.py` TrainingRefusalTests, LoadingAndAvailabilityTests, `analytics/test_commands.py` TrainModelCommandTests |
| 32 | Training only by `python manage.py train_model`, never in a web request | `analytics/management/commands/train_model.py` | `analytics/test_commands.py` TrainModelCommandTests, TrainingNeverHappensOnTheWebTests |
| 33 | Missing or broken model: silent fallback to the rules | `recommendations/engine.py` (`_model_ready`, `rank_with_model`) | `recommendations/test_hybrid.py` FallbackToRulesTests, `web/test_hardening.py` ReliabilityTests |
| 34 | Six recommendation types: EASIER, SAME, HARDER, RELATED, REVISION, NEXT_TOPIC | `recommendations/engine.py` RecommendationEngine, `recommendations/models.py` | `recommendations/tests.py` HarderTests, EasierTests, SameAndRelatedTests, RevisionTests, NextTopicTests; `recommendations/test_hybrid.py` ModelRankingTests |
| 35 | Difficulty adjustment from recent performance | `RecommendationEngine.candidates` (EASIER_MIN_FAILURES, HARDER_MIN_CORRECT) | `recommendations/tests.py` HarderTests, EasierTests |
| 36 | Revision when accuracy dropped or the topic was not practised for REVISION_AFTER_DAYS | `RecommendationEngine.needs_revision` | `recommendations/tests.py` NeedsRevisionTests, RevisionTests |
| 37 | A problem already solved is never recommended (except REVISION) | `RecommendationEngine.candidate_problems` | `recommendations/tests.py` NeverRecommendSolvedTests |
| 38 | New student starts with the easiest problem of the first topic | `RecommendationEngine._first_topic_choice` | `recommendations/tests.py` NewStudentTests |
| 39 | Every recommendation stores a plain-language reason and its source (RULE / MODEL_ASSISTED); the student may open any problem | `recommendations/models.py`, `templates/partials/recommendation_card.html` | `recommendations/tests.py` StorageTests, SuggestionOnlyTests, DeterminismTests; `recommendations/test_hybrid.py` CardShowsTheSourceTests |
| 40 | Recommendation is shown after each submission with a button to open it | `web/submission.py` make_recommendation, `templates/web/problem_detail.html` | `web/test_problem_page.py` RecommendationCardTests, `web/test_submission_service.py` HookTests |
| 41 | Dashboard / chart: accuracy trend over time | `PerformanceAnalyzer.accuracy_trend`, `web/api.py` (trend), `static/js/analytics.js` | `analytics/test_performance.py` test_accuracy_trend_groups_by_day_and_accumulates, `web/test_analytics.py` ChartEndpointTests |
| 42 | Topic-wise and difficulty-wise performance charts (Chart.js, data from DRF endpoints) | `web/api.py`, `web/services.py` ChartDataService, `templates/web/analytics.html` | `web/test_analytics.py` ChartEndpointTests, AnalyticsPageTests |
| 43 | Dashboard shows overall skill, strong topics, weak topics, recent attempts | `web/services.py` DashboardService, `templates/web/dashboard.html` | `web/test_analytics.py` DashboardSkillTests, `web/test_dashboard.py` |
| 44 | Dashboard shows the latest recommendation with its short reason and an open button | `templates/partials/recommendation_card.html` | `web/test_dashboard.py`, `web/test_end_to_end.py` |
| 45 | A student with no attempts sees a clear message instead of empty charts | `templates/web/analytics.html`, `templates/web/dashboard.html` | `web/test_analytics.py` AnalyticsPageTests, `web/test_dashboard.py` NewStudentTests |
| 46 | Dashboard and charts show only the logged-in student's own data | `web/api.py` (request.user only), `ChartDataService`, `DashboardService` | `web/test_analytics.py` ChartEndpointTests, `web/test_end_to_end.py` test_full_journey_of_two_students |

## Requirements that are not fully met

None of REQ-1 to REQ-46 is knowingly missing. Points to be honest about in the report:

- **REQ-5 / security:** submitted code is **not** sandboxed (README). The system is for trusted users only.
- **REQ-28 to 33:** the model can only be as good as the data. With the fake demo data it reaches about 70 % accuracy, which says
  nothing about real students. Retrain on real attempts (`train_model`) before drawing any conclusion.
- **Charts (REQ-41, 42):** Chart.js and Tailwind load from a CDN, so the browser needs internet. The data endpoints and
  the page are tested; the drawing itself was checked with a stubbed Chart object, not in a real browser.
- **Non-functional targets** were measured on 12 problems and 50 fake students (about 1,000 attempts): every page under 0.2 s,
  a recommendation about 0.02 s, a full submission about 0.2 s (targets 3 s, 2 s and 10 s). Measure again on your own machine.
