"""F7 A.E.R.O. ("Hey Aero"): a hands-free field assistant for responders, powered by Claude with tools.

The phone (Huy's app + turtles/ui_docs/hey-turtle.js) turns speech into text and POSTs it to /assistant.
Claude answers in short spoken sentences, and every factual answer comes from a tool that runs our real code:
  list_alerts      -> the alert store (Ethan's SQLite later; JSON for now)
  get_relocation   -> F1 relocation guide (Tanya's rules on the F2 habitat map)
  update_alert     -> confirmed / relocated / false positive + species, sex, size, notes (feeds the F3 report)
  survey_progress  -> counts for "how many left"
  get_flight_plan  -> planner windows
So Claude never invents a drop-off spot. If there's no API key or no internet, an offline rule-based mode answers
the core commands, so the demo can't die on stage.

Run standalone (demo page at http://localhost:8000). Wake phrase: "Hey Aero".
    pip install fastapi uvicorn anthropic
    export ANTHROPIC_API_KEY=...            # optional: without it, offline mode
    python3 -m turtles.backend.assistant --pack "<OneDrive>/reports/voice_pack_2026-10-24.json"
Mount in Ethan's API later:   app.include_router(assistant.router(store))
"""
from __future__ import annotations

import time
import argparse, json, os, re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from turtles.rules import ACTIVE_F

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("TURTLE_MODEL", "claude-haiku-5-5")
STATUSES = ["open", "confirmed", "relocated", "false_positive"]

SYSTEM = f"""You are A.E.R.O. (say it "Aero"), a hands-free field assistant for construction crews and turtle responders on active
construction sites in Virginia. The person is outdoors, often holding a turtle, listening through a phone speaker.

How to answer:
- Speak in 1 to 3 short sentences. No markdown, lists, emoji or symbols. Say distances in feet first, then meters.
- Any instruction about where to take a turtle MUST come from the get_relocation tool. Never invent a location.
- Record what the person reports with update_alert (status, species, sex, approximate size in inches, notes),
  then confirm back briefly what you logged.
- Only set status "relocated" when the person says they moved or carried it; "confirmed" when they say they found a turtle;
  "false_positive" when they say nothing is there. Never infer a status. If they say "next" while the current alert is
  still open, first ask one short question: did they move it, or was it a false alarm?
- "Next" means the next open alert: use list_alerts and tell them its name.
- Never say you logged, recorded, marked or saved anything unless you called update_alert in this same turn, and don't
  talk about logging at all unless you just logged something or they asked.
- You can press the app's buttons with control_app (zoom, my location, open an alert, Site boundary and Fence band
  buttons, tabs, theme, navigation). When asked, do it and say what you did in a few words.
- You cannot see the screen except through [Screen now: ...]. Never say something is on, off or shown unless that
  line says so or you just changed it with control_app.
- "Take me to / guide me to / navigate to" a spot means control_app navigate: the app draws the walking line from their
  GPS position and tracks them there. Distances in [Screen now] are live from their GPS.
- If what they said makes no sense here (a stray word, background talk, a mishearing), reply only "Sorry, I didn't
  catch that." or ask one short question with the likely match ("Spot 5?"). Never send app questions to Tanya.
- Refer to alerts only by spot number and name (for example "Spot 2, the rut"). Never say internal ids like pin-2.
- Handling rules from Tanya Finch (What About the Turtles): hold a box turtle by the sides with a hand under the
  bottom of the shell, "like a hamburger", upright, never upside down. Snapping turtles, or any turtle that cannot
  close its shell completely, are aquatic and defensive on land: keep hands away from the head, place them beside
  water, never in it. Box turtles are most active at {ACTIVE_F[0]}-{ACTIVE_F[1]} F and are dormant by early November.
- If you are unsure, or the question is about an injured turtle, permits, or anything outside these tools, say so
  plainly and tell them to call Tanya. Never guess about animal welfare or safety.
"""

