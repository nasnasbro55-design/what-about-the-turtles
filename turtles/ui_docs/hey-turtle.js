/* A.E.R.O. voice widget ("Hey Aero"): drop into any page (plain HTML or React).
 *   <script src="hey-turtle.js"></script>
 *   HeyTurtle.init({ apiBase: "http://localhost:8000",            // where turtles.backend.assistant runs
 *                    getAlertId: () => selectedAlertId,            // which pin the responder has open (optional)
 *                    onAlertsChanged: () => reloadPins(),          // refresh the map when a status changes
 *                    onFocus: id => selectPin(id) });              // "next" moves the app to another pin
 * Tap the shield and talk (it stops when you pause), or hold it like a walkie-talkie (Space on a laptop).
 * "Hands-free" listens for "Hey Aero ...". Typed box = backup. Each line shows who said it ("NAZ: ...").
 * The chat is a window: drag its top bar to move it, drag the corner to resize; HIDE / CHAT put it away and back.
 * Speech-to-text uses the browser (Chrome / Edge / Safari); the phone needs https or localhost for the mic.
 * Voice out: ElevenLabs through the server if it has ELEVENLABS_API_KEY, else the device's best built-in voice.
 * Options: position: 'left' puts the buttons bottom-left (default bottom-right); userName: 'Naz' (else the
 * name from the sign-in page). React: call HeyTurtle.init(...) once in a useEffect. */
