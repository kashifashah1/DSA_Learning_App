# Personalised DSA Learning System

A web-based platform for practising data structures and algorithms (DSA) and tracking learning progress. Students solve Python problems, review their performance, and receive personalized practice recommendations. The system combines configurable learning rules with an optional machine-learning model trained on recorded attempts.

> B.Tech Project-1 · Medicaps University · August–December 2026

## Features

- **Problem practice:** Browse and filter problems by topic, subtopic, and difficulty; submit Python solutions and see results for each test case.
- **Personal progress:** View a dashboard, topic roadmap, mastery levels, recent attempts, and analytics charts.
- **Adaptive recommendations:** Get a suggested next problem with an explanation. Recommendations use rules by default and can use a trained model when enough attempt data is available.
- **Student accounts:** Register and sign in with an email address, manage a profile, and reset a forgotten password.
- **Problem management:** Staff can manage topics, subtopics, problems, and test cases through Django Admin.

## Technology

| Area | Technologies |
|---|---|
| Backend | Python, Django, Django REST Framework |
| Database | PostgreSQL |
| Frontend | Django templates, Tailwind CSS, Chart.js |
| Analytics and ML | Pandas, NumPy, scikit-learn, Joblib |

Tailwind CSS and Chart.js are loaded from CDNs, so the browser needs an internet connection to display the styled pages and charts.

## Project team

| Member | Enrollment number |
|---|---|
| Kashifa Shah | EN23CS301497 |
| Khushi Gupta | EN23CS301514 |
| Khushi Mahajan | EN23CS301515 |

## Getting started

### Prerequisites

- Python 3
- PostgreSQL
- Git

Run the following commands from the directory containing `manage.py`.

### 1. Create a database

Start PostgreSQL and create an empty database:

```sql
CREATE DATABASE dsa_learning;
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies and configure the environment

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and update the database credentials and secret key.

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Do not commit `.env` or put production credentials in source control.

### 4. Set up and run the application

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_problems
python manage.py runserver
```

`seed_problems` is optional and can safely be run more than once. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) and create a student account. Staff can manage learning content at [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/).

## Useful commands

| Task | Command |
|---|---|
| Run the development server | `python manage.py runserver` |
| Run the test suite | `python manage.py test` |
| Load sample problems | `python manage.py seed_problems` |
| Train or refresh the success model | `python manage.py train_model` |
| Rebuild stored topic performance | `python manage.py rebuild_performance` |

The model-training command requires at least 100 recorded attempts. The application does not train a model during web requests; without an available model it uses rule-based recommendations.

