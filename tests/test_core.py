import json
import os
import tempfile

os.environ["RF_HOME"] = tempfile.mkdtemp()

from rejected_futures import anchors as A  # noqa: E402
from rejected_futures import store  # noqa: E402
from rejected_futures.redact import redact  # noqa: E402
from rejected_futures.sources import claude_code as CC  # noqa: E402


def test_redact_keys_and_tokens():
    s = "API_KEY=abcdefghijklmnop123 and ghp_abcdefghijklmnopqrstuvwxyz0123 and fal key: sk-abcdefghijklmnopqrstu"
    r = redact(s)
    assert "abcdefghijklmnop123" not in r and "ghp_" not in r and "sk-abc" not in r
    assert "jern-managed-runners" in redact("the app jern-managed-runners is fine")


def test_symbols_of_diff_attributes_hunks_to_definitions():
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -3,0 +4,2 @@\n+    y = 1\n+    return y\n"
    lines = ["import os", "", "def outer():", "    pass", "    z = 2", "", "class K:", "    def m(self):", "        pass"]
    syms = A.symbols_of_diff(diff, lambda p: lines)
    assert list(syms) == ["x.py::outer"]
    assert "y = 1" in syms["x.py::outer"]
    diff2 = diff.replace("+4,2", "+8,1")
    assert list(A.symbols_of_diff(diff2, lambda p: lines)) == ["x.py::K::m"]
    assert list(A.symbols_of_diff(diff.replace("x.py", "notes.txt"), lambda p: None)) == ["notes.txt"]


def test_anchor_overlap_counts_file_matches_half():
    assert A.anchor_overlap(["a.py::f", "b.py::g"], {"a.py::f", "b.py::h"}) == 0.75
    assert A.anchor_overlap([], {"a.py::f"}) == 0.0


def test_claim_roundtrip_and_listing():
    c = store.new_claim("Never round temperatures to integers; keep two decimals.", kind="invariant",
                        scope="repository", project="/tmp/proj", since="2026-09-01",
                        evidence=[dict(source="claude-code", session="abc", at="2026-09-01T10:00:00Z", quote="two decimals")])
    back = store.load_claim(c["id"])
    assert back["statement"].startswith("Never round") and back["evidence"][0]["quote"] == "two decimals"
    assert [x["id"] for x in store.list_claims(project="/tmp/proj/sub")] == [c["id"]]
    assert store.list_claims(project="/tmp/other") == []
    p = store.new_claim("Say so when unsure.", kind="preference", scope="personal")
    assert {x["id"] for x in store.list_claims(project="/tmp/other")} == {p["id"]}
    c["status"] = "retired"
    store.save_claim(c)
    assert store.list_claims(project="/tmp/proj") == [] or all(x["id"] != c["id"] for x in store.list_claims(project="/tmp/proj"))


def test_candidates_queue():
    store.append_candidates([dict(id="t1", project="/tmp/proj", p=0.8, user="no, never do that", next="ok", status="open"),
                             dict(id="t2", project="/tmp/other", p=0.5, user="go ahead", next="done", status="open")])
    assert [c["id"] for c in store.open_candidates(project="/tmp/proj")] == ["t1"]
    store.resolve_candidate("t1", "skipped")
    assert store.open_candidates(project="/tmp/proj") == []


def test_claude_code_triples(tmp_path):
    f = tmp_path / "s.jsonl"
    rows = [
        dict(type="user", uuid="u1", timestamp="2026-09-01T10:00:00Z", cwd="/tmp/proj", message=dict(content="do X")),
        dict(type="assistant", uuid="a1", timestamp="2026-09-01T10:00:05Z", cwd="/tmp/proj", message=dict(content=[dict(type="text", text="doing X with token=abcdefghijklmnopqrstuvwxyz")])),
        dict(type="user", uuid="u2", timestamp="2026-09-01T10:01:00Z", cwd="/tmp/proj", message=dict(content="<system-reminder>ignore</system-reminder>")),
        dict(type="user", uuid="u3", timestamp="2026-09-01T10:02:00Z", cwd="/tmp/proj", message=dict(content="no, never X; we decided Y")),
        dict(type="assistant", uuid="a2", timestamp="2026-09-01T10:02:05Z", cwd="/tmp/proj", message=dict(content=[dict(type="text", text="reverting to Y")])),
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows))
    ts = list(CC.triples(str(f), now=os.path.getmtime(f) + 10_000))
    assert [t["turn"] for t in ts] == ["u1", "u3"]
    assert ts[0]["next"].startswith("doing X") and "abcdefghijklmnopqrstuvwxyz" not in ts[0]["next"]
    assert ts[1]["prev"].startswith("doing X") and ts[1]["next"] == "reverting to Y"
    # the last turn is not final while the file is fresh and has no resolution
    f.write_text(f.read_text() + "\n" + json.dumps(dict(type="user", uuid="u4", timestamp="2026-09-01T10:03:00Z", cwd="/tmp/proj", message=dict(content="and also Z please"))))
    assert [t["turn"] for t in CC.triples(str(f), now=os.path.getmtime(f))] == ["u1", "u3"]
    assert [t["turn"] for t in CC.triples(str(f), now=os.path.getmtime(f) + 10_000)] == ["u1", "u3", "u4"]
