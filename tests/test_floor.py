"""The prompt hook's floor follows the size of the store unless the config fixes it."""
import io
import json
import os
import tempfile

os.environ["RF_HOME"] = tempfile.mkdtemp()

from rejected_futures import cli, paths, store  # noqa: E402
from rejected_futures import recall as R  # noqa: E402


def test_default_floor_rises_with_the_number_of_claims():
    assert abs(R.default_floor(1) - 0.61) < 1e-9
    assert R.default_floor(0) == R.default_floor(1)
    floors = [R.default_floor(n) for n in (1, 3, 10, 40, 100)]
    assert floors == sorted(floors)
    assert 0.67 < R.default_floor(100) < 0.69


def _hook_output(monkeypatch, capsys, score, n_claims, config=None):
    home = tempfile.mkdtemp()
    monkeypatch.setattr(paths, "HOME", home)
    monkeypatch.setattr(paths, "CONFIG", os.path.join(home, "config.json"))
    if config is not None:
        with open(paths.CONFIG, "w") as f:
            json.dump(config, f)
    claims = [dict(id=f"claim-{i}", statement=f"claim {i}", kind="decision", scope="personal", since="2026-09-26")
              for i in range(n_claims)]
    monkeypatch.setattr(store, "list_claims", lambda **kw: claims)
    monkeypatch.setattr(R, "rank", lambda *a, **kw: [dict(claim=claims[0], similarity=score, anchor_overlap=0.0, score=score)])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "raise the repository cap on pricing", "cwd": home})))
    cli.hook("prompt")
    return capsys.readouterr().out


def test_hook_uses_the_store_size_floor_when_none_is_set(monkeypatch, capsys):
    # 0.62 clears the floor for one claim (0.61) and not for a hundred (about 0.68).
    assert "claim-0" in _hook_output(monkeypatch, capsys, 0.62, 1)
    assert _hook_output(monkeypatch, capsys, 0.62, 100) == ""


def test_a_configured_floor_wins(monkeypatch, capsys):
    assert _hook_output(monkeypatch, capsys, 0.62, 1, config={"recall_floor": 0.9}) == ""
    assert "claim-0" in _hook_output(monkeypatch, capsys, 0.62, 100, config={"recall_floor": 0.5})
