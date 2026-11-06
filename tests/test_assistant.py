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


def test_ui_assets_exist_and_are_served():
    """The A.E.R.O. UI loads loading.js and bundled fonts from the server: each file must exist and have a route."""
    import re
    from pathlib import Path
    root = Path(__file__).parents[1] / "turtles"
    app = (root / "ui_docs" / "index.html").read_text()
    src = (root / "backend" / "assistant.py").read_text()
    scripts = [s.split("?")[0] for s in re.findall(r'<script src="([^"]+)"', app) if not s.startswith("http") and "API_BASE" not in s]
    fonts = re.findall(r"url\((fonts/[^)]+\.woff2)\)", app)
    assert scripts == ["loading.js"] and len(fonts) >= 5
    for f in scripts + fonts:
        assert (root / "ui_docs" / f).is_file(), f"missing {f}"
    assert '"/loading.js"' in src and '"/fonts/{name}"' in src
    assert '"/aero-control.js"' in src and "aero-control.js" in app and (root / "ui_docs" / "aero-control.js").is_file()
    assert not re.search(r"[\U0001F300-\U0001FAFF]", app), "no emoji in the A.E.R.O. UI"


def test_password_login_page_and_cookie(monkeypatch):
    """Home screen apps can't show a Basic-auth box: the server sends a login page and remembers a cookie."""
    from fastapi.testclient import TestClient
    from turtles.backend.assistant import create_app, AlertStore, ROOT
    monkeypatch.setenv("TURTLE_APP_PASSWORD", "test-pass")
    c = TestClient(create_app(AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json"), mock_zones=True))
    r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/alerts").status_code == 401
    assert c.get("/apple-touch-icon.png").status_code == 200 and c.get("/manifest.webmanifest").status_code == 200
    assert c.post("/login", data={"password": "nope"}).status_code == 401
    r = c.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303 and "aero_session" in r.cookies
    assert c.get("/alerts").status_code == 200                      # cookie kept by the client
    assert TestClient(c.app).get("/alerts", auth=("x", "test-pass")).status_code == 200   # Basic still works


def test_changes_feed_tracks_who_changed_what():
    """Other phones/laptops poll /alerts/changes and reload; each change records who made it."""
    from fastapi.testclient import TestClient
    from turtles.backend.assistant import create_app, AlertStore, ROOT
    store = AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json")
    c = TestClient(create_app(store, mock_zones=True))
    v0 = c.get("/alerts/changes").json()["version"]
    aid = c.get("/alerts").json()[0]["alert_id"]
    a = c.patch(f"/alerts/{aid}", json={"status": "relocated", "user": "Naz"}).json()
    assert a["updated_by"] == "Naz" and a["updated_at"]
    ch = c.get("/alerts/changes").json()
    assert ch["version"] == v0 + 1 and ch["by"] == "Naz" and ch["alert_id"] == aid and ch["status"] == "relocated"
    store.actor = "Ethan"; store.update(aid, note="shell 5 in"); store.actor = ""   # what a voice log does
    assert c.get("/alerts/changes").json()["by"] == "Ethan"


def test_login_keeps_display_name(monkeypatch):
    from fastapi.testclient import TestClient
    from turtles.backend.assistant import create_app, AlertStore, ROOT
    monkeypatch.setenv("TURTLE_APP_PASSWORD", "test-pass")
    c = TestClient(create_app(AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json"), mock_zones=True))
    r = c.post("/login", data={"name": "  Naz  ", "password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303 and r.cookies.get("aero_name") == "Naz"


def say(text):
    return lambda kw: NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


def test_claimed_log_without_tool_gets_done(tmp_path):
    """If A.E.R.O. says "logged" without calling update_alert, it is made to actually log it before anyone hears it."""
    s = store(tmp_path)
    c = FakeClaude([say("Logged Spot 1 as a false alarm."),
                    tool_call("update_alert", {"alert_id": "1", "status": "false_positive"}), answer_from_result])
    r = respond(s, "spot 1 was a false alarm", None, client=c)
    assert s.get("spot-1")["status"] == "false_positive" and r["alerts_changed"]
    assert any("did not call update_alert" in str(m["content"]) for m in c.seen[1]["messages"])


def test_control_app_goes_to_the_screen(tmp_path):
    s = store(tmp_path)
    c = FakeClaude([tool_call("control_app", {"action": "open_alert", "alert_id": "2"}), say("Opened Spot 2.")])
    r = respond(s, "show me spot 2", None, client=c)
    assert r["ui"] == [{"action": "open_alert", "alert_id": "spot-2"}] and r["alert_id"] == "spot-2"


def test_field_changes_survive_a_restart(tmp_path):
    s = store(tmp_path); s.load_state(tmp_path / "pack_state.json")
    s.actor = "Naz"; s.update("spot-1", status="relocated", species="Eastern box turtle"); s.actor = ""
    again = store(tmp_path).load_state(tmp_path / "pack_state.json")
    a = again.get("spot-1"); assert a["status"] == "relocated" and a["updated_by"] == "Naz"
    assert store(tmp_path).load_state(tmp_path / "pack_state.json", reset=True).get("spot-1")["status"] == "open"


def test_screen_state_reaches_claude_and_no_false_log_check(tmp_path):
    """A.E.R.O. is told what the screen shows; saying "already marked" is not treated as a claimed log."""
    s = store(tmp_path); c = FakeClaude([say("Spot 2 was already marked a false alarm. The fence band is off.")])
    r = respond(s, "is the fence band on?", None, client=c, screen={"fence_band": "off", "my_location": "38.79, -77.64"})
    assert "fence band: off" in c.seen[0]["messages"][-1]["content"] and len(c.seen) == 1 and "already marked" in r["reply"]


def test_patch_saves_field_log(tmp_path):
    """The app's field log (species, sex, health-assessment record) is saved, returned and kept across a restart."""
    from fastapi.testclient import TestClient
    from turtles.backend.assistant import create_app, AlertStore, ROOT
    store = AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json").load_state(tmp_path / "s.json")
    c = TestClient(create_app(store, mock_zones=True)); aid = store.list()[0]["alert_id"]
    rec = {"species": "Eastern box turtle", "sex": "Male", "scl_mm": 142, "exam": {"carapace": "ABN"}, "disposition": "Relocated off site"}
    a = c.patch(f"/alerts/{aid}", json={"status": "relocated", "species": "Eastern box turtle", "sex": "Male", "record": rec, "user": "Naz"}).json()
    assert a["species"] == "Eastern box turtle" and a["sex"] == "Male" and a["record"]["scl_mm"] == 142
    s2 = AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json").load_state(tmp_path / "s.json")
    assert s2.get(aid)["record"]["exam"]["carapace"] == "ABN"


def test_control_tool_is_built_from_the_apps_action_list(tmp_path):
    """Every action the app registers (aero-control.js) becomes something A.E.R.O. can press."""
    s = store(tmp_path)
    cat = [{"name": "layer", "say": "Press a map layer button", "args": {"name": "boundary|fence_band", "state": "on|off|toggle"}},
           {"name": "set_field", "say": "Fill a field in the field log", "args": {"field": "key", "value": "value"}}]
    c = FakeClaude([tool_call("control_app", {"action": "layer", "args": {"name": "fence_band", "state": "on"}}), say("Fence band is on.")])
    r = respond(s, "turn on the heat map", None, client=c, catalog=cat)
    tool = next(t for t in c.seen[0]["tools"] if t["name"] == "control_app")
    assert tool["input_schema"]["properties"]["action"]["enum"] == ["layer", "set_field"] and "set_field" in tool["description"]
    assert r["ui"] == [{"action": "layer", "args": {"name": "fence_band", "state": "on"}}]
    assert any("Open now, in priority order (2): Spot 1, Spot 2" in str(m["content"]) for m in c.seen[0]["messages"])


def test_voice_fills_the_field_log(tmp_path):
    """update_alert's record merges into the field log; earlier exam answers are kept."""
    s = store(tmp_path)
    s.update("spot-1", record={"sex": "Male", "exam": {"carapace": "WNL"}})
    s.update("spot-1", status="relocated", record={"scl_mm": 142, "exam": {"eyes": "ABN"}, "findings": "left eye swollen"})
    r = s.get("spot-1")["record"]
    assert r["sex"] == "Male" and r["scl_mm"] == 142 and r["exam"] == {"carapace": "WNL", "eyes": "ABN"} and r["findings"]


def test_screen_command_never_snaps_back_to_the_open_spot(tmp_path):
    """Spot 4 open, "show me spot 5": the answer focuses spot 5, not the spot that was open before."""
    s = store(tmp_path)
    c = FakeClaude([tool_call("control_app", {"action": "open_spot", "args": {"spot": 2}}), say("Done, Spot 2 is open.")])
    assert respond(s, "show me spot 2", "spot-1", client=c)["alert_id"] == "spot-2"
    c = FakeClaude([tool_call("control_app", {"action": "layer", "args": {"name": "fence_band", "state": "on"}}), say("Done.")])
    assert respond(s, "fence band on", "spot-1", client=c)["alert_id"] is None


def drone_store(tmp_path):
    """Two hand-placed test spots plus two drone detections (one high, one review)."""
    s = store(tmp_path)
    s.alerts["F-1-A001"] = {"alert_id": "F-1-A001", "number": 3, "name": "Spot 3: detection 61%", "lat": 38.79, "lon": -77.64, "status": "open",
                            "score": 0.61, "confidence": "review", "detection_ids": ["d1"], "thumbnail": "thumbnails/d1.jpg", "flight_id": "F-1", "notes": []}
    s.alerts["F-1-A002"] = {"alert_id": "F-1-A002", "number": 4, "name": "Spot 4: detection 83%", "lat": 38.79, "lon": -77.64, "status": "open",
                            "score": 0.83, "confidence": "high", "detection_ids": ["d2", "d3"], "thumbnail": "", "flight_id": "F-1", "notes": []}
    return s


def test_drone_spots_carry_score_and_come_first(tmp_path):
    s = drone_store(tmp_path)
    out = run_tool(s, "list_alerts", {"status": "open"})["alerts"]
    assert [a["number"] for a in out] == [4, 3, 1, 2]                       # high first, then score, then the test spots
    assert out[0]["source"] == "drone 83%, high" and out[-1]["source"] == "test spot (no score)"
    g = run_tool(s, "get_alert", {"alert_id": "3"})
    assert g["source"] == "drone 61%, review" and g["close_up_photo"] and g["detections"] == 1
    assert run_tool(s, "list_flights", {})["flights"] == []                  # JSON store: no flights table


def test_claude_sees_each_spots_source_and_priority(tmp_path):
    s = drone_store(tmp_path)
    c = FakeClaude([lambda kw: NS(stop_reason="end_turn", content=[NS(type="text", text="Spot 4.")])])
    respond(s, "which one first", None, client=c)
    ctx = c.seen[0]["messages"][-1]["content"]
    assert "drone 83%, high" in ctx and "test spot (no score)" in ctx and "priority order (4): Spot 4, Spot 3, Spot 1, Spot 2" in ctx


def test_offline_next_and_how_sure_use_the_detector(tmp_path):
    s = drone_store(tmp_path)
    def boom(kw): raise ConnectionError("no wifi")
    assert "number 4" in respond(s, "next", "spot-1", client=FakeClaude([boom]))["reply"]
    assert "83% sure" in respond(s, "how sure is it", "F-1-A002", client=FakeClaude([boom]))["reply"]
    assert "test spot" in respond(s, "how sure is it", "spot-1", client=FakeClaude([boom]))["reply"]


def test_flight_plan_uses_the_live_planner_when_the_server_gives_one(tmp_path):
    s = store(tmp_path)
    s.plan_fn = lambda: [{"zone_name": "Grayson", "start": "2026-11-06T20:00:00Z", "end": "2026-11-06T22:00:00Z", "priority": 0.9,
                          "thermal_ok": False, "reasons": ["Sunny afternoon"], "zone_id": "SITE"}]
    w = run_tool(s, "get_flight_plan", {})["windows"]
    assert w[0]["zone_name"] == "Grayson" and "zone_id" not in w[0]
