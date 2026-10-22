// Fruiting model: weather + season -> index 0..1 per species, per day, per 100 m elevation band.
// Shared by the page (inlined) and by node for calibration (module.exports at the bottom).
const BANDS = Array.from({ length: 20 }, (_, i) => 300 + i * 100); // 300 … 2200 m

// Season windows at 400 m (day of year): start, peak start, peak end, end; shift = days per +100 m
// t: trapezoid on the mean air temperature of the last `td` days (°C); rain: [from, to, mid] = rain that fell
// between `from` and `to` days ago, logistic midpoint in mm; wetw: weight of the rain term; frost: factor per frosty day.
// Cèpe thresholds follow the beech-forest monitoring of Brejon Lamartinière et al. (preprint 2025: 20-day mean ≈ 13 °C,
// rain over the previous 26 days); other species from French/Swiss field guides and local GBIF months.
const SPECIES = {
  cepe:      { win: [215, 255, 310, 332], shift: [-4, -4, -4, -4], td: 20, t: [5.5, 10, 16, 21], rain: [3, 26, 55], wetw: 1, frost: 0.85 },
  bolet:     { win: [150, 175, 265, 300], shift: [2, 1, -3, -4],   td: 10, t: [11, 15, 22, 27], rain: [5, 18, 30], wetw: 1, frost: 0.9 },
  girolle:   { win: [155, 180, 280, 315], shift: [2, 1, -3, -4],   td: 10, t: [8, 12, 20, 25],  rain: [5, 25, 40], wetw: 1, frost: 0.75 },
  trompette: { win: [225, 265, 325, 350], shift: [-2, -3, -5, -5], td: 10, t: [2.5, 6, 13, 18], rain: [8, 28, 50], wetw: 1, frost: 0.6 },
  morille:   { win: [60, 84, 120, 140],   shift: [5.5, 5.5, 5.5, 5.5], td: 15, t: [5, 8.5, 13, 17], rain: [3, 14, 12], wetw: 0.4, frost: 0.9, spring: true },
};
const SP_KEYS = Object.keys(SPECIES);

