"use strict";
// Champignons du Salève — web map (MapLibre). The fruiting model lives in model.js.

// ---------------------------------------------------------------------------------------------- constants
const W = 5.88, E = 6.40, SO = 46.00, NO = 46.36;
const G = 2048; // habitat grid (columns linear in longitude, rows linear in Web Mercator y)
const SP_META = {
  cepe:      { name: "Cèpe de Bordeaux", short: "Cèpe", latin: "Boletus edulis", col: "#e0602a" },
  bolet:     { name: "Autres bolets", short: "Bolets", latin: "B. reticulatus, aereus, pinophilus…", col: "#d6336c" },
  girolle:   { name: "Girolle", short: "Girolle", latin: "Cantharellus cibarius", col: "#f2b705" },
  trompette: { name: "Trompette des morts", short: "Trompette", latin: "Craterellus cornucopioides", col: "#8e6ce0" },
  morille:   { name: "Morilles", short: "Morille", latin: "Morchella spp.", col: "#1fb5a6" },
};
const CLASSES = ["Hors forêt", "Feuillus mélangés", "Chênaie", "Hêtraie", "Châtaigneraie", "Mixte à feuillus dominants", "Mixte à résineux dominants",
  "Sapinière / pessière", "Pinède", "Autres résineux (douglas, mélèze)", "Peupleraie", "Lande, pelouse", "Feuillus (chênaie-charmaie)", "Forêt mixte", "Résineux"];
const GEOL = ["—", "Calcaire", "Grès et flysch (sol acide)", "Moraine, molasse", "Alluvions de rivière", "Calcaire, sol décarbonaté en surface"];
const REGIONS = ["", "Genève", "Vaud", "Ain", "Haute-Savoie"];
const REGION_RULE = {
  1: "Genève : 2 kg par personne et par jour.",
  2: "Vaud : 2 kg par personne et par jour, de 7 h à 20 h.",
  3: "France (Ain) : accord du propriétaire ; forêt communale ou domaniale : env. 5 L tolérés.",
  4: "France (Haute-Savoie) : accord du propriétaire ; forêt communale ou domaniale : env. 5 L tolérés.",
};
const RULE_TXT = { 3: "Cueillette interdite", 2: "Zone protégée, règles à vérifier", 1: "Zone protégée, cueillette admise" };
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const DOW = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
const WX_POINTS = [
  { id: "bassin", name: "Bassin genevois", lat: 46.20, lon: 6.10, z: 420 },
  { id: "bornes", name: "Pied du Salève / Bornes", lat: 46.07, lon: 6.20, z: 800 },
  { id: "jura", name: "Jura gessien", lat: 46.30, lon: 6.02, z: 1000 },
  { id: "saleve", name: "Plateau du Salève", lat: 46.13, lon: 6.18, z: 1150 },
  { id: "voirons", name: "Voirons", lat: 46.22, lon: 6.35, z: 1300 },
];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const isSmall = () => innerWidth < 760;

// ---------------------------------------------------------------------------------------------- state
const st = { sp: "all", day: 0, mode: "f", base: "sat", rules: true, sectors: true, heat: 0.85, exag: 1.3 };
try { Object.assign(st, JSON.parse(localStorage.getItem("champi-ui") || "{}"), { day: 0 }); } catch (e) {}
function saveUi() { try { localStorage.setItem("champi-ui", JSON.stringify({ sp: st.sp, mode: st.mode, base: st.base, rules: st.rules, sectors: st.sectors, heat: st.heat, exag: st.exag })); } catch (e) {} }
let wx = null, TBL = null, DAYS = [], TODAY = 0, NDET = 0, wxState = "loading";
let sectors = [], places = [], reserves = null, forpub = [], chBorder = [];
let dem = null, HAB = null, NZ = null;
let userPos = null, spotMarkers = [], userAreaInfo = "";

