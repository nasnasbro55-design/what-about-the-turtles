/* A.E.R.O. control layer: everything on the dashboard that A.E.R.O. can do, and everything it can see.
 *
 * Hands-free means A.E.R.O. can work every part of the dashboard without anyone touching the phone. This file is
 * the one place that makes that true:
 *   ACTIONS  - every button / field / panel as a named action with arguments. The server turns this list into
 *              A.E.R.O.'s control_app tool on every message, so adding a line here is all it takes to give A.E.R.O.
 *              a new control.
 *   screen() - a snapshot of what is on screen right now (layers, open spot, note sheet and field log values,
 *              guidance, GPS distance to every open spot, panels). Sent with every message so A.E.R.O. never guesses.
 *   run(cmd) - carries out {action, args}; the pressed button flashes; returns what happened (or why it couldn't).
 *
 * Uses the page's own functions (index.html): openDetail, updateAlertStatus, toggleZones, startNav, setRec...
 * Load after the page script:  <script src="aero-control.js"></script>
 */
(function () {
  const st = document.createElement('style');
  st.textContent = `.aero-pressed{animation:aeroPress .7s ease}
  @keyframes aeroPress{0%{box-shadow:0 0 0 3px var(--accent,#4ADE80)}100%{box-shadow:0 0 0 3px transparent}}`;
  document.head.appendChild(st);

  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const press = el => { el = typeof el === 'string' ? $(el) : el; if (!el) return; el.classList.remove('aero-pressed'); void el.offsetWidth; el.classList.add('aero-pressed'); };
  const num = a => +alertNum(a);
  const spotName = a => `Spot ${num(a)}`;
  const findSpot = id => {
    if (id == null || id === '') return null;
    const s = String(id).toLowerCase().trim();
    return alerts.find(a => a.alert_id.toLowerCase() === s) || alerts.find(a => String(a.number || alerts.indexOf(a) + 1) === s.replace(/\D/g, ''));
  };
  const noteOpen = () => !$('#noteModal').hidden;
  // A.E.R.O. moved the map on purpose: stop following the GPS, or the next GPS fix drags the map back to you
  const holdMap = () => { if (typeof followMe !== 'undefined' && followMe) { followMe = false; const b = $('#btnLocate'); b && b.classList.remove('active'); } };
  // one spot at a time: close the one that's open (and its sheet), then center and open the requested one
  function focusSpot(s, zoom) {
    holdMap();
    if (noteOpen()) closeNote(null);
    if (activeAlert && activeAlert.alert_id !== s.alert_id) closeDetail();
    map.setView([s.lat, s.lon], Math.min(21, Math.max(zoom || map.getZoom(), 18)), { animate: false });
    openDetail(s);
    if (phoneView() && document.body.classList.contains('ht-open')) setSheet('detail', true);
  }
  // zoom keeps the open spot in place (not the middle of the screen) while it is on screen
  function zoomBy(n) {
    const z = Math.max(map.getMinZoom(), Math.min(21, map.getZoom() + n));
    if (activeAlert && map.getBounds().contains([activeAlert.lat, activeAlert.lon])) map.setZoomAround([activeAlert.lat, activeAlert.lon], z);
    else map.setZoom(z);
  }
  const STATUS_KEY = { relocated: 'relocated', confirmed: 'confirmed', false_alarm: 'false_positive', false_positive: 'false_positive' };

  // ---- the field log (index.html #fieldLog), read straight from the page so new fields show up by themselves ----
  function fields() {
    const out = {};
    $$('#noteModal [data-k]').forEach(el => {
      const k = el.dataset.k; if (k === 'photos' && !el.classList.contains('seg')) return;
      const own = el.closest('label'), row = el.closest('.ex-row'), q = el.closest('.fl-q');
      const label = (own && own.firstChild && own.firstChild.textContent) || (row && row.querySelector('span').textContent) || (q && q.querySelector('.lbl') && q.querySelector('.lbl').textContent) || '';
      out[k] = { label: (label || k).replace(/\s+/g, ' ').trim().replace(/(g|mm)$/, '').trim(),
                 options: el.dataset.opts ? el.dataset.opts.split('|') : null, multi: el.classList.contains('multi'),
                 unit: el.parentElement && el.parentElement.querySelector('i') ? el.parentElement.querySelector('i').textContent : '', number: el.type === 'number' };
    });
    return out;
  }
  const SAYS = { normal: 'WNL', ok: 'WNL', fine: 'WNL', good: 'WNL', abnormal: 'ABN', bad: 'ABN', 'not examined': 'NE', skip: 'NE', 'not checked': 'NE' };
  function matchOption(opts, v) {
    const s = String(v).toLowerCase().trim();
    return opts.find(o => o.toLowerCase() === s) || opts.find(o => o === SAYS[s]) || opts.find(o => o.toLowerCase().startsWith(s)) || opts.find(o => o.toLowerCase().includes(s));
  }
  function setField(key, value) {
    const f = fields(); let k = key;
    const said = String(key).toLowerCase().replace(/_/g, ' ').trim();
    if (!f[k]) k = Object.keys(f).find(x => x.endsWith('.' + key)) || Object.keys(f).find(x => f[x].label.toLowerCase() === said)
              || Object.keys(f).find(x => f[x].label.toLowerCase().startsWith(said));   // a field key first, then its label
    if (!k) return `No field called ${key}`;
    const d = f[k];
    if (d.options) {
      const vals = d.multi ? String(value).split(/,|\band\b/).map(x => matchOption(d.options, x)).filter(Boolean) : [matchOption(d.options, value)];
      if (!vals[0]) return `${d.label}: choose ${d.options.join(', ')}`;
      if (d.multi) { const set = new Set(logRec[k] || []); vals.forEach(v => set.add(v)); logRec[k] = [...set]; } else setRec(k, vals[0]);
    } else if (d.number) { const n = parseFloat(String(value).replace(/[^\d.]/g, '')); if (isNaN(n)) return `${d.label} needs a number`; setRec(k, n); }
    else setRec(k, String(value).trim());
    paintLog();
    const el = $(`#noteModal [data-k="${k}"]`); if (el) { const det = el.closest('details'); if (det) det.open = true; press(el); }
    return `${d.label} set to ${d.multi ? logRec[k].join(', ') : getRec(k)}${d.unit ? ' ' + d.unit : ''}`;
  }

  // ---- every action A.E.R.O. can take, with its arguments ----
  const ACTIONS = {
    zoom_in:    { say: 'Zoom the map in (around the open spot if one is open)', args: { steps: 'number, default 1' }, run: a => { zoomBy(clampSteps(a.steps)); return 'Zoomed in'; } },
    zoom_out:   { say: 'Zoom the map out', args: { steps: 'number, default 1' }, run: a => { zoomBy(-clampSteps(a.steps)); return 'Zoomed out'; } },
    zoom_to_spot: { say: 'Zoom onto a spot: closes any other open spot, centers on this one, zooms in close and opens it. Use for "zoom in to / into / on spot N"', args: { spot: 'spot number', level: 'optional zoom 18-21, default 20' }, run: a => {
                    const s = findSpot(a.spot); if (!s) return `No spot ${a.spot}`;
                    focusSpot(s, parseInt(a.level, 10) || Math.max(20, map.getZoom())); return `Zoomed to ${spotName(s)}`; } },
    pan:        { say: 'Move the map', args: { direction: 'north|south|east|west', amount: 'little|lot' }, run: a => {
                    const s = map.getSize(), f = a.amount === 'lot' ? 0.6 : 0.3, d = { north: [0, -s.y * f], south: [0, s.y * f], east: [s.x * f, 0], west: [-s.x * f, 0] }[a.direction];
                    if (!d) return 'Say north, south, east or west'; holdMap(); map.panBy(d); return 'Moved the map ' + a.direction; } },
    recenter:   { say: 'Fit the map to the whole site', run: () => { holdMap(); resetMapView(); return 'Recentered on the site'; } },
    locate:     { say: 'Show my GPS position and follow it', run: () => { press('#btnLocate'); locateMe(); return 'Showing your location'; } },
    layer:      { say: 'Press a map layer button', args: { name: 'boundary (site outline) | fence_band (heat map)', state: 'on|off|toggle' }, run: a => {
                    const fence = /fence|heat/.test(a.name || ''), on = fence ? showHeatmap : showZones, want = a.state === 'toggle' || !a.state ? !on : a.state === 'on';
                    press(fence ? '#btnToggleHeatmap' : '#btnToggleZones');
                    if (want !== on) fence ? toggleHeatmap() : toggleZones();
                    return `${fence ? 'Fence band' : 'Site boundary'} ${want ? 'on' : 'off'}`; } },
    tab:        { say: 'Switch the side panel tab', args: { name: 'alerts|flights' }, run: a => {
                    if (noteOpen()) closeNote(null); closeDetail(); const f = /flight/.test(a.name || ''); press(f ? '#tabPlannerBtn' : '#tabAlertsBtn');
                    switchTab(f ? 'planner' : 'alerts'); if (phoneView()) setSheet('list', false); return f ? 'Showing flight windows' : 'Showing alerts'; } },
    filter:     { say: 'Filter the alert list', args: { name: 'all|open|resolved' }, run: a => {
                    const f = a.name === 'resolved' ? 'closed' : a.name === 'open' ? 'open' : 'all';
                    const chip = $$('.filter-chip').find(x => (x.getAttribute('onclick') || '').includes(`'${f}'`));
                    closeDetail(); switchTab('alerts'); if (chip) { press(chip); setFilter(f, chip); } return 'Showing ' + (a.name || 'all') + ' alerts'; } },
    open_spot:  { say: 'Open a spot\'s details and show it on the map', args: { spot: 'spot number' }, run: a => {
                    const s = findSpot(a.spot); if (!s) return `No spot ${a.spot}`;
                    focusSpot(s, 19); return 'Opened ' + spotName(s); } },
    next_spot:  { say: 'Open the next open spot (or the nearest open one if GPS is on)', args: { which: 'next|previous|nearest' }, run: a => {
                    const open = alerts.filter(x => x.status === 'open'); if (!open.length) return 'No open spots left';
                    let s;
                    if (a.which === 'nearest' && me) s = open.slice().sort((x, y) => distM(me, x) - distM(me, y))[0];
                    else { const i = activeAlert ? alerts.indexOf(activeAlert) : -1, list = a.which === 'previous' ? alerts.slice().reverse() : alerts, j = a.which === 'previous' ? alerts.length - 1 - i : i;
                           s = list.slice(j + 1).find(x => x.status === 'open') || list.find(x => x.status === 'open'); }
                    return ACTIONS.open_spot.run({ spot: num(s) }); } },
    close_spot: { say: 'Close the open spot\'s details', run: () => { if (noteOpen()) closeNote(null); closeDetail(); return 'Closed the details'; } },
    navigate:   { say: 'Walking guidance inside the app from my GPS position', args: { spot: 'spot number (default: the open spot)', to: 'turtle|release (release = Tanya\'s release point)' }, run: a => {
                    const s = a.spot ? findSpot(a.spot) : activeAlert; if (!s) return 'Open or name a spot first';
                    if (!activeAlert || activeAlert.alert_id !== s.alert_id) openDetail(s);
                    press('#btnNavMaps');
                    const go = () => { startNav(a.to === 'release' ? 'release' : 'turtle'); };
                    a.to === 'release' && !lastRelocation ? setTimeout(go, 900) : go();   // the relocation guide loads with the spot
                    return `Guiding you to ${a.to === 'release' ? 'the release point for ' : ''}${spotName(s)}`; } },
    stop_navigation: { say: 'Stop the walking guidance', run: () => { stopNav(); return 'Guidance stopped'; } },
    press_status: { say: 'Press a responder button on the open spot (opens the field log sheet like tapping it)', args: { status: 'relocated|confirmed|false_alarm', spot: 'optional spot number' }, run: a => {
                    const s = a.spot ? findSpot(a.spot) : activeAlert; if (!s) return 'Open or name a spot first';
                    if (!activeAlert || activeAlert.alert_id !== s.alert_id) openDetail(s);
                    const k = STATUS_KEY[a.status]; if (!k) return 'Say relocated, confirmed or false alarm';
                    press({ relocated: '.btn-relocated', confirmed: '.btn-confirmed', false_positive: '.btn-fp' }[k]);
                    setTimeout(() => updateAlertStatus(k), 120); return `Opened the ${a.status.replace('_', ' ')} sheet for ${spotName(s)}`; } },
    set_field:  { say: 'Fill a field in the open field log sheet', args: { field: 'field key (see screen field_log.fields)', value: 'value or option' }, run: a => noteOpen() ? setField(a.field, a.value) : 'Open the sheet first (press_status)' },
    set_note:   { say: 'Write the field note in the open sheet', args: { text: 'the note', mode: 'replace|append' }, run: a => {
                    if (!noteOpen()) return 'Open the sheet first (press_status)'; const t = $('#noteText');
                    t.value = a.mode === 'replace' || !t.value.trim() ? a.text : t.value.trim().replace(/[.,]$/, '') + '. ' + a.text; press(t); return 'Note updated'; } },
    add_tag:    { say: 'Tap a quick tag in the open sheet', args: { tag: 'tag text' }, run: a => {
                    const b = $$('#noteTags button').find(x => x.textContent.toLowerCase().includes(String(a.tag).toLowerCase())); if (!b) return 'No tag like ' + a.tag;
                    if (!b.classList.contains('on')) b.click(); press(b); return 'Added ' + b.textContent; } },
    save_sheet: { say: 'Press Save on the field log sheet', run: () => { if (!noteOpen()) return 'No sheet open'; press('#noteSave'); $('#noteForm').requestSubmit(); return 'Saved'; } },
    cancel_sheet: { say: 'Cancel the field log sheet without saving', run: () => { if (!noteOpen()) return 'No sheet open'; closeNote(null); return 'Cancelled'; } },
    sheet:      { say: 'Phone: slide a bottom panel up or down', args: { which: 'list|detail', state: 'up|down' }, run: a => { setSheet(a.which === 'detail' ? 'detail' : 'list', a.state === 'down'); return `${a.which || 'list'} panel ${a.state}`; } },
    chat:       { say: 'Show or hide the A.E.R.O. chat window', args: { state: 'show|hide' }, run: a => { a.state === 'show' ? HeyTurtle.show() : HeyTurtle.hide(); return 'Chat ' + (a.state === 'show' ? 'shown' : 'hidden'); } },
    theme:      { say: 'Switch the theme', args: { mode: 'dark|light' }, run: a => { press('#themeToggle'); applyTheme(a.mode === 'light' ? 'light' : 'dark'); return (a.mode === 'light' ? 'Light' : 'Dark') + ' theme'; } },
    refresh:    { say: 'Reload the alerts from the server', run: () => { loadData(); return 'Refreshed'; } },
  };
  const clampSteps = s => Math.max(1, Math.min(4, parseInt(s, 10) || 1));

  // the catalog the server turns into A.E.R.O.'s control_app tool
  function catalog() {
    return Object.entries(ACTIONS).map(([name, a]) => ({ name, say: a.say, args: a.args || {} }));
  }

  // ---- what is on screen right now ----
  function screen() {
    const s = {
      layers: `site boundary ${showZones ? 'on' : 'off'}, fence band ${showHeatmap ? 'on' : 'off'}`,
      panel: document.getElementById('tabPlanner').style.display === 'none' ? `alerts list, filter ${currentFilter === 'closed' ? 'resolved' : currentFilter}` : 'flight windows',
      theme: document.documentElement.dataset.theme, map_zoom: map.getZoom(),
      gps: typeof geoState !== 'undefined' ? (geoState === 'on' && me ? `on, ±${Math.round(me.acc)} m` : geoState) : 'off',
    };
    if (phoneView()) s.phone_panels = `alert list ${isSheetDown('list') ? 'down' : 'up'}${$('#detailSheet').classList.contains('open') ? ', details ' + (isSheetDown('detail') ? 'down' : 'up') : ''}, chat ${document.body.classList.contains('ht-open') ? 'open' : 'hidden'}`;
    if (activeAlert) {
      const a = activeAlert, rel = lastRelocation && lastRelocation.alert_id === a.alert_id ? lastRelocation : null;
      s.open_spot = `${spotName(a)} ${alertName(a).replace(/^Spot \d+:\s*/, '')} (${a.status}${a.species ? ', ' + a.species : ''}${a.sex ? ', ' + a.sex : ''})` +
        (a.note ? `; note: ${a.note}` : '') + (rel ? `; relocation guide: ${Math.round(rel.distance_m)} m ${compass(rel.bearing_deg)}` : '') +
        (me ? `; you are ${Math.round(distM(me, a))} m ${compass(bearingTo(me, a))} of it` : '');
      const log = typeof logSummary === 'function' ? logSummary(a.record, a) : ''; if (log) s.open_spot += `; field log: ${log}`;
    }
    if (me) {
      const open = alerts.filter(a => a.status === 'open').map(a => [a, distM(me, a)]).sort((x, y) => x[1] - y[1]);
      if (open.length) s.open_spots_by_distance = open.map(([a, d]) => `${spotName(a)} ${Math.round(d)} m ${compass(bearingTo(me, a))}`).join('; ');
    }
    if (typeof nav !== 'undefined' && nav) s.guidance = `${nav.kind === 'release' ? 'to the release point of' : 'to'} Spot ${+nav.num}` +
      (me ? `, ${Math.round(distM(me, nav))} m ${compass(bearingTo(me, nav))}` : ', waiting for GPS') + (nav.arrived ? ', ARRIVED' : '');
    if (noteOpen()) {
      const f = fields(), filled = Object.keys(f).filter(k => { const v = getRec(k); return v && (!Array.isArray(v) || v.length); });
      s.field_log_sheet = `open for ${$('#noteTitle').textContent}, button ${$('#noteStatus').textContent}; filled: ` +
        (filled.map(k => `${k}=${Array.isArray(getRec(k)) ? getRec(k).join('/') : getRec(k)}`).join(', ') || 'nothing yet') +
        `; note: "${$('#noteText').value}"; tags: ${$$('#noteTags button').map(b => b.textContent + (b.classList.contains('on') ? ' (on)' : '')).join(', ')}`;
      s.field_log_fields = Object.entries(f).map(([k, d]) => `${k}${d.options ? ' [' + d.options.join('|') + ']' : d.unit ? ' (' + d.unit + ')' : ''}`).join('; ');
    }
    return s;
  }

  // ---- carry out one command; the result line goes into the chat ----
  function run(c) {
    const name = c.action === 'open_alert' ? 'open_spot' : c.action === 'close_alert' ? 'close_spot' : c.action;
    const a = ACTIONS[name];
    if (!a) return `I can't do "${c.action}" yet`;
    const args = { ...(c.args || {}), ...c };   // accepts {action, args:{...}} and flat {action, spot, value}
    if (args.alert_id && !args.spot) args.spot = args.alert_id;
    if (name === 'layer' && args.value && !args.name) { args.name = args.value.split('_')[0]; args.state = args.value.split('_').pop(); }
    if (/^(tab|filter)$/.test(name) && args.value && !args.name) args.name = args.value;
    if (name === 'theme' && args.value && !args.mode) args.mode = args.value;
    if (name === 'chat' && args.value && !args.state) args.state = args.value === 'show' ? 'show' : 'hide';
    if (name === 'sheet' && args.value && !args.state) args.state = args.value;
    if (/zoom/.test(name) && args.value && !args.steps) args.steps = args.value;
    try { return a.run(args) || 'Done'; } catch (e) { console.warn('A.E.R.O. control', c, e); return `Couldn't ${name.replace('_', ' ')}: ${e.message}`; }
  }

  window.AeroControl = { ACTIONS, catalog, screen, run, fields, setField };
})();