TOOLS = [
    {"name": "list_alerts", "description": "List drone alerts (possible turtles) with number, id, name, status and species.",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string", "enum": STATUSES + ["all"],
                      "description": "Filter; default all"}}}},
    {"name": "get_relocation", "description": "Where to carry the turtle at an alert: distance, direction and reasons, "
     "from the relocation guide built on Tanya's rules and the site's habitat map.",
     "input_schema": {"type": "object", "required": ["alert_id"], "properties": {
         "alert_id": {"type": "string"},
         "species": {"type": "string", "enum": ["box", "snapping", "aquatic"], "description": "default box"}}}},
    {"name": "update_alert", "description": "Record what the responder found at an alert.",
     "input_schema": {"type": "object", "required": ["alert_id"], "properties": {
         "alert_id": {"type": "string"},
         "status": {"type": "string", "enum": STATUSES[1:]},
         "species": {"type": "string", "description": "e.g. Eastern box turtle, Common snapping turtle"},
         "sex": {"type": "string", "enum": ["Male", "Female", "Unknown"]},
         "est_length_in": {"type": "number", "description": "approximate shell length in inches"},
         "note": {"type": "string"},
         "record": {"type": "object", "description": "Field log (A.E.R.O. health assessment) values the person actually said, merged "
                    "into what is already logged: sex, age_class (Adult|Subadult|Juvenile|Hatchling), mass_g, scl_mm (carapace length), "
                    "width_mm, height_mm, plastron_mm, encounter_type, substrate (Bare dirt|Leaf litter|Grass|Brush|Gravel|Along silt "
                    "fence|Other), circumstances, exam {posture, respiration, eyes, nares, carapace, plastron, margins, skin, tail, "
                    "parasites, gait: WNL|ABN|NE}, findings, photos [list], disposition (Relocated off site|Released at site|Admitted to "
                    "care|Transferred|Held for observation|Other), disposition_location. Never fill what they didn't say."}}}},
    {"name": "control_app", "description": "Do something on the person's screen right now, the same as pressing the button: "
     "zoom the map in or out, recenter on the site, show their own location, open or close an alert's details, press the "
     "Site boundary or Fence band (heat map) buttons, switch the Alerts / Flight windows tab, filter alerts, switch dark or "
     "light theme, slide the alert list or chat away, or start / stop walking navigation to an alert (in the app, from "
     "their GPS position). Use it whenever they ask to see, show, open, zoom, switch, hide, press, take them to or guide "
     "them somewhere. Several calls in one turn are fine.",
     "input_schema": {"type": "object", "required": ["action"], "properties": {
         "action": {"type": "string", "enum": ["zoom_in", "zoom_out", "recenter", "locate", "open_alert", "close_alert", "layer",
                                              "tab", "filter", "theme", "list", "chat", "navigate", "stop_navigation"]},
         "alert_id": {"type": "string", "description": "for open_alert and navigate"},
         "value": {"type": "string", "description": "layer: boundary_on, boundary_off, boundary_toggle, fence_on, fence_off or "
                   "fence_toggle (the fence band is the heat map; the boundary is the site outline); tab: alerts or "
                   "flights; filter: all, open or resolved; theme: dark or light; list: up or down; chat: hide; "
                   "zoom_in / zoom_out: how many steps (default 1)"}}}},
    {"name": "survey_progress", "description": "Counts of open, confirmed, relocated and false-alarm alerts.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_flight_plan", "description": "Recommended upcoming drone flight windows from the planner.",
     "input_schema": {"type": "object", "properties": {}}},
]


class AlertStore:
    """In-memory alerts. Ethan: subclass with SQLite and keep these four methods."""
    def __init__(self, alerts: List[Dict[str, Any]]):
        self.version, self.last, self.actor = 0, {"version": 0}, ""   # bumped on every change, so other phones/laptops refresh
        self.alerts = {a["alert_id"]: a for a in alerts}
        self._cells = None
        self.state_path: Optional[Path] = None

    KEEP = ("status", "species", "sex", "est_length_in", "notes", "note", "record", "updated_at", "updated_by")

    def load_state(self, path, reset: bool = False):
        """Field changes survive a restart: kept in <pack>_state.json beside the pack (private data, not in git)."""
        self.state_path = Path(path)
        if reset and self.state_path.exists(): self.state_path.unlink(); print("A.E.R.O.: cleared saved alert changes")
        if self.state_path.exists():
            for k, v in json.loads(self.state_path.read_text()).items():
                if k in self.alerts: self.alerts[k].update(v)
            print(f"A.E.R.O.: restored saved alert changes from {self.state_path.name}")
        return self

    def save(self):
        if not self.state_path: return
        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: {f: a.get(f) for f in self.KEEP if f in a} for k, a in self.alerts.items()}, indent=1))
            tmp.replace(self.state_path)
        except Exception as e: print(f"  (couldn't save alert changes: {e})")

    @classmethod
    def from_pack(cls, path) -> "AlertStore":
        """A relocation pack from `python3 -m turtles.planner.relocation --points ... --out ...`."""
        out = []
        for i, p in enumerate(json.loads(Path(path).read_text())):
            out.append({"alert_id": p["alert_id"], "number": i + 1, "name": p["label"], "lat": p["lat"], "lon": p["lon"],
                        "status": "open", "species": "", "sex": "", "est_length_in": None, "notes": [], "updated_at": "",
                        "_reloc": {"box": p["suggestion"], "snapping": p.get("suggestion_snapping")},
                        **{k: p[k] for k in ("score", "confidence", "sensors", "detection_ids", "thumbnail", "flight_id", "created_at") if k in p}})
        return cls(out)

    @classmethod
    def from_alerts(cls, path) -> "AlertStore":
        out = []
        for i, a in enumerate(json.loads(Path(path).read_text())):
            out.append({**a, "number": i + 1, "name": a.get("note") or f"Alert {i + 1}", "species": "", "sex": "",
                        "est_length_in": None, "notes": [], "updated_at": ""})
        return cls(out)

    def list(self, status: str = "all") -> List[Dict[str, Any]]:
        return [a for a in self.alerts.values() if status in ("all", None) or a["status"] == status]

    def get(self, alert_id: str) -> Optional[Dict[str, Any]]:
        a = self.alerts.get(alert_id)
        if a is None:  # accept "3" or "pin 3"
            m = re.search(r"\d+", str(alert_id)); n = int(m.group()) if m else -1
            a = next((x for x in self.alerts.values() if x.get("number") == n), None)
        return a

    def update(self, alert_id: str, **fields) -> Optional[Dict[str, Any]]:
        a = self.get(alert_id)
        if a is None: return None
        note = fields.pop("note", None)
        if note: a["notes"].append(note)
        rec = fields.pop("record", None)
        if isinstance(rec, dict) and rec:   # field log said out loud: merge, keep what was already there
            cur = dict(a.get("record") or {}); exam = {**(cur.get("exam") or {}), **(rec.pop("exam", None) or {})}
            cur.update({k: v for k, v in rec.items() if v not in (None, "", [])}); cur["exam"] = exam if exam else cur.get("exam", {})
            if not cur.get("exam"): cur.pop("exam", None)
            a["record"] = cur
        a.update({k: v for k, v in fields.items() if v not in (None, "")})
        return self.touch(a)

    def touch(self, a: Dict[str, Any], by: str = "") -> Dict[str, Any]:
        """Record that an alert changed and who changed it (the name typed on the sign-in page)."""
        by = (by or self.actor or "").strip()[:24]
        a["updated_at"] = datetime.now().strftime("%H:%M"); a["updated_by"] = by
        self.version += 1
        self.last = {"version": self.version, "alert_id": a["alert_id"], "label": a.get("name") or a["alert_id"],
                     "status": a["status"], "by": by, "at": a["updated_at"]}
        self.save()
        return a

    def relocation(self, alert_id: str, species: str = "box") -> Optional[Dict[str, Any]]:
        a = self.get(alert_id)
        if a is None: return None
        key = "snapping" if species in ("snapping", "aquatic") else "box"
        if a.get("_reloc", {}).get(key): return a["_reloc"][key]
        from dataclasses import asdict
        from turtles.planner import relocation as R
        if self._cells is None:
            self._cells = R.load_cells() if R.HEATMAP.exists() else {}
        if not self._cells: return {"reasons": ["No habitat map loaded for this site: call Tanya before moving it."]}
        return asdict(R.suggest(a["alert_id"], a["lat"], a["lon"], self._cells, None, key))