(function () {
  // [A.E.R.O. UI] theme colors come from the page's CSS variables when it has them
  const css = `#ht-dock{position:fixed;right:18px;bottom:18px;z-index:10000;display:flex;align-items:center;gap:10px}
  #ht-btn{position:relative;display:flex;align-items:center;gap:12px;min-height:64px;padding:8px 20px 8px 8px;
  border-radius:40px;border:1px solid var(--accent,#4ADE80);background:var(--panel-2,#050B07);color:var(--ink,#E6EDE7);cursor:pointer;touch-action:none;
  -webkit-user-select:none;user-select:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent;
  box-shadow:0 0 0 6px color-mix(in srgb,var(--accent,#4ADE80) 10%,transparent),0 10px 30px rgba(0,0,0,.35);transition:box-shadow .2s ease}
  :root[data-theme="light"] #ht-btn,:root[data-theme="light"] #ht-chat{background:var(--panel,#fff)}
  #ht-btn svg{width:46px;height:46px;flex-shrink:0;display:block;pointer-events:none}
  #ht-btn .ht-t{display:flex;flex-direction:column;gap:2px;text-align:left;pointer-events:none}
  #ht-btn .ht-a{font:500 14px/1.1 'Oxanium',-apple-system,Helvetica,Arial,sans-serif;letter-spacing:.2em}
  #ht-btn .ht-b{font:500 9.5px/1.2 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.14em;color:var(--muted,#9FB3A5);text-transform:uppercase}
  #ht-btn::before,#ht-btn::after{content:'';position:absolute;left:31px;top:50%;width:56px;height:56px;margin:-28px 0 0 -28px;border-radius:50%;border:1.5px solid var(--accent,#4ADE80);opacity:0;pointer-events:none}
  #ht-btn.live{box-shadow:0 0 0 8px color-mix(in srgb,var(--accent,#4ADE80) 22%,transparent),0 10px 30px rgba(0,0,0,.35)}
  #ht-btn.live::before,#ht-btn.live::after{animation:htPing 1.6s ease-out infinite}#ht-btn.live::after{animation-delay:.8s}
  #ht-btn.busy{border-color:var(--review,#FBBF24)}#ht-btn.busy .ht-b{color:var(--review,#FBBF24)}
  @keyframes htPing{0%{transform:scale(.8);opacity:.8}100%{transform:scale(1.9);opacity:0}}
  #ht-chat{display:flex;align-items:center;gap:8px;height:44px;padding:0 14px;border-radius:22px;border:1px solid var(--line,#1C2E21);background:var(--panel-2,#050B07);
  color:var(--muted,#9FB3A5);cursor:pointer;font:500 10.5px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.14em;box-shadow:0 6px 18px rgba(0,0,0,.25)}
  #ht-chat:hover{color:var(--ink,#E6EDE7)}#ht-chat svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linejoin:round}
  #ht-panel.open ~ #ht-dock #ht-chat{display:none}
  @media (max-width:768px){#ht-btn{padding:6px;border-radius:50%;min-height:0}#ht-btn .ht-t{display:none}#ht-btn::before,#ht-btn::after{left:50%}
  #ht-dock{flex-direction:column-reverse;gap:8px}#ht-chat{width:44px;padding:0;justify-content:center}#ht-chat span{display:none}}
  @media (prefers-reduced-motion:reduce){#ht-btn.live::before,#ht-btn.live::after{animation:none;opacity:.6}}
  #ht-panel{position:fixed;left:18px;top:18px;width:380px;height:320px;z-index:9999;background:var(--panel,#0F1D14);color:var(--ink,#E6EDE7);
  border:1px solid var(--line,#1C2E21);border-radius:10px;box-shadow:0 14px 36px rgba(0,0,0,.4);font:14px/1.45 'Inter',-apple-system,Helvetica,Arial,sans-serif;display:none;flex-direction:column;overflow:hidden}
  #ht-panel.open{display:flex}
  #ht-grip{flex-shrink:0;height:40px;display:flex;align-items:center;justify-content:space-between;padding:0 6px 0 14px;cursor:move;touch-action:none;border-bottom:1px solid var(--line,#1C2E21);
  font:500 10px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.16em;color:var(--muted,#9FB3A5);-webkit-user-select:none;user-select:none;background:var(--panel-2,#050B07)}
  :root[data-theme="light"] #ht-grip{background:var(--bg,#EEF3EF)}
  #ht-grip .dots{display:inline-block;width:14px;height:10px;margin-right:9px;vertical-align:-1px;background:radial-gradient(circle,currentColor 1.1px,transparent 1.3px) 0 0/5px 5px;opacity:.7}
  #ht-min{background:none;border:none;color:var(--muted,#9FB3A5);font:inherit;letter-spacing:inherit;cursor:pointer;min-height:40px;min-width:56px;padding:0 8px}
  #ht-min:hover{color:var(--ink,#E6EDE7)}
  #ht-size{position:absolute;right:0;bottom:0;width:28px;height:28px;cursor:nwse-resize;touch-action:none;
  background:linear-gradient(135deg,transparent 55%,var(--muted,#9FB3A5) 55%,var(--muted,#9FB3A5) 60%,transparent 60%,transparent 70%,var(--muted,#9FB3A5) 70%,var(--muted,#9FB3A5) 75%,transparent 75%);opacity:.6}
  #ht-log{flex:1;min-height:0;overflow:auto;padding:10px 14px}
  #ht-log .u,#ht-log .b{margin:7px 0}#ht-log .u{color:var(--ink,#E6EDE7)}#ht-log .u.live{color:var(--muted,#9FB3A5);font-style:italic}
  #ht-log .who{font:500 11px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;color:var(--muted,#9FB3A5);text-transform:uppercase;margin-right:8px;font-style:normal}
  #ht-log .b .who{color:var(--accent-text,#4ADE80)}
  #ht-log .hint{color:var(--muted,#9FB3A5);font-size:13px}
  #ht-log .thinking{color:var(--muted,#9FB3A5)}#ht-log .thinking .dots::after{content:'';animation:htDots 1.2s steps(4,end) infinite}
  @keyframes htDots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
  #ht-log .act{margin:4px 0;font:500 10.5px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--accent-text,#4ADE80)}
  #ht-log .act::before{content:'→ '}
  #ht-row{display:flex;gap:6px;padding:10px 34px 10px 10px;border-top:1px solid var(--line,#1C2E21)}
  #ht-row input{flex:1;min-width:0;background:var(--bg,#0A140D);border:1px solid var(--line,#1C2E21);color:var(--ink,#E6EDE7);border-radius:6px;padding:9px;font:16px 'Inter',-apple-system,sans-serif}
  #ht-row button{background:transparent;border:1px solid var(--line,#1C2E21);color:var(--muted,#9FB3A5);border-radius:6px;padding:0 10px;cursor:pointer;min-height:40px;font:500 10.5px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase}
  #ht-row button:hover{color:var(--ink,#E6EDE7)}
  #ht-mode{font:500 10px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.08em;color:var(--muted,#9FB3A5);padding:0 14px 8px}`;
  const MARK = '<svg viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="htG" x1="0.2" y1="0" x2="0.6" y2="1"><stop offset="0" stop-color="#4ADE80"/><stop offset="0.55" stop-color="#16A34A"/><stop offset="1" stop-color="#052E16"/></linearGradient></defs><path fill="url(#htG)" d="M32 3 L56 11 V30 C56 45 46 55 32 61 C18 55 8 45 8 30 V11 Z"/><polygon fill="#DCFCE7" stroke="#052E16" stroke-width="1.6" stroke-linejoin="round" points="32,19 41.5,24.5 41.5,35.5 32,41 22.5,35.5 22.5,24.5"/></svg>';
  const BUBBLE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/></svg>';
  let cfg = {}, hist = [], rec = null, hands = false, busy = false, listening = false, holdTimer = 0, holding = false, live = null;
  const $ = s => document.querySelector(s);
  const toFeet = t => t.replace(/(\d+(?:\.\d+)?) m\b/g, (_, m) => `${Math.round(m / 0.3048 / 5) * 5} feet (${m} meters)`);

  // who is talking: the name from the sign-in page (cookie), else one saved on this device, else "You"
  function userName() {
    if (cfg.userName) return cfg.userName;
    const m = document.cookie.match(/(?:^|;\s*)aero_name=([^;]*)/); let n = m ? decodeURIComponent(m[1]) : '';
    if (!n) try { n = localStorage.getItem('aero-name') || ''; } catch (e) {}
    return (n || 'You').trim();
  }
  function line(cls, who, text) {
    const d = document.createElement('div'), w = document.createElement('span');
    d.className = cls; w.className = 'who'; w.textContent = who; d.append(w, document.createTextNode(text)); return d;
  }
  function show() { const was = $('#ht-panel').classList.contains('open'); $('#ht-panel').classList.add('open'); document.body.classList.add('ht-open'); place();
    if (!was) window.dispatchEvent(new CustomEvent('heyturtle:panel', { detail: { open: true } })); }
  function hide() { $('#ht-panel').classList.remove('open'); document.body.classList.remove('ht-open'); window.dispatchEvent(new CustomEvent('heyturtle:panel', { detail: { open: false } })); }
  function log(cls, t) {
    $('#ht-log .hint') && $('#ht-log .hint').remove();
    $('#ht-log').appendChild(cls === 'b' ? line('b', 'A.E.R.O.', t) : line('u', userName(), t));
    $('#ht-log').scrollTop = 1e9; show();
  }
  // the words the mic is hearing, shown live as "NAZ: ..." and kept as the final line
  function liveText(t) {
    if (!live) { $('#ht-log .hint') && $('#ht-log .hint').remove(); live = line('u live', userName(), ''); $('#ht-log').appendChild(live); show(); }
    live.lastChild.textContent = t || '…'; $('#ht-log').scrollTop = 1e9;
  }
  function liveDone(t) { if (!live) return; if (t) { live.lastChild.textContent = t; live.classList.remove('live'); } else live.remove(); live = null; }

  let audio = null, cloudVoice = true, unlocked = false;   // ElevenLabs via the server; falls back to the browser's best voice
  // iPhone Safari only plays audio that starts during a tap. A.E.R.O.'s reply arrives seconds later, so on the
  // first tap we play a tiny silent clip on one <audio> element and reuse that element for every reply.
  const SILENT = 'data:audio/wav;base64,UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YSADAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==';
  function unlockAudio() {
    if (unlocked) return; unlocked = true;
    try { audio = audio || new Audio(); audio.setAttribute('playsinline', ''); audio.onerror = null; audio.src = SILENT; audio.play().catch(() => { unlocked = false; }); } catch (e) {}
    try { speechSynthesis.speak(new SpeechSynthesisUtterance('')); } catch (e) {}
  }
  function stopTalking() { try { speechSynthesis.cancel(); audio && audio.pause(); } catch (e) {} }
  function browserSpeak(t) { try { const u = new SpeechSynthesisUtterance(t); u.lang = 'en-US';
    const vs = speechSynthesis.getVoices().filter(v => /^en(-|_)US/.test(v.lang));
    const v = vs.find(v => /Premium|Enhanced|Neural|Natural/i.test(v.name)) || vs.find(v => /Ava|Zoe|Samantha|Google US|Allison/.test(v.name));
    if (v) u.voice = v; speechSynthesis.speak(u); } catch (e) {} }
  // ElevenLabs streams through the server: the <audio> starts playing the first chunk while the rest is still being made.
  // If the server has no voice (no key, out of credits, timeout) the device's own voice reads it instead.
  async function speak(t) {
    stopTalking(); t = toFeet(t);
    if (cloudVoice && cfg.voice !== 'browser') {
      audio = audio || new Audio(); audio.setAttribute('playsinline', '');
      let fell = false;
      const fallback = why => { if (fell) return; fell = true; $('#ht-mode').textContent += ' · voice: browser (' + why + ')'; browserSpeak(t); };
      audio.onerror = () => fallback('no ElevenLabs audio, see server window');
      audio.src = (cfg.apiBase || '') + '/assistant/speak.mp3?text=' + encodeURIComponent(t.slice(0, 800));
      try { await audio.play(); if (!fell) $('#ht-mode').textContent += ' · voice: ElevenLabs'; }
      catch (e) { fallback(e.name); }
      return;
    }
    browserSpeak(t);
  }
  // what A.E.R.O. did, shown as it happens: "→ LOGGED SPOT 1 · FALSE ALARM", "→ ZOOMED IN"
  const STATUS_WORD = { relocated: 'relocated', false_positive: 'false alarm', confirmed: 'confirmed', open: 'open' };
  function actionText(x) {
    const i = x.input || x, id = i.alert_id ? ('SPOT ' + String(i.alert_id).replace(/\D/g, '')) : '';
    if (x.tool === 'update_alert') return 'Logged ' + id + (i.status ? ' · ' + STATUS_WORD[i.status] : '') + (i.species ? ' · ' + i.species : '');
    if (x.tool === 'get_relocation') return 'Relocation guide · ' + id;
    if (x.tool !== 'control_app' && !i.action) return '';
    return ({ zoom_in: 'Zoomed in', zoom_out: 'Zoomed out', recenter: 'Recentered on the site', open_alert: 'Opened ' + id,
      close_alert: 'Closed the alert', layer: 'Map layer · ' + (i.value || '').replace('_', ' '), tab: 'Showing ' + (i.value === 'flights' ? 'flight windows' : 'alerts'),
      filter: 'Filter · ' + i.value, theme: (i.value || 'dark') + ' theme', list: 'Alert list ' + (i.value === 'down' ? 'down' : 'up'), chat: 'Chat hidden' })[i.action] || i.action;
  }
  function act(t) { if (!t) return; const d = document.createElement('div'); d.className = 'act'; d.textContent = t; $('#ht-log').appendChild(d); $('#ht-log').scrollTop = 1e9; }
  function runUi(cmds) { (cmds || []).forEach(c => { try { cfg.onCommand && cfg.onCommand(c); } catch (e) { console.warn('A.E.R.O. command', c, e); } window.dispatchEvent(new CustomEvent('heyturtle:command', { detail: c })); }); }

  // simple screen commands run instantly on the phone, no server round trip ("zoom in", "show spot 3", "dark mode")
  const NUM = { one: 1, two: 2, three: 3, four: 4, for: 4, five: 5, six: 6, seven: 7, eight: 8, ate: 8, nine: 9, ten: 10 };
  function localCommand(text) {
    const t = text.toLowerCase().replace(/[.!?,]/g, ' ').replace(/\b(please|can you|could you|a\.?e\.?r\.?o\.?|aero|hey)\b/g, ' ').replace(/\s+/g, ' ').trim();
    let m;
    if ((m = t.match(/^zoom (in|out)( a lot| more| all the way)?$/))) return { action: 'zoom_' + m[1], value: m[2] ? '3' : '1' };
    if (/^(re ?cent(er|re)|center|centre)( the)?( map| site| on the site)?$/.test(t)) return { action: 'recenter' };
    if ((m = t.match(/^(switch to |turn on |go |use )?(dark|light|night|day) (mode|theme)$/))) return { action: 'theme', value: /dark|night/.test(m[2]) ? 'dark' : 'light' };
    if (/^(show|open|go to|pull up)( me)?( the)? flight(s| windows?)$/.test(t)) return { action: 'tab', value: 'flights' };
    if (/^(show|open|go to|pull up)( me)?( the)?( open)? alerts( list)?$/.test(t)) return { action: 'tab', value: 'alerts' };
    if ((m = t.match(/^(show|open|go to|pull up|zoom to)( me)?( the)? (spot|alert|pin) (\d+|\w+)$/)) && (+m[5] || NUM[m[5]])) return { action: 'open_alert', alert_id: String(+m[5] || NUM[m[5]]) };
    if (/^(close|back)( it| the alert| details| that)?$/.test(t)) return { action: 'close_alert' };
    if (/^(hide|close)( the)? chat$/.test(t)) return { action: 'chat', value: 'hide' };
    if ((m = t.match(/^(show|hide|turn on|turn off) (the )?(fence band|heat ?map|boundary|site boundary)$/))) return { action: 'layer', value: (/boundary/.test(m[3]) ? 'boundary' : 'fence') + (/show|on/.test(m[1]) ? '_on' : '_off') };
    return null;
  }

  async function send(text, logged) {
    text = (text || '').trim(); if (!text || busy) return; if (!logged) log('u', text);
    const quick = localCommand(text);
    if (quick) { act(actionText(quick)); runUi([quick]); $('#ht-mode').textContent = 'mode: instant (on this device)'; return; }
    busy = true; $('#ht-btn').classList.add('busy');
    const think = line('b thinking', 'A.E.R.O.', ''); think.lastChild.textContent = 'thinking'; const dots = document.createElement('span'); dots.className = 'dots'; think.appendChild(dots);
    $('#ht-log').appendChild(think); $('#ht-log').scrollTop = 1e9;
    try {
      const r = await fetch((cfg.apiBase || '') + '/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, alert_id: cfg.getAlertId ? cfg.getAlertId() : null, history: hist.slice(-8), user: userName() }) });
      const j = await r.json(); think.remove();
      if (!r.ok || j.reply == null) { const m = 'Server error ' + r.status + ': ' + JSON.stringify(j.detail || j).slice(0, 200); log('b', m); $('#ht-mode').textContent = m; busy = false; $('#ht-btn').classList.remove('busy'); return; }
      hist.push({ role: 'user', content: text }, { role: 'assistant', content: j.reply });
      (j.actions || []).forEach(x => act(actionText(x)));
      runUi(j.ui);                                   // do it on screen first...
      if (j.alerts_changed) { cfg.onAlertsChanged && cfg.onAlertsChanged(); window.dispatchEvent(new CustomEvent('heyturtle:alerts-changed')); }
      if (j.alert_id && cfg.onFocus && !(j.ui || []).some(c => c.action === 'close_alert')) cfg.onFocus(j.alert_id);
      log('b', j.reply); speak(j.reply); $('#ht-mode').textContent = 'mode: ' + j.mode;   // ...then say it
      window.dispatchEvent(new CustomEvent('heyturtle:reply', { detail: j }));
    } catch (e) { think.remove(); const m = "I can't reach the A.E.R.O. server. Check the connection."; log('b', m); speak(m); }
    busy = false; $('#ht-btn').classList.remove('busy');
  }

  // ---- listening: tap = talk until you pause, hold = walkie-talkie, hands-free = "Hey Aero ..." ----
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const WAKE = /\b(?:hey|hi|ok|okay|yo)[\s,]+(?:a\.?\s?e\.?\s?r\.?\s?o\.?|aero|aaro|airo|arrow|arrows|ero|hero|zero|aereo|turtle)\b[\s,!.?]*(.*)$/i;
  let armedAt = 0;
  const armed = () => performance.now() - armedAt < 8000;
  const speakingNow = () => (audio && !audio.paused && !audio.ended && /speak\.mp3/.test(audio.src)) || (window.speechSynthesis && speechSynthesis.speaking);
  function setListening(on) {
    listening = on; $('#ht-btn').classList.toggle('live', on || hands);
    $('#ht-btn .ht-a').textContent = hands ? 'HANDS-FREE' : on ? 'LISTENING' : 'TAP TO TALK';
    $('#ht-btn .ht-b').textContent = hands ? (armed() ? 'go ahead' : 'say “Hey Aero”') : on ? 'tap again to send' : 'or hold · “Hey Aero”';
  }
  // One short listening session at a time (works the same on iPhone Safari, Mac Safari and Chrome).
  // Tap mode sends what it heard. Hands-free restarts after every pause and only acts on "Hey Aero ..."
  // (or on the next sentence after a bare "Hey Aero"); it ignores its own voice while A.E.R.O. is talking.
  function listen(mode) {
    if (!SR) { log('b', 'Voice needs Chrome, Edge or Safari. You can type below.'); hands = false; return; }
    const r = rec = new SR(); r.lang = 'en-US'; r.interimResults = true; r.continuous = false;
    let heard = '', interim = '';
    r.onresult = e => {
      interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) heard += t; else interim += t; }
      const t = (heard + interim).trim();
      if (mode === 'tap' || (t && !speakingNow())) liveText(t);      // you see what the mic is picking up, live
    };
    r.onend = () => {
      if (rec === r) rec = null;
      const t = (heard || interim).trim();
      if (mode === 'tap') { liveDone(t); setListening(false); if (t) send(t, true); return; }
      let cmd = '';
      if (t && !speakingNow() && !busy) {
        const m = t.match(WAKE);
        if (m) { cmd = m[1].trim(); if (!cmd) { armedAt = performance.now(); liveDone(''); log('b', 'Yes?'); browserSpeak('Yes?'); } }
        else if (armed()) cmd = t;
      }
      if (cmd) { armedAt = 0; liveDone(cmd); send(cmd, true); } else if (live) liveDone('');
      if (hands) setTimeout(resume, 200); else setListening(false);
    };
    r.onerror = e => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        hands = false; $('#ht-hf').textContent = 'Hands-free'; setListening(false);
        log('b', 'Microphone blocked: allow it in Settings, and use https or localhost.');
      }
    };
    try { r.start(); setListening(true); } catch (e) { if (mode === 'hands') setTimeout(resume, 600); else setListening(false); }
  }
  function resume() { if (!hands || rec) return; if (speakingNow() || busy) { setTimeout(resume, 300); return; } listen('hands'); setListening(true); }
  const startTalk = () => { if (listening) return; stopTalking(); listen('tap'); };
  const stopTalk = () => { try { rec && rec.stop(); } catch (e) {} };

  // ---- the chat window: drag the top bar to move, drag the corner to resize; remembered per device ----
  const phone = () => innerWidth <= 768, key = () => 'aero-chat-rect-' + (phone() ? 'phone' : 'desk');
  let rect = null;
  function defaultRect() {
    const w = phone() ? innerWidth - 16 : 380, h = phone() ? Math.round(innerHeight * 0.4) : 320, d = $('#ht-dock').getBoundingClientRect();
    return phone() ? { x: 8, y: innerHeight - h - 8, w, h } : { x: d.right - w, y: d.top - h - 12, w, h };
  }
  function clamp(r) {
    r.w = Math.min(Math.max(r.w, 260), innerWidth - 16); r.h = Math.min(Math.max(r.h, 170), innerHeight - 16);
    r.x = Math.min(Math.max(r.x, 8), innerWidth - r.w - 8); r.y = Math.min(Math.max(r.y, 8), innerHeight - r.h - 8); return r;
  }
  function place(save) {
    if (!rect) { let r = null; try { r = JSON.parse(localStorage.getItem(key()) || 'null'); } catch (e) {} rect = r && r.w ? r : defaultRect(); }
    clamp(rect); Object.assign($('#ht-panel').style, { left: rect.x + 'px', top: rect.y + 'px', width: rect.w + 'px', height: rect.h + 'px' });
    if (save) try { localStorage.setItem(key(), JSON.stringify(rect)); } catch (e) {}
  }
  function dragger(el, apply) {
    el.addEventListener('pointerdown', e => {
      if (e.target.closest('button')) return; e.preventDefault(); el.setPointerCapture(e.pointerId);
      const x0 = e.clientX, y0 = e.clientY, r0 = { ...rect };
      const mv = ev => { apply(r0, ev.clientX - x0, ev.clientY - y0); place(); };
      const up = () => { el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); place(true); };
      el.addEventListener('pointermove', mv); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    });
  }

  window.HeyTurtle = {
    init(c = {}) {
      cfg = c; if ($('#ht-btn')) return;
      const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
      document.body.insertAdjacentHTML('beforeend', `<div id="ht-panel" role="region" aria-label="A.E.R.O. conversation">
        <div id="ht-grip" title="Drag to move"><span><span class="dots"></span>A.E.R.O.</span><button id="ht-min" type="button">HIDE</button></div>
        <div id="ht-log"><div class="hint">Tap the shield and talk, hold it like a walkie-talkie, or type below.</div></div><div id="ht-mode"></div>
        <div id="ht-row"><input id="ht-in" placeholder="Type instead…" enterkeyhint="send" autocomplete="off"><button id="ht-hf" type="button">Hands-free</button></div>
        <div id="ht-size" title="Drag to resize" aria-hidden="true"></div></div>
        <div id="ht-dock"><button id="ht-chat" type="button" aria-label="Show A.E.R.O. chat">${BUBBLE}<span>CHAT</span></button>
        <button id="ht-btn" type="button" aria-label="Talk to A.E.R.O.">${MARK}<span class="ht-t"><span class="ht-a">TAP TO TALK</span><span class="ht-b">or hold · “Hey Aero”</span></span></button></div>`);
      if (c.position === 'left') { $('#ht-dock').style.left = '18px'; $('#ht-dock').style.right = 'auto'; }
      const b = $('#ht-btn');
      // tap: listen until you pause (tap again to send early). Hold past 0.35 s: listen until you let go.
      b.addEventListener('pointerdown', e => {
        e.preventDefault(); unlockAudio();
        if (hands) { armedAt = performance.now(); setListening(true); liveText(''); return; }
        if (listening) { stopTalk(); return; }
        holding = false; startTalk(); holdTimer = setTimeout(() => { holding = true; }, 350);
      });
      const release = () => { clearTimeout(holdTimer); if (holding) { holding = false; stopTalk(); } };
      b.addEventListener('pointerup', release); b.addEventListener('pointercancel', release);
      b.addEventListener('contextmenu', e => e.preventDefault());
      b.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); unlockAudio(); listening ? stopTalk() : startTalk(); } });
      $('#ht-in').addEventListener('keydown', e => { unlockAudio(); if (e.key === 'Enter') { send(e.target.value); e.target.value = ''; } });
      $('#ht-min').onclick = hide;
      $('#ht-chat').onclick = () => { show(); $('#ht-in').focus({ preventScroll: true }); };
      dragger($('#ht-grip'), (r0, dx, dy) => { rect.x = r0.x + dx; rect.y = r0.y + dy; });
      dragger($('#ht-size'), (r0, dx, dy) => { rect.w = r0.w + dx; rect.h = r0.h + dy; });
      let lastPhone = phone();
      addEventListener('resize', () => { if (phone() !== lastPhone) { lastPhone = phone(); rect = null; } if ($('#ht-panel').classList.contains('open')) place(); });
      $('#ht-hf').onclick = () => { unlockAudio(); hands = !hands; $('#ht-hf').textContent = hands ? 'Hands-free on' : 'Hands-free';
        if (hands) { stopTalk(); log('b', 'Hands-free on. Say "Hey Aero" and then what you need.'); setTimeout(resume, 250); }
        else { stopTalk(); liveDone(''); setListening(false); } };
      const typing = () => ['INPUT', 'TEXTAREA'].includes((document.activeElement || {}).tagName);
      addEventListener('keydown', e => { if (e.code === 'Space' && !typing() && !e.repeat && document.activeElement !== b) { e.preventDefault(); unlockAudio(); holding = true; startTalk(); } });
      addEventListener('keyup', e => { if (e.code === 'Space' && !typing() && holding) { e.preventDefault(); holding = false; stopTalk(); } });
    },
    send, speak, userName, show, hide,
  };
})();
