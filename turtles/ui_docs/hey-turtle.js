/* A.E.R.O. voice widget ("Hey Aero"): drop into any page (plain HTML or React).
 *   <script src="hey-turtle.js"></script>
 *   HeyTurtle.init({ apiBase: "http://localhost:8000",            // where turtles.backend.assistant runs
 *                    getAlertId: () => selectedAlertId,            // which pin the responder has open (optional)
 *                    onAlertsChanged: () => reloadPins(),          // refresh the map when a status changes
 *                    onFocus: id => selectPin(id) });              // "next" moves the app to another pin
 * Hold the big button (or Space) and talk. "Hands-free" listens for "Hey Aero ...". Typed box = backup.
 * Speech-to-text uses the browser (Chrome / Edge / Safari); the phone needs https or localhost for the mic.
 * Voice out: ElevenLabs through the server if it has ELEVENLABS_API_KEY, else the device's best built-in voice.
 * Options: position: 'left' puts the button and panel bottom-left (default bottom-right).
 * React: call HeyTurtle.init(...) once in a useEffect; it adds its own button and cleans nothing up you own. */
(function () {
  const css = `#ht-btn{position:fixed;right:18px;bottom:18px;width:72px;height:72px;border-radius:50%;border:none;z-index:9999;
  background:#2f6b3a;color:#fff;font:600 13px -apple-system,Helvetica,Arial;box-shadow:0 6px 20px rgba(0,0,0,.35);cursor:pointer;touch-action:none}
  #ht-btn.live{background:#d64541;box-shadow:0 0 0 10px rgba(214,69,65,.25)}#ht-btn.busy{background:#8a7a2a}
  #ht-panel{position:fixed;right:18px;bottom:102px;width:min(360px,calc(100vw - 36px));z-index:9999;background:#14210f;color:#f3f1e6;
  border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.4);font:14px/1.45 -apple-system,Helvetica,Arial;display:none}
  #ht-panel.open{display:block}#ht-log{max-height:220px;overflow:auto;padding:12px 14px}#ht-log .u{color:#a9b59c;margin:6px 0}
  #ht-log .b{margin:6px 0}#ht-log .b::before{content:"A.E.R.O. ";color:#5be37d;font-weight:600}#ht-row{display:flex;gap:6px;padding:10px;border-top:1px solid #2d4224}
  #ht-row input{flex:1;min-width:0;background:#1d2d17;border:1px solid #2d4224;color:#f3f1e6;border-radius:8px;padding:9px}
  #ht-row button{background:#1d2d17;border:1px solid #2d4224;color:#f3f1e6;border-radius:8px;padding:0 10px;cursor:pointer}
  #ht-mode{font-size:11px;color:#a9b59c;padding:0 14px 8px}`;
  let cfg = {}, hist = [], rec = null, talking = false, hands = false, busy = false;
  const $ = s => document.querySelector(s);
  const toFeet = t => t.replace(/(\d+(?:\.\d+)?) m\b/g, (_, m) => `${Math.round(m / 0.3048 / 5) * 5} feet (${m} meters)`);
  function log(cls, t) { const d = document.createElement('div'); d.className = cls; d.textContent = t; $('#ht-log').appendChild(d);
    $('#ht-log').scrollTop = 1e9; $('#ht-panel').classList.add('open'); }
  let audio = null, cloudVoice = true;   // ElevenLabs via the server; falls back to the browser's best voice
  function stopTalking() { try { speechSynthesis.cancel(); audio && audio.pause(); } catch (e) {} }
  function browserSpeak(t) { try { const u = new SpeechSynthesisUtterance(t); u.lang = 'en-US';
    const vs = speechSynthesis.getVoices().filter(v => /^en(-|_)US/.test(v.lang));
    const v = vs.find(v => /Premium|Enhanced|Neural|Natural/i.test(v.name)) || vs.find(v => /Ava|Zoe|Samantha|Google US|Allison/.test(v.name));
    if (v) u.voice = v; speechSynthesis.speak(u); } catch (e) {} }
  async function speak(t) {
    stopTalking(); t = toFeet(t);
    if (cloudVoice && cfg.voice !== 'browser') {
      try { const r = await fetch((cfg.apiBase || '') + '/assistant/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) });
        if (r.status === 200) { audio = new Audio(URL.createObjectURL(await r.blob())); await audio.play(); $('#ht-mode').textContent += ' · voice: ElevenLabs'; return; }
        if (r.status === 204) { $('#ht-mode').textContent += ' · voice: browser (server had no ElevenLabs audio, see server window)'; }
      } catch (e) { $('#ht-mode').textContent += ' · voice: browser (' + e.name + ')'; console.warn('A.E.R.O. voice', e); }
    }
    browserSpeak(t);
  }
  async function send(text) {
    text = (text || '').trim(); if (!text || busy) return; log('u', text); busy = true; $('#ht-btn').classList.add('busy');
    try {
      const r = await fetch((cfg.apiBase || '') + '/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, alert_id: cfg.getAlertId ? cfg.getAlertId() : null, history: hist.slice(-8) }) });
      const j = await r.json();
      if (!r.ok || j.reply == null) { const m = 'Server error ' + r.status + ': ' + JSON.stringify(j.detail || j).slice(0, 200); log('b', m); $('#ht-mode').textContent = m; busy = false; $('#ht-btn').classList.remove('busy'); return; }
      hist.push({ role: 'user', content: text }, { role: 'assistant', content: j.reply });
      log('b', j.reply); speak(j.reply); $('#ht-mode').textContent = 'mode: ' + j.mode;
      if (j.alerts_changed) { cfg.onAlertsChanged && cfg.onAlertsChanged(); window.dispatchEvent(new CustomEvent('heyturtle:alerts-changed')); }
      if (j.alert_id && cfg.onFocus) cfg.onFocus(j.alert_id);
      window.dispatchEvent(new CustomEvent('heyturtle:reply', { detail: j }));
    } catch (e) { const m = "I can't reach the A.E.R.O. server. Check the connection."; log('b', m); speak(m); }
    busy = false; $('#ht-btn').classList.remove('busy');
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function listen(cont) {
    if (!SR) { log('b', 'Voice needs Chrome, Edge or Safari. You can type below.'); return; }
    rec = new SR(); rec.lang = 'en-US'; rec.interimResults = false; rec.continuous = cont;
    rec.onresult = e => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) {
      let t = e.results[i][0].transcript;
      if (hands) { const m = t.toLowerCase().match(/\b(?:hey|hi|ok|okay)\s+(?:a\.?\s?e\.?\s?r\.?\s?o\.?|aero|arrow|ero|airo|aaro|turtle)\b[,!.?]?\s*(.*)/); if (!m) continue; t = m[1] || 'hello'; }
      send(t); } };
    rec.onend = () => { $('#ht-btn').classList.toggle('live', hands); if (hands) try { listen(true) } catch (e) {} };
    rec.onerror = e => { if (e.error === 'not-allowed') log('b', 'Microphone blocked: allow it, and use https or localhost.'); };
    try { rec.start(); $('#ht-btn').classList.add('live'); } catch (e) {}
  }
  const start = () => { if (hands || talking) return; talking = true; stopTalking(); listen(false); };
  const stop = () => { if (!talking) return; talking = false; try { rec && rec.stop() } catch (e) {} ; $('#ht-btn').classList.remove('live'); };
  window.HeyTurtle = {
    init(c = {}) {
      cfg = c; if ($('#ht-btn')) return;
      const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
      document.body.insertAdjacentHTML('beforeend', `<div id="ht-panel"><div id="ht-log"></div><div id="ht-mode"></div>
        <div id="ht-row"><input id="ht-in" placeholder="Type instead…"><button id="ht-hf">Hands-free</button><button id="ht-x">✕</button></div></div>
        <button id="ht-btn" aria-label="Hold to talk to A.E.R.O.">A.E.R.O.<br><small style="font-weight:400">hold to talk</small></button>`);
      if (c.position === 'left') { $('#ht-btn').style.left = $('#ht-panel').style.left = '18px'; $('#ht-btn').style.right = $('#ht-panel').style.right = 'auto'; }
      const b = $('#ht-btn');
      b.addEventListener('pointerdown', e => { e.preventDefault(); start(); }); b.addEventListener('pointerup', stop); b.addEventListener('pointerleave', stop);
      $('#ht-in').addEventListener('keydown', e => { if (e.key === 'Enter') { send(e.target.value); e.target.value = ''; } });
      $('#ht-x').onclick = () => $('#ht-panel').classList.remove('open');
      $('#ht-hf').onclick = () => { hands = !hands; $('#ht-hf').textContent = hands ? 'Hands-free ON' : 'Hands-free';
        if (hands) { listen(true); log('b', 'Listening. Start with "Hey Aero".'); } else { try { rec && rec.stop() } catch (e) {} } };
      const typing = () => ['INPUT', 'TEXTAREA'].includes((document.activeElement || {}).tagName);
      addEventListener('keydown', e => { if (e.code === 'Space' && !typing() && !e.repeat) { e.preventDefault(); start(); } });
      addEventListener('keyup', e => { if (e.code === 'Space' && !typing()) { e.preventDefault(); stop(); } });
    },
    send, speak,
  };
})();
