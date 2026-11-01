"""F7 Hey Turtle tests: fake Claude client, no API key or internet needed.  python3 -m pytest -q"""
import json
from types import SimpleNamespace as NS

from turtles.backend.assistant import AlertStore, clean_history, respond, run_tool

PACK = [{"alert_id": "spot-1", "label": "Spot 1: Open bare dirt", "lat": 38.79, "lon": -77.64,
         "suggestion": {"reasons": ["Carry it 44 m northeast to dense cover.", "Support the bottom of the shell."], "distance_m": 44, "bearing_deg": 45},
         "suggestion_snapping": {"reasons": ["Carry it 61 m north to beside the water (not in it)."], "distance_m": 61, "bearing_deg": 0}},
        {"alert_id": "spot-2", "label": "Spot 2: Rut", "lat": 38.791, "lon": -77.641,
         "suggestion": {"reasons": ["Carry it 51 m northwest to dense cover."], "distance_m": 51, "bearing_deg": 315}}]


def store(tmp_path):
    p = tmp_path / "pack.json"; p.write_text(json.dumps(PACK)); return AlertStore.from_pack(p)


class FakeClaude:
    """Plays back a scripted conversation: first asks for a tool, then answers using its result."""
    def __init__(self, script): self.script, self.seen = list(script), []; self.messages = self

    def create(self, **kw):
        self.seen.append(kw); return self.script.pop(0)(kw)


def tool_call(name, inp):
    return lambda kw: NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name=name, input=inp)])


def answer_from_result(kw):
    res = json.loads(kw["messages"][-1]["content"][0]["content"])
    text = res["reasons"][0] if "reasons" in res else f"Logged {res.get('status')}."
    return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


def test_where_uses_the_relocation_tool(tmp_path):
    s = store(tmp_path); c = FakeClaude([tool_call("get_relocation", {"alert_id": "spot-1"}), answer_from_result])
    r = respond(s, "where do I take it", "spot-1", client=c)
    assert r["mode"] == "claude" and "44 m northeast" in r["reply"] and r["actions"][0]["tool"] == "get_relocation"
    assert "alert #1" in c.seen[0]["messages"][0]["content"]          # current pin is passed as context


def test_update_flags_alerts_changed(tmp_path):
    s = store(tmp_path)
    c = FakeClaude([tool_call("update_alert", {"alert_id": "1", "status": "relocated", "species": "Eastern box turtle", "est_length_in": 5}), answer_from_result])
    r = respond(s, "relocated, box turtle, five inches", "spot-1", client=c)
    assert r["alerts_changed"] and s.get("spot-1")["status"] == "relocated" and s.get("spot-1")["est_length_in"] == 5


def test_snapping_turtle_goes_beside_water(tmp_path):
    out = run_tool(store(tmp_path), "get_relocation", {"alert_id": "spot-1", "species": "snapping"})
    assert "beside the water" in out["reasons"][0]


def test_offline_mode_when_claude_fails(tmp_path):
    s = store(tmp_path)
    def boom(kw): raise ConnectionError("no wifi")
    r = respond(s, "where do I take it", "spot-1", client=FakeClaude([boom]))
    assert r["mode"].startswith("offline") and "44 m northeast" in r["reply"]
    r = respond(s, "false alarm", "spot-2", client=FakeClaude([boom]))
    assert s.get("spot-2")["status"] == "false_positive" and r["alerts_changed"]
    r = respond(s, "how many left", None, client=FakeClaude([boom]))
    assert r["reply"].startswith("1 of 2")


def test_progress_and_list(tmp_path):
    s = store(tmp_path); s.update("spot-1", status="relocated")
    assert run_tool(s, "survey_progress", {})["relocated"] == 1
    assert [a["number"] for a in run_tool(s, "list_alerts", {"status": "open"})["alerts"]] == [2]


def test_history_is_cleaned_before_claude_sees_it():
    h = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"}, {"role": "assistant", "content": ""},
         {"role": "user", "content": "b"}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "dangling"}]
    assert clean_history(h) == [{"role": "user", "content": "b"}, {"role": "assistant", "content": "ok"}]


def test_alerts_served_to_huys_app_match_the_contract(tmp_path):
    from dataclasses import fields
    from turtles.backend.assistant import as_contract
    from turtles.contracts import Alert
    s = store(tmp_path); s.update("spot-1", status="relocated", species="Eastern box turtle", sex="Male", est_length_in=5)
    a = as_contract(s.get("spot-1"))
    assert {f.name for f in fields(Alert)} <= set(a) and a["status"] == "relocated"
    assert "Eastern box turtle, male, about 5 in" in a["note"] and a["score"] is None and a["label"].startswith("Spot 1")


def test_every_route_huys_app_calls_is_served():
    import re
    from pathlib import Path
    src = (Path(__file__).parents[1] / "turtles" / "backend" / "assistant.py").read_text()
    routes = set(re.findall(r'@r\.(?:get|post|patch)\("([^"]+)"\)', src))
    app = (Path(__file__).parents[1] / "turtles" / "ui_docs" / "index.html").read_text()
    called = {re.sub(r"\$\{[^}]+\}", "{alert_id}", u) for u in re.findall(r"\$\{API_BASE\}(/[^`'\"?]+)", app)}
    assert called and called <= routes, f"app calls routes the server lacks: {called - routes}"
