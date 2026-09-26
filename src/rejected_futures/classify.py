"""The local step: a 33M-parameter embedding model on the CPU and a logistic regression
trained on hand-labelled turns. It decides which (turn, resolution) pairs are worth a
short read by the host agent's model. No provider call, nothing leaves the machine."""
import json
import math
import os
import sys

import numpy as np

from . import paths

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Set before fastembed (and so huggingface_hub) is imported: quiet the progress bars, hold the
# "unauthenticated requests" warning back, and send no telemetry. setdefault keeps a caller's
# own choice, so an operator who set any of these keeps it.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

_embedder = None


def _model_cached():
    """True when the embedding model has already been fetched under paths.MODELS."""
    try:
        return any(os.scandir(paths.MODELS))
    except FileNotFoundError:
        return False


def embedder():
    global _embedder
    if _embedder is None:
        if not _model_cached():
            print("rf: downloading the embedding model (64 MB, once) from Hugging Face",
                  file=sys.stderr, flush=True)
        from fastembed import TextEmbedding
        paths.ensure()
        _embedder = TextEmbedding(MODEL_NAME, cache_dir=paths.MODELS)
    return _embedder


def embed(texts, normalize=False):
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    E = np.array(list(embedder().embed(list(texts), batch_size=32)), dtype=np.float32)
    if normalize:
        E = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    return E


def views(t):
    """The two views the classifier reads: the user turn, and the turn with its resolution."""
    user = t["user"][:1500]
    nxt = (t.get("next") or "")[:800]
    return user, f"User said: {user}\n\nAssistant then: {nxt}"


def features(triples):
    vs = [views(t) for t in triples]
    return np.hstack([embed([v[0] for v in vs]), embed([v[1] for v in vs])])


class Model:
    def __init__(self, coef, intercept, threshold):
        self.coef = np.asarray(coef, dtype=np.float32)
        self.intercept = float(intercept)
        self.threshold = float(threshold)

    @classmethod
    def load(cls, path=None):
        path = path or os.path.join(os.path.dirname(__file__), "model.json")
        with open(path) as f:
            m = json.load(f)
        return cls(m["coef"], m["intercept"], m["threshold"])

    def proba(self, X):
        z = X @ self.coef + self.intercept
        return 1.0 / (1.0 + np.exp(-z))

    def score(self, triples):
        if not triples:
            return np.zeros(0)
        return self.proba(features(triples))
