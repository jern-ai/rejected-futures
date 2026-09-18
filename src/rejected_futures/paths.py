import os

HOME = os.environ.get("RF_HOME") or os.path.expanduser("~/.rejected-futures")
CLAIMS = os.path.join(HOME, "claims")
CANDIDATES = os.path.join(HOME, "candidates.jsonl")
STATE = os.path.join(HOME, "state.json")
MODELS = os.path.join(HOME, "models")
INDEX = os.path.join(HOME, "index.json")
CONFIG = os.path.join(HOME, "config.json")
LOG = os.path.join(HOME, "rf.log")


def ensure():
    for d in (HOME, CLAIMS, MODELS):
        os.makedirs(d, exist_ok=True)
    return HOME
