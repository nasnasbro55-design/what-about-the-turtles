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
- "Next" means the next open alert: use list_alerts and tell them its name. Refer to alerts by number and name.
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
         "note": {"type": "string"}}}},
    {"name": "survey_progress", "description": "Counts of open, confirmed, relocated and false-alarm alerts.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_flight_plan", "description": "Recommended upcoming drone flight windows from the planner.",
     "input_schema": {"type": "object", "properties": {}}},
]


class AlertStore:
    """In-memory alerts. Ethan: subclass with SQLite and keep these four methods."""
    def __init__(self, alerts: List[Dict[str, Any]]):
        self.alerts = {a["alert_id"]: a for a in alerts}
        self._cells = None

    @classmethod
    def from_pack(cls, path) -> "AlertStore":
        """A relocation pack from `python3 -m turtles.planner.relocation --points ... --out ...`."""
        out = []
        for i, p in enumerate(json.loads(Path(path).read_text())):
            out.append({"alert_id": p["alert_id"], "number": i + 1, "name": p["label"], "lat": p["lat"], "lon": p["lon"],
                        "status": "open", "species": "", "sex": "", "est_length_in": None, "notes": [], "updated_at": "",
                        "_reloc": {"box": p["suggestion"], "snapping": p.get("suggestion_snapping")}})
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
        a.update({k: v for k, v in fields.items() if v not in (None, "")})
        a["updated_at"] = datetime.now().strftime("%H:%M")
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


THINKING_OFF = {"type": "disabled"}   # voice needs fast answers; set None if a model rejects this setting


def create(client, messages, max_tokens: int = 1024):
    """One Messages API call. Thinking off for speed; if the model refuses that setting, retry without it."""
    global THINKING_OFF
    kw = dict(model=MODEL, max_tokens=max_tokens, system=SYSTEM, tools=TOOLS, messages=messages)
    if THINKING_OFF:
        try:
            return client.messages.create(**kw, thinking=THINKING_OFF)
        except Exception as e:
            if "thinking" not in str(e).lower(): raise
            print("  (model doesn't accept thinking=disabled; using its default)"); THINKING_OFF = None
    return client.messages.create(**kw)


def ask_claude(store: AlertStore, text: str, alert_id: Optional[str], history: List[Dict[str, str]], client=None):
    """Tool-use loop. Returns (reply, actions)."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    cur = store.get(alert_id) if alert_id else None
    context = f"[The person is at alert #{cur['number']} ({cur['alert_id']}): {cur['name']}, status {cur['status']}.] " if cur else ""
    messages = [*clean_history(history), {"role": "user", "content": context + text}]
    actions = []
    for _ in range(6):
        r = create(client, messages)
        print(f"  claude: stop={r.stop_reason} blocks={[b.type for b in r.content]}")
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
        if text and not uses: return text, actions
        # cut off (or no words): never send a half-finished tool call back; ask again with room to answer
        r2 = create(client, messages, max_tokens=1500)
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


def respond(store: AlertStore, text: str, alert_id: Optional[str] = None, history=None, client=None) -> Dict[str, Any]:
    history = history or []
    try:
        if client is None and not os.environ.get("ANTHROPIC_API_KEY"): raise RuntimeError("no key")
        reply, actions = ask_claude(store, text, alert_id, history, client); mode = "claude"
    except Exception as e:  # no key, no internet, API error -> keep working
        print(f"  claude unavailable -> offline: {type(e).__name__}: {str(e)[:300]}")
        reply, actions = offline(store, text, alert_id); mode = f"offline ({type(e).__name__})"
    print(f"[{mode}] you: {text!r}\n  turtle: {reply!r}")
    focus = next((x["input"].get("alert_id") for x in reversed(actions) if x["input"].get("alert_id")), alert_id)
    f = store.get(focus) if focus else None
    return {"reply": reply, "mode": mode, "actions": actions, "alert_id": f["alert_id"] if f else alert_id,
            "alerts_changed": any(x["tool"] == "update_alert" for x in actions)}


try:  # request body for POST /assistant; module level so FastAPI can resolve the type
    from pydantic import BaseModel

    class Ask(BaseModel):
        text: str
        alert_id: Optional[str] = None
        history: List[Dict[str, Any]] = []
except ImportError:  # tests and offline use don't need pydantic
    Ask = None


ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")   # any voice id from your ElevenLabs account
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")


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

    @r.post("/assistant/speak")
    def speak(q: Ask):
        mp3 = tts_mp3(q.text)
        return Response(content=mp3, media_type="audio/mpeg") if mp3 else Response(status_code=204)

    @r.post("/assistant")
    def assistant(q: Ask): return respond(store, q.text, q.alert_id, q.history)

    @r.get("/assistant/alerts")
    def alerts(): return [public(a) for a in store.list()]

    return r


def create_app(store: AlertStore):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    app = FastAPI(title="A.E.R.O. field assistant")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router(store))
    ui = ROOT / "ui_docs"
    app.get("/")(lambda: FileResponse(ui / "hey_turtle_demo.html"))
    app.get("/hey-turtle.js")(lambda: FileResponse(ui / "hey-turtle.js", media_type="text/javascript"))
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A.E.R.O. voice assistant server")
    ap.add_argument("--pack", help="relocation pack JSON (real pins)"); ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    store = AlertStore.from_pack(a.pack) if a.pack else AlertStore.from_alerts(ROOT / "architecture" / "mock" / "alerts.json")
    import uvicorn
    print(f"A.E.R.O.: {len(store.alerts)} alerts, model {MODEL}, "
          f"{'Claude' if os.environ.get('ANTHROPIC_API_KEY') else 'OFFLINE mode (no ANTHROPIC_API_KEY)'}, "
          f"voice: {'ElevenLabs' if os.environ.get('ELEVENLABS_API_KEY') else 'browser'} -> http://localhost:{a.port}")
    uvicorn.run(create_app(store), host="0.0.0.0", port=a.port)