const doyOf = (iso) => { const d = new Date(iso + "T12:00:00Z"); return Math.round((d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 864e5) + 1; };
const trap = (x, a, b, c, d) => x <= a || x >= d ? 0 : x < b ? (x - a) / (b - a) : x <= c ? 1 : (d - x) / (d - c);
const sig = (x, mid, w) => 1 / (1 + Math.exp(-(x - mid) / w));

// Merge the deterministic run and the seasonal extension into one daily series per point.
function series(wx) {
  const days = wx.days.concat(wx.seasonal && wx.seasonal.days ? wx.seasonal.days : []);
  const nd = wx.days.length;
  const pts = wx.points.map((p, k) => {
    const s = wx.seasonal || {};
    const pick = (a, b) => a[k].concat(b && b[k] ? b[k] : []);
    const tmax = pick(wx.tmax, s.tmax), tmin = pick(wx.tmin, s.tmin), prec = pick(wx.precip, s.precip);
    const tmean = days.map((_, i) => i < nd && wx.tmean[k][i] != null ? wx.tmean[k][i] : (tmax[i] + tmin[i]) / 2);
    // soil warmth: 7-day mean air temperature + an offset calibrated on the modelled soil temperature
    const air7 = tmean.map((_, i) => avg(tmean.slice(Math.max(0, i - 6), i + 1)));
    const diffs = [];
    for (let i = 0; i < nd; i++) if (wx.soilT[k][i] != null) diffs.push(wx.soilT[k][i] - air7[i]);
    const off = diffs.length ? avg(diffs.slice(-30)) : 0.5;
    return { z: p.z, tmax, tmin, tmean, prec: prec.map((x) => x || 0), soil: air7.map((x) => x + off), snow: wx.snow ? wx.snow[k] : [] };
  });
  pts.sort((a, b) => a.z - b.z);
  return { days, nd, pts };
}
const avg = (a) => { let s = 0, n = 0; for (const x of a) if (x != null && !Number.isNaN(x)) { s += x; n++; } return n ? s / n : 0; };

// Interpolate a per-point daily variable to elevation z (linear between points sorted by elevation;
// temperature extrapolated with -0.55 °C / 100 m, rain held constant beyond the end points).
function atZ(S, key, i, z, isTemp) {
  const ps = S.pts;
  if (z <= ps[0].z) return ps[0][key][i] + (isTemp ? (ps[0].z - z) * 0.0055 : 0);
  const top = ps[ps.length - 1];
  if (z >= top.z) return top[key][i] - (isTemp ? (z - top.z) * 0.0055 : 0);
  for (let j = 0; j < ps.length - 1; j++) {
    const a = ps[j], b = ps[j + 1];
    if (z >= a.z && z <= b.z) { const t = (z - a.z) / (b.z - a.z); return a[key][i] * (1 - t) + b[key][i] * t; }
  }
}

// Index for one species, one band, one day index i (into S.days)
function fruit(S, sp, z, i, detail) {
  const P = SPECIES[sp];
  const doy = doyOf(S.days[i]);
  const dz = (z - 400) / 100;
  const w = P.win.map((d, k) => d + P.shift[k] * dz);
  const season = trap(doy, w[0], w[1], w[2], w[3]);
  if (season <= 0) return detail ? { v: 0, season: 0 } : 0;
  let tsum = 0, tn = 0;
  for (let k = 0; k < P.td; k++) if (i - k >= 0) { tsum += atZ(S, "tmean", i - k, z, true); tn++; }
  const tmean = tsum / tn;
  const temp = trap(tmean, P.t[0], P.t[1], P.t[2], P.t[3]);
  // rain that can trigger today's flush: fell between rain[0] and rain[1] days ago
  let trig = 0;
  for (let k = P.rain[0]; k <= P.rain[1]; k++) if (i - k >= 0) trig += atZ(S, "prec", i - k, z, false);
  // moisture kept up recently (persistence of the flush)
  let recent = 0;
  for (let k = 0; k < 10; k++) if (i - k >= 0) recent += atZ(S, "prec", i - k, z, false);
  const wet = (1 - P.wetw) + P.wetw * sig(trig, P.rain[2], P.rain[2] * 0.3) * (0.55 + 0.45 * sig(recent, 6, 3));
  // frost / snow in the last 5 days
  let frost = 1;
  for (let k = 0; k < 5; k++) if (i - k >= 0) {
    const tn = atZ(S, "tmin", i - k, z, true);
    if (tn < -1) frost *= P.frost;
    if (tn < -4) frost *= P.frost;
  }
  // spring morels need the soil to be warming
  let warm = 1;
  if (P.spring && i >= 10) warm = 0.6 + 0.4 * sig(atZ(S, "soil", i, z, true) - atZ(S, "soil", i - 10, z, true), 0.5, 0.7);
  // a cool snap after warmth often starts cèpe flushes
  let snap = 1;
  if (sp === "cepe" && i >= 10) {
    const before = avg([3, 4, 5, 6, 7, 8, 9].map((k) => atZ(S, "tmax", i - k, z, true)));
    const now = avg([0, 1, 2].map((k) => atZ(S, "tmax", i - k, z, true)));
    if (before - now > 4 && before > 16) snap = 1.15;
  }
  const v = Math.min(1, season * temp * wet * frost * warm * snap);
  return detail ? { v, season, temp, tmean, trig, recent, wet, frost } : v;
}

// Calendar-only index (no weather): the season window alone
function seasonOnly(sp, z, iso) {
  const P = SPECIES[sp], dz = (z - 400) / 100, w = P.win.map((d, k) => d + P.shift[k] * dz);
  return trap(doyOf(iso), w[0], w[1], w[2], w[3]);
}

// Full table: [species][day][band]
function table(wx) {
  const S = series(wx);
  const out = {};
  for (const sp of SP_KEYS) out[sp] = S.days.map((_, i) => BANDS.map((z) => fruit(S, sp, z, i)));
  return { S, out };
}

if (typeof module !== "undefined") module.exports = { SPECIES, SP_KEYS, BANDS, series, fruit, table, doyOf, seasonOnly };
