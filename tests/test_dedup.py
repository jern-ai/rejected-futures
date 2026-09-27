"""The same decision must not become two claims: record and resolve find an existing one.

The embedding model is stubbed the way tests/test_floor.py stubs ranking, so these run offline.
"""
import os
import tempfile

import numpy as np
import pytest

os.environ["RF_HOME"] = tempfile.mkdtemp()

from rejected_futures import cli, mcp_server, paths, store  # noqa: E402
from rejected_futures import classify, recall  # noqa: E402


def _unit(x, y):
    v = np.zeros(384, dtype=np.float32)
    v[0] = x
    v[1] = y
    return v / np.linalg.norm(v)


def _sim(s):
    """A unit vector whose dot with _unit(1, 0) is s."""
    return _unit(s, (1.0 - s * s) ** 0.5)


VECS = {}


def fake_embed(texts, normalize=False):
    out = []
    for t in texts:
        v = VECS.get(t)
        if v is None:
            v = np.zeros(384, dtype=np.float32)
            v[(hash(t) % 382) + 2] = 1.0
        out.append(v)
    return np.array(out, dtype=np.float32)


def fake_claim_vectors(claims):
    return {c["id"]: np.asarray(VECS[c["statement"]], dtype=np.float32) for c in claims}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    monkeypatch.setattr(paths, "CLAIMS", str(tmp_path / "claims"))
    monkeypatch.setattr(paths, "CANDIDATES", str(tmp_path / "candidates.jsonl"))
    monkeypatch.setattr(paths, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(paths, "INDEX", str(tmp_path / "index.json"))
    monkeypatch.setattr(classify, "embed", fake_embed)
    monkeypatch.setattr(recall, "claim_vectors", fake_claim_vectors)
    VECS.clear()
    paths.ensure()
    return tmp_path


def _claim_files(home):
    return sorted(f for f in os.listdir(paths.CLAIMS) if f.endswith(".md"))


def test_record_then_resolve_extends_the_same_claim(home):
    proj = tempfile.mkdtemp()
    quote = "never store money as a float, always integer cents please"

    out = mcp_server.record(statement="Money is kept as integer cents.", kind="invariant",
                            scope="repository", project=proj, quote=quote)
    assert out.startswith("recorded ")
    cid = out.split()[1]

    store.append_candidates([dict(id="c1", project=proj, source="claude-code", session="s1",
                                  ts="2026-09-01T10:00:00Z", p=0.9, status="open",
                                  user=f"no. {quote}. and don't round either")])
    out = mcp_server.resolve(candidate_id="c1", action="claim",
                             statement="Money is kept as integer cents, never floats.",
                             kind="invariant", scope="repository")
    assert out.startswith(f"already on record as {cid}")

    assert _claim_files(home) == [cid + ".md"]
    c = store.load_claim(cid)
    assert len(c["evidence"]) == 2
    cand = [x for x in store.load_candidates() if x["id"] == "c1"][0]
    assert cand["status"] == "claimed" and cand["claim"] == cid


def test_a_similar_statement_reuses_the_claim(home):
    proj = tempfile.mkdtemp()
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["money stays as integer cents"] = _sim(0.90)

    out = mcp_server.record(statement="keep money in integer cents", project=proj)
    cid = out.split()[1]
    out = mcp_server.record(statement="money stays as integer cents", project=proj)
    assert out == f"already on record as {cid}; evidence added"
    assert _claim_files(home) == [cid + ".md"]


def test_a_statement_below_the_threshold_makes_a_new_claim(home):
    proj = tempfile.mkdtemp()
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["represent amounts in cents"] = _sim(0.85)

    mcp_server.record(statement="keep money in integer cents", project=proj)
    out = mcp_server.record(statement="represent amounts in cents", project=proj)
    assert out.startswith("recorded ")
    assert len(_claim_files(home)) == 2


def test_a_duplicate_in_another_project_or_retired_is_not_matched(home):
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["money stays as integer cents"] = _sim(0.90)
    p1, p2 = tempfile.mkdtemp(), tempfile.mkdtemp()

    c = store.new_claim("keep money in integer cents", project=p1)
    assert store.find_duplicate("money stays as integer cents", p2, "repository", "") is None
    assert store.find_duplicate("money stays as integer cents", p1, "repository", "") == c["id"]

    c["status"] = "retired"
    store.save_claim(c)
    assert store.find_duplicate("money stays as integer cents", p1, "repository", "") is None


def test_a_short_quote_does_not_contain_a_longer_one(home):
    proj = tempfile.mkdtemp()
    VECS["Money is kept as integer cents."] = _unit(1.0, 0.0)
    VECS["Use tabs, not spaces, in the Makefile."] = _unit(0.0, 1.0)

    out = mcp_server.record(statement="Money is kept as integer cents.", kind="invariant",
                            scope="repository", project=proj,
                            quote="never store money as a float, always integer cents please")
    assert out.startswith("recorded ")

    out = mcp_server.record(statement="Use tabs, not spaces, in the Makefile.",
                            project=proj, quote="money")
    assert out.startswith("recorded ")
    assert len(_claim_files(home)) == 2


def test_a_repository_claim_matches_a_held_personal_claim(home):
    proj = tempfile.mkdtemp()
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["money stays as integer cents"] = _sim(0.90)
    p = store.new_claim("keep money in integer cents", scope="personal")
    assert store.find_duplicate("money stays as integer cents", proj, "repository", "") == p["id"]


def test_a_personal_claim_matches_only_personal_claims(home):
    proj = tempfile.mkdtemp()
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["money stays as integer cents"] = _sim(0.90)
    store.new_claim("keep money in integer cents", project=proj)
    assert store.find_duplicate("money stays as integer cents", "", "personal", "") is None


def test_duplicate_pairs_compares_personal_with_repository(home):
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["money stays as integer cents"] = _sim(0.85)
    p = store.new_claim("keep money in integer cents", scope="personal")
    r = store.new_claim("money stays as integer cents", project="/tmp/proj")
    pairs = store.duplicate_pairs()
    ids = {(x["id"], y["id"]) for _, x, y in pairs}
    assert (p["id"], r["id"]) in ids


def test_find_duplicate_returns_the_most_similar(home):
    proj = tempfile.mkdtemp()
    VECS["money stays as integer cents"] = _unit(1.0, 0.0)
    VECS["hold money as integer cents"] = _sim(0.90)   # first in listing order
    VECS["keep money in integer cents"] = _sim(0.95)   # more similar
    store.new_claim("hold money as integer cents", project=proj)
    b = store.new_claim("keep money in integer cents", project=proj)
    assert store.find_duplicate("money stays as integer cents", proj, "repository", "") == b["id"]


def test_duplicates_lists_a_pair_and_changes_nothing(home, capsys):
    VECS["keep money in integer cents"] = _unit(1.0, 0.0)
    VECS["represent amounts in cents"] = _sim(0.85)
    a = store.new_claim("keep money in integer cents", project="/tmp/proj")
    b = store.new_claim("represent amounts in cents", project="/tmp/proj")

    before = {f: os.path.getmtime(os.path.join(paths.CLAIMS, f)) for f in _claim_files(home)}
    cli.main(["duplicates"])
    out = capsys.readouterr().out
    assert a["id"] in out and b["id"] in out and "0.850" in out
    after = {f: os.path.getmtime(os.path.join(paths.CLAIMS, f)) for f in _claim_files(home)}
    assert before == after
    assert store.load_claim(a["id"])["status"] == "held"
    assert store.load_claim(b["id"])["status"] == "held"