def public(a: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in a.items() if not k.startswith("_")}


def run_tool(store: AlertStore, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "list_alerts":
        return {"alerts": [{k: a.get(k) for k in ("number", "alert_id", "name", "status", "species")} for a in store.list(args.get("status", "all"))]}
    if name == "get_relocation":
        r = store.relocation(args["alert_id"], args.get("species", "box"))
        return r if r is not None else {"error": "no such alert"}
    if name == "update_alert":
        a = store.update(**args)
        return public(a) if a else {"error": "no such alert"}
    if name == "control_app":
        spot = args.get("alert_id") or (args.get("args") or {}).get("spot")
        if spot not in (None, ""):
            if store.get(str(spot)) is None: return {"error": f"no spot {spot}"}
        return {"ok": True, "done": "shown on the person's screen"}
    if name == "survey_progress":
        al = store.list(); return {s: sum(a["status"] == s for a in al) for s in STATUSES} | {"total": len(al)}
    if name == "get_flight_plan":
        p = ROOT / "architecture" / "mock" / "windows.json"
        return {"windows": json.loads(p.read_text())[:3] if p.exists() else [], "note": "sample windows until the live planner is wired in"}
    return {"error": f"unknown tool {name}"}


def clean_history(history: List[Dict[str, Any]], keep: int = 8) -> List[Dict[str, str]]:
    """Only non-empty text turns, strictly alternating user/assistant, starting with user and ending with assistant
    (the API rejects anything else, and one bad turn from the phone would break every later request)."""
    out: List[Dict[str, str]] = []
    for h in history or []:
        role, content = h.get("role"), h.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip(): continue
        if out and out[-1]["role"] == role: out[-1] = {"role": role, "content": content}   # keep the latest of a repeat
        else: out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user": out.pop(0)
    if out and out[-1]["role"] != "assistant": out.pop()
    out = out[-keep:]
    while out and out[0]["role"] != "user": out.pop(0)
    return out


FAST_NOTE = ("\n- What they say reaches you through speech-to-text. Numbers often arrive as sound-alikes: for/fore = 4, "
             "to/too = 2, won = 1, tree = 3, ate = 8, sex/sicks = 6, and \"Spotify\" = \"spot five\". Read the spot number that fits "
             "the spots that exist and what they are doing; if it is still unclear, ask in a few words."
             "\n- [Screen now: ...] lists every open spot by distance when GPS is on (open spots by distance); use it for 'closest' and 'where am I'."
             "\n- To log what someone found by voice, use update_alert (status + record for the field log). Use control_app "
             "press_status / set_field / save_sheet only when they ask to fill or press the sheet on screen."
             "\n- Screen commands (zoom, layers, tabs, open a spot, guidance): answer in a few words, like \"Done, Spot 3 is "
             "open.\" Don't add the alert status or ask about another spot unless they asked."
             "\n- \"Zoom in to / into / on spot N\" = control_app zoom_to_spot with that spot (it closes any other open spot). "
             "\"Show me spot N\" = open_spot."
             "\n- Distances over 1 km: say them in miles and say they are off site; never read out a number like 36,117 meters."
             "\n- Speed matters: each message starts with [Alerts now: ...], the live list. Answer questions about which alerts "
             "exist or are open straight from it; don't call list_alerts or survey_progress for that.")
THINKING_OFF = {"type": "disabled"}   # voice needs fast answers; set None if a model rejects this setting


def control_tool(catalog: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """control_app built from the app's action list, so every button the app registers is one A.E.R.O. can press."""
    if not catalog: return next(t for t in TOOLS if t["name"] == "control_app")
    lines = "\n".join(f"- {c['name']}" + (f"({', '.join(f'{k}: {v}' for k, v in (c.get('args') or {}).items())})" if c.get("args") else "")
                      + f": {c.get('say', '')}" for c in catalog)
    return {"name": "control_app", "description": "Press anything on the person's screen right now, exactly like tapping it: "
            "the map, layers, tabs, filters, spots, phone panels, chat, theme, walking guidance, the responder buttons and every "
            "field of the field log sheet. Use it whenever they ask to see, show, open, zoom, switch, press, fill, save or be "
            "taken somewhere. Several calls in one turn run in order. Actions:\n" + lines,
            "input_schema": {"type": "object", "required": ["action"], "properties": {
                "action": {"type": "string", "enum": [c["name"] for c in catalog]},
                "args": {"type": "object", "description": "the action's arguments, e.g. {\"spot\": 4} or {\"name\": \"fence_band\", \"state\": \"on\"}"}}}}


def create(client, messages, max_tokens: int = 1024, tools: Optional[List[Dict[str, Any]]] = None):
    """One Messages API call. Thinking off for speed; if the model refuses that setting, retry without it."""
    global THINKING_OFF
    kw = dict(model=MODEL, max_tokens=max_tokens, tools=tools or TOOLS, messages=messages,
              system=[{"type": "text", "text": SYSTEM + FAST_NOTE, "cache_control": {"type": "ephemeral"}}])
    if THINKING_OFF:
        try:
            return client.messages.create(**kw, thinking=THINKING_OFF)
        except Exception as e:
            if "thinking" not in str(e).lower(): raise
            print("  (model doesn't accept thinking=disabled; using its default)"); THINKING_OFF = None
    return client.messages.create(**kw)


def screen_text(screen: Optional[Dict[str, Any]]) -> str:
    """What the person's screen shows right now (sent by the app with every message), so A.E.R.O. never guesses."""
    if not screen: return ""
    return "[Screen now: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in screen.items() if v not in (None, "")) + "] "


def ask_claude(store: AlertStore, text: str, alert_id: Optional[str], history: List[Dict[str, str]], client=None,
               screen: Optional[Dict[str, Any]] = None, catalog: Optional[List[Dict[str, Any]]] = None):
    """Tool-use loop. Returns (reply, actions)."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    cur = store.get(alert_id) if alert_id else None
    context = f"[The person is at alert #{cur['number']} ({cur['alert_id']}): {cur['name']}, status {cur['status']}.] " if cur else ""
    open_now = [a for a in store.list() if a["status"] == "open"]
    context = f"[Open now ({len(open_now)}): " + (", ".join(f"Spot {a.get('number')}" for a in open_now) or "none") + "] " + context
    context = "[Alerts now: " + "; ".join(f"#{a.get('number')} {a.get('name') or a['alert_id']} ({a['alert_id']}): {a['status']}"
                                         + (f", {a['species']}" if a.get("species") else "") for a in store.list()) + "] " + screen_text(screen) + context
    tools = [control_tool(catalog) if t["name"] == "control_app" else t for t in TOOLS]
    messages = [*clean_history(history), {"role": "user", "content": context + text}]
    actions, checked = [], False
    for _ in range(6):
        t0 = time.time(); r = create(client, messages, tools=tools)
        print(f"  claude: {time.time() - t0:.2f}s stop={r.stop_reason} blocks={[b.type for b in r.content]}")
        uses = [b for b in r.content if b.type == "tool_use"]
        if uses and r.stop_reason != "max_tokens":
            messages.append({"role": "assistant", "content": r.content})
            results = []
            for b in uses:
                out = run_tool(store, b.name, dict(b.input)); actions.append({"tool": b.name, "input": dict(b.input)})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
            messages.append({"role": "user", "content": results})
            continue
        text = " ".join(b.text for b in r.content if b.type == "text").strip()
        if text and not uses and not checked and re.search(r"^(?:logged|recorded|marked|saved)\b|\bI(?:'ve| have| just)?\s+(?:logged|recorded|marked|saved)\b", text, re.I) \
                and not any(x["tool"] == "update_alert" for x in actions):
            # it claimed a log without calling the tool: make it actually do it (or take it back) before the person hears it
            checked = True; print("  claude claimed a log without update_alert -> asking it to do it")
            messages += [{"role": "assistant", "content": r.content},
                         {"role": "user", "content": "[Check: you said you logged or recorded something, but you did not call "
                          "update_alert in this turn. If the person asked you to record something, call update_alert now and then "
                          "confirm. If not, answer again without claiming you logged anything.]"}]
            continue
        if text and not uses: return text, actions
        # cut off (or no words): never send a half-finished tool call back; ask again with room to answer
        r2 = create(client, messages, max_tokens=1500, tools=tools)
        print(f"  claude retry: stop={r2.stop_reason} blocks={[b.type for b in r2.content]}")
        if any(b.type == "tool_use" for b in r2.content) and r2.stop_reason != "max_tokens":
            r = r2; messages.append({"role": "assistant", "content": r.content}); results = []
            for b in r.content:
                if b.type == "tool_use":
                    out = run_tool(store, b.name, dict(b.input)); actions.append({"tool": b.name, "input": dict(b.input)})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
            messages.append({"role": "user", "content": results}); continue
        text = " ".join(b.text for b in r2.content if b.type == "text").strip()
        if text: return text, actions
        raise RuntimeError(f"no spoken reply (stop={r2.stop_reason})")
    return "Sorry, that took too many steps. Try asking one thing at a time.", actions


NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}


def offline(store: AlertStore, text: str, alert_id: Optional[str]):
    """Rule-based fallback for the core commands (no key, no internet)."""
    t = text.lower(); a = store.get(alert_id) if alert_id else None; acts = []
    if a is None: a = (store.list("open") or store.list())[0]
    species = "snapping" if "snap" in t else "box"
    if re.search(r"how many|progress|left", t):
        p = run_tool(store, "survey_progress", {}); return f"{p['open']} of {p['total']} alerts left. {p['relocated']} relocated so far.", acts
    if re.search(r"\bnext\b", t):
        nxt = next((x for x in store.list("open") if x["alert_id"] != a["alert_id"]), None)
        return (f"Next is number {nxt['number']}, {nxt['name']}." if nxt else "No open alerts left."), [{"tool": "focus", "input": {"alert_id": nxt["alert_id"]}}] if nxt else []
    fields = {}
    if "snap" in t: fields["species"] = "Common snapping turtle"
    elif "box" in t: fields["species"] = "Eastern box turtle"
    m = re.search(r"(\d+(?:\.\d+)?|" + "|".join(NUM) + r")\s*inch", t)
    if m: fields["est_length_in"] = float(m.group(1)) if m.group(1)[0].isdigit() else NUM[m.group(1)]
    if re.search(r"\bfemale\b", t): fields["sex"] = "Female"
    elif re.search(r"\bmale\b", t): fields["sex"] = "Male"
    for pat, st in ((r"false alarm|not a turtle|nothing here|no turtle", "false_positive"), (r"relocat|moved it", "relocated"),
                    (r"confirm|found (it|one)|it'?s a turtle|got one", "confirmed")):
        if re.search(pat, t):
            store.update(a["alert_id"], status=st, **fields); acts.append({"tool": "update_alert", "input": {"alert_id": a["alert_id"], "status": st, **fields}})
            return f"Logged number {a['number']} as {st.replace('_', ' ')}.", acts
    if re.search(r"where|which way|take it|move it|carry|put it", t):
        r = store.relocation(a["alert_id"], species); return " ".join(r["reasons"]), acts
    return "I'm in offline mode. Try: where do I take it, relocated, false alarm, next, or how many left.", acts


def respond(store: AlertStore, text: str, alert_id: Optional[str] = None, history=None, client=None,
            screen: Optional[Dict[str, Any]] = None, catalog: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    history = history or []
    try:
        if client is None and not os.environ.get("ANTHROPIC_API_KEY"): raise RuntimeError("no key")
        reply, actions = ask_claude(store, text, alert_id, history, client, screen, catalog); mode = "claude"
    except Exception as e:  # no key, no internet, API error -> keep working
        print(f"  claude unavailable -> offline: {type(e).__name__}: {str(e)[:300]}")
        reply, actions = offline(store, text, alert_id); mode = f"offline ({type(e).__name__})"
    print(f"[{mode}] you: {text!r}\n  turtle: {reply!r}")
    # the spot the app should show after this answer: the last one an action named. Screen commands decide it
    # themselves; never fall back to the spot that was open before ("show spot 5" must not snap back to spot 4).
    named = [x["input"].get("alert_id") or (x["input"].get("args") or {}).get("spot") for x in actions]
    named = [str(n) for n in named if n not in (None, "")]
    screen_cmds = any(x["tool"] == "control_app" for x in actions)
    focus = named[-1] if named else (None if screen_cmds else alert_id)
    f = store.get(focus) if focus else None
    return {"reply": reply, "mode": mode, "actions": actions, "alert_id": f["alert_id"] if f else (None if screen_cmds else alert_id),
            "alerts_changed": any(x["tool"] == "update_alert" for x in actions),
            "ui": [ui_cmd(store, x["input"]) for x in actions if x["tool"] == "control_app"]}   # the widget carries these out on screen


def ui_cmd(store: AlertStore, cmd: Dict[str, Any]) -> Dict[str, Any]:
    """A control_app call as the widget gets it: "2" or "spot 2" becomes the real alert id."""
    a = store.get(cmd["alert_id"]) if cmd.get("alert_id") else None
    out = {**cmd, "alert_id": a["alert_id"]} if a else dict(cmd)
    sp = (out.get("args") or {}).get("spot")
    if sp not in (None, "") and store.get(str(sp)): out["args"] = {**out["args"], "spot": store.get(str(sp)).get("number") or sp}
    return out


try:  # request body for POST /assistant; module level so FastAPI can resolve the type
    from pydantic import BaseModel

    class Ask(BaseModel):
        text: str
        alert_id: Optional[str] = None
        history: List[Dict[str, Any]] = []
        catalog: Optional[List[Dict[str, Any]]] = None   # every action the app can do (aero-control.js)
        screen: Optional[Dict[str, Any]] = None   # what the phone shows right now (layers on/off, open spot, GPS distance)
        user: str = ""   # who is talking (shown as "NAZ: ..." in the chat, saved with any alert they change)

    class Patch(BaseModel):   # PATCH /alerts/{id}; module level for the same reason (inside a function it became a query param -> 422)
        status: Optional[str] = None
        note: Optional[str] = None
        user: Optional[str] = None
        species: Optional[str] = None    # from the app's field log (A.E.R.O. health assessment, sections 1-5)
        sex: Optional[str] = None
        record: Optional[Dict[str, Any]] = None
except ImportError:  # tests and offline use don't need pydantic
    Ask = Patch = None


ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")   # any voice id from your ElevenLabs account
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")   # ~75 ms model; multilingual_v2 sounds a bit richer but is several times slower


def tts_stream(text: str):
    """Start ElevenLabs streaming. Returns (chunks, None) or (None, why). The phone starts playing the first chunk
    while the rest is still being generated, instead of waiting for the whole file."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key: return None, "no ELEVENLABS_API_KEY on the server"
    if not text.strip(): return None, "empty text"
    import urllib.request
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}/stream?output_format=mp3_22050_32",
        method="POST", headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        data=json.dumps({"text": text[:800], "model_id": ELEVEN_MODEL,
                         "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}}).encode())
    t0 = time.time()
    try: r = urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        body = e.read().decode(errors="ignore")[:300] if hasattr(e, "read") else ""
        why = f"{e} {body}".strip(); print(f"  voice: ElevenLabs FAILED -> browser voice. {why}"); return None, why

    def chunks():
        n, first = 0, True
        with r:
            while True:
                c = r.read(4096)
                if not c: break
                if first: print(f"  voice: ElevenLabs first audio after {time.time() - t0:.2f}s"); first = False
                n += len(c); yield c
        print(f"  voice: ElevenLabs done ({n // 1024} KB in {time.time() - t0:.1f}s)")
    return chunks(), None


def tts_mp3(text: str) -> Optional[bytes]:
    """Realistic voice via ElevenLabs (key stays on the server). None -> the browser speaks instead."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or not text.strip(): return None
    import urllib.request
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}", method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        data=json.dumps({"text": text[:800], "model_id": ELEVEN_MODEL,
                         "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}}).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(); print(f"  voice: ElevenLabs OK ({len(data) // 1024} KB)"); return data
    except Exception as e:
        body = e.read().decode(errors="ignore")[:400] if hasattr(e, "read") else ""
        print(f"  voice: ElevenLabs FAILED -> browser voice. {e} {body}"); return None


def router(store: AlertStore):
    from fastapi import APIRouter, Response
    r = APIRouter()

    @r.get("/assistant/speak.mp3")   # streamed voice: the widget points an <audio> at this URL
    def speak_stream(text: str):
        from fastapi.responses import StreamingResponse
        it, why = tts_stream(text)
        if it is None: return Response(status_code=503, headers={"X-Voice-Error": why.encode("ascii", "ignore").decode()[:200]})
        return StreamingResponse(it, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @r.post("/assistant/speak")
    def speak(q: Ask):
        mp3 = tts_mp3(q.text)
        return Response(content=mp3, media_type="audio/mpeg") if mp3 else Response(status_code=204)

    @r.post("/assistant")
    def assistant(q: Ask):
        store.actor = q.user; t0 = time.time()
        try: return respond(store, q.text, q.alert_id, q.history, screen=q.screen, catalog=q.catalog)
        finally: store.actor = ""; print(f"  reply ready in {time.time() - t0:.2f}s")

    @r.get("/assistant/alerts")
    def alerts(): return [public(a) for a in store.list()]

    return r


def as_contract(a: Dict[str, Any]) -> Dict[str, Any]:
    """An alert in the shape of contracts.Alert, which Huy's app reads (plus a few extras it ignores)."""
    parts = []
    if a.get("species"): parts.append(a["species"] + (f", {a['sex'].lower()}" if a.get("sex") else "")
                                      + (f", about {a['est_length_in']:g} in" if a.get("est_length_in") else ""))
    parts += a.get("notes", [])
    return {"alert_id": a["alert_id"], "site_id": a.get("site_id", "grayson"), "flight_id": a.get("flight_id", "F-20261024"),
            "lat": a["lat"], "lon": a["lon"], "confidence": a.get("confidence", "review"), "score": a.get("score"),   # None = test spot, no detector score yet
            "sensors": a.get("sensors", ["rgb"]), "detection_ids": a.get("detection_ids", []), "thumbnail": a.get("thumbnail", ""),
            "created_at": a.get("created_at", "2026-10-24T15:00:00Z"), "status": a["status"],
            "note": a.get("note") or " · ".join(x for x in parts if x), "number": a.get("number"), "species": a.get("species", ""),
            "sex": a.get("sex", ""), "record": a.get("record") or {},
            "label": a.get("name") or a["alert_id"], "updated_at": a.get("updated_at", ""), "updated_by": a.get("updated_by", "")}


_heat_cache: Dict[str, Any] = {}


def app_router(store: AlertStore, mock_zones: bool):
    """The endpoints Huy's app calls (ARCHITECTURE section 6), served from the same store A.E.R.O. updates,
    until Ethan's api.py takes over. Then he keeps these routes and swaps the store for SQLite."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    r = APIRouter(); mock = ROOT / "architecture" / "mock"

    @r.get("/alerts")
    def alerts(): return [as_contract(a) for a in store.list()]

    @r.get("/thumbnails/{name}")   # detector crops written by turtles.detection.run_flight beside the pack
    def thumbnail(name: str):
        from fastapi.responses import FileResponse
        p = (getattr(store, "media_dir", None) or Path(".")) / "thumbnails" / Path(name).name
        if not p.exists(): raise HTTPException(404)
        return FileResponse(p, media_type="image/jpeg")

    @r.get("/alerts/changes")   # tiny poll: every open phone/laptop checks this and reloads when the version moves
    def changes(): return store.last

    @r.get("/alerts/{alert_id}/relocation")
    def relocation(alert_id: str):
        a = store.get(alert_id)
        if a is None: raise HTTPException(404, "no such alert")
        rel = store.relocation(alert_id, "snapping" if "snap" in a.get("species", "").lower() else "box")
        return {"alert_id": a["alert_id"], **rel}

    @r.patch("/alerts/{alert_id}")
    def patch(alert_id: str, p: Patch):
        a = store.get(alert_id)
        if a is None: raise HTTPException(404, "no such alert")
        if p.status in STATUSES: a["status"] = p.status
        if p.note is not None: a["note"] = p.note
        if p.species is not None: a["species"] = p.species
        if p.sex is not None: a["sex"] = p.sex
        if p.record is not None: a["record"] = p.record
        store.touch(a, p.user or "")
        return as_contract(a)

    @r.get("/zones")
    def zones():
        if mock_zones: return json.loads((mock / "zones.json").read_text())
        site = ROOT / "planner" / "sites" / "grayson.geojson"   # real site: show the traced boundary (no work zones yet)
        if not site.exists(): return []
        ring = json.loads(site.read_text())["features"][0]["geometry"]["coordinates"][0]
        out = [{"zone_id": "SITE", "site_id": "grayson", "name": "Grayson Overlook site boundary",
                "polygon": [[round(la, 6), round(lo, 6)] for lo, la in ring], "work": "active construction", "work_starts": None}]
        lod = ROOT / "planner" / "sites" / "grayson_lod.geojson"   # Logan's official limits of disturbance (KML, Sep 29)
        if lod.exists():
            for i, f in enumerate(json.loads(lod.read_text())["features"], 1):
                out.append({"zone_id": f"LOD-{i}", "site_id": "grayson", "name": "Limits of disturbance (Logan, Sep 29)",
                            "polygon": [[round(c[1], 6), round(c[0], 6)] for c in f["geometry"]["coordinates"][0]],
                            "work": "limits of disturbance", "work_starts": None})
        return out

    @r.get("/plan")
    def plan(): return json.loads((mock / "windows.json").read_text())   # planner windows (sample until live forecast is wired in)

    @r.get("/heatmap")
    def heatmap(min_likelihood: float = 0.5, min_on_site: float = 0.2, band_m: float = 60):
        """F2 turtle-likelihood cells within band_m of the site fence (Tanya finds turtles within 6-10 ft of it):
        inside the fence = where trapped turtles likely are; outside = the woods they come from. Light enough for a phone."""
        hm = ROOT / "planner" / "out" / "heatmap.geojson"
        if not hm.exists(): raise HTTPException(404, "no heat map yet: run python3 -m turtles.planner.habitat ...")
        key = (min_likelihood, min_on_site, band_m, hm.stat().st_mtime)
        if _heat_cache.get("key") == key: return _heat_cache["fc"]
        site = ROOT / "planner" / "sites" / "grayson.geojson"
        ring = json.loads(site.read_text())["features"][0]["geometry"]["coordinates"][0] if site.exists() else None
        if ring:
            import math
            lat0 = sum(p[1] for p in ring) / len(ring); kx, ky = 111_320 * math.cos(math.radians(lat0)), 111_320
            seg = [((x1 * kx, y1 * ky), (x2 * kx, y2 * ky)) for (x1, y1), (x2, y2) in zip(ring, ring[1:])]
            def fence_dist(x, y):
                px, py, best = x * kx, y * ky, 1e18
                for (ax, ay), (bx, by) in seg:
                    dx, dy = bx - ax, by - ay; t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
                    best = min(best, (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2)
                return best ** 0.5
        keep = []
        for f in json.loads(hm.read_text())["features"]:
            pr = f["properties"]
            # inside the fence (cleared ground, where trapped turtles are) scores lower by design, so it gets its own cutoff
            if pr.get("likelihood", 0) < (min_on_site if pr.get("on_site") else min_likelihood): continue
            pts = f["geometry"]["coordinates"][0]
            if ring:
                cx, cy = sum(p[0] for p in pts[:4]) / 4, sum(p[1] for p in pts[:4]) / 4
                if fence_dist(cx, cy) > band_m: continue
            keep.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in pts]]},
                         "properties": {"likelihood": pr["likelihood"], "on_site": pr.get("on_site", False), "why": (pr.get("reasons") or [""])[0]}})
        _heat_cache.update(key=key, fc={"type": "FeatureCollection", "features": keep})
        return _heat_cache["fc"]

    return r


def create_app(store: AlertStore, mock_zones: bool = False, first=None):
    """first: a router mounted ahead of app_router, so backend/api.py can override GET /alerts and /plan."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    app = FastAPI(title="A.E.R.O. field assistant")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    @app.middleware("http")
    async def no_stale(request, call_next):   # phones must never show an old page or old alert list
        r = await call_next(request)
        if request.url.path in ("/", "/hey-turtle.js", "/loading.js", "/aero-control.js"): r.headers["Cache-Control"] = "no-cache"
        elif r.headers.get("content-type", "").startswith("application/json"): r.headers["Cache-Control"] = "no-store"
        return r

    password = os.environ.get("TURTLE_APP_PASSWORD")
    if password:  # required before sharing a public link: site locations + paid API keys sit behind this server
        # A login page + 30-day cookie (an iPhone home screen app can't show the browser's password box),
        # and HTTP Basic still works for scripts. Icons/manifest stay open so iOS can fetch the app icon.
        import base64, hashlib, hmac, secrets
        from urllib.parse import parse_qs, quote
        from fastapi import Request
        from fastapi.responses import Response as Plain, HTMLResponse, RedirectResponse
        token = hmac.new(password.encode(), b"aero-session-v1", hashlib.sha256).hexdigest()
        public = ("/login", "/manifest.webmanifest", "/apple-touch-icon", "/icons/", "/fonts/", "/favicon")

        def authed(request: Request) -> bool:
            if secrets.compare_digest(request.cookies.get("aero_session", ""), token): return True
            auth = request.headers.get("authorization", "")
            try: given = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)[1] if auth.startswith("Basic ") else ""
            except Exception: given = ""
            return bool(given) and secrets.compare_digest(given, password)

        @app.middleware("http")
        async def require_password(request: Request, call_next):
            if request.url.path.startswith(public) or authed(request):
                return await call_next(request)
            if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/login", status_code=303)
            return Plain(status_code=401)

        @app.get("/login", response_class=HTMLResponse)
        def login_page(): return LOGIN_HTML.replace("{msg}", "")

        async def login(request):
            form = parse_qs((await request.body()).decode())
            given, name = form.get("password", [""])[0], " ".join(form.get("name", [""])[0].split())[:24]
            if not secrets.compare_digest(given, password):
                return HTMLResponse(LOGIN_HTML.replace("{msg}", "Wrong password. Try again."), status_code=401)
            r = RedirectResponse("/", status_code=303)
            r.set_cookie("aero_session", token, max_age=30 * 86400, httponly=True, samesite="lax",
                         secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https")
            if name: r.set_cookie("aero_name", quote(name), max_age=30 * 86400, samesite="lax")   # display name only, not a secret
            return r
        login.__annotations__["request"] = Request   # real class, not the string the __future__ import makes
        app.post("/login")(login)
    if first is not None: app.include_router(first)
    app.include_router(router(store))
    app.include_router(app_router(store, mock_zones))
    ui = ROOT / "ui_docs"
    app.get("/")(lambda: FileResponse(ui / "index.html"))                  # Huy's responder app, A.E.R.O. built in
    app.get("/demo")(lambda: FileResponse(ui / "hey_turtle_demo.html"))    # bare A.E.R.O. test page
    app.get("/hey-turtle.js")(lambda: FileResponse(ui / "hey-turtle.js", media_type="text/javascript"))
    app.get("/loading.js")(lambda: FileResponse(ui / "loading.js", media_type="text/javascript"))   # A.E.R.O. loading screen
    app.get("/aero-control.js")(lambda: FileResponse(ui / "aero-control.js", media_type="text/javascript"))   # hands-free control layer
    # home screen app: icon + manifest (public, so iOS can fetch the icon)
    app.get("/manifest.webmanifest")(lambda: FileResponse(ui / "manifest.webmanifest", media_type="application/manifest+json"))
    app.get("/apple-touch-icon.png")(lambda: FileResponse(ui / "icons" / "apple-touch-icon.png", media_type="image/png"))

    @app.get("/icons/{name}")
    def icon(name: str):
        f = ui / "icons" / name
        if f.suffix != ".png" or f.parent != ui / "icons" or not f.is_file():
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/fonts/{name}")   # bundled fonts, so the demo doesn't need venue Wi-Fi for type
    def font(name: str):
        f = ui / "fonts" / name
        if f.suffix != ".woff2" or f.parent != ui / "fonts" or not f.is_file():
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(f, media_type="font/woff2", headers={"Cache-Control": "public, max-age=604800"})
    return app


LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>A.E.R.O. sign in</title><meta name="theme-color" content="#0A140D">
<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="A.E.R.O.">
<style>
@font-face{font-family:Oxanium;font-weight:300;src:url(/fonts/oxanium-latin-300-normal.woff2) format('woff2')}
@font-face{font-family:Oxanium;font-weight:500;src:url(/fonts/oxanium-latin-500-normal.woff2) format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:500;src:url(/fonts/jetbrains-mono-latin-500-normal.woff2) format('woff2')}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:#0A140D;color:#E6EDE7;font-family:Oxanium,-apple-system,sans-serif}
body{display:flex;align-items:center;justify-content:center;padding:24px}
form{width:min(340px,100%);display:flex;flex-direction:column;align-items:center;gap:18px}
h1{margin:0;font-weight:300;font-size:44px;letter-spacing:.04em}
.mono{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;color:#9FB3A5;text-transform:uppercase}
input{width:100%;height:52px;border-radius:6px;border:1px solid #1C2E21;background:#050B07;color:#E6EDE7;padding:0 14px;font-size:17px}
input:focus{outline:2px solid #4ADE80;outline-offset:1px}
button{width:100%;height:52px;border-radius:6px;border:1px solid #4ADE80;background:#16A34A;color:#04140A;font:500 16px Oxanium,sans-serif;letter-spacing:.24em;cursor:pointer}
.err{color:#F87171;min-height:1em}
</style></head><body>
<form method="post" action="/login">
<svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="g" x1=".2" y1="0" x2=".6" y2="1"><stop offset="0" stop-color="#4ADE80"/><stop offset=".55" stop-color="#16A34A"/><stop offset="1" stop-color="#052E16"/></linearGradient></defs><path fill="url(#g)" d="M32 3 L56 11 V30 C56 45 46 55 32 61 C18 55 8 45 8 30 V11 Z"/><polygon fill="#DCFCE7" stroke="#052E16" stroke-width="1.6" points="32,19 41.5,24.5 41.5,35.5 32,41 22.5,35.5 22.5,24.5"/></svg>
<h1>A.E.R.O.</h1><span class="mono">What About the Turtles · Field system</span>
<input type="text" name="name" placeholder="Your name" autocomplete="nickname" maxlength="24" autofocus required>
<input type="password" name="password" placeholder="Team password" autocomplete="current-password" required>
<button type="submit">SIGN IN</button><span class="mono err">{msg}</span>
</form></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A.E.R.O. voice assistant server")
    ap.add_argument("--pack", help="relocation pack JSON (real pins)"); ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reset", action="store_true", help="forget saved field changes (fresh demo)")
    a = ap.parse_args()
    store = AlertStore.from_pack(a.pack) if a.pack else AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json")
    if a.pack: store.media_dir = Path(a.pack).parent
    if a.pack: store.load_state(Path(a.pack).with_name(Path(a.pack).stem + "_state.json"), reset=a.reset)
    import uvicorn
    print(f"A.E.R.O.: {len(store.alerts)} alerts, model {MODEL}, "
          f"{'Claude' if os.environ.get('ANTHROPIC_API_KEY') else 'OFFLINE mode (no ANTHROPIC_API_KEY)'}, "
          f"voice: {'ElevenLabs' if os.environ.get('ELEVENLABS_API_KEY') else 'browser'}, "
          f"password: {'ON' if os.environ.get('TURTLE_APP_PASSWORD') else 'OFF (set TURTLE_APP_PASSWORD before sharing a link)'} "
          f"-> app http://localhost:{a.port}  (bare test page: /demo)")
    uvicorn.run(create_app(store, mock_zones=not a.pack), host="0.0.0.0", port=a.port)
