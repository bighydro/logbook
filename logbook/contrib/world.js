(function () {
"use strict";
var world = JSON.parse(document.getElementById("world").textContent);
var table = JSON.parse(document.getElementById("land").textContent);
var canvas = document.getElementById("globe"), ctx = canvas.getContext("2d");
var bandCanvas = document.getElementById("bands"), bctx = bandCanvas.getContext("2d");
var slider = document.getElementById("time"), readout = document.getElementById("readout");
var clockText = document.getElementById("clock"), panel = document.getElementById("panel");
var playButton = document.getElementById("play"), list = document.getElementById("list");
var RAD = Math.PI / 180, EARTH_M = 6371000, MAX_ZOOM = 20000, PLAY_S = 40;
var win = world.window, span = Math.max(1, win.minutes), gap = win.gap_min;
var view = {lon: 10, lat: 50, zoom: 1}, size = {w: 0, h: 0, r: 0, cx: 0, cy: 0, base: 1};
var rot = null, T = 0, playing = false, last = 0, hits = [], queued = [], selected = null, pending = false;
var colors = {};

function unit(lat, lon) {
  var p = lat * RAD, l = lon * RAD, c = Math.cos(p);
  return [c * Math.cos(l), c * Math.sin(l), Math.sin(p)];
}
var land = table.polygons.map(function (polygon) {
  return polygon.map(function (ring) {
    var s = table.scale, x = ring[0], y = ring[1], v = [unit(y / s, x / s)], ll = [[x / s, y / s]];
    for (var i = 2; i < ring.length; i += 2) {
      x += ring[i]; y += ring[i + 1];
      v.push(unit(y / s, x / s)); ll.push([x / s, y / s]);
    }
    return {v: v, ll: ll, t: null};
  });
});
var places = world.places, assets = world.assets, staysList = world.stays;
var journeys = world.journeys, chapters = world.chapters, summaries = world.summaries;
var assetById = {};
assets.forEach(function (a) { assetById[a.id] = a; });
var placeById = {};
places.forEach(function (p) { placeById[p.id] = p; });

/* -- the projection: an orthographic globe, x towards the viewer -- */
function rotation() {
  var l = view.lon * RAD, p = view.lat * RAD;
  return {cl: Math.cos(l), sl: Math.sin(l), cp: Math.cos(p), sp: Math.sin(p)};
}
function turn(v) {
  var x1 = v[0] * rot.cl + v[1] * rot.sl, y1 = -v[0] * rot.sl + v[1] * rot.cl;
  return [x1 * rot.cp + v[2] * rot.sp, y1, -x1 * rot.sp + v[2] * rot.cp];
}
function screen(t) { return [size.cx + size.r * t[1], size.cy - size.r * t[2]]; }
function rim(t) {
  var n = Math.sqrt(t[1] * t[1] + t[2] * t[2]) || 1;
  return [size.cx + size.r * t[1] / n, size.cy - size.r * t[2] / n];
}
function cross(a, b) {
  var k = a[0] / (a[0] - b[0]);
  return [0, a[1] + k * (b[1] - a[1]), a[2] + k * (b[2] - a[2])];
}
function project(lat, lon) {
  var t = turn(unit(lat, lon));
  return t[0] < 0 ? null : screen(t);
}

/* -- the land: each ring clamped to the horizon, filled even-odd, a polygon that holds the far
   side of the globe filled as the disc less its outline -- */
function ringPath(ring) {
  var pts = ring.t, n = pts.length, start = -1, out = [], k;
  for (k = 0; k < n; k++) { if (pts[k][0] >= 0) { start = k; break; } }
  if (start < 0) return null;
  for (k = 0; k < n; k++) {
    var a = pts[(start + k) % n], b = pts[(start + k + 1) % n];
    out.push(a[0] >= 0 ? screen(a) : rim(a));
    if ((a[0] >= 0) !== (b[0] >= 0)) out.push(rim(cross(a, b)));
  }
  return out;
}
function winding(path) {
  var total = 0, q = path[path.length - 1], prev = Math.atan2(q[1] - size.cy, q[0] - size.cx);
  for (var i = 0; i < path.length; i++) {
    var a = Math.atan2(path[i][1] - size.cy, path[i][0] - size.cx), d = a - prev;
    if (d > Math.PI) d -= 2 * Math.PI; else if (d < -Math.PI) d += 2 * Math.PI;
    total += d; prev = a;
  }
  return Math.round(total / (2 * Math.PI));
}
function holds(ring, lon, lat) {
  var ll = ring.ll, inside = false;
  for (var i = 0, j = ll.length - 1; i < ll.length; j = i++) {
    var xi = ll[i][0], yi = ll[i][1], xj = ll[j][0], yj = ll[j][1];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function drawLand() {
  ctx.fillStyle = colors.land;
  for (var p = 0; p < land.length; p++) {
    var flips = 0, any = false;
    ctx.beginPath();
    for (var r = 0; r < land[p].length; r++) {
      var ring = land[p][r];
      ring.t = ring.v.map(turn);
      var path = ringPath(ring);
      if (!path) continue;
      any = true;
      if (winding(path) !== 0 && !holds(ring, view.lon, view.lat)) flips++;
      ctx.moveTo(path[0][0], path[0][1]);
      for (var i = 1; i < path.length; i++) ctx.lineTo(path[i][0], path[i][1]);
      ctx.closePath();
    }
    if (!any) continue;
    if (flips % 2) { ctx.moveTo(size.cx + size.r, size.cy); ctx.arc(size.cx, size.cy, size.r, 0, 2 * Math.PI); }
    ctx.fill("evenodd");
  }
  ctx.strokeStyle = colors.coast; ctx.lineWidth = 0.8;
  ctx.beginPath();
  for (p = 0; p < land.length; p++) {
    for (r = 0; r < land[p].length; r++) { if (land[p][r].t) segments(land[p][r].t, true); }
  }
  ctx.stroke();
}
function segments(pts, closed) {
  var n = pts.length, end = closed ? n : n - 1;
  for (var i = 0; i < end; i++) {
    var a = pts[i], b = pts[(i + 1) % n], s, e;
    if (a[0] < 0 && b[0] < 0) continue;
    s = a[0] >= 0 ? screen(a) : rim(cross(a, b));
    e = b[0] >= 0 ? screen(b) : rim(cross(a, b));
    ctx.moveTo(s[0], s[1]); ctx.lineTo(e[0], e[1]);
  }
}
function line(latlons) {
  segments(latlons.map(function (q) { return turn(unit(q[0], q[1])); }), false);
}
function drawGraticule() {
  var dpp = 1 / (size.r * RAD), steps = [30, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01], step = 30, k;
  for (k = 0; k < steps.length; k++) { if (steps[k] / dpp >= 90) step = steps[k]; }
  var half = Math.min(90, Math.max(size.w, size.h) * dpp + step);
  var lat0 = Math.max(-90, view.lat - half), lat1 = Math.min(90, view.lat + half);
  var lonHalf = half >= 60 ? 180 : Math.min(180, half / Math.max(0.05, Math.cos(view.lat * RAD)));
  var lon0 = view.lon - lonHalf, lon1 = view.lon + lonHalf, fine = Math.min(2, step / 4), q, x, pts;
  ctx.strokeStyle = colors.grid; ctx.lineWidth = 1;
  ctx.beginPath();
  for (k = Math.ceil(lat0 / step); k * step <= lat1; k++) {
    pts = [];
    for (x = lon0; x <= lon1 + 1e-9; x += Math.max(fine, (lon1 - lon0) / 180)) pts.push([k * step, x]);
    line(pts);
  }
  for (k = Math.ceil(lon0 / step); k * step <= lon1; k++) {
    pts = [];
    for (q = lat0; q <= lat1 + 1e-9; q += Math.max(fine, (lat1 - lat0) / 180)) pts.push([q, k * step]);
    line(pts);
  }
  ctx.stroke();
}

/* -- time -- */
var zoneKnown = true, dayFormat, clockFormat, shortFormat;
function formats(zone) {
  dayFormat = new Intl.DateTimeFormat("en-GB", {timeZone: zone, weekday: "short", day: "numeric", month: "short", year: "numeric"});
  clockFormat = new Intl.DateTimeFormat("en-GB", {timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23"});
  shortFormat = new Intl.DateTimeFormat("en-GB", {timeZone: zone, day: "numeric", month: "short"});
}
try {
  formats(win.tz);
} catch {
  zoneKnown = false; /* the record's zone is not this browser's to know: say so, never guess another */
  formats("UTC");
}
function moment(m) { return new Date((win.start + m * 60) * 1000); }
function when(m) {
  var d = moment(m);
  return dayFormat.format(d) + " " + clockFormat.format(d) + (zoneKnown ? "" : " UTC (this browser does not know " + win.tz + ")");
}
function chapterAt(m) {
  var found = null;
  chapters.forEach(function (c) { if (c.t0 <= m && m <= c.t1) found = c; });
  return found;
}
function positionOf(asset, m) {
  var tr = asset.track, n = tr.length / 3;
  if (!n || m < tr[0]) return null;
  var lo = 0, hi = n - 1;
  while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (tr[mid * 3] <= m) lo = mid; else hi = mid - 1; }
  var i = lo * 3;
  if (lo === n - 1 || tr[i + 3] - tr[i] > gap) {
    return {lat: tr[i + 1], lon: tr[i + 2], seen: m - tr[i] <= gap};
  }
  var f = (m - tr[i]) / Math.max(1, tr[i + 3] - tr[i]), dl = tr[i + 5] - tr[i + 2];
  if (dl > 180) dl -= 360; else if (dl < -180) dl += 360;
  var lon = tr[i + 2] + f * dl;
  if (lon > 180) lon -= 360; else if (lon < -180) lon += 360;
  return {lat: tr[i + 1] + f * (tr[i + 4] - tr[i + 1]), lon: lon, seen: true};
}
function stayAt(m) {
  var lo = 0, hi = staysList.length - 1, found = -1;
  while (lo <= hi) { var mid = (lo + hi) >> 1; if (staysList[mid].t0 <= m) { found = mid; lo = mid + 1; } else hi = mid - 1; }
  return found;
}
function ownerAt(m) {
  var i = stayAt(m), s = i >= 0 ? staysList[i] : null, next = staysList[i + 1];
  if (s && m <= s.t1) {
    if (s.aboard && assetById[s.aboard]) {
      var p = positionOf(assetById[s.aboard], m);
      if (p && p.seen) return {lat: p.lat, lon: p.lon, stay: s, aboard: s.aboard};
    }
    return {lat: s.lat, lon: s.lon, stay: s, aboard: s.aboard};
  }
  if (s && next && next.t0 - s.t1 <= 2880) {
    var f = (m - s.t1) / Math.max(1, next.t0 - s.t1);
    return {lat: s.lat + f * (next.lat - s.lat), lon: s.lon + f * (next.lon - s.lon), between: [s, next]};
  }
  return null;
}

/* -- drawing -- */
function readColors() {
  var css = getComputedStyle(document.documentElement);
  ["space", "ocean", "land", "coast", "grid", "stay", "you", "journey", "yacht", "aircraft", "car", "asset", "place", "fg", "mute", "bg", "band1", "band2"].forEach(function (k) {
    colors[k] = css.getPropertyValue("--" + k).trim() || "#888";
  });
}
function assetColor(a) { return colors[a.kind] || colors.asset; }
function label(text, x, y, color, rank) {
  queued.push({text: text, x: x, y: y, color: color, rank: rank});
}
function labels() {
  /* the labels last, over everything, the owner's first, then the assets', then the places': one
     that would cover another already written is left out */
  var boxes = [];
  ctx.font = "12px system-ui, sans-serif";
  queued.sort(function (a, b) { return a.rank - b.rank; }).forEach(function (l) {
    var w = ctx.measureText(l.text).width + 6, box = [l.x, l.y - 12, l.x + w, l.y + 3];
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      if (box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]) return;
    }
    boxes.push(box);
    ctx.lineWidth = 3; ctx.strokeStyle = colors.bg; ctx.strokeText(l.text, l.x + 3, l.y);
    ctx.fillStyle = l.color; ctx.fillText(l.text, l.x + 3, l.y);
  });
}
function dot(s, radius, fill, stroke) {
  ctx.beginPath(); ctx.arc(s[0], s[1], radius, 0, 2 * Math.PI);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke(); }
}
function pathPoints(flat) {
  var out = [];
  for (var i = 0; i < flat.length; i += 2) out.push([flat[i], flat[i + 1]]);
  return out;
}
function along(pts, f) {
  var lengths = [0], total = 0, i;
  for (i = 1; i < pts.length; i++) {
    total += Math.hypot(pts[i][0] - pts[i - 1][0], (pts[i][1] - pts[i - 1][1]) * Math.cos(pts[i][0] * RAD));
    lengths.push(total);
  }
  var goal = f * total, out = [pts[0]];
  for (i = 1; i < pts.length; i++) {
    if (lengths[i] >= goal) {
      var g = (goal - lengths[i - 1]) / Math.max(1e-12, lengths[i] - lengths[i - 1]);
      out.push([pts[i - 1][0] + g * (pts[i][0] - pts[i - 1][0]), pts[i - 1][1] + g * (pts[i][1] - pts[i - 1][1])]);
      return out;
    }
    out.push(pts[i]);
  }
  return out;
}
function drawJourneys() {
  journeys.forEach(function (j) {
    var pts = pathPoints(j.path), end = j.t1 === null ? j.t0 : j.t1;
    if (!pts.length) return;
    if (pts.length === 1) {
      var s = project(pts[0][0], pts[0][1]);
      if (s) { ctx.fillStyle = colors.journey; ctx.globalAlpha = T >= j.t0 ? 0.9 : 0.3; ctx.fillRect(s[0] - 3, s[1] - 3, 6, 6); ctx.globalAlpha = 1; }
      return;
    }
    ctx.strokeStyle = colors.journey;
    if (T < j.t0) { ctx.globalAlpha = 0.35; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.2; }
    else if (T > end) { ctx.globalAlpha = 0.55; ctx.lineWidth = 1.5; }
    else { ctx.globalAlpha = 0.35; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5; }
    ctx.beginPath(); line(pts); ctx.stroke();
    ctx.setLineDash([]);
    if (T >= j.t0 && T <= end) {
      var done = along(pts, (T - j.t0) / Math.max(1, end - j.t0));
      ctx.globalAlpha = 1; ctx.lineWidth = 3;
      ctx.beginPath(); line(done); ctx.stroke();
      var head = done[done.length - 1], hs = project(head[0], head[1]);
      if (hs) dot(hs, 3.5, colors.journey, null);
    }
    ctx.globalAlpha = 1;
  });
}
function drawStays(owner) {
  staysList.forEach(function (s) {
    var p = project(s.lat, s.lon);
    if (!p) return;
    var r = s.night ? 3.5 : 2.5;
    ctx.globalAlpha = s.t1 <= T ? 0.8 : (s.t0 > T ? 0.25 : 1);
    dot(p, r, colors.stay, null);
    ctx.globalAlpha = 1;
  });
  if (owner && owner.stay && !owner.aboard) {
    var c = project(owner.stay.lat, owner.stay.lon);
    if (c) dot(c, 7, null, colors.stay);
  }
}
function drawPlaces() {
  places.forEach(function (p) {
    var s = project(p.lat, p.lon);
    if (!s) return;
    var r = Math.max(5, Math.min(40, p.radius_m / EARTH_M * size.r));
    dot(s, r, null, colors.place);
    dot(s, 2, colors.place, null);
    if (p.id === selected) dot(s, r + 4, null, colors.you);
    label(p.name, s[0] + r + 2, s[1] - 2, colors.place, 2);
    hits.push({x: s[0], y: s[1], r: Math.max(10, r), id: p.id, rank: 1});
  });
}
function drawAssets(owner) {
  var trail = Math.max(360, Math.min(2880, span / 10));
  assets.forEach(function (a) {
    var tr = a.track, color = assetColor(a), i, pts = [], recent = [];
    if (!tr.length) return;
    ctx.strokeStyle = color;
    for (i = 0; i < tr.length; i += 3) {
      if (i && tr[i] - tr[i - 3] > gap) { flush(pts, 0.25, 1); pts = []; }
      pts.push([tr[i + 1], tr[i + 2]]);
    }
    flush(pts, 0.25, 1);
    for (i = 0; i < tr.length; i += 3) {
      if (tr[i] > T) break;
      if (tr[i] < T - trail) continue;
      if (recent.length && tr[i] - tr[i - 3] > gap) recent = [];
      recent.push([tr[i + 1], tr[i + 2]]);
    }
    var at = positionOf(a, T);
    if (at && at.seen && recent.length) recent.push([at.lat, at.lon]);
    flush(recent, 0.9, 2.5);
    if (!at) return;
    var s = project(at.lat, at.lon);
    if (!s) return;
    if (at.seen) dot(s, 5.5, color, colors.bg); else dot(s, 5.5, colors.bg, color);
    if (a.id === selected) dot(s, 10, null, colors.you);
    var aboard = owner && owner.aboard === a.id && at.seen;
    if (aboard) dot(s, 8, null, colors.you);
    label(aboard ? a.name + ", you aboard" : a.name, s[0] + 8, s[1] + 4, aboard ? colors.you : color, aboard ? 0 : 1);
    hits.push({x: s[0], y: s[1], r: 12, id: a.id, rank: 0});
  });
}
function flush(pts, alpha, width) {
  if (pts.length < 2) return;
  ctx.globalAlpha = alpha; ctx.lineWidth = width;
  ctx.beginPath(); line(pts); ctx.stroke();
  ctx.globalAlpha = 1;
}
function drawOwner(owner) {
  if (!owner) return;
  var on = owner.aboard && assetById[owner.aboard] ? positionOf(assetById[owner.aboard], T) : null;
  if (on && on.seen) return; /* aboard: the asset's dot is the owner's too, ringed */
  var s = project(owner.lat, owner.lon);
  if (!s) return;
  dot(s, 4.5, colors.you, colors.bg);
  label("you", s[0] + 7, s[1] - 7, colors.you, 0);
}
function draw() {
  pending = false;
  rot = rotation(); hits = []; queued = [];
  var dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = colors.space; ctx.fillRect(0, 0, size.w, size.h);
  ctx.save();
  ctx.beginPath(); ctx.arc(size.cx, size.cy, size.r, 0, 2 * Math.PI);
  ctx.fillStyle = colors.ocean; ctx.fill();
  ctx.clip();
  drawLand();
  drawGraticule();
  var owner = ownerAt(T);
  drawJourneys();
  drawStays(owner);
  drawPlaces();
  drawAssets(owner);
  drawOwner(owner);
  labels();
  ctx.restore();
  ctx.beginPath(); ctx.arc(size.cx, size.cy, size.r, 0, 2 * Math.PI);
  ctx.strokeStyle = colors.coast; ctx.lineWidth = 1; ctx.stroke();
  drawBands();
  tell(owner);
}
function redraw() { if (!pending) { pending = true; window.requestAnimationFrame(draw); } }
function tell(owner) {
  var parts = [when(T)], c = chapterAt(T);
  if (c) parts.push("chapter " + c.name);
  if (owner && owner.stay) {
    if (owner.aboard) parts.push("aboard " + (assetById[owner.aboard] ? assetById[owner.aboard].name : owner.aboard));
    else if (owner.stay.place) parts.push("at " + placeById[owner.stay.place].name);
    else parts.push("at " + owner.stay.lat + ", " + owner.stay.lon);
  } else if (owner && owner.between) {
    parts.push("on the way");
  }
  readout.textContent = parts.join(" \u00b7 ");
  clockText.textContent = when(T);
  if (selected && selected.indexOf("asset:") === 0 && !panel.hidden) show(selected);
}

/* -- the scrubber: ticks, the chapters as bands, the time -- */
function drawBands() {
  var dpr = window.devicePixelRatio || 1, w = bandCanvas.clientWidth, h = bandCanvas.clientHeight;
  if (bandCanvas.width !== Math.round(w * dpr)) { bandCanvas.width = Math.round(w * dpr); bandCanvas.height = Math.round(h * dpr); }
  bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  bctx.clearRect(0, 0, w, h);
  var pad = 8, x = function (m) { return pad + (w - 2 * pad) * m / span; };
  bctx.font = "11px system-ui, sans-serif";
  chapters.forEach(function (c, n) {
    var a = x(c.t0), b = x(c.t1);
    bctx.fillStyle = n % 2 ? colors.band2 : colors.band1;
    bctx.fillRect(a, 2, Math.max(2, b - a), 14);
    bctx.fillStyle = colors.fg;
    var text = c.name;
    if (bctx.measureText(text).width < b - a - 6) bctx.fillText(text, a + 3, 13);
  });
  var px = (w - 2 * pad) / span, m, d, n, text, lastX = -1e9;
  bctx.fillStyle = colors.mute; bctx.strokeStyle = colors.mute;
  bctx.beginPath();
  if (span <= 120 * 1440) {
    /* a tick a day (every six hours for a few days), a date under every day there is room for */
    var unit = span <= 4 * 1440 ? 360 : 1440;
    var every = [1, 2, 7, 14, 28].filter(function (q) { return q * 1440 * px >= 52; })[0] || 28;
    for (n = 0, m = 0; m <= span; n++, m = n * unit) {
      bctx.moveTo(x(m), 18); bctx.lineTo(x(m), m % 1440 ? 20 : 23);
      if (m % 1440 === 0 && (m / 1440) % every === 0 && m + 720 <= span) bctx.fillText(shortFormat.format(moment(m + 720)), x(m) + 2, 31);
    }
  } else {
    /* a tick a month, or a year for a long record; a label wherever it fits */
    var first = moment(0), years = span > 3 * 525600;
    d = new Date(Date.UTC(first.getUTCFullYear(), years ? 0 : first.getUTCMonth(), 1));
    while ((d.getTime() / 1000 - win.start) / 60 <= span) {
      m = (d.getTime() / 1000 - win.start) / 60;
      if (m >= 0) {
        bctx.moveTo(x(m), 18); bctx.lineTo(x(m), 23);
        text = years || d.getUTCMonth() === 0 ? String(d.getUTCFullYear()) : d.toLocaleString("en-GB", {month: "short", timeZone: "UTC"});
        if (x(m) - lastX >= bctx.measureText(text).width + 8) { bctx.fillText(text, x(m) + 2, 31); lastX = x(m); }
      }
      d = years ? new Date(Date.UTC(d.getUTCFullYear() + 1, 0, 1)) : new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    }
  }
  bctx.stroke();
  bctx.strokeStyle = colors.you; bctx.lineWidth = 2;
  bctx.beginPath(); bctx.moveTo(x(T), 0); bctx.lineTo(x(T), h); bctx.stroke();
  bctx.lineWidth = 1;
}
function setTime(m) {
  T = Math.max(0, Math.min(span, m));
  slider.value = String(Math.round(T));
  redraw();
}
slider.max = String(span);
slider.addEventListener("input", function () { setTime(Number(slider.value)); });
slider.addEventListener("keydown", function (e) {
  var step = e.shiftKey ? 1440 : 60;
  if (e.key === "ArrowRight" || e.key === "ArrowUp") { setTime(T + step); e.preventDefault(); }
  else if (e.key === "ArrowLeft" || e.key === "ArrowDown") { setTime(T - step); e.preventDefault(); }
  else if (e.key === "PageUp") { setTime(T + 1440); e.preventDefault(); }
  else if (e.key === "PageDown") { setTime(T - 1440); e.preventDefault(); }
});
bandCanvas.addEventListener("pointerdown", function (e) {
  var r = bandCanvas.getBoundingClientRect();
  setTime((e.clientX - r.left - 8) / Math.max(1, r.width - 16) * span);
});
function tick(now) {
  if (!playing) return;
  if (last) setTime(T + (now - last) / 1000 * span / PLAY_S);
  last = now;
  if (T >= span) { playing = false; playButton.textContent = "play"; return; }
  window.requestAnimationFrame(tick);
}
playButton.addEventListener("click", function () {
  playing = !playing;
  playButton.textContent = playing ? "pause" : "play";
  if (playing) { if (T >= span) setTime(0); last = 0; window.requestAnimationFrame(tick); }
});

/* -- the view: drag to turn the globe, wheel or buttons to zoom -- */
function resize() {
  var dpr = window.devicePixelRatio || 1;
  size.w = canvas.clientWidth; size.h = canvas.clientHeight;
  canvas.width = Math.round(size.w * dpr); canvas.height = Math.round(size.h * dpr);
  size.base = 0.45 * Math.min(size.w, size.h); size.r = size.base * view.zoom;
  size.cx = size.w / 2; size.cy = size.h / 2;
  redraw();
}
function zoomTo(z) {
  view.zoom = Math.max(0.9, Math.min(MAX_ZOOM, z));
  size.r = size.base * view.zoom;
  redraw();
}
function normalise() {
  view.lon = ((view.lon + 540) % 360) - 180;
  view.lat = Math.max(-89.9, Math.min(89.9, view.lat));
}
function everything() {
  var pts = [];
  places.forEach(function (p) { pts.push([p.lat, p.lon]); });
  staysList.forEach(function (s) { pts.push([s.lat, s.lon]); });
  assets.forEach(function (a) { for (var i = 0; i < a.track.length; i += 3) pts.push([a.track[i + 1], a.track[i + 2]]); });
  journeys.forEach(function (j) { pathPoints(j.path).forEach(function (q) { pts.push(q); }); });
  return pts;
}
function fit() {
  var pts = everything(), sx = 0, sy = 0, sz = 0;
  if (!pts.length) { view.lon = 10; view.lat = 30; zoomTo(1); return; }
  pts.forEach(function (q) { var v = unit(q[0], q[1]); sx += v[0]; sy += v[1]; sz += v[2]; });
  var n = Math.sqrt(sx * sx + sy * sy + sz * sz);
  if (n < 1e-9 * pts.length) { view.lon = 10; view.lat = 30; zoomTo(1); return; }
  view.lat = Math.asin(sz / n) / RAD; view.lon = Math.atan2(sy, sx) / RAD;
  var c = unit(view.lat, view.lon), widest = 0.002;
  pts.forEach(function (q) {
    var v = unit(q[0], q[1]), dotp = v[0] * c[0] + v[1] * c[1] + v[2] * c[2];
    widest = Math.max(widest, Math.acos(Math.max(-1, Math.min(1, dotp))));
  });
  normalise();
  zoomTo(widest >= Math.PI / 2 ? 1 : 0.85 / Math.sin(widest));
}
function focus(lat, lon) { view.lat = lat; view.lon = lon; normalise(); zoomTo(Math.max(view.zoom, 200)); }
var drag = null;
canvas.addEventListener("pointerdown", function (e) {
  drag = {x: e.clientX, y: e.clientY, lon: view.lon, lat: view.lat, moved: false};
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", function (e) {
  if (!drag) return;
  var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  if (!drag.moved) return;
  view.lon = drag.lon - dx / size.r / RAD / Math.max(0.1, Math.cos(view.lat * RAD));
  view.lat = drag.lat + dy / size.r / RAD;
  normalise(); redraw();
});
canvas.addEventListener("pointerup", function (e) {
  var was = drag; drag = null;
  if (!was || was.moved) return;
  var r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, best = null;
  hits.forEach(function (h) {
    var d = Math.hypot(h.x - x, h.y - y);
    if (d <= h.r && (!best || h.rank < best.rank || (h.rank === best.rank && d < best.d))) best = {id: h.id, rank: h.rank, d: d};
  });
  if (best) show(best.id); else hide();
});
canvas.addEventListener("wheel", function (e) { e.preventDefault(); zoomTo(view.zoom * Math.exp(-e.deltaY * 0.0015)); }, {passive: false});
document.getElementById("zoom-in").addEventListener("click", function () { zoomTo(view.zoom * 2); });
document.getElementById("zoom-out").addEventListener("click", function () { zoomTo(view.zoom / 2); });
document.getElementById("fit").addEventListener("click", fit);
document.getElementById("whole").addEventListener("click", function () { zoomTo(1); });

/* -- the summary of an anchor or an asset -- */
function hide() { selected = null; panel.hidden = true; }
function row(dl, term, text) {
  var dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = term; dd.textContent = text; dl.appendChild(dt); dl.appendChild(dd);
}
function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
function show(id) {
  var s = summaries[id];
  if (!s) return;
  selected = id;
  panel.textContent = "";
  var h = document.createElement("h2"), dl = document.createElement("dl"), close = document.createElement("button");
  h.textContent = s.name;
  close.textContent = "close"; close.className = "close";
  close.addEventListener("click", hide);
  row(dl, "kind", (id.indexOf("asset:") === 0 ? "asset" : "place") + (s.kind ? ", " + s.kind : ""));
  row(dl, "nights", plural(s.nights, "night", "nights") + (id.indexOf("asset:") === 0 ? " aboard" : ""));
  row(dl, "journeys", plural(s.journeys, "journey", "journeys"));
  row(dl, "photos", plural(s.photos, "photo", "photos"));
  row(dl, id.indexOf("asset:") === 0 ? "fixes" : "visits", s.first ? (s.first === s.last ? s.first : s.first + " \u2013 " + s.last) : "none in the window");
  Object.keys(s.identifiers || {}).forEach(function (k) { row(dl, k, s.identifiers[k]); });
  if (id.indexOf("asset:") === 0) {
    var at = positionOf(assetById[id], T);
    row(dl, "now", at ? at.lat.toFixed(4) + ", " + at.lon.toFixed(4) + (at.seen ? "" : " (last fix)") : "not seen yet");
  } else {
    var p = placeById[id];
    row(dl, "position", p.lat + ", " + p.lon + ", " + p.radius_m + " m");
  }
  panel.appendChild(close); panel.appendChild(h); panel.appendChild(dl);
  panel.hidden = false;
}
function entry(id, name, kind) {
  var li = document.createElement("li"), b = document.createElement("button");
  b.textContent = name; b.title = kind;
  b.addEventListener("click", function () {
    show(id);
    var p = placeById[id], a = assetById[id], at = a ? positionOf(a, T) : null;
    if (p) focus(p.lat, p.lon);
    else if (at) focus(at.lat, at.lon);
    else if (a && a.track.length) focus(a.track[1], a.track[2]);
  });
  li.appendChild(b); list.appendChild(li);
}
places.forEach(function (p) { entry(p.id, p.name, "place, " + p.kind); });
assets.forEach(function (a) { entry(a.id, a.name, "asset" + (a.kind ? ", " + a.kind : "")); });

readColors();
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { readColors(); redraw(); });
window.addEventListener("resize", resize);
resize();
fit();
setTime(0);
})();
