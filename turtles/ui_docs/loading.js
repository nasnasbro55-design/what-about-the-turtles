/* A.E.R.O. loading screen (canvas artboard 07): radar + a wireframe that morphs turtle -> shield -> drone -> turtle.
 *   const L = AeroLoading.show({ site: 'Grayson Overlook' });
 *   L.step(i, label)   // 0 site, 1 habitat map, 2 alerts, 3 voice: marks step i done and shows the label
 *   L.ready()          // all loaded: shows ENTER (the morph keeps looping until the responder presses it)
 *   L.close()          // remove it (ENTER calls this); also Esc / Enter key
 * Skips itself with ?skip in the URL. Reduced motion: one still frame, no glitch, no loop. */
(function () {
  const css = `
#aero-load{position:fixed;inset:0;z-index:20000;background:#0A140D;color:#E6EDE7;font-family:'Oxanium',sans-serif;overflow:hidden;transition:opacity .45s ease}
#aero-load.out{opacity:0;pointer-events:none}
#aero-load canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
#aero-load .al-top{position:absolute;left:clamp(16px,3vw,40px);right:clamp(16px,3vw,40px);top:max(20px,env(safe-area-inset-top));display:flex;align-items:center;justify-content:space-between;gap:12px}
#aero-load .al-brand{display:flex;align-items:center;gap:12px;min-width:0}
#aero-load .mono{font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.2em;text-transform:uppercase}
#aero-load .al-sub{color:#9FB3A5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#aero-load .al-form{color:#4ADE80;white-space:nowrap}
#aero-load .al-bot{position:absolute;left:16px;right:16px;bottom:max(36px,calc(env(safe-area-inset-bottom) + 20px));display:flex;flex-direction:column;align-items:center;gap:16px}
#aero-load .title{position:relative;font-size:clamp(46px,7vw,66px);font-weight:300;letter-spacing:.04em;line-height:1}
#aero-load .al-status{width:min(420px,100%);display:flex;flex-direction:column;gap:10px}
#aero-load .al-row{display:flex;justify-content:space-between;gap:12px;font-size:11.5px;letter-spacing:.14em}
#aero-load .al-bar{height:3px;background:#1C2E21}
#aero-load .al-fill{height:3px;width:0;background:linear-gradient(90deg,#4ADE80,#16A34A);transition:width .5s ease}
#aero-load .al-enter{visibility:hidden;background:#16A34A;border:1px solid #4ADE80;color:#04140A;font-family:'Oxanium',sans-serif;font-weight:500;font-size:18px;letter-spacing:.28em;padding:12px 34px;border-radius:4px;cursor:pointer;min-height:48px;min-width:180px}
#aero-load .al-enter:hover,#aero-load .al-enter:focus-visible{background:#22C55E;outline:2px solid #DCFCE7;outline-offset:3px}
#aero-load .al-enter.on{visibility:visible}
#aero-load .g{opacity:0}
#aero-load.run .g{animation:alIn .8s steps(1,end) both}
#aero-load.run .d1{animation-delay:.2s}#aero-load.run .d3{animation-delay:.6s}#aero-load.run .d4{animation-delay:1.5s}#aero-load.run .d5{animation-delay:1.85s}
#aero-load .al-enter.on{animation:alIn .8s steps(1,end) both}
@keyframes alIn{0%{opacity:0;transform:translateX(-10px);clip-path:inset(42% 0 44% 0)}12%{opacity:1;transform:translateX(7px) skewX(-10deg);clip-path:inset(8% 0 72% 0)}24%{opacity:.3;transform:translateX(-5px);clip-path:inset(62% 0 6% 0)}36%{opacity:1;transform:translateX(4px);clip-path:inset(0 0 0 0)}48%{opacity:.6;transform:translateX(-3px) skewX(6deg);clip-path:inset(28% 0 36% 0)}60%{opacity:1;transform:translateX(2px);clip-path:inset(0 0 0 0)}74%{opacity:.85;transform:translateX(-1px);clip-path:inset(70% 0 0 0)}86%,100%{opacity:1;transform:none;clip-path:inset(0 0 0 0)}}
#aero-load .title::before,#aero-load .title::after{content:attr(data-text);position:absolute;left:0;top:0;width:100%;opacity:0;pointer-events:none}
#aero-load.run .title::before{color:#4ADE80;animation:alA .95s steps(1,end) 1.5s both}
#aero-load.run .title::after{color:#86EFAC;animation:alB .95s steps(1,end) 1.5s both}
@keyframes alA{0%{opacity:.85;transform:translate(-6px,1px);clip-path:inset(0 0 62% 0)}20%{transform:translate(5px,-1px);clip-path:inset(55% 0 12% 0)}40%{transform:translate(-4px,0);clip-path:inset(18% 0 52% 0)}60%{opacity:.6;transform:translate(3px,0);clip-path:inset(72% 0 0 0)}80%{opacity:.4;transform:translate(-2px,0);clip-path:inset(35% 0 40% 0)}100%{opacity:0;transform:none}}
@keyframes alB{0%{opacity:.7;transform:translate(6px,-1px);clip-path:inset(60% 0 8% 0)}20%{transform:translate(-5px,1px);clip-path:inset(5% 0 70% 0)}40%{transform:translate(4px,0);clip-path:inset(48% 0 22% 0)}60%{opacity:.5;transform:translate(-3px,0);clip-path:inset(0 0 75% 0)}80%{opacity:.3;transform:translate(2px,0);clip-path:inset(62% 0 15% 0)}100%{opacity:0;transform:none}}
@media (max-width:600px){#aero-load .al-sub{display:none}}
@media (prefers-reduced-motion: reduce){#aero-load .g,#aero-load .al-enter.on{animation:none!important;opacity:1}#aero-load.run .title::before,#aero-load.run .title::after{animation:none}#aero-load .al-fill{transition:none}}`;
  const SHIELD = '<svg width="28" height="28" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="alG" x1="0.2" y1="0" x2="0.6" y2="1"><stop offset="0" stop-color="#4ADE80"/><stop offset="0.55" stop-color="#16A34A"/><stop offset="1" stop-color="#052E16"/></linearGradient></defs><path fill="url(#alG)" d="M32 3 L56 11 V30 C56 45 46 55 32 61 C18 55 8 45 8 30 V11 Z"/><polygon fill="#DCFCE7" stroke="#052E16" stroke-width="1.6" stroke-linejoin="round" points="32,19 41.5,24.5 41.5,35.5 32,41 22.5,35.5 22.5,24.5"/></svg>';

  class Engine {
    constructor(cv) {
      this.cv = cv;
      this.names = { turtle: 'FORM 01 · TURTLE', shield: 'FORM 02 · SHIELD', drone: 'FORM 03 · DRONE' };
      this.cycle = [['hold', 'turtle', 'turtle', 10], ['morph', 'turtle', 'shield', 1.8], ['hold', 'shield', 'shield', 6], ['morph', 'shield', 'drone', 1.8], ['hold', 'drone', 'drone', 7], ['morph', 'drone', 'turtle', 1.8]];
      this.resize();
    }
    resize() { this.W = innerWidth; this.H = innerHeight; this.build(); }
  mk() {
    const V = [], E = [], P = [{ kind: 'body' }]; let part = 0;
    const v = (x, y, z, c, w) => { V.push({ x, y, z, c, w: w ?? 1, part }); return V.length - 1; };
    const e = (a, b) => E.push([a, b]);
    const setPart = (q) => { P.push(q); part = P.length - 1; }, bodyPart = () => { part = 0; };
    const mesh = (ox, oy, oz, rx, ry, rz, nLat, nLon, dome, c, w) => {
      const top = v(ox, oy + ry, oz, c, w), rings = [], last = dome ? nLat : nLat - 1;
      for (let i = 1; i <= last; i++) {
        const th = (dome ? Math.PI / 2 : Math.PI) * i / nLat, ring = [], off = i % 2 ? Math.PI / nLon : 0;
        for (let j = 0; j < nLon; j++) { const ph = 2 * Math.PI * j / nLon + off; ring.push(v(ox + rx * Math.sin(th) * Math.cos(ph), oy + ry * Math.cos(th), oz + rz * Math.sin(th) * Math.sin(ph), c, w)); }
        rings.push(ring);
      }
      rings[0].forEach((k) => e(top, k));
      rings.forEach((ring, q) => ring.forEach((k, j) => {
        e(k, ring[(j + 1) % nLon]);
        const nx = rings[q + 1]; if (!nx) return;
        if (q % 2 === 0) { e(k, nx[j]); e(k, nx[(j + 1) % nLon]); } else { e(k, nx[(j + nLon - 1) % nLon]); e(k, nx[j]); }
      }));
      if (!dome) { const bot = v(ox, oy - ry, oz, c, w); rings[rings.length - 1].forEach((k) => e(bot, k)); }
      return rings;
    };
    return { V, E, P, v, e, setPart, bodyPart, mesh };
  }
  turtle() {
    const T = this.mk(), { V, v, e, mesh, setPart } = T;
    const shell = mesh(0, 0, 0, 150, 108, 112, 5, 20, true, 'shell'), rim = shell[shell.length - 1];
    const flare = rim.map((k) => v(V[k].x * 1.08, -7, V[k].z * 1.08, 'rim'));
    rim.forEach((k, j) => { e(k, flare[j]); e(flare[j], flare[(j + 1) % flare.length]); });
    setPart({ kind: 'head', px: 140, py: 2, pz: 0 });
    mesh(162, 4, 0, 32, 16, 16, 3, 8, false, 'skin');
    mesh(202, 14, 0, 34, 22, 20, 4, 10, false, 'skin');
    v(222, 24, 14, 'eye'); v(222, 24, -14, 'eye');
    const claws = (fx, fy, fz) => [-7, 0, 7].forEach((dz) => { const a = v(fx, fy, fz + dz, 'skin'), b = v(fx + 9, fy - 4, fz + dz * 1.2, 'claw'); e(a, b); });
    const leg = (x, z, front, phase) => {
      setPart({ kind: 'leg', px: x, py: -4, pz: z, phase });
      if (front) { mesh(x + 8, -16, z, 14, 14, 13, 3, 8, false, 'skin'); mesh(x + 14, -36, z, 10, 17, 10, 3, 8, false, 'skin'); mesh(x + 22, -53, z, 15, 5, 12, 2, 8, false, 'skin'); claws(x + 35, -54, z); }
      else { mesh(x - 6, -17, z, 18, 15, 15, 3, 8, false, 'skin'); mesh(x - 8, -37, z, 13, 17, 13, 3, 8, false, 'skin'); mesh(x - 4, -53, z, 17, 5, 14, 2, 8, false, 'skin'); claws(x + 11, -55, z); }
    };
    leg(96, 76, true, 0); leg(96, -76, true, Math.PI); leg(-94, 72, false, Math.PI); leg(-94, -72, false, 0);
    setPart({ kind: 'tail', px: -146, py: -2, pz: 0 });
    mesh(-166, -4, 0, 22, 7, 7, 2, 6, false, 'skin');
    T.rgb = V.map((p) => { const f = p.c === 'shell' ? Math.max(0, p.y) / 108 : p.c === 'rim' ? 0 : p.c === 'eye' ? 3 : 0.55; return f > 2 ? [220, 252, 231] : [21 + 53 * f, 128 + 94 * f, 61 + 67 * f]; });
    return T;
  }
  shield() {
    const S = this.mk(), { v, e } = S, sp = [];
    const ln = (a, b, n) => { for (let i = 0; i < n; i++) sp.push([a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n]); };
    const cb = (p0, p1, p2, p3, n) => { for (let i = 0; i < n; i++) { const t = i / n, u = 1 - t; sp.push([u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0], u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]]); } };
    ln([32, 3], [56, 11], 6); ln([56, 11], [56, 30], 5); cb([56, 30], [56, 45], [46, 55], [32, 61], 8); cb([32, 61], [18, 55], [8, 45], [8, 30], 8); ln([8, 30], [8, 11], 5); ln([8, 11], [32, 3], 6);
    const W = ([a, b]) => [(a - 32) * 5, (32 - b) * 5], dome = (x, y) => 18 + 16 * Math.max(0, 1 - (x / 125) ** 2 - (y / 150) ** 2), n = sp.length;
    const F = sp.map((p) => { const [x, y] = W(p); return v(x, y, 18, 'sh'); });
    const B = sp.map((p) => { const [x, y] = W(p); return v(x, y, -18, 'back', 0.55); });
    const I = sp.map((p) => { const [x, y] = W(p), ix = x * 0.78, iy = 8 + (y - 8) * 0.78; return v(ix, iy, dome(ix, iy), 'sh'); });
    for (let i = 0; i < n; i++) { const j = (i + 1) % n; e(F[i], F[j]); e(B[i], B[j]); e(I[i], I[j]); e(F[i], B[i]); if (i % 2 === 0) e(I[i], F[i]); }
    const poly = I.map((k) => [S.V[k].x, S.V[k].y]), inside = (x, y) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
    const grid = {}, c1 = W([32, 30]);
    for (let r = -8; r <= 8; r++) for (let q = -8; q <= 8; q++) {
      const x = q * 22 + (r % 2 ? 11 : 0), y = r * 19;
      if (!inside(x, y) || Math.hypot(x - c1[0], (y - c1[1]) * 1.1) < 52) continue;
      grid[r + ',' + q] = v(x, y, dome(x, y), 'sh', 0.5);
    }
    for (const key in grid) { const [r, q] = key.split(',').map(Number), o = r % 2 ? 1 : 0; [[r, q + 1], [r + 1, q - 1 + o], [r + 1, q + o]].forEach(([a, b]) => { const k2 = grid[a + ',' + b]; if (k2 !== undefined) e(grid[key], k2); }); }
    const hx = [[32, 21], [39.8, 25.5], [39.8, 34.5], [32, 39], [24.2, 34.5], [24.2, 25.5]].map((p) => { const [x, y] = W(p); return v(x, y, dome(x, y) + 4, 'core'); });
    const c0 = W([32, 30]), mid = v(c0[0], c0[1], dome(c0[0], c0[1]) + 6, 'core');
    hx.forEach((k, i) => {
      e(k, hx[(i + 1) % 6]); e(mid, k);
      const hp = S.V[k], dx = hp.x - c0[0], dy = hp.y - c0[1], L = Math.hypot(dx, dy);
      let best = 0, bd = -2; I.forEach((q, j) => { const qp = S.V[q], qx = qp.x - c0[0], qy = qp.y - c0[1], d = (qx * dx + qy * dy) / (Math.hypot(qx, qy) * L); if (d > bd) { bd = d; best = j; } });
      e(k, I[best]);
    });
    S.rgb = S.V.map((p) => { if (p.c === 'core') return [220, 252, 231]; const f = Math.min(1, Math.max(0, (p.y + 145) / 290)); return [21 + 53 * f, 128 + 94 * f, 61 + 67 * f]; });
    return S;
  }
  drone() {
    const D = this.mk(), { v, e, mesh, setPart, bodyPart } = D;
    mesh(0, 0, 0, 52, 18, 36, 4, 14, false, 'body');
    mesh(38, -18, 0, 9, 9, 9, 3, 6, false, 'cam');
    [[95, 95, 1], [95, -95, -1], [-95, 95, -1], [-95, -95, 1]].forEach(([mx, mz, dir]) => {
      bodyPart();
      const ax = Math.sign(mx) * 28, az = Math.sign(mz) * 20, a = [], b = [];
      for (let i = 0; i <= 6; i++) { const f = i / 6, x = ax + (mx - ax) * f, z = az + (mz - az) * f; a.push(v(x, 0, z, 'arm')); b.push(v(x, 5, z, 'arm')); }
      a.forEach((k, i) => { e(k, b[i]); if (i) { e(a[i - 1], k); e(b[i - 1], b[i]); } });
      const lo = [], hi = [];
      for (let j = 0; j < 8; j++) { const ph = j / 8 * 6.2832; lo.push(v(mx + Math.cos(ph) * 11, 0, mz + Math.sin(ph) * 11, 'motor')); hi.push(v(mx + Math.cos(ph) * 11, 14, mz + Math.sin(ph) * 11, 'motor')); }
      lo.forEach((k, j) => { e(k, lo[(j + 1) % 8]); e(hi[j], hi[(j + 1) % 8]); e(k, hi[j]); });
      const disk = []; for (let j = 0; j < 18; j++) { const ph = j / 18 * 6.2832; disk.push(v(mx + Math.cos(ph) * 60, 18, mz + Math.sin(ph) * 60, 'disk', 0.35)); }
      disk.forEach((k, j) => e(k, disk[(j + 1) % 18]));
      setPart({ kind: 'prop', mx, mz, dir });
      const hub = v(mx, 20, mz, 'blade');
      [0, Math.PI].forEach((b0) => { let prev = hub; for (let r = 10; r <= 58; r += 9.6) { const k = v(mx + Math.cos(b0 + r * 0.004) * r, 20, mz + Math.sin(b0 + r * 0.004) * r, 'blade'); e(prev, k); prev = k; } });
      bodyPart();
    });
    [-30, 30].forEach((z) => {
      const rail = []; for (let i = 0; i <= 5; i++) rail.push(v(-55 + i * 22, -38, z, 'skid'));
      rail.forEach((k, i) => i && e(rail[i - 1], k));
      [-25, 25].forEach((x) => { const s0 = v(x, -10, z * 0.7, 'skid'), s1 = v(x, -24, z * 0.85, 'skid'); e(s0, s1); e(s1, rail[x < 0 ? 1 : 4]); });
    });
    const pal = { body: [74, 222, 128], cam: [134, 239, 172], arm: [34, 197, 94], motor: [22, 163, 74], disk: [74, 222, 128], blade: [220, 252, 231], skid: [34, 197, 94] };
    D.rgb = D.V.map((p) => pal[p.c]);
    return D;
  }
  build() {
    let s = 11; const r = () => (s = (s * 16807) % 2147483647) / 2147483647; this.r = r;
    const W = this.W, H = this.H;
    this.shapes = { turtle: this.turtle(), shield: this.shield(), drone: this.drone() };
    this.buf = {}; for (const k in this.shapes) this.buf[k] = this.shapes[k].V.map(() => ({}));
    const N = Math.max(...Object.values(this.shapes).map((q) => q.V.length));
    this.pts = Array.from({ length: N }, () => ({ sx: r() * W, sy: r() * H, d: r(), jx: (r() - 0.5) * 9, jy: (r() - 0.5) * 9, sw: r() < 0.5 ? -1 : 1 }));
    this.stars = Array.from({ length: Math.round(460 * W * H / 1024000) + 60 }, () => ({ x: r() * W, y: r() * H, v: 3 + r() * 12, a: 0.08 + r() * 0.32, s: r() < 0.12 ? 2 : r() < 0.5 ? 1.3 : 0.9, tw: r() * 6.28 }));
    this.blips = Array.from({ length: 9 }, () => this.newBlip());
    this.cx = W / 2; this.cy = H * (W < 700 ? 0.38 : 0.41); this.k = Math.min(W / 900, H / 800, 1.25); this.R = Math.max(W, H) * 0.55;
  }
  newBlip() { const r = this.r; return { a: r() * 6.2832, d: 170 + r() * 380, t0: -1, live: false }; }
  project(name, t) {
    const sh = this.shapes[name], out = this.buf[name], cx = this.cx, cy = this.cy;
    let Y, P0, S, bob = 0;
    if (name === 'turtle') {
      const walk = Math.min(1, Math.max(0, (t - 1.6) / 0.8));
      for (const q of sh.P) {
        if (q.kind === 'leg') q.a = walk * 0.22 * Math.sin(t * 1.8 + q.phase);
        if (q.kind === 'head') { q.yaw = walk * 0.16 * Math.sin(t * 0.7); q.pitch = walk * 0.06 * Math.sin(t * 1.8); q.slide = walk * 6 * Math.sin(t * 0.9); }
        if (q.kind === 'tail') q.yaw = walk * 0.3 * Math.sin(t * 1.8);
      }
      Y = 0.3 + 0.24 * Math.sin(t * 0.45); P0 = 0.2; S = 1.25 * (1 + 0.008 * Math.sin(t * 1.7));
    } else if (name === 'shield') { Y = 0.45 * Math.sin(t * 0.5); P0 = 0.12; S = 1.1; bob = 10 * Math.sin(t * 1.1); }
    else { Y = 0.6 + t * 0.28; P0 = 0.3 + 0.04 * Math.sin(t * 0.9); S = 1.6; bob = 8 * Math.sin(t * 1.5); }
    S *= this.k;
    const cY = Math.cos(Y), sY = Math.sin(Y), cp = Math.cos(P0), sp = Math.sin(P0);
    sh.V.forEach((p, i) => {
      let x = p.x, y = p.y, z = p.z; const q = sh.P[p.part];
      if (q.kind === 'leg' || q.kind === 'head') { const a = q.kind === 'leg' ? q.a : q.pitch, dx = x - q.px, dy = y - q.py; x = q.px + dx * Math.cos(a) - dy * Math.sin(a); y = q.py + dx * Math.sin(a) + dy * Math.cos(a); }
      if (q.kind === 'head' || q.kind === 'tail') { const dx = x - q.px, dz = z - q.pz; x = q.px + dx * Math.cos(q.yaw) - dz * Math.sin(q.yaw); z = q.pz + dx * Math.sin(q.yaw) + dz * Math.cos(q.yaw); }
      if (q.kind === 'head') x += q.slide;
      if (q.kind === 'prop') { const a = q.dir * t * 24, dx = x - q.mx, dz = z - q.mz; x = q.mx + dx * Math.cos(a) - dz * Math.sin(a); z = q.mz + dx * Math.sin(a) + dz * Math.cos(a); }
      y += bob;
      const x1 = x * cY + z * sY, z1 = -x * sY + z * cY, y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp, k = 900 / (900 + z2), o = out[i];
      o.x = cx + x1 * k * S; o.y = cy - y2 * k * S; o.near = Math.min(1, Math.max(0, 1 - (z2 + 160) / 320)); o.rgb = sh.rgb[i]; o.w = p.w; o.eye = p.c === 'eye';
    });
    return out;
  }
  phase(t) {
    if (t < 1.6) return { kind: 'intro', from: null, to: 'turtle', f: t };
    const total = this.cycle.reduce((a, c) => a + c[3], 0); let u = (t - 1.6) % total;
    for (const [kind, from, to, dur] of this.cycle) { if (u < dur) return { kind, from, to, f: u / dur, dur }; u -= dur; }
    return { kind: 'hold', from: 'turtle', to: 'turtle', f: 1 };
  }
  draw(now) {
    const cv = this.cv; if (!cv || !this.pts) return;
    const dpr = window.devicePixelRatio || 1, W = this.W, H = this.H, cx = this.cx, cy = this.cy, R = this.R, TAU = 6.2832;
    if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
    const t = (now - this.t0) / 1000, on = Math.min(1, Math.max(0, (t - 0.6) / 1.2));
    for (const st of this.stars) { c.globalAlpha = st.a * (0.7 + 0.3 * Math.sin(t * 2 + st.tw)); c.fillStyle = '#9FB3A5'; c.fillRect((st.x + t * st.v) % W, st.y, st.s, st.s); }
    if (on > 0) {
      c.lineWidth = 1; c.strokeStyle = '#22C55E';
      for (let rr = 80 * this.k; rr <= R; rr += 80 * this.k) { c.globalAlpha = 0.1 * on; c.beginPath(); c.arc(cx, cy, rr, 0, TAU); c.stroke(); }
      c.globalAlpha = 0.07 * on; c.beginPath();
      for (let k = 0; k < 8; k++) { const a = k * TAU / 8; c.moveTo(cx + Math.cos(a) * 40, cy + Math.sin(a) * 40); c.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); }
      c.stroke();
      c.globalAlpha = 0.22 * on; c.beginPath();
      for (let k = 0; k < 72; k++) { const a = k * TAU / 72, l = k % 9 === 0 ? 14 : 6; c.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); c.lineTo(cx + Math.cos(a) * (R - l), cy + Math.sin(a) * (R - l)); }
      c.stroke();
      const sweep = (-Math.PI / 2 + t * TAU / 4.5) % TAU, prev = this.prevSweep ?? sweep;
      for (let k = 0; k < 30; k++) { c.globalAlpha = 0.16 * on * (1 - k / 30); c.fillStyle = '#16A34A'; c.beginPath(); c.moveTo(cx, cy); c.arc(cx, cy, R, sweep - (k + 1) * 0.026, sweep - k * 0.026); c.closePath(); c.fill(); }
      c.globalAlpha = 0.75 * on; c.strokeStyle = '#4ADE80'; c.lineWidth = 1.6;
      c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + Math.cos(sweep) * R, cy + Math.sin(sweep) * R); c.stroke();
      const norm = (a) => ((a % TAU) + TAU) % TAU, p0 = norm(prev), p1 = norm(sweep);
      this.blips = this.blips.map((b) => {
        const crossed = p1 >= p0 ? b.a > p0 && b.a <= p1 : b.a > p0 || b.a <= p1;
        if (!b.live && crossed && on >= 1) return { ...b, live: true, t0: t };
        if (b.live && t - b.t0 > 2.4) return this.newBlip();
        return b;
      });
      this.prevSweep = sweep;
      for (const b of this.blips) {
        if (!b.live) continue;
        const bx = cx + Math.cos(b.a) * b.d, by = cy + Math.sin(b.a) * b.d, age = t - b.t0;
        c.globalAlpha = Math.max(0, 1 - age / 1.8); c.fillStyle = '#86EFAC'; c.beginPath(); c.arc(bx, by, 3, 0, TAU); c.fill();
        c.strokeStyle = '#4ADE80'; c.lineWidth = 1.2;
        for (let k = 0; k < 3; k++) { const a2 = age - k * 0.3; if (a2 < 0 || a2 > 1.8) continue; c.globalAlpha = 0.6 * (1 - a2 / 1.8); c.beginPath(); c.arc(bx, by, 4 + a2 * 52, 0, TAU); c.stroke(); }
      }
    }
    const ph = this.phase(t), B = this.project(ph.to, t), A = ph.from && ph.from !== ph.to ? this.project(ph.from, t) : null;
    const nB = B.length, nA = A ? A.length : 0, morph = ph.kind === 'morph';
    const ease = (m) => m < 0.5 ? 4 * m * m * m : 1 - (-2 * m + 2) ** 3 / 2;
    this.pts.forEach((p, i) => {
      let e;
      if (ph.kind === 'intro') { const u = Math.min(1, Math.max(0, (t - 0.1 - p.d * 0.6) / 1.5)); e = 1 - (1 - u) ** 3; }
      else if (morph) e = ease(Math.min(1, Math.max(0, (ph.f * ph.dur - p.d * 0.6) / 1.2)));
      else e = 1;
      const pb = B[i % nB], pa = A ? A[i % nA] : ph.kind === 'intro' ? { x: p.sx, y: p.sy, near: 0.5, rgb: [159, 179, 165], w: 0.6 } : pb;
      const dup = (A && i >= nA ? 1 - e : 0) + (i >= nB ? e : 0);
      let x = pa.x + (pb.x - pa.x) * e + p.jx * dup, y = pa.y + (pb.y - pa.y) * e + p.jy * dup;
      if (morph) { const sw = Math.sin(Math.PI * e) * 26 * p.sw, dx = pb.x - pa.x, dy = pb.y - pa.y, L = Math.hypot(dx, dy) || 1; x += -dy / L * sw; y += dx / L * sw; }
      p.x = x; p.y = y; p.e = e; p.dup = dup;
      p.near = pa.near + (pb.near - pa.near) * e; p.w = pa.w + (pb.w - pa.w) * e;
      p.col = 'rgb(' + Math.round(pa.rgb[0] + (pb.rgb[0] - pa.rgb[0]) * e) + ',' + Math.round(pa.rgb[1] + (pb.rgb[1] - pa.rgb[1]) * e) + ',' + Math.round(pa.rgb[2] + (pb.rgb[2] - pa.rgb[2]) * e) + ')';
      p.eye = (pb.eye && e > 0.5) || (pa.eye && e <= 0.5);
    });
    const P = this.pts, edges = (list, fade) => {
      for (const [a, b] of list) {
        const pa = P[a], pb = P[b], k = fade(pa, pb); if (k <= 0.01) continue;
        c.globalAlpha = k * (0.08 + 0.42 * (pa.near + pb.near) / 2) * Math.min(pa.w, pb.w);
        c.strokeStyle = pa.col; c.beginPath(); c.moveTo(pa.x, pa.y); c.lineTo(pb.x, pb.y); c.stroke();
      }
    };
    c.lineWidth = 1;
    if (A) edges(this.shapes[ph.from].E, (a, b) => (1 - Math.max(a.e, b.e)) ** 2);
    edges(this.shapes[ph.to].E, (a, b) => Math.min(a.e, b.e) ** 2);
    for (const p of P) {
      const z = p.eye ? 4 : (1.4 + 1.6 * p.near) * (p.w < 1 ? 0.8 : 1);
      c.globalAlpha = (ph.kind === 'intro' ? 0.3 + 0.7 * p.e : 1) * (0.35 + 0.65 * p.near) * Math.min(1, p.w + 0.2) * (1 - 0.65 * p.dup);
      c.fillStyle = p.eye ? '#DCFCE7' : p.col; c.fillRect(p.x - z / 2, p.y - z / 2, z, z);
    }
    c.globalAlpha = 1;
    const form = morph ? this.names[ph.from].slice(10) + ' → ' + this.names[ph.to].slice(10) : this.names[ph.to];
    if (form !== this.form) { this.form = form; this.onForm && this.onForm(form); }
  }
  }

  let eng = null, root = null, raf = 0, done = 0, isReady = false, closed = false, onClose = null;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = s => root.querySelector(s);
  function loop(now) { eng.draw(now); raf = requestAnimationFrame(loop); }
  function close() {
    if (!root || closed) return; closed = true;
    root.classList.add('out'); removeEventListener('keydown', onKey); removeEventListener('resize', onResize);
    setTimeout(() => { cancelAnimationFrame(raf); root.remove(); onClose && onClose(); }, 470);
  }
  function onKey(e) { if (isReady && (e.key === 'Enter' || e.key === 'Escape')) { e.preventDefault(); close(); } }
  function onResize() { if (!eng) return; const t0 = eng.t0; eng.resize(); eng.t0 = t0; if (still) eng.draw(eng.t0 + 3000); }
  function setPct() { $('.al-fill').style.width = (done / 4 * 100) + '%'; $('.al-pct').textContent = Math.round(done / 4 * 100) + '%'; }

  window.AeroLoading = {
    show(opts = {}) {
      const api = { step: () => api, ready: () => api, close: () => {} , skipped: true };
      if (/[?&]skip\b/.test(location.search)) { setTimeout(() => opts.onClose && opts.onClose(), 0); return api; }
      onClose = opts.onClose;
      const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
      root = document.createElement('div'); root.id = 'aero-load'; root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'A.E.R.O. is loading');
      root.innerHTML = `<canvas aria-hidden="true"></canvas>
        <div class="al-top"><div class="al-brand g d1">${SHIELD}<span class="mono al-sub">What About the Turtles · Field system</span></div><span class="mono al-form g d3" aria-hidden="true"></span></div>
        <div class="al-bot"><span class="title g d4" data-text="A.E.R.O.">A.E.R.O.</span>
          <div class="al-status g d5"><div class="al-row mono"><span class="al-label" style="color:#9FB3A5" aria-live="polite">LOADING SITE · ${(opts.site || 'Grayson Overlook').toUpperCase()}</span><span class="al-pct" style="color:#4ADE80">0%</span></div><div class="al-bar"><div class="al-fill"></div></div></div>
          <button class="al-enter" type="button">ENTER</button></div>`;
      document.body.appendChild(root);
      eng = new Engine($('canvas')); eng.onForm = f => { $('.al-form').textContent = f; };
      eng.t0 = performance.now();
      if (still) eng.draw(eng.t0 + 3000); else { root.classList.add('run'); raf = requestAnimationFrame(loop); }
      $('.al-enter').onclick = close;
      addEventListener('keydown', onKey); addEventListener('resize', onResize);
      const shownAt = performance.now(), minMs = still ? 0 : (opts.minMs ?? 2800);
      return Object.assign(api, {
        skipped: false,
        step(i, label) { done = Math.max(done, Math.min(4, i + 1)); if (label) $('.al-label').textContent = label; setPct(); return api; },
        ready() {
          if (isReady) return api;
          setTimeout(() => { isReady = true; done = 4; setPct(); $('.al-label').textContent = 'READY'; const b = $('.al-enter'); b.classList.add('on'); b.focus({ preventScroll: true }); },
                     Math.max(0, minMs - (performance.now() - shownAt)));
          return api;
        },
        close,
      });
    },
  };
})();
