"""SuccessPredictor: estimates the chance that a student solves a problem.

Training happens ONLY through `python manage.py train_model`, never inside a web request.
Two models are trained (Logistic Regression and a small Decision Tree), compared on a
held-back part of the data (accuracy and F1), and the better one is saved with Joblib.

The recommendation engine uses the model only if `is_available()` says yes: the model file
loads AND there are enough stored attempts (MIN_ATTEMPTS_FOR_MODEL). Otherwise the rules are
used and the student never sees an error.

Only load model files that you trained yourself: a Joblib file can run code when it is loaded.
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from django.conf import settings
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from attempts.models import Attempt

from .services import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

LOGISTIC = "Logistic Regression"
TREE = "Decision Tree"

# Loaded models are remembered, so a web request does not read the file again every time.
# The key is the file path; the stored signature changes when `train_model` writes a new file.
_MODEL_CACHE = {}


class ModelTrainingError(Exception):
    """The data cannot be used to train a model. The message explains why."""


class ModelUnavailableError(Exception):
    """There is no usable model file."""


@dataclass(frozen=True)
class ModelScore:
    name: str
    accuracy: float
    f1: float


@dataclass(frozen=True)
class TrainingReport:
    rows: int
    solved_rows: int
    train_rows: int
    test_rows: int
    scores: list
    chosen: str
    path: str


def choose_best(scores):
    """Higher F1 wins; then higher accuracy; if still equal, the simpler Logistic Regression."""
    return max(scores, key=lambda score: (score.f1, score.accuracy, score.name == LOGISTIC))


class SuccessPredictor:
    def __init__(self):
        self._payload = None

    # ------------------------------------------------------------------ training
    def train(self, df, notes=None):
        """Train both models on df (columns: FEATURE_COLUMNS and `solved`), keep and save the better one.
        notes: optional facts stored inside the model file (for example that it used demo data)."""
        self._check_training_data(df)
        features = df[FEATURE_COLUMNS].astype(float)
        labels = df["solved"].astype(int)
        x_train, x_test, y_train, y_test = train_test_split(
            features, labels,
            test_size=settings.MODEL_TEST_SIZE,
            random_state=settings.MODEL_RANDOM_STATE,
            stratify=labels,
        )

        scores, fitted = [], {}
        for name, pipeline in self._pipelines().items():
            pipeline.fit(x_train, y_train)
            predicted = pipeline.predict(x_test)
            scores.append(ModelScore(
                name=name,
                accuracy=float(accuracy_score(y_test, predicted)),
                f1=float(f1_score(y_test, predicted, zero_division=0)),
            ))
            fitted[name] = pipeline
        best = choose_best(scores)

        path = Path(settings.MODEL_PATH)
        self._save(path, {
            "pipeline": fitted[best.name],
            "model_name": best.name,
            "feature_columns": list(FEATURE_COLUMNS),
            "metrics": {score.name: {"accuracy": score.accuracy, "f1": score.f1} for score in scores},
            "rows": len(df),
            "notes": dict(notes or {}),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "sklearn_version": sklearn.__version__,
        })
        return TrainingReport(
            rows=len(df), solved_rows=int(labels.sum()), train_rows=len(x_train), test_rows=len(x_test),
            scores=scores, chosen=best.name, path=str(path),
        )

    @staticmethod
    def _pipelines():
        """Both models are Scikit-learn Pipelines: fill gaps, (scale,) then the model itself."""
        fill = lambda: SimpleImputer(strategy="median", keep_empty_features=True)
        return {
            LOGISTIC: Pipeline([
                ("fill", fill()),
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000, random_state=settings.MODEL_RANDOM_STATE)),
            ]),
            TREE: Pipeline([
                ("fill", fill()),
                ("model", DecisionTreeClassifier(
                    max_depth=settings.TREE_MAX_DEPTH,
                    min_samples_leaf=settings.TREE_MIN_SAMPLES_LEAF,
                    random_state=settings.MODEL_RANDOM_STATE,
                )),
            ]),
        }

    @staticmethod
    def _check_training_data(df):
        missing = [c for c in [*FEATURE_COLUMNS, "solved"] if c not in df.columns]
        if missing:
            raise ModelTrainingError(f"The training data has no column(s): {', '.join(missing)}.")
        solved = int((df["solved"] == 1).sum())
        not_solved = int((df["solved"] == 0).sum())
        needed = settings.MODEL_MIN_CLASS_ROWS
        if solved < needed or not_solved < needed:
            raise ModelTrainingError(
                f"The model needs both solved and not-solved attempts (at least {needed} of each). "
                f"Found {solved} solved and {not_solved} not solved."
            )

    @staticmethod
    def _save(path, payload):
        """Write to a temporary file first, so a running server never reads a half-written model."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        os.close(handle)
        try:
            joblib.dump(payload, temp_name)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)
        _MODEL_CACHE.pop(str(path), None)

    # ------------------------------------------------------------------ using the model
    def load(self):
        """Load the model file. True if a usable model is loaded; False otherwise (never raises)."""
        path = Path(settings.MODEL_PATH)
        self._payload = None
        try:
            stat = path.stat()
        except OSError:
            return False  # no model file yet: normal in the beginning

        signature = (stat.st_mtime_ns, stat.st_size)
        cached = _MODEL_CACHE.get(str(path))
        if cached and cached[0] == signature:
            self._payload = cached[1]
            return self._payload is not None

        payload = None
        try:
            loaded = joblib.load(path)
            if self._is_valid(loaded):
                payload = loaded
            else:
                logger.warning("Model file %s does not have the expected content: using rules instead", path)
        except Exception:
            logger.warning("Model file %s could not be loaded: using rules instead", path, exc_info=True)
        _MODEL_CACHE[str(path)] = (signature, payload)  # also remember a bad file, to avoid repeating this
        self._payload = payload
        return payload is not None

    @staticmethod
    def _is_valid(payload):
        return (
            isinstance(payload, dict)
            and payload.get("feature_columns") == FEATURE_COLUMNS
            and hasattr(payload.get("pipeline"), "predict_proba")
        )

    def is_available(self):
        """True only if the model file loads AND the database holds at least MIN_ATTEMPTS_FOR_MODEL attempts."""
        try:
            if not self.load():
                return False
            return Attempt.objects.count() >= settings.MIN_ATTEMPTS_FOR_MODEL
        except Exception:
            logger.exception("Could not check whether the model is available")
            return False

    def predict_probability(self, features):
        """Chance (0 to 1) that the student solves the problem. features: dict with FEATURE_COLUMNS.
        Missing or NaN values are filled in by the model."""
        if self._payload is None and not self.load():
            raise ModelUnavailableError("There is no usable model file.")
        row = {name: np.nan if features.get(name) is None else float(features[name]) for name in FEATURE_COLUMNS}
        pipeline = self._payload["pipeline"]
        probabilities = pipeline.predict_proba(pd.DataFrame([row], columns=FEATURE_COLUMNS))[0]
        solved_index = list(pipeline.classes_).index(1)
        return float(min(1.0, max(0.0, probabilities[solved_index])))

    def info(self):
        """What is known about the loaded model (for reports), or None."""
        if self._payload is None and not self.load():
            return None
        return {key: self._payload.get(key) for key in ("model_name", "metrics", "rows", "trained_at", "notes")}