const $ = (id) => document.getElementById(id);
const isoToday = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const fmtDate = (iso) => { const d = new Date(iso + "T12:00:00Z"); return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
const level = (v) => v >= 0.66 ? "fort" : v >= 0.4 ? "bon" : v >= 0.18 ? "faible" : "nul";
const fr = (x, d = 0) => x.toLocaleString("fr-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hexRgb = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

// ---------------------------------------------------------------------------------------------- geo helpers
const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
const unmerc = (y) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;
const MY0 = merc(NO), MY1 = merc(SO);
const inBox = (lon, lat) => lon > W && lon < E && lat > SO && lat < NO;
function gridXY(lon, lat) { return [Math.floor((lon - W) / (E - W) * G), Math.floor((merc(lat) - MY0) / (MY1 - MY0) * G)]; }
function gridLonLat(x, y) { return [W + (x + 0.5) / G * (E - W), unmerc(MY0 + (y + 0.5) / G * (MY1 - MY0))]; }
function elevAt(lon, lat) {
  if (!dem) return 0;
  const fx = (lon - W) / (E - W) * 1024 - 0.5, fy = (NO - lat) / (NO - SO) * 1024 - 0.5;
  const x0 = Math.max(0, Math.min(1022, Math.floor(fx))), y0 = Math.max(0, Math.min(1022, Math.floor(fy)));
  const tx = Math.min(1, Math.max(0, fx - x0)), ty = Math.min(1, Math.max(0, fy - y0)), g = (x, y) => dem[y * 1024 + x];
  return g(x0, y0) * (1 - tx) * (1 - ty) + g(x0 + 1, y0) * tx * (1 - ty) + g(x0, y0 + 1) * (1 - tx) * ty + g(x0 + 1, y0 + 1) * tx * ty;
}
function inRing(lon, lat, ring) {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
function distKm(a, b) { return Math.hypot((a[0] - b[0]) * 111.32 * Math.cos(a[1] * Math.PI / 180), (a[1] - b[1]) * 111.2); }
function bearing(a, b) { const dx = (b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), dy = b[1] - a[1]; return (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360; }

// ---------------------------------------------------------------------------------------------- forecast access
function F(sp, b, d) { return TBL ? TBL.out[sp][d][b] : seasonOnly(sp, BANDS[b], DAYS[d]) * 0.75; }
function Fz(sp, z, d) {
  const u = Math.max(0, Math.min(19, (z - 300) / 100)), b0 = Math.floor(u), b1 = Math.min(19, b0 + 1), t = u - b0;
  return F(sp, b0, d) * (1 - t) + F(sp, b1, d) * t;
}
const spList = () => st.sp === "all" ? SP_KEYS : [st.sp];
function buildDays() {
  const today = isoToday();
  if (wx) {
    TBL = table(wx); DAYS = TBL.S.days; NDET = wx.days.length;
    TODAY = DAYS.indexOf(today); if (TODAY < 0) TODAY = Math.max(0, DAYS.indexOf(wx.today));
  } else {
    TBL = null; DAYS = []; NDET = 0;
    for (let k = -21; k <= 60; k++) DAYS.push(addDays(today, k));
    TODAY = 21;
  }
  const slider = $("day");
  slider.min = Math.max(0, TODAY - 30); slider.max = DAYS.length - 1;
  if (!st.dayChosen) st.day = TODAY;
  st.day = Math.max(+slider.min, Math.min(st.day, DAYS.length - 1));
}

// ---------------------------------------------------------------------------------------------- live weather (Open-Meteo, cached 3 h)
async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
async function fetchWeather() {
  try {
    const c = JSON.parse(localStorage.getItem("champi-wx") || "null");
    if (c && Date.now() - c.t < 3 * 3600e3 && c.doc.today === isoToday()) return c.doc;
  } catch (e) {}
  const q = (k) => WX_POINTS.map((p) => p[k]).join(",");
  const fc = await getJSON(`https://api.open-meteo.com/v1/forecast?latitude=${q("lat")}&longitude=${q("lon")}&elevation=${q("z")}` +
    "&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,snowfall_sum" +
    "&hourly=soil_temperature_6cm&past_days=60&forecast_days=16&timezone=Europe%2FZurich");
  const days = fc[0].daily.time;
  const dailyMean = (v) => days.map((_, d) => { const xs = v.slice(d * 24, d * 24 + 24).filter((x) => x != null); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; });
  const doc = { updated: new Date().toISOString(), today: isoToday(), points: WX_POINTS, days, tmax: [], tmin: [], tmean: [], precip: [], snow: [], soilT: [],
    seasonal: { days: [], tmax: [], tmin: [], precip: [] } };
  for (const loc of fc) {
    const d = loc.daily;
    doc.tmax.push(d.temperature_2m_max); doc.tmin.push(d.temperature_2m_min); doc.tmean.push(d.temperature_2m_mean);
    doc.precip.push(d.precipitation_sum); doc.snow.push(d.snowfall_sum); doc.soilT.push(dailyMean(loc.hourly.soil_temperature_6cm));
  }
  // seasonal ensemble mean, kept for the 30 days after the deterministic run
  try {
    const last = days[days.length - 1];
    const seas = await Promise.all(WX_POINTS.map((p) => getJSON(`https://seasonal-api.open-meteo.com/v1/seasonal?latitude=${p.lat}&longitude=${p.lon}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&forecast_days=60`)));
    seas.forEach((s, k) => {
      const sd = s.daily, t = sd.time;
      const ens = (v) => { const keys = Object.keys(sd).filter((x) => x.startsWith(v)); return t.map((_, i) => { const xs = keys.map((kk) => sd[kk][i]).filter((x) => x != null); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }); };
      const tx = ens("temperature_2m_max"), tn = ens("temperature_2m_min"), pr = ens("precipitation_sum");
      const keep = t.map((x, i) => (x > last && x <= addDays(last, 30) ? i : -1)).filter((i) => i >= 0);
      const dz = (WX_POINTS[k].z - (s.elevation ?? WX_POINTS[k].z)) * -0.0055;
      if (!doc.seasonal.days.length) doc.seasonal.days = keep.map((i) => t[i]);
      doc.seasonal.tmax.push(keep.map((i) => tx[i] == null ? null : tx[i] + dz));
      doc.seasonal.tmin.push(keep.map((i) => tn[i] == null ? null : tn[i] + dz));
      doc.seasonal.precip.push(keep.map((i) => pr[i]));
    });
    if (doc.seasonal.tmax.some((a) => a.some((x) => x == null))) doc.seasonal = { days: [], tmax: [], tmin: [], precip: [] };
  } catch (e) { doc.seasonal = { days: [], tmax: [], tmin: [], precip: [] }; }
  try { localStorage.setItem("champi-wx", JSON.stringify({ t: Date.now(), doc })); } catch (e) {}
  return doc;
}

// ---------------------------------------------------------------------------------------------- data loading
async function decode(url) {
  const r = await fetch(url); if (!r.ok) throw new Error(`${url} ${r.status}`);
  const bmp = await createImageBitmap(await r.blob(), { premultiplyAlpha: "none", colorSpaceConversion: "none" });
  const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
  const cx = c.getContext("2d", { willReadFrequently: true }); cx.drawImage(bmp, 0, 0);
  return cx.getImageData(0, 0, bmp.width, bmp.height).data;
}
async function loadData() {
  const files = [["habA", () => decode("data/hab_a.png")], ["habB", () => decode("data/hab_b.png")], ["mask", () => decode("data/mask.png")],
    ["dem", () => decode("data/dem.png")], ["sectors", () => getJSON("data/sectors.json")], ["places", () => getJSON("data/places.json")],
    ["reserves", () => getJSON("data/reserves.geojson")], ["forpub", () => getJSON("data/forets_publiques.json")], ["border", () => getJSON("data/ch_border.json")]];
  let done = 0;
  const R = Object.fromEntries(await Promise.all(files.map(([k, f]) => f().then((v) => { done++; $("loadBar").value = done / files.length; return [k, v]; }))));
  const n = G * G;
  HAB = { h: [0, 1, 2, 3, 4].map(() => new Uint8Array(n)), z: new Uint8Array(n), rule: new Uint8Array(n), cls: new Uint8Array(n), rg: new Uint8Array(n) };
  const nz = [];
  for (let i = 0, o = 0; i < n; i++, o += 4) {
    HAB.h[0][i] = R.habA[o]; HAB.h[1][i] = R.habA[o + 1]; HAB.h[2][i] = R.habA[o + 2];
    HAB.h[3][i] = R.habB[o]; HAB.h[4][i] = R.habB[o + 1]; HAB.z[i] = R.habB[o + 2];
    HAB.rule[i] = Math.round(R.mask[o] / 80); HAB.cls[i] = Math.round(R.mask[o + 1] / 16); HAB.rg[i] = R.mask[o + 2];
    if (R.habA[o] | R.habA[o + 1] | R.habA[o + 2] | R.habB[o] | R.habB[o + 1]) nz.push(i);
  }
  NZ = Uint32Array.from(nz);
  dem = new Float32Array(1024 * 1024);
  for (let i = 0; i < dem.length; i++) dem[i] = (R.dem[i * 4] * 256 + R.dem[i * 4 + 1]) / 10;
  sectors = R.sectors; places = R.places; reserves = R.reserves; forpub = R.forpub; chBorder = R.border;
}

// ---------------------------------------------------------------------------------------------- habitat overlay (canvas source)
// One spare column keeps the canvas non-power-of-two: MapLibre would otherwise sample it with mipmaps it never builds (renders black).
const OVW = G + 1, E_OV = E + (E - W) / G;
const ovCanvas = document.createElement("canvas"); ovCanvas.width = OVW; ovCanvas.height = G;
const ovCtx = ovCanvas.getContext("2d");
const ovImg = ovCtx.createImageData(OVW, G);
const ov32 = new Uint32Array(ovImg.data.buffer);
// per-species factor for each altitude code (code = (z_eff - 300) / 100 * 12)
function lutFor(sp, d) {
  const L = new Float32Array(256);
  for (let c = 0; c < 256; c++) L[c] = st.mode === "f" ? Fz(sp, 300 + c / 12 * 100, d) : 1;
  return L;
}
let LUTS = null;
function scoreAt(i) { // best score at grid cell i for the selected species: [score, species index]
  let best = 0, bi = -1; const zc = HAB.z[i];
  for (const sp of spList()) { const k = SP_KEYS.indexOf(sp); const v = HAB.h[k][i] / 252 * LUTS[k][zc]; if (v > best) { best = v; bi = k; } }
  return [best, bi];
}
let ovPending = false;
function scheduleOverlay() { if (!ovPending) { ovPending = true; requestAnimationFrame(() => { ovPending = false; drawOverlay(); }); } }
function drawOverlay() {
  if (!HAB) return;
  LUTS = SP_KEYS.map((sp) => lutFor(sp, st.day));
  const sel = st.sp === "all" ? -1 : SP_KEYS.indexOf(st.sp);
  const cols = SP_KEYS.map((k) => hexRgb(SP_META[k].col));
  const heat = st.heat, h = HAB.h, z = HAB.z;
  ov32.fill(0);
  for (let j = 0; j < NZ.length; j++) {
    const i = NZ[j], zc = z[i];
    let sc, k;
    if (sel >= 0) { sc = h[sel][i] * LUTS[sel][zc] / 252; k = sel; }
    else {
      sc = 0; k = 0;
      for (let s = 0; s < 5; s++) { const v = h[s][i] * LUTS[s][zc]; if (v > sc) { sc = v; k = s; } }
      sc /= 252;
    }
    if (sc < 0.22) continue;
    let a = Math.min(1, (sc - 0.22) / 0.58); a = a * a * (3 - 2 * a);
    const hot = sc > 0.78 ? Math.min(1, (sc - 0.78) / 0.22) * 0.45 : 0;
    const c = cols[k];
    const r = c[0] + (255 - c[0]) * hot, g = c[1] + (250 - c[1]) * hot, b = c[2] + (235 - c[2]) * hot;
    ov32[i + ((i / G) | 0)] = ((a * heat * 0.92 * 255) << 24) | (b << 16) | (g << 8) | r;
  }
  ovCtx.putImageData(ovImg, 0, 0);
  const src = map.getSource && map.getSource("hab");
  if (src) { src.play(); requestAnimationFrame(() => src.pause()); }
}

// ---------------------------------------------------------------------------------------------- map
// IGN orthophotos stop at the border: tiles straddling Switzerland get the Swiss part cut out so swisstopo shows through.
const tileLon = (x, z) => x / 2 ** z * 360 - 180;
const tileLat = (y, z) => unmerc(Math.PI * (1 - 2 * y / 2 ** z));
let EMPTY_TILE = null;
async function emptyTile() {
  if (EMPTY_TILE) return EMPTY_TILE;
  const c = document.createElement("canvas"); c.width = c.height = 1;
  EMPTY_TILE = await (await new Promise((res) => c.toBlob(res, "image/png"))).arrayBuffer();
  return EMPTY_TILE;
}
function borderRelation(z, x, y) {
  const w = tileLon(x, z), e = tileLon(x + 1, z), n = tileLat(y, z), s = tileLat(y + 1, z);
  let vertexInside = false, cornersIn = 0;
  for (const ring of chBorder) for (const [lon, lat] of ring) if (lon > w && lon < e && lat > s && lat < n) { vertexInside = true; break; }
  for (const [lon, lat] of [[w, n], [e, n], [e, s], [w, s], [(w + e) / 2, (n + s) / 2]]) if (chBorder.some((r) => inRing(lon, lat, r))) cornersIn++;
  if (!vertexInside && cornersIn === 0) return "fr";
  if (!vertexInside && cornersIn === 5) return "ch";
  return "edge";
}
maplibregl.addProtocol("ignfr", async (params, abort) => {
  const [z, x, y] = params.url.slice("ignfr://".length).split("/").map(Number);
  const rel = chBorder.length ? borderRelation(z, x, y) : "fr";
  if (rel === "ch") return { data: await emptyTile() };
  const url = `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX=${z}&TILEROW=${y}&TILECOL=${x}&FORMAT=image/jpeg`;
  const r = await fetch(url, { signal: abort.signal });
  if (!r.ok) throw new Error(`IGN ${r.status}`);
  const buf = await r.arrayBuffer();
  if (rel === "fr") return { data: buf };
  const bmp = await createImageBitmap(new Blob([buf]));
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const cx = c.getContext("2d"); cx.drawImage(bmp, 0, 0, 256, 256);
  cx.globalCompositeOperation = "destination-out"; cx.beginPath();
  const px = (lon) => (lon - tileLon(x, z)) / (tileLon(x + 1, z) - tileLon(x, z)) * 256;
  const my0 = merc(tileLat(y, z)), my1 = merc(tileLat(y + 1, z)), py = (lat) => (merc(lat) - my0) / (my1 - my0) * 256;
  for (const ring of chBorder) { ring.forEach(([lon, lat], i) => i ? cx.lineTo(px(lon), py(lat)) : cx.moveTo(px(lon), py(lat))); cx.closePath(); }
  cx.fill();
  return { data: await (await new Promise((res) => c.toBlob(res, "image/png"))).arrayBuffer() };
});

const map = new maplibregl.Map({
  container: "map", style: "https://tiles.openfreemap.org/styles/liberty",
  center: [6.17, 46.15], zoom: isSmall() ? 9.6 : 10.3, pitch: 55, bearing: -18, maxPitch: 78,
  maxBounds: [[5.62, 45.86], [6.66, 46.5]], attributionControl: false, hash: true,
});
map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Habitats : IGN BD Forêt, OFEV, swisstopo, SITG · Météo : Open-Meteo · Photo : © IGN, © swisstopo · Relief : © Mapterhorn" }), isSmall() ? "top-left" : "bottom-right");
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
const geoCtl = new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true, timeout: 15000 }, trackUserLocation: true, showUserHeading: true, fitBoundsOptions: { maxZoom: 15 } });
map.addControl(geoCtl, "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), isSmall() ? "top-left" : "bottom-right");

const FILL_LAYERS = [];
function hatch(color) {
  const c = document.createElement("canvas"); c.width = c.height = 12;
  const cx = c.getContext("2d"); cx.strokeStyle = color; cx.lineWidth = 2.4;
  cx.beginPath(); for (let k = -12; k <= 24; k += 6) { cx.moveTo(k, 12); cx.lineTo(k + 12, 0); } cx.stroke();
  return cx.getImageData(0, 0, 12, 12);
}
function sectorRings() {
  return { type: "FeatureCollection", features: sectors.map((s) => ({ type: "Feature", properties: { id: s.id },
    geometry: { type: "LineString", coordinates: Array.from({ length: 97 }, (_, k) => { const a = k / 96 * Math.PI * 2; return [s.lon + Math.cos(a) * s.r / 77.1, s.lat + Math.sin(a) * s.r / 111.2]; }) } })) };
}
function setupLayers() {
  const style = map.getStyle();
  const font = map.getLayoutProperty("label_village", "text-font") || ["Noto Sans Regular"];
  const fontBold = font.map((f) => f.replace("Regular", "Bold"));
  for (const l of style.layers) if ((l.type === "fill" || l.type === "fill-extrusion") && l.id !== "background") FILL_LAYERS.push(l.id);
  map.addSource("dem", { type: "raster-dem", tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"], tileSize: 512, encoding: "terrarium", maxzoom: 15 });
  map.addSource("dem-hs", { type: "raster-dem", tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"], tileSize: 512, encoding: "terrarium", maxzoom: 15 });
  map.addSource("swissimage", { type: "raster", tiles: ["https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg"], tileSize: 256, maxzoom: 19 });
  map.addSource("ignortho", { type: "raster", tiles: ["ignfr://{z}/{x}/{y}"], tileSize: 256, maxzoom: 19, bounds: [5.6, 45.85, 6.7, 46.5] });
  map.addSource("hab", { type: "canvas", canvas: ovCanvas, coordinates: [[W, NO], [E_OV, NO], [E_OV, SO], [W, SO]], animate: false });
  map.addSource("reserves", { type: "geojson", data: reserves });
  map.addSource("rings", { type: "geojson", data: sectorRings() });
  map.addImage("hatch-red", hatch("rgba(196,42,60,.85)"));
  map.addImage("hatch-orange", hatch("rgba(227,149,34,.75)"));
  const firstFill = style.layers.find((l) => l.type === "fill").id;
  map.addLayer({ id: "sat-ch", type: "raster", source: "swissimage", paint: { "raster-fade-duration": 120 } }, firstFill);
  map.addLayer({ id: "sat-fr", type: "raster", source: "ignortho", paint: { "raster-fade-duration": 120 } }, firstFill);
  map.addLayer({ id: "hillshade", type: "hillshade", source: "dem-hs", paint: { "hillshade-exaggeration": 0.4, "hillshade-shadow-color": "#3b3a33", "hillshade-highlight-color": "#ffffff" } }, "waterway_tunnel");
  map.addLayer({ id: "hab", type: "raster", source: "hab", paint: { "raster-fade-duration": 0, "raster-resampling": "linear" } }, "waterway_tunnel");
  map.addLayer({ id: "res-fill", type: "fill", source: "reserves", filter: [">=", ["get", "rule"], 2], paint: { "fill-pattern": ["case", ["==", ["get", "rule"], 3], "hatch-red", "hatch-orange"] } }, "waterway_tunnel");
  map.addLayer({ id: "res-line", type: "line", source: "reserves", filter: [">=", ["get", "rule"], 2], paint: { "line-color": ["case", ["==", ["get", "rule"], 3], "#c42a3c", "#e39522"], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.8, 15, 2] } }, "waterway_tunnel");
  // OSM paths and tracks, visible from zoom 12 (the base style only shows paths from 14)
  map.addLayer({ id: "osm-trails", type: "line", source: "openmaptiles", "source-layer": "transportation", minzoom: 12,
    filter: ["match", ["get", "class"], ["path", "track"], true, false],
    paint: { "line-color": "#ffe28c", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.8, 15, 1.8, 18, 3], "line-dasharray": [2.5, 1.5], "line-opacity": 0.95 } }, "waterway_line_label");
  map.addLayer({ id: "rings", type: "line", source: "rings", paint: { "line-color": "#fff3dc", "line-width": 1.6, "line-dasharray": [3, 2], "line-opacity": 0.9 } }, "waterway_line_label");
  map.addLayer({ id: "peaks", type: "symbol", source: "openmaptiles", "source-layer": "mountain_peak", minzoom: 10,
    layout: { "text-field": ["concat", "▲ ", ["get", "name"], ["case", ["has", "ele"], ["concat", "\n", ["to-string", ["get", "ele"]], " m"], ""]], "text-font": fontBold, "text-size": 11.5, "text-anchor": "top", "text-offset": [0, 0.2] },
    paint: { "text-color": "#3b2a12", "text-halo-color": "#fff8e8", "text-halo-width": 1.6 } });
  map.setTerrain({ source: "dem", exaggeration: st.exag });
  map.setSky && map.setSky({ "sky-color": "#a9c1d0", "horizon-color": "#e4e8e0", "fog-color": "#e4e8e0", "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.35 });
  applyLayerState();
}
function vis(id, on) { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); }
function applyLayerState() {
  if (!map.getLayer("hab")) return;
  const sat = st.base === "sat";
  vis("sat-ch", sat); vis("sat-fr", sat); vis("hillshade", !sat);
  for (const id of FILL_LAYERS) vis(id, !sat);
  vis("res-fill", st.rules); vis("res-line", st.rules); vis("rings", st.sectors);
  map.setPaintProperty("osm-trails", "line-color", sat ? "#ffe28c" : "#9a5b2a");
  for (const m of sectorMarkers) m.getElement().style.display = st.sectors ? "" : "none";
  if (map.getTerrain()) map.setTerrain({ source: "dem", exaggeration: st.exag });
}
function setPadding() {
  const p = $("panel").getBoundingClientRect();
  const pad = isSmall() ? { top: 0, bottom: Math.max(0, innerHeight - p.top), left: 0, right: 0 } : { top: 0, bottom: 0, left: p.right, right: 0 };
  map.setPadding(pad);
}

// ---------------------------------------------------------------------------------------------- sectors
let sectorMarkers = [];
function buildSectorMarkers() {
  sectorMarkers.forEach((m) => m.remove());
  sectorMarkers = sectors.map((s) => {
    const el = document.createElement("div");
    el.className = "sec"; el.tabIndex = 0; el.setAttribute("role", "button");
    el.innerHTML = "<span></span><small></small>"; el.firstChild.textContent = s.name;
    el.addEventListener("click", (e) => { e.stopPropagation(); showSector(s, true); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showSector(s, true); } });
    const m = new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat([s.lon, s.lat]).addTo(map);
    m._sec = s; return m;
  });
}
function sectorScore(s, d) {
  let best = null, bestV = 0, bestRel = 0;
  for (const sp of spList()) {
    const stt = s.stats[SP_KEYS.indexOf(sp)];
    let v = 0, hab = 0;
    for (let b = 0; b < 20; b++) { const f = st.mode === "f" ? F(sp, b, d) : 1; v += stt[b] * f; hab += stt[b]; }
    if (v > bestV) { bestV = v; best = sp; bestRel = hab > 0 ? v / hab : 0; }
  }
  return { v: bestV, best: best || spList()[0], rel: bestRel };
}
function updateSectorMarkers() {
  for (const m of sectorMarkers) {
    const sc = sectorScore(m._sec, st.day), el = m.getElement();
    el.style.setProperty("--sec-c", SP_META[sc.best].col);
    el.lastChild.textContent = sc.v > 0.002 ? `${SP_META[sc.best].short} · ${level(sc.rel)}` : "calme";
  }
}
function flyTo(lon, lat, zoom = 13.5) { map.flyTo({ center: [lon, lat], zoom, pitch: Math.max(map.getPitch(), 45), duration: reduceMotion ? 0 : 1600, essential: true }); }

// ---------------------------------------------------------------------------------------------- near me
function nearbySpots(pos, radiusKm = 1.5, max = 6) {
  const [cx, cy] = gridXY(pos[0], pos[1]);
  const kmX = (E - W) * 111.32 * Math.cos(46.18 * Math.PI / 180) / G, kmY = (NO - SO) * 111.2 / G;
  const rx = Math.ceil(radiusKm / kmX), ry = Math.ceil(radiusKm / kmY);
  const cand = [];
  for (let y = Math.max(0, cy - ry); y <= Math.min(G - 1, cy + ry); y++) for (let x = Math.max(0, cx - rx); x <= Math.min(G - 1, cx + rx); x++) {
    const dx = (x - cx) * kmX, dy = (y - cy) * kmY; if (dx * dx + dy * dy > radiusKm * radiusKm) continue;
    const i = y * G + x; if (HAB.rule[i] === 3 || HAB.cls[i] === 0) continue;
    const [sc, k] = scoreAt(i); if (sc >= 0.3) cand.push([sc, x, y, k]);
  }
  cand.sort((a, b) => b[0] - a[0]);
  const out = [];
  for (const c of cand) {
    if (out.some((o) => Math.hypot((o[1] - c[1]) * kmX, (o[2] - c[2]) * kmY) < 0.25)) continue;
    out.push(c); if (out.length >= max) break;
  }
  return out.map(([sc, x, y, k]) => { const ll = gridLonLat(x, y); return { lon: ll[0], lat: ll[1], sc, sp: SP_KEYS[k], d: distKm(pos, ll), b: bearing(pos, ll), z: Math.round(elevAt(ll[0], ll[1])), rule: HAB.rule[y * G + x] }; });
}
function renderNear() {
  spotMarkers.forEach((m) => m.remove()); spotMarkers = [];
  const ol = $("nearList"); ol.textContent = "";
  const msg = $("nearMsg");
  if (!userPos) return;
  if (!inBox(userPos[0], userPos[1])) { msg.textContent = "Vous êtes hors de la zone couverte par la carte (Salève, Voirons, Vuache, Jura gessien, bassin genevois)."; return; }
  if (!HAB) { msg.textContent = "Chargement des habitats…"; return; }
  LUTS = LUTS || SP_KEYS.map((sp) => lutFor(sp, st.day));
  const [gx, gy] = gridXY(userPos[0], userPos[1]), i = gy * G + gx;
  const [sc, k] = scoreAt(i);
  const z = Math.round(elevAt(userPos[0], userPos[1]));
  const here = HAB.rule[i] === 3 ? " · <b>réserve : cueillette interdite</b>" : "";
  msg.innerHTML = `Ici : ${z} m, ${esc(HAB.cls[i] ? CLASSES[HAB.cls[i]].toLowerCase() : "hors forêt")}` + (k >= 0 && sc > 0.05 ? ` · ${SP_META[SP_KEYS[k]].short} ${level(sc)}` : "") + here +
    (userPos[2] ? ` <span style="white-space:nowrap">(± ${Math.round(userPos[2])} m)</span>` : "");
  const spots = nearbySpots(userPos);
  if (!spots.length) { msg.innerHTML += "<br>Aucun coin favorable à moins de 1,5 km pour cette date et cette espèce."; return; }
  spots.forEach((s, n) => {
    const col = SP_META[s.sp].col;
    const li = document.createElement("li"), b = document.createElement("button");
    b.style.setProperty("--c", col);
    b.innerHTML = `<span class="nm"><span class="num">${n + 1}</span></span><span class="bar"><i></i></span><span class="sb"></span>`;
    b.querySelector(".nm").append(`${fr(s.d, s.d < 1 ? 2 : 1)} km ${COMPASS[Math.round(s.b / 45) % 8]}`);
    b.querySelector(".bar i").style.width = `${Math.round(s.sc * 100)}%`;
    b.querySelector(".sb").textContent = `${SP_META[s.sp].short} ${level(s.sc)} · ${s.z} m` + (s.rule === 2 ? " · zone protégée" : "");
    b.onclick = () => { flyTo(s.lon, s.lat, 16); showPoint(s.lon, s.lat); };
    li.appendChild(b); ol.appendChild(li);
    const el = document.createElement("div"); el.className = "spot"; el.style.setProperty("--c", col); el.innerHTML = `<b>${n + 1}</b>`;
    el.title = `${SP_META[s.sp].short} ${level(s.sc)}, ${fr(s.d, 1)} km`;
    el.addEventListener("click", (e) => { e.stopPropagation(); showPoint(s.lon, s.lat); });
    spotMarkers.push(new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat([s.lon, s.lat]).addTo(map));
  });
}
geoCtl.on("geolocate", (p) => {
  const first = !userPos;
  userPos = [p.coords.longitude, p.coords.latitude, p.coords.accuracy];
  if (first || !renderNear._t || Date.now() - renderNear._t > 20000) { renderNear._t = Date.now(); renderNear(); }
});
geoCtl.on("error", () => { $("nearMsg").textContent = "Localisation refusée ou indisponible. Autorisez-la dans les réglages du navigateur, puis réessayez."; });
$("locBtn").onclick = () => {
  const s = geoCtl._watchState; // already tracking: recenter instead of toggling the control off
  if (userPos && (s === "ACTIVE_LOCK" || s === "BACKGROUND")) flyTo(userPos[0], userPos[1], 15); else geoCtl.trigger();
};

// ---------------------------------------------------------------------------------------------- UI: species, date, chart
function renderSpecies() {
  const box = $("species"); box.textContent = "";
  const items = [["all", "Toutes", "#8a8f86"]].concat(SP_KEYS.map((k) => [k, SP_META[k].short, SP_META[k].col]));
  for (const [k, nm, col] of items) {
    const b = document.createElement("button");
    b.className = "sp"; b.style.setProperty("--c", col); b.setAttribute("aria-pressed", st.sp === k);
    let best = 0;
    for (const sp of k === "all" ? SP_KEYS : [k]) for (let bd = 1; bd < 14; bd++) best = Math.max(best, F(sp, bd, st.day));
    b.innerHTML = "<b></b><span></span>"; b.firstChild.textContent = nm;
    b.lastChild.textContent = k === "all" ? "la meilleure par endroit" : `${level(best)} · max ${fr(best * 100)}`;
    b.title = k === "all" ? "Couleur de l'espèce la plus favorable à chaque endroit" : `${SP_META[k].name} (${SP_META[k].latin})`;
    b.onclick = () => { st.sp = k; saveUi(); refresh(); };
    box.appendChild(b);
  }
}
function confOf(d) {
  if (d < TODAY) return ["observé", ""];
  if (!TBL) return ["calendrier", "t"];
  if (d - TODAY <= 7) return ["prévision fiable", "f"];
  if (d < NDET) return ["tendance", "t"];
  return ["saisonnier", ""];
}
function renderDate() {
  $("day").value = st.day; $("dateLbl").textContent = fmtDate(DAYS[st.day]);
  const k = st.day - TODAY;
  $("relLbl").textContent = k === 0 ? "Aujourd'hui" : k > 0 ? `Dans ${k} jour${k > 1 ? "s" : ""}` : `Il y a ${-k} jour${k < -1 ? "s" : ""}`;
  const [txt, cls] = confOf(st.day); const c = $("conf"); c.textContent = txt; c.className = "conf " + cls;
}
const chart = $("chart"), cctx = chart.getContext("2d");
const CH = { top: 26, z0: 350, z1: 1750, left: 34 };
function drawChart() {
  const dpr = Math.min(2, devicePixelRatio || 1), w = chart.clientWidth, h = chart.clientHeight;
  if (!w) return;
  if (chart.width !== Math.round(w * dpr)) { chart.width = Math.round(w * dpr); chart.height = Math.round(h * dpr); }
  cctx.setTransform(dpr, 0, 0, dpr, 0, 0); cctx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement), v = (n) => css.getPropertyValue(n).trim();
  const ink = v("--ink"), muted = v("--muted"), line = v("--line");
  const d0 = +$("day").min, d1 = DAYS.length - 1, nd = d1 - d0 + 1;
  const L = CH.left, R = w - 4, T = CH.top, B = h - 16, cw = (R - L) / nd;
  cctx.fillStyle = v("--panel-2"); cctx.fillRect(L, T, R - L, B - T);
  const bands = []; for (let z = CH.z0; z < CH.z1; z += 50) bands.push(z);
  const ch = (B - T) / bands.length;
  for (let d = d0; d <= d1; d++) for (let j = 0; j < bands.length; j++) {
    let val = 0, col = "#888";
    for (const sp of spList()) { const f = Fz(sp, bands[j] + 25, d); if (f > val) { val = f; col = SP_META[sp].col; } }
    if (val < 0.03) continue;
    cctx.globalAlpha = Math.min(1, 0.12 + val * 0.95); cctx.fillStyle = col;
    cctx.fillRect(L + (d - d0) * cw, B - (j + 1) * ch, Math.ceil(cw), Math.ceil(ch));
  }
  cctx.globalAlpha = 1;
  if (TBL) {
    const xT = L + (Math.min(NDET, TODAY + 8) - d0) * cw, xS = L + (NDET - d0) * cw;
    cctx.fillStyle = "rgba(127,127,127,.10)"; cctx.fillRect(xT, T, R - xT, B - T);
    if (xS < R) { cctx.fillStyle = "rgba(127,127,127,.12)"; cctx.fillRect(xS, T, R - xS, B - T); }
    const pr = TBL.S.pts[0].prec; cctx.fillStyle = "#4f8fd6";
    for (let d = d0; d <= d1; d++) { const bh = Math.min(1, (pr[d] || 0) / 30) * (T - 6); cctx.fillRect(L + (d - d0) * cw, T - 2 - bh, Math.max(1, cw - 0.5), bh); }
  }
  cctx.fillStyle = muted; cctx.font = "10px 'IBM Plex Mono', monospace"; cctx.textAlign = "right"; cctx.textBaseline = "middle";
  for (const z of [400, 800, 1200, 1600]) {
    const y = B - (z - CH.z0) / (CH.z1 - CH.z0) * (B - T); cctx.fillText(z, L - 4, y);
    cctx.strokeStyle = line; cctx.globalAlpha = .6; cctx.beginPath(); cctx.moveTo(L, y); cctx.lineTo(R, y); cctx.stroke(); cctx.globalAlpha = 1;
  }
  cctx.textAlign = "center"; cctx.textBaseline = "top";
  for (let d = d0; d <= d1; d++) {
    const dt = new Date(DAYS[d] + "T12:00:00Z");
    if (dt.getUTCDate() === 1 || dt.getUTCDate() === 15) cctx.fillText(dt.getUTCDate() === 1 ? MONTHS[dt.getUTCMonth()] : "15", L + (d - d0 + 0.5) * cw, B + 3);
  }
  const xt = L + (TODAY - d0 + 0.5) * cw;
  cctx.strokeStyle = muted; cctx.setLineDash([3, 3]); cctx.beginPath(); cctx.moveTo(xt, T - 4); cctx.lineTo(xt, B); cctx.stroke(); cctx.setLineDash([]);
  const xs = L + (st.day - d0 + 0.5) * cw;
  cctx.strokeStyle = ink; cctx.lineWidth = 2; cctx.beginPath(); cctx.moveTo(xs, T - 6); cctx.lineTo(xs, B + 1); cctx.stroke(); cctx.lineWidth = 1;
  cctx.fillStyle = ink; cctx.beginPath(); cctx.moveTo(xs - 5, T - 10); cctx.lineTo(xs + 5, T - 10); cctx.lineTo(xs, T - 4); cctx.fill();
  $("chartR").textContent = TBL ? "barres bleues : pluie en plaine" : "sans météo : saison seule";
}
function chartPick(ev) {
  const r = chart.getBoundingClientRect(), d0 = +$("day").min, d1 = DAYS.length - 1;
  const cw = (r.width - CH.left - 4) / (d1 - d0 + 1);
  const d = Math.max(d0, Math.min(d1, d0 + Math.floor((ev.clientX - r.left - CH.left) / cw)));
  if (d !== st.day) { st.day = d; st.dayChosen = true; refresh(); }
}
chart.addEventListener("pointerdown", (e) => { chart.setPointerCapture(e.pointerId); chartPick(e); });
chart.addEventListener("pointermove", (e) => { if (e.buttons) chartPick(e); });

function renderVerdict() {
  const v = $("verdict"), strong = v.querySelector("strong"), p = v.querySelector("p");
  let best = null, bestV = 0, bestZ = [0, 0];
  for (const sp of spList()) {
    const vals = BANDS.map((_, b) => F(sp, b, st.day)), mx = Math.max(...vals.slice(0, 15));
    if (mx > bestV) {
      bestV = mx; best = sp;
      const ok = vals.map((x, b) => (x >= mx * 0.6 && b < 15 ? b : -1)).filter((b) => b >= 0);
      bestZ = [BANDS[ok[0]] - 50, BANDS[ok[ok.length - 1]] + 50];
    }
  }
  if (!best || bestV < 0.05) {
    strong.textContent = st.sp === "all" ? "Pas de poussée attendue" : `${SP_META[st.sp].name} : hors saison ou trop sec`;
    p.textContent = TBL ? "Aucune espèce ne trouve à la fois la bonne saison, la bonne température et assez de pluie ce jour-là." : "Sans météo, la prévision ne tient compte que de la saison.";
    return;
  }
  strong.textContent = `${SP_META[best].name} : ${level(bestV)} entre ${Math.max(350, bestZ[0])} et ${bestZ[1]} m`;
  if (TBL) {
    const det = fruit(TBL.S, best, (bestZ[0] + bestZ[1]) / 2, st.day, true);
    p.textContent = det.season ? `Température moyenne ${fr(det.tmean, 1)} °C, ${fr(det.trig)} mm de pluie dans la fenêtre de déclenchement.` : "";
  } else p.textContent = "D'après la saison seule (météo indisponible).";
}
function renderRank() {
  const ol = $("rank"); ol.textContent = "";
  const rows = sectors.map((s) => ({ s, sc: sectorScore(s, st.day) })).sort((a, b) => b.sc.v - a.sc.v);
  const mx = Math.max(0.0001, ...rows.map((r) => r.sc.v));
  rows.slice(0, 7).forEach(({ s, sc }) => {
    const li = document.createElement("li"), b = document.createElement("button");
    b.style.setProperty("--c", SP_META[sc.best].col);
    const forbid = s.rule3 > 0.05, check = /APPB|arrêté/.test(s.terr);
    b.innerHTML = '<span class="nm"></span><span class="bar"><i></i></span><span class="sb"></span>';
    b.querySelector(".nm").textContent = s.name;
    b.querySelector(".bar i").style.width = `${Math.round(sc.v / mx * 100)}%`;
    b.querySelector(".sb").textContent = (sc.v < 0.002 ? "calme" : `${SP_META[sc.best].short} · ${level(sc.rel)}`) + ` · ${s.zmin}–${s.zmax} m` + (forbid ? " · réserves interdites" : check ? " · règles à vérifier" : "");
    b.onclick = () => showSector(s, true);
    li.appendChild(b); ol.appendChild(li);
  });
}
function renderLegend() {
  const r = $("ramp");
  r.style.background = st.sp === "all" ? `linear-gradient(90deg, ${SP_KEYS.map((k, i) => `${SP_META[k].col} ${i * 20}% ${(i + 1) * 20}%`).join(",")})`
    : `linear-gradient(90deg, color-mix(in srgb, ${SP_META[st.sp].col} 12%, transparent), ${SP_META[st.sp].col} 70%, #fff6e6)`;
}
function renderCalendar() {
  const box = $("cal"); box.textContent = ""; box.appendChild(document.createElement("span"));
  MONTHS.forEach((m) => { const s = document.createElement("span"); s.className = "m"; s.textContent = m[0].toUpperCase(); box.appendChild(s); });
  for (const sp of SP_KEYS) {
    const n = document.createElement("span"); n.className = "sn"; n.textContent = SP_META[sp].short; box.appendChild(n);
    for (let m = 0; m < 12; m++) {
      const cell = document.createElement("span"); cell.className = "cell";
      for (const z of [1300, 900, 450]) {
        let val = 0; for (let d = 1; d <= 28; d += 3) val = Math.max(val, seasonOnly(sp, z, `2027-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`));
        const i = document.createElement("i"); i.style.background = SP_META[sp].col; i.style.opacity = (0.08 + val * 0.92).toFixed(2); cell.appendChild(i);
      }
      box.appendChild(cell);
    }
  }
}
function renderStatus() {
  const s = $("status");
  if (wx) {
    const d = new Date(wx.updated); s.className = "status ok";
    s.lastChild.textContent = `Météo du ${d.getDate()} ${MONTHS[d.getMonth()]} à ${String(d.getHours()).padStart(2, "0")} h ${String(d.getMinutes()).padStart(2, "0")} · Open-Meteo`;
  } else { s.className = "status"; s.lastChild.textContent = wxState === "loading" ? "Chargement de la météo…" : "Météo indisponible : prévision d'après la saison seule"; }
}
function refresh() {
  if (!DAYS.length) return;
  renderSpecies(); renderDate(); drawChart(); renderVerdict(); renderRank(); renderLegend(); renderStatus();
  scheduleOverlay(); updateSectorMarkers();
  if (userPos) { LUTS = null; requestAnimationFrame(renderNear); }
  if (cardState) cardState.kind === "pt" ? showPoint(cardState.lon, cardState.lat) : showSector(cardState.s, false);
}

// ---------------------------------------------------------------------------------------------- info cards
let cardState = null;
const card = $("card");
function closeCard() { card.hidden = true; cardState = null; if (clickMarker) { clickMarker.remove(); clickMarker = null; } }
function cardLinks(lon, lat) {
  const ll = `${lat.toFixed(5)},${lon.toFixed(5)}`;
  return `<div class="links">
    <a href="https://map.geo.admin.ch/#/map?lang=fr&center=${lon},${lat}&z=10&crosshair=marker,${lon},${lat}&bgLayer=ch.swisstopo.pixelkarte-farbe" target="_blank" rel="noopener">swisstopo</a>
    <a href="https://www.geoportail.gouv.fr/carte?c=${lon},${lat}&z=16&l0=ORTHOIMAGERY.ORTHOPHOTOS::GEOPORTAIL:OGC:WMTS(1)&permalink=yes" target="_blank" rel="noopener">Géoportail</a>
    <a href="https://www.google.com/maps/dir/?api=1&destination=${ll}" target="_blank" rel="noopener">Itinéraire</a></div>`;
}
function nearestPlace(lon, lat) {
  let best = null, bd = 1e9;
  for (const p of places) if (p.t === "v") { const d = distKm([lon, lat], [p.lon, p.lat]); if (d < bd) { bd = d; best = p; } }
  return best ? { n: best.n, d: bd } : null;
}
let clickMarker = null;
function showPoint(lon, lat) {
  if (!HAB || !inBox(lon, lat)) return;
  const [gx, gy] = gridXY(lon, lat), i = gy * G + gx;
  LUTS = LUTS || SP_KEYS.map((sp) => lutFor(sp, st.day));
  const z = Math.round(elevAt(lon, lat)), zEff = 300 + HAB.z[i] / 12 * 100, off = zEff - z;
  const hab = HAB.h.map((a) => a[i] / 252), cls = HAB.cls[i], reg = Math.floor(HAB.rg[i] / 64) + 1, geo = Math.round((HAB.rg[i] % 64) / 10);
  const resv = reserves.features.filter((f) => f.geometry.coordinates.some((pl) => inRing(lon, lat, pl[0]))).map((f) => f.properties).sort((a, b) => b.rule - a.rule);
  const fp = reg >= 3 ? forpub.find((f) => f.polys.some((pl) => inRing(lon, lat, pl))) : null;
  const np = nearestPlace(lon, lat);
  const expo = off < -40 ? "versant sud (chaud)" : off > 40 ? "versant nord (frais)" : "plat ou peu marqué";
  const rows = SP_KEYS.map((sp, k) => {
    const v = hab[k] * (st.mode === "f" ? Fz(sp, zEff, st.day) : 1);
    return `<tr><td><span class="dot" style="background:${SP_META[sp].col}"></span>${SP_META[sp].short}</td>
      <td><span class="mini" style="--c:${SP_META[sp].col}"><i style="width:${Math.round(hab[k] * 100)}%"></i></span></td>
      <td><span class="lvl" style="--c:${SP_META[sp].col}">${level(v)}</span></td></tr>`;
  }).join("");
  let ruleHtml = "";
  if (resv[0]) { const t = resv[0]; ruleHtml += `<div class="rule r${t.rule}"><b>${esc(RULE_TXT[t.rule])}</b>${esc(t.kind)} « ${esc(t.name)} »${resv.length > 1 ? ` · aussi : ${resv.slice(1, 3).map((r) => esc(r.name)).join(", ")}` : ""}</div>`; }
  let land = REGION_RULE[reg] || "";
  if (fp) land = `${fp.name} (${fp.kind.toLowerCase()}) : cueillette familiale présumée tolérée, env. 5 L, sauf règle locale.`;
  else if (reg >= 3) land = "Terrain probablement privé : les champignons appartiennent au propriétaire, demandez son accord.";
  ruleHtml += `<div class="rule"><b>${REGIONS[reg]}</b>${esc(land)}</div>`;
  const dist = userPos ? ` · à ${fr(distKm(userPos, [lon, lat]), 1)} km de vous` : "";
  card.innerHTML = `<header><div><h3>${np && np.d < 2.5 ? (np.d < 0.4 ? esc(np.n) : "Près de " + esc(np.n)) : "Point choisi"}</h3>
      <div class="coords">${lat.toFixed(5)} N, ${lon.toFixed(5)} E · ${z} m${dist}</div></div>
      <button class="btn icon" id="cardClose" aria-label="Fermer">×</button></header>
    <dl class="facts"><dt>Peuplement</dt><dd>${cls === 0 && Math.max(...hab) > 0 ? "Lisière, bord de forêt" : CLASSES[cls] || "—"}</dd><dt>Sol</dt><dd>${GEOL[geo] || "—"}</dd><dt>Exposition</dt><dd>${expo}</dd></dl>
    ${ruleHtml}
    <table class="sptab"><thead><tr><th>Espèce</th><th>Habitat</th><th>${fmtDate(DAYS[st.day])}</th></tr></thead><tbody>${rows}</tbody></table>
    ${cardLinks(lon, lat)}`;
  card.hidden = false; cardState = { kind: "pt", lon, lat };
  $("cardClose").onclick = closeCard;
  if (!clickMarker) clickMarker = new maplibregl.Marker({ color: "#1b251e", scale: 0.8 });
  clickMarker.setLngLat([lon, lat]).addTo(map);
}
function showSector(s, fly) {
  if (fly) flyTo(s.lon, s.lat, Math.max(11.8, 14.2 - s.r * 0.6));
  if (clickMarker) { clickMarker.remove(); clickMarker = null; }
  const rows = SP_KEYS.map((sp, k) => {
    const stt = s.stats[k]; let hab = 0, v = 0;
    for (let b = 0; b < 20; b++) { hab += stt[b]; v += stt[b] * F(sp, b, st.day); }
    return `<tr><td><span class="dot" style="background:${SP_META[sp].col}"></span>${SP_META[sp].short}</td>
      <td><span class="mini" style="--c:${SP_META[sp].col}"><i style="width:${Math.min(100, Math.round(hab / 0.6 * 100))}%"></i></span></td>
      <td><span class="lvl" style="--c:${SP_META[sp].col}">${st.mode === "f" ? level(hab > 0 ? v / hab : 0) : "—"}</span></td></tr>`;
  }).join("");
  card.innerHTML = `<header><div><h3>${esc(s.name)}</h3><div class="coords">${esc(s.sub)} · ${s.zmin}–${s.zmax} m</div></div>
      <button class="btn icon" id="cardClose" aria-label="Fermer">×</button></header>
    <p style="margin:0;font-size:14px">${esc(s.desc)}</p>
    <div class="rule ${s.rule3 > 0.05 ? "r3" : /APPB|arrêté|Réserve naturelle nationale/.test(s.terr) ? "r2" : ""}"><b>Statut</b>${esc(s.terr)}</div>
    <table class="sptab"><thead><tr><th>Espèce</th><th>Habitat du secteur</th><th>${fmtDate(DAYS[st.day])}</th></tr></thead><tbody>${rows}</tbody></table>
    ${cardLinks(s.lon, s.lat)}`;
  card.hidden = false; cardState = { kind: "sec", s };
  $("cardClose").onclick = closeCard;
}
map.on("click", (e) => showPoint(e.lngLat.lng, e.lngLat.lat));

// ---------------------------------------------------------------------------------------------- controls wiring
$("day").addEventListener("input", (e) => { st.day = +e.target.value; st.dayChosen = true; refresh(); });
$("prevDay").onclick = () => { st.day = Math.max(+$("day").min, st.day - 1); st.dayChosen = true; refresh(); };
$("nextDay").onclick = () => { st.day = Math.min(DAYS.length - 1, st.day + 1); st.dayChosen = true; refresh(); };
$("todayBtn").onclick = () => { st.day = TODAY; refresh(); };
$("modeF").onclick = () => { st.mode = "f"; syncToggles(); saveUi(); refresh(); };
$("modeH").onclick = () => { st.mode = "h"; syncToggles(); saveUi(); refresh(); };
$("baseSat").onclick = () => { st.base = "sat"; syncToggles(); saveUi(); applyLayerState(); };
$("basePlan").onclick = () => { st.base = "plan"; syncToggles(); saveUi(); applyLayerState(); };
for (const [id, key] of [["tRules", "rules"], ["tSec", "sectors"]]) $(id).addEventListener("change", (e) => { st[key] = e.target.checked; saveUi(); applyLayerState(); });
$("heat").addEventListener("input", (e) => { st.heat = +e.target.value; $("heatOut").textContent = `${Math.round(st.heat * 100)} %`; saveUi(); scheduleOverlay(); });
$("exag").addEventListener("input", (e) => { st.exag = +e.target.value; $("exagOut").textContent = `×${fr(st.exag, 1)}`; saveUi(); applyLayerState(); });
$("sheetToggle").onclick = () => {
  const c = $("panel").classList.toggle("collapsed");
  $("sheetToggle").textContent = c ? "Détails" : "Réduire"; $("sheetToggle").setAttribute("aria-expanded", String(!c));
  setPadding(); drawChart();
};
document.addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, button, select, textarea, .maplibregl-canvas")) return;
  if (e.key === "ArrowRight") $("nextDay").click(); else if (e.key === "ArrowLeft") $("prevDay").click(); else if (e.key === "Escape") closeCard();
});
function syncToggles() {
  const pr = (id, on) => $(id).setAttribute("aria-pressed", on);
  pr("modeF", st.mode === "f"); pr("modeH", st.mode === "h"); pr("baseSat", st.base === "sat"); pr("basePlan", st.base === "plan");
  $("tRules").checked = st.rules; $("tSec").checked = st.sectors;
  $("heat").value = st.heat; $("heatOut").textContent = `${Math.round(st.heat * 100)} %`;
  $("exag").value = st.exag; $("exagOut").textContent = `×${fr(st.exag, 1)}`;
}
addEventListener("resize", () => { setPadding(); drawChart(); });

// ---------------------------------------------------------------------------------------------- boot
(async function boot() {
  syncToggles(); renderCalendar(); buildDays(); refresh(); setPadding();
  const wxP = fetchWeather().then((d) => { wx = d; wxState = "ok"; }).catch((e) => { console.warn("météo", e); wxState = "error"; });
  const styleP = new Promise((res) => map.once("load", res));
  try { await loadData(); }
  catch (e) { $("err").textContent = "Impossible de charger les données de la carte (" + e.message + "). Rechargez la page."; console.error(e); return; }
  await styleP;
  setupLayers(); buildSectorMarkers(); applyLayerState();
  $("loader").hidden = true;
  document.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
  drawOverlay(); updateSectorMarkers(); renderRank();
  await wxP;
  buildDays(); refresh();
})();
