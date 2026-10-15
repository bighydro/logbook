(function () {
"use strict";
/* The chart: the record on paper. The paper is drawn here — Mercator's sea chart, its coasts from the
   same land table as the globe, hachured, a compass rose and its rhumb lines, the graticule engraved —
   or it is the owner's own chart, an image the page carries, with the fit export world made of it.
   The record on it is evidence: every position is drawn where the paper puts it and nowhere else, a
   track is the straight segments between its own fixes (never smoothed, never moved), an asset is at
   its last fix (never between two), a day mark is at a recorded fix or a journey's own end, and its
   date is the record's day, which the export worked out from the record's own instants and wrote into
   the page (`chart.marks`), never this browser's clock or a rounded minute. */
var world = JSON.parse(document.getElementById("world").textContent);
var table = JSON.parse(document.getElementById("land").textContent);
var chart = JSON.parse(document.getElementById("chart").textContent);
var canvas = document.getElementById("globe"), ctx = canvas.getContext("2d");
var bandCanvas = document.getElementById("bands"), bctx = bandCanvas.getContext("2d");
var slider = document.getElementById("time"), readout = document.getElementById("readout");
var clockText = document.getElementById("clock"), panel = document.getElementById("panel");
var playButton = document.getElementById("play"), list = document.getElementById("list");
var RAD = Math.PI / 180, EARTH_M = 6371000, MAX_LAT = 85, PLAY_S = 40, FRAME = 30, BAND = 8;
var win = world.window, span = Math.max(1, win.minutes), gap = win.gap_min;
var size = {w: 0, h: 0}, view = {x: 0, y: 0, k: 1};
var T = 0, playing = false, last = 0, hits = [], queued = [], selected = null, pending = false, marksOnly = false;
var FAMILY = "'IM Fell English', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif";
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/* the paper is paper: the same colours in a dark room */
var colors = {
  paper: "#f1e4c4", vignette: "rgba(112,78,36,0.22)", land: "#e5d09f", coast: "#3d2b17", hachure: "#6e5434",
  grid: "rgba(74,53,32,0.55)", ink: "#2e2012", journey: "#9a2c1d", stay: "#2e2012", you: "#b3311f",
  place: "#1f3a56", point: "#1f3a56", fg: "#2b1d10", mute: "#6a5640", bg: "#f1e4c4",
  band1: "#e3cfa2", band2: "#d4bd8c",
  rhumb: ["rgba(46,32,18,0.30)", "rgba(62,104,58,0.34)", "rgba(154,44,29,0.28)"]
};
var places = world.places, assets = world.assets, staysList = world.stays;
var journeys = world.journeys, chapters = world.chapters, summaries = world.summaries;
var assetById = {};
assets.forEach(function (a) { assetById[a.id] = a; });
var placeById = {};
places.forEach(function (p) { placeById[p.id] = p; });
var marks = chart.marks, firstDay = chart.days.first.split("-").map(Number);

function hand(px, italic) { return (italic ? "italic " : "") + px + "px " + FAMILY; }
function wrap(d) { return ((d + 180) % 360 + 360) % 360 - 180; }
function north(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / RAD; }
function latitude(y) { return (2 * Math.atan(Math.exp(-y * RAD)) - Math.PI / 2) / RAD; }

/* -- the fit: a position to a pixel of the owner's chart, as chart_fit.Transform.to_pixel -- */
function chartTransform(fit) {
  var h = fit.h, src = fit.src, dst = fit.dst, lon0 = fit.lon0;
  return function (lat, lon) {
    if (!(lat > -85 && lat < 85)) return null;
    var d = lon - lon0, east = ((d + 180) % 360 + 360) % 360 - 180;
    var nn = Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) * 180 / Math.PI;
    var e = (east - src[0]) * src[2], n = (nn - src[1]) * src[2];
    var w = h[6] * e + h[7] * n + 1;
    if (!(w > 0)) return null;
    return [(h[0] * e + h[1] * n + h[2]) / w / dst[2] + dst[0], (h[3] * e + h[4] * n + h[5]) / w / dst[2] + dst[1]];
  };
}
/* -- end of the fit -- */

var onImage = chart.paper === "image";
var toPixel = onImage ? chartTransform(chart.fit) : null;
var paperImage = null, paperFailed = false;

/* -- the paper: a position to a point of the paper (Mercator's degrees, y down; or the image's
   pixels), the paper to the screen -- */
function toPaper(lat, lon) {
  if (onImage) return toPixel(lat, lon);
  if (!(lat > -MAX_LAT && lat < MAX_LAT)) return null;
  return [lon, -north(lat)];
}
function near(x) { return onImage ? x : view.x + wrap(x - view.x); }
function screen(p) { return [size.w / 2 + (p[0] - view.x) * view.k, size.h / 2 + (p[1] - view.y) * view.k]; }
function project(lat, lon) {
  var p = toPaper(lat, lon);
  return p ? screen([near(p[0]), p[1]]) : null;
}
function trace(latlons) {
  /* a line through positions, each where the paper puts it and a straight segment between two (on
     Mercator's chart, the rhumb line a navigator lays off between two fixes); broken where a position
     is off the paper; never smoothed */
  var prev = null;
  for (var i = 0; i < latlons.length; i++) {
    var p = toPaper(latlons[i][0], latlons[i][1]);
    if (!p) { prev = null; continue; }
    var x = onImage ? p[0] : (prev ? prev[0] + wrap(p[0] - prev[0]) : near(p[0])), s = screen([x, p[1]]);
    if (prev) ctx.lineTo(s[0], s[1]); else ctx.moveTo(s[0], s[1]);
    prev = [x, p[1]];
  }
}
function frameRect() { return onImage ? [0, 0, size.w, size.h] : [FRAME, FRAME, size.w - FRAME, size.h - FRAME]; }
function viewBox() {
  return [view.x - size.w / 2 / view.k, view.y - size.h / 2 / view.k, view.x + size.w / 2 / view.k, view.y + size.h / 2 / view.k];
}
function clip(a, b, r) {
  /* Liang and Barsky: the part of the segment a–b inside the rectangle r, as [t0, t1], or null */
  var t0 = 0, t1 = 1, dx = b[0] - a[0], dy = b[1] - a[1];
  var p = [-dx, dx, -dy, dy], q = [a[0] - r[0], r[2] - a[0], a[1] - r[1], r[3] - a[1]];
  for (var i = 0; i < 4; i++) {
    if (p[i] === 0) { if (q[i] < 0) return null; continue; }
    var t = q[i] / p[i];
    if (p[i] < 0) { if (t > t1) return null; if (t > t0) t0 = t; }
    else { if (t < t0) return null; if (t < t1) t1 = t; }
  }
  return [t0, t1];
}

/* -- the land: the globe's table on Mercator's chart, each ring clamped to the chart's latitudes;
   the side of a coast the land is on from the ring's own turning (a hole's land is outside it) -- */
var land = table.polygons.map(function (polygon) {
  return polygon.map(function (ring, r) {
    var s = table.scale, x = ring[0], y = ring[1], pts = [[x / s, -north(Math.max(-MAX_LAT, Math.min(MAX_LAT, y / s)))]];
    for (var i = 2; i < ring.length; i += 2) {
      x += ring[i]; y += ring[i + 1];
      pts.push([x / s, -north(Math.max(-MAX_LAT, Math.min(MAX_LAT, y / s)))]);
    }
    var area = 0, box = [Infinity, Infinity, -Infinity, -Infinity];
    for (i = 0; i < pts.length; i++) {
      var a = pts[i], b = pts[(i + 1) % pts.length];
      area += a[0] * b[1] - b[0] * a[1];
      box = [Math.min(box[0], a[0]), Math.min(box[1], a[1]), Math.max(box[2], a[0]), Math.max(box[3], a[1])];
    }
    return {p: pts, inward: (area > 0 ? 1 : -1) * (r === 0 ? 1 : -1), box: box};
  });
});
function shifts(box) {
  var out = [];
  for (var k = -1; k <= 1; k++) { if (-180 + 360 * k <= box[2] && 180 + 360 * k >= box[0]) out.push(360 * k); }
  return out;
}
function seen(box, dx, vb) { return box[0] + dx <= vb[2] && box[2] + dx >= vb[0] && box[1] <= vb[3] && box[3] >= vb[1]; }
function ringPath(pts, dx) {
  for (var i = 0; i < pts.length; i++) {
    var s = screen([pts[i][0] + dx, pts[i][1]]);
    if (i) ctx.lineTo(s[0], s[1]); else ctx.moveTo(s[0], s[1]);
  }
  ctx.closePath();
}
function hachure(ring, dx, r) {
  /* short strokes from the coast into the land, a few pixels apart, long and short in turn */
  var pts = ring.p, n = pts.length, step = 3.2;
  for (var i = 0; i < n; i++) {
    var a = screen([pts[i][0] + dx, pts[i][1]]), b = screen([pts[(i + 1) % n][0] + dx, pts[(i + 1) % n][1]]);
    var ex = b[0] - a[0], ey = b[1] - a[1], length = Math.hypot(ex, ey);
    if (length < 0.5) continue;
    var t = clip(a, b, r);
    if (!t) continue;
    var nx = -ey / length * ring.inward, ny = ex / length * ring.inward;
    for (var j = Math.ceil(t[0] * length / step); j * step <= t[1] * length; j++) {
      var f = j * step / length, x = a[0] + f * ex, y = a[1] + f * ey, l = [5.5, 3, 4][j % 3];
      ctx.moveTo(x, y); ctx.lineTo(x + nx * l, y + ny * l);
    }
  }
}
function drawLand() {
  var vb = viewBox(), r = frameRect(), wide = [r[0] - 8, r[1] - 8, r[2] + 8, r[3] + 8], moves = shifts(vb);
  ctx.fillStyle = colors.land;
  moves.forEach(function (dx) {
    land.forEach(function (polygon) {
      if (!seen(polygon[0].box, dx, vb)) return;
      ctx.beginPath();
      polygon.forEach(function (ring) { ringPath(ring.p, dx); });
      ctx.fill("evenodd");
    });
  });
  ctx.strokeStyle = colors.hachure; ctx.lineWidth = 0.6;
  ctx.beginPath();
  moves.forEach(function (dx) {
    land.forEach(function (polygon) {
      if (!seen(polygon[0].box, dx, vb)) return;
      polygon.forEach(function (ring) { hachure(ring, dx, wide); });
    });
  });
  ctx.stroke();
  ctx.strokeStyle = colors.coast; ctx.lineWidth = 1.1;
  ctx.beginPath();
  moves.forEach(function (dx) {
    land.forEach(function (polygon) {
      if (!seen(polygon[0].box, dx, vb)) return;
      polygon.forEach(function (ring) { ringPath(ring.p, dx); });
    });
  });
  ctx.stroke();
}

/* -- the graticule, engraved, and its scale in the border: a step of degrees and minutes the zoom
   gives room for, each cut in fifths or sixths -- */
var STEPS = [[30, 5], [10, 2], [5, 1], [2, 0.5], [1, 1 / 6], [0.5, 1 / 12], [1 / 6, 1 / 60], [1 / 12, 1 / 60],
  [1 / 30, 1 / 120], [1 / 60, 1 / 360], [1 / 120, 1 / 720], [1 / 360, 1 / 3600]];
function gridStep() {
  var found = STEPS[0];
  for (var i = 0; i < STEPS.length; i++) { if (STEPS[i][0] * view.k >= 80) found = STEPS[i]; }
  return found;
}
function degrees(v, pos, neg) {
  var a = Math.abs(v), d = Math.floor(a + 1e-9), m = Math.round((a - d) * 60 * 10) / 10;
  if (m >= 60) { d += 1; m = 0; }
  return d + "°" + (m ? (m % 1 ? m.toFixed(1) : m) + "′" : "") + (v > 1e-9 ? pos : v < -1e-9 ? neg : "");
}
function lonLines(step, fn) {
  var vb = viewBox();
  for (var k = Math.ceil(vb[0] / step - 1e-9); k * step <= vb[2] + 1e-9; k++) fn(k * step, wrap(k * step));
}
function latLines(step, fn) {
  var vb = viewBox(), top = Math.min(MAX_LAT, latitude(vb[1])), bottom = Math.max(-MAX_LAT, latitude(vb[3]));
  for (var k = Math.ceil(bottom / step - 1e-9); k * step <= top + 1e-9; k++) fn(k * step);
}
function drawGraticule() {
  var step = gridStep()[0], r = frameRect();
  ctx.strokeStyle = colors.grid; ctx.lineWidth = 0.5;
  ctx.beginPath();
  lonLines(step, function (x) { var s = screen([x, 0]); ctx.moveTo(s[0], r[1]); ctx.lineTo(s[0], r[3]); });
  latLines(step, function (lat) { var s = screen([0, -north(lat)]); ctx.moveTo(r[0], s[1]); ctx.lineTo(r[2], s[1]); });
  ctx.stroke();
  ctx.font = hand(11, true); ctx.fillStyle = colors.mute;
  latLines(step, function (lat) {
    var s = screen([0, -north(lat)]);
    if (s[1] > r[1] + 12 && s[1] < r[3] - 4) ctx.fillText(degrees(lat, " N", " S"), r[0] + 4, s[1] - 3);
  });
}
function drawBorder() {
  /* the neatline and the graduated band outside it: degrees of longitude along the top and the
     bottom, of latitude (Mercator's, so they widen towards the pole) down the sides */
  var r = frameRect(), sub = gridStep()[1], step = gridStep()[0], o = [r[0] - BAND, r[1] - BAND, r[2] + BAND, r[3] + BAND];
  ctx.fillStyle = "#fbf3dc";
  ctx.fillRect(o[0], o[1], o[2] - o[0], BAND); ctx.fillRect(o[0], r[3], o[2] - o[0], BAND);
  ctx.fillRect(o[0], o[1], BAND, o[3] - o[1]); ctx.fillRect(r[2], o[1], BAND, o[3] - o[1]);
  ctx.fillStyle = colors.ink;
  lonLines(sub, function (x) {
    if (Math.round(x / sub) % 2 === 0) return;
    var a = Math.max(r[0], screen([x, 0])[0]), b = Math.min(r[2], screen([x + sub, 0])[0]);
    if (b > a) { ctx.fillRect(a, o[1] + 2, b - a, BAND - 4); ctx.fillRect(a, r[3] + 2, b - a, BAND - 4); }
  });
  latLines(sub, function (lat) {
    if (Math.round(lat / sub) % 2 === 0) return;
    var a = Math.max(r[1], screen([0, -north(Math.min(MAX_LAT, lat + sub))])[1]), b = Math.min(r[3], screen([0, -north(lat)])[1]);
    if (b > a) { ctx.fillRect(o[0] + 2, a, BAND - 4, b - a); ctx.fillRect(r[2] + 2, a, BAND - 4, b - a); }
  });
  ctx.strokeStyle = colors.ink; ctx.lineWidth = 1;
  ctx.strokeRect(r[0], r[1], r[2] - r[0], r[3] - r[1]);
  ctx.lineWidth = 1.6;
  ctx.strokeRect(o[0], o[1], o[2] - o[0], o[3] - o[1]);
  ctx.font = hand(11, true); ctx.fillStyle = colors.fg; ctx.textAlign = "center";
  lonLines(step, function (x, lon) {
    var s = screen([x, 0]);
    if (s[0] > r[0] + 20 && s[0] < r[2] - 20) ctx.fillText(degrees(lon, " E", " W"), s[0], o[1] - 5);
  });
  ctx.textAlign = "start";
}

/* -- the compass rose, and its thirty-two rhumb lines across the chart: north is up on Mercator's
   chart, so a line at a bearing from the rose is a rhumb line wherever the rose stands -- */
function rose() {
  var radius = Math.max(34, Math.min(92, Math.min(size.w, size.h) * 0.1));
  return {x: size.w - FRAME - radius - 26, y: size.h - FRAME - radius - 26, r: radius};
}
function drawRhumbs() {
  var c = rose(), far = size.w + size.h;
  for (var i = 0; i < 32; i++) {
    var b = i * 11.25 * RAD, dx = Math.sin(b), dy = -Math.cos(b);
    ctx.strokeStyle = colors.rhumb[i % 4 === 0 ? 0 : i % 2 === 0 ? 1 : 2];
    ctx.lineWidth = i % 4 === 0 ? 0.8 : 0.55;
    ctx.beginPath(); ctx.moveTo(c.x + dx * c.r, c.y + dy * c.r); ctx.lineTo(c.x + dx * far, c.y + dy * far); ctx.stroke();
  }
}
function drawRose() {
  var c = rose(), r = c.r, i, a;
  ctx.save(); ctx.translate(c.x, c.y);
  ctx.fillStyle = "rgba(246,236,210,0.94)";
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.fill();
  ctx.strokeStyle = colors.ink; ctx.lineWidth = 1.2; ctx.stroke();
  ctx.lineWidth = 0.6;
  ctx.beginPath(); ctx.arc(0, 0, r * 0.88, 0, 2 * Math.PI); ctx.stroke();
  ctx.beginPath();
  for (i = 0; i < 128; i++) {
    a = i * Math.PI / 64;
    var inner = i % 4 === 0 ? 0.88 : 0.94;
    ctx.moveTo(Math.sin(a) * r * inner, -Math.cos(a) * r * inner); ctx.lineTo(Math.sin(a) * r, -Math.cos(a) * r);
  }
  ctx.stroke();
  /* the points, the shortest first: quarter winds, half winds, the eight winds, the four cardinal */
  [[1, 0.36], [2, 0.5], [4, 0.66], [8, 0.86]].forEach(function (rank) {
    for (i = 0; i < 32; i++) {
      if (i % rank[0] !== 0 || (rank[0] < 8 && i % (rank[0] * 2) === 0)) continue;
      a = i * 11.25 * RAD;
      var tip = r * rank[1], half = tip * 0.16, sx = Math.sin(a), cy = -Math.cos(a), px = -cy, py = sx;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(sx * tip, cy * tip); ctx.lineTo(px * half, py * half); ctx.closePath();
      ctx.fillStyle = colors.ink; ctx.fill();
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(sx * tip, cy * tip); ctx.lineTo(-px * half, -py * half); ctx.closePath();
      ctx.fillStyle = "#fbf3dc"; ctx.fill(); ctx.strokeStyle = colors.ink; ctx.lineWidth = 0.6; ctx.stroke();
    }
  });
  ctx.beginPath(); ctx.arc(0, 0, r * 0.05, 0, 2 * Math.PI); ctx.fillStyle = colors.journey; ctx.fill();
  ctx.font = hand(Math.round(r * 0.24), true); ctx.fillStyle = colors.ink; ctx.textAlign = "center";
  ctx.fillText("N", 0, -r - 5);
  ctx.textAlign = "start";
  ctx.restore();
}

/* -- the owner's chart: the image, each of its pixels as many of the file the control points were
   measured on as the export shrank it by, and the control points on it -- */
if (onImage) {
  try {
    var text = atob(document.getElementById("chart-image").textContent.trim()), bytes = new Uint8Array(text.length);
    for (var b = 0; b < text.length; b++) bytes[b] = text.charCodeAt(b);
    window.createImageBitmap(new Blob([bytes], {type: chart.image.type})).then(
      function (bitmap) { paperImage = bitmap; redraw(); },
      function () { paperFailed = true; redraw(); }
    );
  } catch (e) {
    paperFailed = true;
  }
}
function drawImage() {
  var a = screen([0, 0]), w = chart.fit.width * view.k, h = chart.fit.height * view.k, f = chart.image.factor;
  if (paperImage) {
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
    ctx.drawImage(paperImage, a[0], a[1], paperImage.width * f * view.k, paperImage.height * f * view.k);
  } else {
    ctx.font = hand(14, true); ctx.fillStyle = colors.mute;
    ctx.fillText(paperFailed ? "this browser cannot draw the chart's image" : "the chart is being drawn…", a[0] + 12, a[1] + 24);
  }
  ctx.strokeStyle = colors.ink; ctx.lineWidth = 1; ctx.strokeRect(a[0], a[1], w, h);
  ctx.strokeStyle = colors.point; ctx.lineWidth = 1.2;
  chart.fit.points.forEach(function (p) {
    var s = screen([p.x, p.y]);
    ctx.beginPath(); ctx.moveTo(s[0] - 6, s[1]); ctx.lineTo(s[0] + 6, s[1]); ctx.moveTo(s[0], s[1] - 6); ctx.lineTo(s[0], s[1] + 6); ctx.stroke();
    label(p.name, s[0] + 4, s[1] - 4, colors.point, 5, 0, hand(11, false));
  });
}
function drawPaper() {
  var dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = colors.paper; ctx.fillRect(0, 0, size.w, size.h);
  var g = ctx.createRadialGradient(size.w / 2, size.h / 2, Math.min(size.w, size.h) * 0.35, size.w / 2, size.h / 2, Math.max(size.w, size.h) * 0.75);
  g.addColorStop(0, "rgba(255,250,235,0)"); g.addColorStop(1, colors.vignette);
  ctx.fillStyle = g; ctx.fillRect(0, 0, size.w, size.h);
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
function fixAt(asset, m) {
  /* the asset's last fix at or before the minute: where the record last put it, and whether that is
     recent enough to call it seen there; never a position between two fixes */
  var tr = asset.track, n = tr.length / 3;
  if (!n || m < tr[0]) return null;
  var lo = 0, hi = n - 1;
  while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (tr[mid * 3] <= m) lo = mid; else hi = mid - 1; }
  return {i: lo, at: tr[lo * 3], lat: tr[lo * 3 + 1], lon: tr[lo * 3 + 2], seen: m - tr[lo * 3] <= gap};
}
function stayAt(m) {
  var lo = 0, hi = staysList.length - 1, found = -1;
  while (lo <= hi) { var mid = (lo + hi) >> 1; if (staysList[mid].t0 <= m) { found = mid; lo = mid + 1; } else hi = mid - 1; }
  return found;
}
function ownerAt(m) {
  /* the stay the owner was in at the minute (aboard, the boat's last fix); between two stays, no
     position: the record has the stays, not the way between them */
  var i = stayAt(m), s = i >= 0 ? staysList[i] : null, next = staysList[i + 1];
  if (s && m <= s.t1) {
    if (s.aboard && assetById[s.aboard]) {
      var p = fixAt(assetById[s.aboard], m);
      if (p && p.seen) return {lat: p.lat, lon: p.lon, stay: s, aboard: s.aboard};
    }
    return {lat: s.lat, lon: s.lon, stay: s, aboard: s.aboard};
  }
  if (s && next) return {between: [s, next]};
  return null;
}
function dateText(i) {
  /* the window's first day and i more: arithmetic on the calendar, no zone */
  var d = new Date(Date.UTC(firstDay[0], firstDay[1] - 1, firstDay[2] + i));
  return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + (chart.days.years ? " " + d.getUTCFullYear() : "");
}

/* -- drawing the record -- */
function label(text, x, y, color, rank, angle, font, other) {
  /* `other`, a second place for it (the far side of a mark), tried when the first is taken */
  if (marksOnly) return;
  queued.push({text: text, at: other ? [[x, y], other] : [[x, y]], color: color, rank: rank, angle: angle || 0, font: font || hand(13, true)});
}
function labels() {
  /* the labels after the record, the owner's first, then the assets', the places', the dates, the
     stays', the control points'; one that would cover another already written moves to its other
     place, or is left out. The marks are drawn again over them: a label never hides a position */
  var boxes = [];
  queued.sort(function (a, b) { return a.rank - b.rank; }).forEach(function (l) {
    ctx.font = l.font;
    var w = ctx.measureText(l.text).width + 6, c = Math.cos(l.angle), s = Math.sin(l.angle);
    for (var k = 0; k < l.at.length; k++) {
      var x0 = l.at[k][0], y0 = l.at[k][1], box = [Infinity, Infinity, -Infinity, -Infinity], free = true;
      [[0, -12], [w, -12], [w, 4], [0, 4]].forEach(function (q) {
        var x = x0 + q[0] * c - q[1] * s, y = y0 + q[0] * s + q[1] * c;
        box = [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)];
      });
      for (var i = 0; i < boxes.length && free; i++) {
        var b = boxes[i];
        if (box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]) free = false;
      }
      if (!free) continue;
      boxes.push(box);
      ctx.save(); ctx.translate(x0, y0); ctx.rotate(l.angle);
      ctx.lineWidth = 3; ctx.strokeStyle = colors.paper; ctx.strokeText(l.text, 3, 0);
      ctx.fillStyle = l.color; ctx.fillText(l.text, 3, 0);
      ctx.restore();
      return;
    }
  });
}
function dot(s, radius, fill, stroke, width) {
  ctx.beginPath(); ctx.arc(s[0], s[1], radius, 0, 2 * Math.PI);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width || 1.2; ctx.stroke(); }
}
function pathPoints(flat) {
  var out = [];
  for (var i = 0; i < flat.length; i += 2) out.push([flat[i], flat[i + 1]]);
  return out;
}
function upright(angle) { return angle > Math.PI / 2 ? angle - Math.PI : angle < -Math.PI / 2 ? angle + Math.PI : angle; }
function heading(a, b) {
  var s = project(a[0], a[1]), e = project(b[0], b[1]);
  return s && e && (s[0] !== e[0] || s[1] !== e[1]) ? Math.atan2(e[1] - s[1], e[0] - s[0]) : 0;
}
function mark(at, toward, day, start) {
  /* a day mark: a bar across the track at a recorded position, the record's day written by it */
  var s = project(at[0], at[1]);
  if (!s) return;
  var a = toward ? heading(at, toward) : 0, nx = -Math.sin(a), ny = Math.cos(a);
  ctx.beginPath(); ctx.moveTo(s[0] - nx * 5, s[1] - ny * 5); ctx.lineTo(s[0] + nx * 5, s[1] + ny * 5);
  ctx.strokeStyle = colors.journey; ctx.lineWidth = 1.4; ctx.stroke();
  if (start) dot(s, 3, null, colors.journey, 1.2);
  var text = dateText(day);
  ctx.font = hand(13, true);
  var w = ctx.measureText(text).width + 6;
  label(text, s[0] + nx * 8 - (nx < 0 ? w : 0), s[1] + ny * 8 + 4, colors.journey, 3, 0, null,
    [s[0] - nx * 8 - (nx > 0 ? w : 0), s[1] - ny * 8 + 4]);
}
function drawJourneys() {
  journeys.forEach(function (j) {
    var pts = pathPoints(j.path), end = j.t1 === null ? j.t0 : j.t1;
    if (!pts.length) return;
    ctx.globalAlpha = T < j.t0 ? 0.4 : 1;
    if (pts.length === 1) {
      var s = project(pts[0][0], pts[0][1]);
      if (s) { ctx.strokeStyle = colors.journey; ctx.lineWidth = 1.4; ctx.strokeRect(s[0] - 3.5, s[1] - 3.5, 7, 7); }
    } else {
      ctx.strokeStyle = colors.journey; ctx.lineWidth = T > end ? 1.7 : 1.3;
      ctx.setLineDash([7, 4]);
      ctx.beginPath(); trace(pts); ctx.stroke();
      ctx.setLineDash([]);
    }
    dayMarks(j, pts);
    ctx.globalAlpha = 1;
  });
}
function dayMarks(j, pts) {
  /* the first fix of each of the record's days the journey runs, on its asset's own track, and the
     journey's two ends at the positions its line gives: each with the day the export found for it */
  var found = marks.journeys[j.id], a = j.subject ? assetById[j.subject] : null, tr = a ? a.track : [], n = tr.length / 3;
  if (!found) return;
  found.marks.forEach(function (m) {
    var i = m[0];
    if (i >= n) return;
    var next = i + 1 < n ? [tr[i * 3 + 4], tr[i * 3 + 5]] : i > 0 ? [tr[i * 3 - 2], tr[i * 3 - 1]] : null;
    mark([tr[i * 3 + 1], tr[i * 3 + 2]], next, m[1], false);
  });
  mark(pts[0], pts[1] || null, found.from, true);
  if (found.to !== null && pts.length > 1) mark(pts[pts.length - 1], pts[pts.length - 2], found.to, false);
}
function drawTracks() {
  /* each asset's track, fix to fix: what it had sailed by the scrubber's time in ink, what was still
     to come faint; a silence longer than the gap is a break, never a line */
  assets.forEach(function (a) {
    var tr = a.track;
    [false, true].forEach(function (done) {
      var run = [];
      ctx.strokeStyle = colors.ink; ctx.lineWidth = done ? 1.3 : 0.9; ctx.globalAlpha = done ? 0.95 : 0.3;
      ctx.beginPath();
      for (var i = 0; i + 3 < tr.length; i += 3) {
        var ok = tr[i + 3] - tr[i] <= gap && (tr[i + 3] <= T) === done;
        if (ok) {
          if (!run.length) run.push([tr[i + 1], tr[i + 2]]);
          run.push([tr[i + 4], tr[i + 5]]);
        } else if (run.length) { trace(run); run = []; }
      }
      if (run.length) trace(run);
      ctx.stroke();
      ctx.globalAlpha = 1;
    });
  });
}
function drawStays(owner) {
  /* a stay is a pricked position: the prick at its centre and the ring a navigator draws round a fix;
     a night's larger, written with its day */
  staysList.forEach(function (s, n) {
    var p = project(s.lat, s.lon);
    if (!p) return;
    ctx.globalAlpha = s.t0 > T ? 0.35 : 1;
    dot(p, s.night ? 1.5 : 1.1, colors.stay, null);
    dot(p, s.night ? 4.5 : 3.2, null, colors.stay, 0.8);
    ctx.globalAlpha = 1;
    if (s.night) label(dateText(marks.stays[n]), p[0] + 5, p[1] + 13, colors.mute, 4, 0, hand(11, true), [p[0] - 40, p[1] + 13]);
  });
  if (owner && owner.stay && !owner.aboard) {
    var c = project(owner.stay.lat, owner.stay.lon);
    if (c) dot(c, 8, null, colors.you, 1.6);
  }
}
function drawPlaces() {
  places.forEach(function (p) {
    var s = project(p.lat, p.lon);
    if (!s) return;
    var r = onImage ? 0 : p.radius_m / EARTH_M / RAD / Math.cos(p.lat * RAD) * view.k;
    if (r > 7) { ctx.setLineDash([2, 3]); dot(s, r, null, colors.place, 0.8); ctx.setLineDash([]); }
    dot(s, 3.5, null, colors.place, 1.2);
    dot(s, 1.2, colors.place, null);
    if (p.id === selected) dot(s, Math.max(r, 3.5) + 5, null, colors.you, 1.4);
    ctx.font = hand(14, true);
    label(p.name, s[0] + 6, s[1] - 4, colors.place, 2, 0, hand(14, true), [s[0] - 12 - ctx.measureText(p.name).width, s[1] + 14]);
    if (!marksOnly) hits.push({x: s[0], y: s[1], r: Math.max(10, r), id: p.id, rank: 1});
  });
}
function drawAssets(owner) {
  assets.forEach(function (a) {
    var at = fixAt(a, T);
    if (!at) return;
    var s = project(at.lat, at.lon);
    if (!s) return;
    if (at.seen) dot(s, 4.5, colors.ink, colors.paper, 1.2); else dot(s, 4.5, colors.paper, colors.ink, 1.4);
    if (a.id === selected) dot(s, 10, null, colors.you, 1.4);
    var aboard = owner && owner.aboard === a.id && at.seen;
    if (aboard) dot(s, 8, null, colors.you, 1.6);
    /* the name on the track: along the leg that brought it to this fix */
    var tr = a.track, i = at.i * 3, angle = 0;
    if (i >= 3 && tr[i] - tr[i - 3] <= gap) angle = upright(heading([tr[i - 2], tr[i - 1]], [tr[i + 1], tr[i + 2]]));
    var text = aboard ? a.name + ", you aboard" : a.name;
    label(text, s[0] + 8 * Math.sin(angle) + 6 * Math.cos(angle), s[1] - 8 * Math.cos(angle) + 6 * Math.sin(angle), aboard ? colors.you : colors.ink, aboard ? 0 : 1, angle, hand(14, true));
    if (!marksOnly) hits.push({x: s[0], y: s[1], r: 12, id: a.id, rank: 0});
  });
}
function drawOwner(owner) {
  if (!owner || owner.between || owner.aboard) return;
  var s = project(owner.lat, owner.lon);
  if (!s) return;
  label("you", s[0] + 9, s[1] - 8, colors.you, 0);
}
function draw() {
  pending = false;
  hits = []; queued = [];
  drawPaper();
  var r = frameRect();
  ctx.save();
  ctx.beginPath(); ctx.rect(r[0], r[1], r[2] - r[0], r[3] - r[1]); ctx.clip();
  if (onImage) {
    drawImage();
  } else {
    drawLand();
    drawRhumbs();
    drawGraticule();
    drawRose();
  }
  var owner = ownerAt(T);
  drawTracks();
  drawJourneys();
  drawStays(owner);
  drawPlaces();
  drawAssets(owner);
  drawOwner(owner);
  labels();
  marksOnly = true;
  drawStays(owner);
  drawPlaces();
  drawAssets(owner);
  marksOnly = false;
  ctx.restore();
  if (!onImage) drawBorder();
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
  readout.textContent = parts.join(" · ");
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

/* -- the view: drag to move the chart, wheel or buttons to zoom -- */
function resize() {
  var dpr = window.devicePixelRatio || 1;
  size.w = canvas.clientWidth; size.h = canvas.clientHeight;
  canvas.width = Math.round(size.w * dpr); canvas.height = Math.round(size.h * dpr);
  redraw();
}
function paperBox() { return onImage ? [0, 0, chart.fit.width, chart.fit.height] : [-180, -north(80), 180, north(80)]; }
function scaleFor(box) {
  var r = frameRect();
  return Math.min((r[2] - r[0]) / Math.max(1e-9, box[2] - box[0]), (r[3] - r[1]) / Math.max(1e-9, box[3] - box[1]));
}
function zoomTo(k) {
  view.k = Math.max(scaleFor(paperBox()) * 0.5, Math.min(onImage ? 64 : 2e5, k));
  redraw();
}
function frameTo(box) {
  view.x = (box[0] + box[2]) / 2; view.y = (box[1] + box[3]) / 2;
  zoomTo(0.85 * scaleFor(box));
}
function normalise() {
  if (!onImage) view.x = wrap(view.x);
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
  var pts = everything(), sx = 0, sy = 0, box = [Infinity, Infinity, -Infinity, -Infinity];
  pts.forEach(function (q) { sx += Math.sin(q[1] * RAD); sy += Math.cos(q[1] * RAD); });
  var middle = Math.atan2(sx, sy) / RAD;
  pts.forEach(function (q) {
    var p = toPaper(q[0], q[1]);
    if (!p) return;
    var x = onImage ? p[0] : middle + wrap(p[0] - middle);
    box = [Math.min(box[0], x), Math.min(box[1], p[1]), Math.max(box[2], x), Math.max(box[3], p[1])];
  });
  if (!(box[2] >= box[0])) { frameTo(paperBox()); return; }
  var least = onImage ? 60 : 0.02;
  if (box[2] - box[0] < least) { box[0] -= least / 2; box[2] += least / 2; }
  if (box[3] - box[1] < least) { box[1] -= least / 2; box[3] += least / 2; }
  frameTo(box);
  normalise();
}
function focus(lat, lon) {
  var p = toPaper(lat, lon);
  if (!p) return;
  view.x = p[0]; view.y = p[1];
  normalise();
  zoomTo(Math.max(view.k, onImage ? 1 : Math.min(size.w, size.h) / 0.2));
}
var drag = null;
canvas.addEventListener("pointerdown", function (e) {
  drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false};
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", function (e) {
  if (!drag) return;
  var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  if (!drag.moved) return;
  view.x = drag.vx - dx / view.k; view.y = drag.vy - dy / view.k;
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
function zoomAt(k, x, y) {
  /* the point of the paper under (x, y) stays under it */
  var px = view.x + (x - size.w / 2) / view.k, py = view.y + (y - size.h / 2) / view.k;
  zoomTo(k);
  view.x = px - (x - size.w / 2) / view.k; view.y = py - (y - size.h / 2) / view.k;
  normalise();
}
canvas.addEventListener("wheel", function (e) {
  e.preventDefault();
  var r = canvas.getBoundingClientRect();
  zoomAt(view.k * Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
}, {passive: false});
document.getElementById("zoom-in").addEventListener("click", function () { zoomTo(view.k * 2); });
document.getElementById("zoom-out").addEventListener("click", function () { zoomTo(view.k / 2); });
document.getElementById("fit").addEventListener("click", fit);
document.getElementById("whole").addEventListener("click", function () { frameTo(paperBox()); normalise(); });

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
  row(dl, id.indexOf("asset:") === 0 ? "fixes" : "visits", s.first ? (s.first === s.last ? s.first : s.first + " – " + s.last) : "none in the window");
  Object.keys(s.identifiers || {}).forEach(function (k) { row(dl, k, s.identifiers[k]); });
  if (id.indexOf("asset:") === 0) {
    var at = fixAt(assetById[id], T);
    row(dl, "last fix", at ? at.lat + ", " + at.lon + " at " + when(at.at) + (at.seen ? "" : " (not seen since)") : "not seen yet");
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
    var p = placeById[id], a = assetById[id], at = a ? fixAt(a, T) : null;
    if (p) focus(p.lat, p.lon);
    else if (at) focus(at.lat, at.lon);
    else if (a && a.track.length) focus(a.track[1], a.track[2]);
  });
  li.appendChild(b); list.appendChild(li);
}
places.forEach(function (p) { entry(p.id, p.name, "place, " + p.kind); });
assets.forEach(function (a) { entry(a.id, a.name, "asset" + (a.kind ? ", " + a.kind : "")); });

window.addEventListener("resize", resize);
resize();
fit();
setTime(0);
})();
