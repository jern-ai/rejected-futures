"""Graduation suggestions: held claims worth moving into the repository, ranked, with a
proposed target. Read-only throughout, so it uses the temporary-home fixture the other tests
use."""
import os
import tempfile

os.environ["RF_HOME"] = tempfile.mkdtemp()

import pytest  # noqa: E402

from rejected_futures import cli, graduate, paths, store  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    monkeypatch.setattr(paths, "CLAIMS", str(tmp_path / "claims"))
    monkeypatch.setattr(paths, "CANDIDATES", str(tmp_path / "candidates.jsonl"))
    monkeypatch.setattr(paths, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(paths, "INDEX", str(tmp_path / "index.json"))
    monkeypatch.setattr(paths, "CONFIG", str(tmp_path / "config.json"))
    paths.ensure()
    return tmp_path


def _a_claim(statement, kind="decision", scope="repository", project="", since="2026-09-01",
             evidence=None, anchors=None, status="held"):
    return store.new_claim(statement, kind=kind, scope=scope, project=project, since=since,
                           evidence=evidence, anchors=anchors, status=status)


def _ev(n, superseded=False):
    out = []
    for i in range(n):
        e = dict(source="test", at=f"2026-09-0{i + 1}", quote=f"q{i}")
        if superseded:
            e["superseded"] = True
        out.append(e)
    return out


# ---- target mapping ----------------------------------------------------------------------

def test_every_kind_and_scope_maps_to_a_target(home):
    proj = tempfile.mkdtemp()
    open(os.path.join(proj, "CLAUDE.md"), "w").close()

    inv = _a_claim("keep cents", kind="invariant", project=proj, anchors=["m.py::f", "m.py::g"])
    assert graduate.target_for(inv) == ("test", ["m.py::f", "m.py::g"])

    rej = _a_claim("don't cache", kind="rejected", project=proj, anchors=["m.py::h"])
    assert graduate.target_for(rej) == ("test", ["m.py::h"])

    rej_bare = _a_claim("don't poll", kind="rejected", project=proj)
    assert graduate.target_for(rej_bare) == ("doc: CLAUDE.md", [])

    for kind in ("decision", "fact", "preference"):
        c = _a_claim("thing", kind=kind, project=proj)
        assert graduate.target_for(c) == ("doc: CLAUDE.md", [])

    for kind in store.KINDS:
        p = _a_claim("personal thing", kind=kind, scope="personal")
        assert graduate.target_for(p) == ("doc: ~/.claude/CLAUDE.md", [])


def test_a_test_target_lists_up_to_three_anchors(home):
    proj = tempfile.mkdtemp()
    c = _a_claim("keep cents", kind="invariant", project=proj,
                 anchors=["a.py::1", "b.py::2", "c.py::3", "d.py::4"])
    _, covers = graduate.target_for(c)
    assert covers == ["a.py::1", "b.py::2", "c.py::3"]


def test_repository_doc_prefers_claude_then_agents_then_neither(home):
    both = tempfile.mkdtemp()
    open(os.path.join(both, "CLAUDE.md"), "w").close()
    open(os.path.join(both, "AGENTS.md"), "w").close()
    assert graduate.target_for(_a_claim("x", kind="decision", project=both))[0] == "doc: CLAUDE.md"

    agents = tempfile.mkdtemp()
    open(os.path.join(agents, "AGENTS.md"), "w").close()
    assert graduate.target_for(_a_claim("x", kind="decision", project=agents))[0] == "doc: AGENTS.md"

    neither = tempfile.mkdtemp()
    target = graduate.target_for(_a_claim("x", kind="decision", project=neither))[0]
    assert target == "doc (no CLAUDE.md or AGENTS.md in this repository)"


# ---- ranking -----------------------------------------------------------------------------

def test_restated_beats_kind(home):
    proj = tempfile.mkdtemp()
    restated_pref = _a_claim("prefer tabs", kind="preference", project=proj,
                             since="2026-09-20", evidence=_ev(2))
    plain_inv = _a_claim("keep cents", kind="invariant", project=proj, since="2026-09-01")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids.index(restated_pref["id"]) < ids.index(plain_inv["id"])


def test_kind_beats_anchored(home):
    proj = tempfile.mkdtemp()
    anchored_pref = _a_claim("prefer tabs", kind="preference", project=proj,
                             since="2026-09-01", anchors=["m.py::f"])
    plain_inv = _a_claim("keep cents", kind="invariant", project=proj, since="2026-09-20")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids.index(plain_inv["id"]) < ids.index(anchored_pref["id"])


def test_anchored_beats_age(home):
    proj = tempfile.mkdtemp()
    anchored_new = _a_claim("prefer spaces", kind="preference", project=proj,
                            since="2026-09-20", anchors=["m.py::f"])
    plain_old = _a_claim("prefer tabs", kind="preference", project=proj, since="2026-09-01")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids.index(anchored_new["id"]) < ids.index(plain_old["id"])


def test_older_since_first_then_id_for_ties(home):
    proj = tempfile.mkdtemp()
    newer = _a_claim("keep cents two decimals", kind="invariant", project=proj, since="2026-09-20")
    older = _a_claim("keep cents three decimals", kind="invariant", project=proj, since="2026-09-01")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids.index(older["id"]) < ids.index(newer["id"])


def test_superseded_evidence_does_not_count_as_restated(home):
    proj = tempfile.mkdtemp()
    genuinely = _a_claim("prefer spaces", kind="preference", project=proj,
                         since="2026-09-01", evidence=_ev(2))
    carried = _a_claim("prefer tabs", kind="preference", project=proj, since="2026-09-02",
                       evidence=[dict(source="test", at="2026-09-01", quote="live"),
                                 dict(source="test", at="2026-09-01", quote="old", superseded=True)])
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids.index(genuinely["id"]) < ids.index(carried["id"])


def test_the_limit_caps_the_list(home):
    proj = tempfile.mkdtemp()
    for i in range(5):
        _a_claim(f"claim number {i}", kind="invariant", project=proj, since=f"2026-09-0{i + 1}")
    assert len(graduate.suggest(project=proj, limit=2)) == 2


# ---- exclusion and read-only -------------------------------------------------------------

def test_non_held_claims_are_excluded(home):
    proj = tempfile.mkdtemp()
    held = _a_claim("keep cents", kind="invariant", project=proj)
    _a_claim("retired thing", kind="invariant", project=proj, status="retired")
    _a_claim("superseded thing", kind="invariant", project=proj, status="superseded")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert ids == [held["id"]]


def test_personal_claims_are_included(home):
    proj = tempfile.mkdtemp()
    p = _a_claim("say so when unsure", kind="preference", scope="personal")
    ids = [s["id"] for s in graduate.suggest(project=proj)]
    assert p["id"] in ids


def test_suggesting_leaves_every_claim_file_unchanged(home):
    proj = tempfile.mkdtemp()
    _a_claim("keep cents", kind="invariant", project=proj, anchors=["m.py::f"])
    _a_claim("prefer tabs", kind="preference", project=proj)
    before = {}
    for f in sorted(os.listdir(paths.CLAIMS)):
        if f.endswith(".md"):
            p = os.path.join(paths.CLAIMS, f)
            with open(p, "rb") as fh:
                before[f] = fh.read()

    out = graduate.render(graduate.suggest(project=proj))
    assert "keep cents" in out and "prefer tabs" in out

    after = {}
    for f in sorted(os.listdir(paths.CLAIMS)):
        if f.endswith(".md"):
            p = os.path.join(paths.CLAIMS, f)
            with open(p, "rb") as fh:
                after[f] = fh.read()
    assert before == after


# ---- cli and output ----------------------------------------------------------------------

def test_cli_graduate_without_suggest_exits_nonzero(home, capsys):
    code = cli.main(["graduate"])
    assert code != 0
    assert "only --suggest is implemented" in capsys.readouterr().out


def test_cli_graduate_suggest_prints_blocks_and_count(home, capsys):
    proj = tempfile.mkdtemp()
    _a_claim("keep cents", kind="invariant", project=proj, anchors=["m.py::f"])
    code = cli.main(["graduate", "--suggest", "--project", proj])
    out = capsys.readouterr().out
    assert code == 0
    assert "-> test (covers: m.py::f)" in out
    assert "keep cents" in out
    assert "1 claims suggested" in out


def test_cli_graduate_suggest_empty_prints_message(home, capsys):
    proj = tempfile.mkdtemp()
    cli.main(["graduate", "--suggest", "--project", proj])
    assert "no held claims for this project" in capsys.readouterr().out


def test_mcp_graduation_candidates_matches(home):
    from rejected_futures import mcp_server
    proj = tempfile.mkdtemp()
    _a_claim("keep cents", kind="invariant", project=proj)
    text = mcp_server.graduation_candidates(project=proj)
    assert "keep cents" in text and "-> test" in text
    assert mcp_server.graduation_candidates(project="*").endswith("1 claims suggested")
