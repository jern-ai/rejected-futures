"""Importing the classifier sets the Hugging Face environment before fastembed loads, and
leaves any value the caller already chose alone."""
import json
import subprocess
import sys

HF_VARS = ["HF_HUB_DISABLE_PROGRESS_BARS", "HF_HUB_VERBOSITY", "HF_HUB_DISABLE_TELEMETRY"]


def test_importing_classify_sets_hf_env_without_overriding():
    code = (
        "import json, os; "
        "os.environ['HF_HUB_VERBOSITY'] = 'warning'; "
        "import rejected_futures.classify; "
        "print(json.dumps({k: os.environ.get(k) for k in " + repr(HF_VARS) + "}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    env = json.loads(out.stdout)
    assert env["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    # a value already set is kept, not overridden
    assert env["HF_HUB_VERBOSITY"] == "warning"
