# Administrator guide

## Create the administrator account
`python manage.py createsuperuser` (asks for e-mail, name and password). Only staff users can open `/admin/`;
the **Admin** link appears in the menu for them.

## Add topics, subtopics and problems
1. Log in and open **Admin** (`/admin/`).
2. **Topics**: add a name and an *order* (the roadmap follows this order). Add the topics first.
3. **Subtopics**: choose the topic, give a name and an order.
4. **Problems**: title, statement, difficulty (Easy / Medium / Hard) and subtopic. No code change is needed.
5. In the same screen add the **test cases** (inline): the input, the expected output, and tick *is sample* for the ones
   students may see (usually 1 or 2). Add several hidden test cases too, including edge cases.
   A problem without test cases cannot be submitted.
6. Problems must read from standard input and print to standard output.
7. Changing a problem's difficulty later does not change old attempts (they keep the difficulty at the time).

Quick start with sample data: `python manage.py seed_problems` (safe to run twice).

## Attempts and students
Attempts are read-only in the admin: they cannot be edited or deleted (this keeps the analysis honest).
Deleting a student removes the student's attempts and scores too.

## Train the model
1. Wait until students have made at least 100 attempts in total.
2. Run `python manage.py train_model`. It trains Logistic Regression and a Decision Tree, compares them on attempts
   it did not see, keeps the better one and saves `ml_models/success_model.joblib`. Run it again from time to time.
3. Below 100 attempts, or without a model file, the system uses its rules only. Nobody sees an error.
4. Only load model files you trained yourself.
5. Development only: `python manage.py generate_demo_attempts` makes FAKE students (e-mail `...@demo.invalid`) so training
   can be tried. Remove them with `python manage.py generate_demo_attempts --clear`. Never present fake data as real.

## Settings (thresholds and weights)
All numbers (minimum attempts, recent window, revision days, target success probability, mastery weights, level ranges,
time limit) are in the **RuleConfig** section of `dsa_learning/settings.py`. Restart the server after changing them.
Stored topic scores are refreshed after the next attempt, or all at once with `python manage.py rebuild_performance`.

## Backup and logs
- Backup: `pg_dump -U postgres -h localhost -F c -f dsa_learning_backup.dump dsa_learning`
- Errors are written to `logs/app.log`.
- Run the server as a normal user, never as administrator or root. Trusted users only: submitted code is not sandboxed.
