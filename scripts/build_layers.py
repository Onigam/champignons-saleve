"""Build every data file of the web map from raw/ (run fetch_raw.py first).

Grid: NX x NY cells over W..E, S..N (config.py), plate carrée while computing; exported with rows
linear in Web Mercator y because MapLibre stretches the canvas source between its corners in Mercator.
Outputs in data/:
  hab_a.png  R cèpe de Bordeaux, G cèpes d'été, B girolle         (0..252, step 4)
  hab_b.png  R trompette, G morilles, B altitude code              (code = (z_eff - 300) / 100 * 12)
  mask.png   R rule*80 (0 none, 1 info, 2 to check, 3 forbidden), G forest class*16, B (region-1)*64 + geology*10
  dem.png    DW x DH plate carrée, decimetres in R (high byte) / G (low byte)
  reserves.geojson, forets_publiques.json, places.json, sectors.json, ch_border.json, meta.json
Usage: python3 scripts/build_layers.py
"""
import glob, json, math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from config import W, E, S, N, NX, NY, DW, DH, MIDLAT, RAW, BUILD, DATA

Image.MAX_IMAGE_PIXELS = None
BUILD.mkdir(exist_ok=True); DATA.mkdir(exist_ok=True)

def px(lon, lat, nx=NX, ny=NY):
    return ((lon - W) / (E - W) * nx, (N - lat) / (N - S) * ny)

def rings(geom):
    t, c = geom["type"], geom["coordinates"]
    for p in (c if t == "MultiPolygon" else [c] if t == "Polygon" else []):
        yield p[0], p[1:]

def raster_polys(features, value_of, out=None):
    """Rasterize polygons (with holes) onto the grid; later features overwrite earlier ones."""
    out = np.zeros((NY, NX), np.uint8) if out is None else out
    for f in features:
        v = value_of(f)
        if v is None or not f.get("geometry"): continue
        for outer, holes in rings(f["geometry"]):
            pts = [px(x, y) for x, y, *_ in outer]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0, x1 = max(0, int(min(xs)) - 1), min(NX, int(max(xs)) + 2)
            y0, y1 = max(0, int(min(ys)) - 1), min(NY, int(max(ys)) + 2)
            if x1 <= x0 or y1 <= y0: continue
            m = Image.new("L", (x1 - x0, y1 - y0), 0); d = ImageDraw.Draw(m)
            d.polygon([(x - x0, y - y0) for x, y in pts], fill=1)
            for h in holes:
                d.polygon([(px(x, y)[0] - x0, px(x, y)[1] - y0) for x, y, *_ in h], fill=0)
            out[y0:y1, x0:x1][np.asarray(m, bool)] = v
    return out

def poly(pts):
    return {"geometry": {"type": "Polygon", "coordinates": [pts + [pts[0]]]}}

def features(name):
    fs = []
    for f in sorted(glob.glob(str(RAW / "wfs" / f"{name}_*.json"))):
        fs += json.load(open(f))["features"]
    return fs

def wms_grid(tag):
    """swisstopo WMS mosaic resampled to 2x the grid (RGBA uint8)."""
    meta = json.load(open(RAW / "wms" / f"{tag}.json"))
    cols, rows = meta["cols"], meta["rows"]
    m = Image.new("RGBA", (cols * 1024, rows * 1024))
    for j in range(rows):
        for i in range(cols):
            m.paste(Image.open(RAW / "wms" / f"{tag}_{j}_{i}.png").convert("RGBA"), (i * 1024, j * 1024))
    return np.asarray(m.resize((2 * NX, 2 * NY), Image.NEAREST))

def down2(a):
    return a.reshape(NY, 2, NX, 2).mean(axis=(1, 3))

def simplify(pts, tol):
    """Douglas-Peucker on lon/lat (tol in degrees) for an open polyline."""
    if len(pts) < 5: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True; st = [(0, len(pts) - 1)]
    while st:
        a, b = st.pop(); (x0, y0), (x1, y1) = pts[a][:2], pts[b][:2]
        dx, dy = x1 - x0, y1 - y0; den = math.hypot(dx, dy) or 1e-12; best, bi = 0, None
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x0) - dx * (pts[i][1] - y0)) / den
            if d > best: best, bi = d, i
        if bi is not None and best > tol: keep[bi] = True; st += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]

def simplify_ring(ring, tol):
    """Closed ring: split at the vertex farthest from the start so both halves are open polylines."""
    if len(ring) < 5: return ring
    x0, y0 = ring[0][:2]
    k = max(range(len(ring)), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
    return simplify(ring[:k + 1], tol) + simplify(ring[k:], tol)[1:]

def in_bbox(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return max(xs) > W and min(xs) < E and max(ys) > S and min(ys) < N

jj, ii = np.mgrid[0:NY, 0:NX]
LON = W + (ii + 0.5) / NX * (E - W)
LAT = N - (jj + 0.5) / NY * (N - S)

# ------------------------------------------------------------------ elevation (Terrain Tiles z12, terrarium)
Z = 12
tiles = {tuple(map(int, os.path.basename(f)[:-4].split("_")[1:])): f for f in glob.glob(str(RAW / "dem" / "12_*.png"))}
X0, Y0 = min(t[0] for t in tiles), min(t[1] for t in tiles)
mos = np.zeros(((max(t[1] for t in tiles) - Y0 + 1) * 256, (max(t[0] for t in tiles) - X0 + 1) * 256), np.float32)
for (x, y), f in tiles.items():
    a = np.asarray(Image.open(f).convert("RGB"), np.float32)
    mos[(y - Y0) * 256:(y - Y0 + 1) * 256, (x - X0) * 256:(x - X0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

def dem_sample(lon, lat):
    X = (lon + 180) / 360 * 2 ** Z * 256 - X0 * 256 - 0.5
    r = np.radians(lat)
    Y = (1 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2 * 2 ** Z * 256 - Y0 * 256 - 0.5
    x0 = np.floor(X).astype(int); y0 = np.floor(Y).astype(int); fx = X - x0; fy = Y - y0
    g = lambda yy, xx: mos[np.clip(yy, 0, mos.shape[0] - 1), np.clip(xx, 0, mos.shape[1] - 1)]
    return g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy) + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy

DEM = np.maximum(dem_sample(LON, LAT), 330).astype(np.float32)
j2, i2 = np.mgrid[0:DH, 0:DW]
dm = dem_sample(W + (i2 + 0.5) / DW * (E - W), N - (j2 + 0.5) / DH * (N - S))
dm = np.clip(np.round(np.maximum(dm, 330) * 10), 0, 65535).astype(np.uint16)
Image.fromarray(np.dstack([(dm >> 8).astype(np.uint8), (dm & 255).astype(np.uint8), np.zeros_like(dm, np.uint8)]), "RGB").save(DATA / "dem.png", optimize=True)
cx = (E - W) / NX * 111320 * math.cos(math.radians(MIDLAT)); cy = (N - S) / NY * 111200
gy, gx = np.gradient(DEM.astype(np.float64))
dzdx, dzdy = gx / cx, -gy / cy
SLOPE = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
SOUTH = np.where(SLOPE > 0.5, dzdy / np.maximum(np.hypot(dzdx, dzdy), 1e-9), 0)   # +1 on south-facing slopes
print("DEM", DEM.min(), DEM.max(), "cell m", round(cx, 1), round(cy, 1))

# ------------------------------------------------------------------ regions: 1 Genève, 2 Vaud, 3 Ain, 4 Haute-Savoie
cantons = json.load(open(RAW / "ch" / "cantons.json"))["results"]
REG = raster_polys(cantons, lambda f: {"Genève": 1, "Vaud": 2}.get(f["properties"].get("name")))
fr = REG == 0
rhone = np.interp(LON, [5.86, 5.90, 5.93, 5.96, 5.98, 6.00], [46.115, 46.118, 46.13, 46.145, 46.155, 46.17])
ain = fr & (LON < 6.17) & (((LON < 6.0) & (LAT > rhone)) | ((LON >= 6.0) & (LAT > 46.17)))
REG[ain] = 3; REG[fr & ~ain] = 4

# ------------------------------------------------------------------ water (Swiss water network: lake and Rhône surfaces)
w4 = wms_grid("water")
lake = (w4[..., 3] > 100) & (np.abs(w4[..., 0].astype(int) - 158) < 12) & (np.abs(w4[..., 2].astype(int) - 255) < 4)
WATER = down2(lake.astype(np.float32)) > 0.5

# ------------------------------------------------------------------ forest classes
# 1 feuillus mélangés, 2 chênes, 3 hêtre, 4 châtaignier, 5 mixte feuillus+, 6 mixte conifères+, 7 sapin/épicéa,
# 8 pins, 9 autres conifères, 10 peupleraie, 11 lande/pelouse, 12 feuillus (CH), 13 mixte (CH), 14 conifères (CH)
TFV = {"FF1-00": 1, "FF1-00-00": 1, "FF1-49-49": 1, "FF1-14-14": 1, "FO1": 1, "FF1G01-01": 2, "FF1-09-09": 3, "FF1-10-10": 4,
       "FF31": 5, "FO3": 5, "FF32": 6, "FF2G61-61": 7, "FF2-52-52": 8, "FF2G53-53": 8, "FF2-80-80": 8, "FF2G58-58": 8,
       "FF2-00": 9, "FF2-00-00": 9, "FF2-64-64": 9, "FF2-90-90": 9, "FF2-63-63": 9, "FO2": 9,
       "FP": 10, "LA4": 11, "LA6": 11, "FF0": 11}
bdf = features("bdforet")
unknown = sorted({f["properties"]["code_tfv"] for f in bdf} - set(TFV))
if unknown: print("unmapped BD Forêt codes:", unknown)
OPEN = raster_polys(bdf, lambda f: 1 if f["properties"]["code_tfv"].startswith("FO") else None).astype(bool)
CLS = raster_polys(bdf, lambda f: TFV.get(f["properties"]["code_tfv"]))
CLS[REG <= 2] = 0   # BD Forêt is France only
wald = down2((wms_grid("wald")[..., 3] > 100).astype(np.float32)) > 0.5
mix4 = wms_grid("mix")
mixop = down2((mix4[..., 3] > 100).astype(np.float32))
mixg = down2(np.where(mix4[..., 3] > 100, mix4[..., 1], 0).astype(np.float32)) / np.maximum(mixop, 1e-6)
conif = np.clip((255 - mixg) / (255 - 76), 0, 1)
ch = (REG <= 2) & wald
CLS[ch] = 12
CLS[ch & (mixop > 0.25) & (conif >= 0.3)] = 13
CLS[ch & (mixop > 0.25) & (conif >= 0.7)] = 14
CLS[WATER] = 0
FOREST = (CLS > 0) & (CLS != 11)
print("forest share", round(float(FOREST.mean()), 3))

# ------------------------------------------------------------------ geology
# 1 calcaire, 2 grès/flysch acide, 3 moraine/molasse, 4 alluvions, 5 calcaire à sols décarbonatés (plateau du Salève)
GEO = np.full((NY, NX), 3, np.uint8)
jura_foot = np.interp(LON, [5.86, 5.90, 5.93, 5.955, 5.99, 6.04, 6.10, 6.17], [46.12, 46.13, 46.16, 46.20, 46.26, 46.315, 46.345, 46.38])
GEO[(LAT > jura_foot) & (DEM >= 560)] = 1
def zone(pts):
    return raster_polys([poly(pts)], lambda f: 1).astype(bool)
GEO[zone([(5.86, 46.13), (5.925, 46.13), (5.95, 46.08), (5.94, 46.00), (5.92, 45.96), (5.86, 45.96)]) & (DEM >= 600)] = 1        # Vuache
crest = [(6.240, 46.186), (6.224, 46.169), (6.217, 46.154), (6.180, 46.139), (6.170, 46.118), (6.140, 46.094), (6.126, 46.077), (6.107, 46.065), (6.088, 46.050)]
kse = [0.5, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.5]
saleve = zone([(x - 0.024, y + 0.013) for x, y in crest] + [(x + 0.0256 * k, y - 0.0139 * k) for (x, y), k in zip(crest, kse)][::-1])
GEO[saleve & (DEM >= 650)] = 1
GEO[saleve & (DEM >= 1050) & (SLOPE < 12)] = 5
GEO[zone([(6.29, 46.29), (6.34, 46.30), (6.41, 46.24), (6.41, 46.15), (6.33, 46.15), (6.30, 46.20)]) & (DEM >= 750)] = 2       # Voirons sandstone
GEO[zone([(6.20, 45.85), (6.41, 45.85), (6.41, 46.06), (6.33, 46.045), (6.27, 45.99), (6.21, 45.93)]) & (DEM >= 900)] = 1      # Bornes prealps: Parmelan, Glières, Sous-Dîne
GEO[zone([(5.98, 45.995), (6.10, 45.995), (6.125, 45.955), (6.06, 45.925), (5.98, 45.95)]) & (DEM >= 620)] = 1                # Mandallaz
RIVERS = {"le Rhône", "l'Arve", "l'Allondon", "la Versoix", "la Laire", "l'Aire", "le Foron", "la Menoge", "l'Annaz", "l'Hermance",
          "les Usses", "la Valserine", "le London", "le Sion", "le Fier", "la Fillière", "le Borne"}
riv = Image.new("L", (NX, NY), 0); dr = ImageDraw.Draw(riv)
for f in features("cours"):
    if (f["properties"].get("toponyme") or "") not in RIVERS or not f.get("geometry"): continue
    g = f["geometry"]
    for ln in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
        dr.line([px(x, y) for x, y, *_ in ln], fill=1, width=2)
riv = np.asarray(riv, bool) & ~WATER
relev = np.where(riv, DEM, np.inf).astype(np.float32); known = riv.copy()
for _ in range(8):   # spread the river level ~160 m sideways
    best = relev.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx: best = np.minimum(best, np.roll(np.roll(relev, dy, 0), dx, 1))
    new = ~known & np.isfinite(best); relev[new] = best[new]; known |= new
ufer = down2((wms_grid("ufer")[..., 3] > 100).astype(np.float32)) > 0.3
ALLUV = (known & (DEM - relev < 8) & (SLOPE < 12)) | ufer
GEO[ALLUV & ((GEO != 1) | (DEM < 700))] = 4

# ------------------------------------------------------------------ edges
fimg = Image.fromarray((FOREST * 255).astype(np.uint8))
DIN = np.zeros((NY, NX), np.uint8); cur = fimg
for _ in range(4):
    cur = cur.filter(ImageFilter.MinFilter(3)); DIN += (np.asarray(cur) > 0).astype(np.uint8)
EDGE = FOREST & (DIN <= 1)
NEARF = (np.asarray(fimg.filter(ImageFilter.MaxFilter(3))) > 0) & ~FOREST & ~WATER

# ------------------------------------------------------------------ habitat model
# cepe = cèpe de Bordeaux + cèpe des pins (B. edulis, B. pinophilus); cepe_ete = cèpes d'été (B. reticulatus, B. aereus)
SP = ["cepe", "cepe_ete", "girolle", "trompette", "morille"]
HOST = np.array([  # rows = forest class 0..14
    [0, 0, 0, 0, 0],
    [0.65, 0.80, 0.60, 0.75, 0.35],   # 1 feuillus mélangés
    [0.80, 1.00, 0.75, 0.60, 0.20],   # 2 chênes
    [0.90, 0.75, 0.80, 1.00, 0.25],   # 3 hêtre
    [0.95, 1.00, 0.85, 0.50, 0.10],   # 4 châtaignier
    [0.95, 0.75, 0.85, 0.90, 0.40],   # 5 mixte feuillus+
    [1.00, 0.45, 0.85, 0.70, 0.45],   # 6 mixte conifères+
    [0.95, 0.15, 0.75, 0.35, 0.40],   # 7 sapin / épicéa
    [0.75, 0.15, 0.55, 0.15, 0.15],   # 8 pins
    [0.55, 0.10, 0.45, 0.20, 0.30],   # 9 autres conifères
    [0.05, 0.10, 0.05, 0.10, 0.80],   # 10 peupleraie
    [0.05, 0.10, 0.05, 0.00, 0.10],   # 11 lande / pelouse
    [0.70, 0.95, 0.65, 0.70, 0.35],   # 12 feuillus (CH)
    [0.90, 0.65, 0.80, 0.75, 0.35],   # 13 mixte (CH)
    [0.80, 0.15, 0.65, 0.30, 0.30],   # 14 conifères (CH)
], np.float32)
GEOF = np.array([
    [0, 0, 0, 0, 0],
    [0.75, 0.80, 0.55, 1.00, 0.90],   # 1 calcaire
    [1.00, 0.85, 1.00, 0.70, 0.35],   # 2 grès / flysch acide
    [0.90, 0.90, 0.85, 0.80, 0.60],   # 3 moraine / molasse
    [0.20, 0.40, 0.15, 0.40, 1.00],   # 4 alluvions
    [0.90, 0.80, 0.80, 0.90, 0.70],   # 5 calcaire, sols décarbonatés
], np.float32)
ramp = lambda x, a, b: np.clip((b - x) / (b - a), 0, 1)   # 1 below a, 0 above b
ELEVF = np.stack([ramp(DEM, 1650, 1900), 0.6 + 0.4 * ramp(DEM, 1000, 1500), ramp(DEM, 1550, 1850),
                  ramp(DEM, 1350, 1650), 0.5 + 0.5 * ramp(DEM, 1300, 1700)], -1)
SLOPEF = np.where(SLOPE > 40, 0.2, np.where(SLOPE > 30, 0.7, 1.0))[..., None]
sw = (np.minimum(SLOPE, 20) / 20)[..., None]
ASPF = np.stack([np.ones_like(SOUTH), 1 + 0.10 * SOUTH, 1 - 0.05 * SOUTH, 1 - 0.15 * SOUTH, 1 + 0.05 * SOUTH], -1) * sw + (1 - sw)
EDGEF = np.where(EDGE[..., None], np.array([1.15, 1.15, 1.10, 0.95, 1.10]), 1.0)
OPENF = np.where(OPEN[..., None], np.array([0.8, 0.9, 0.7, 0.6, 0.9]), 1.0)
H = HOST[CLS] * GEOF[GEO] * ELEVF * SLOPEF * ASPF * EDGEF * OPENF
riparian = ALLUV & np.isin(CLS, [1, 2, 5, 10, 12, 13])     # floodplain ash / poplar / alder stands: morels
H[..., 4] = np.where(riparian, np.maximum(H[..., 4], 0.95), H[..., 4])
halo = np.zeros_like(H)
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        halo = np.maximum(halo, np.roll(np.roll(H, dy, 0), dx, 1))
H = np.where(NEARF[..., None], 0.35 * halo, H)   # forest edge just outside the stand
H[WATER] = 0
H = np.clip(H, 0, 1)
print("habitat mean in forest", H[FOREST].mean(0).round(3))
q = lambda a: (np.clip(np.round(a * 63), 0, 63) * 4).astype(np.uint8)   # 64 levels keep the PNGs small
offset = np.clip(np.round(-150 * SOUTH * np.minimum(SLOPE, 20) / 20 / 16), -15, 15) * 16   # south slopes count as lower, north as higher
ZEFF = DEM + offset
zcode = np.clip(np.round((ZEFF - 300) / 100 * 12), 0, 252).astype(np.uint8)

# ------------------------------------------------------------------ protected areas
RES = []
FR_KIND = {"Réserve naturelle": ("Réserve naturelle nationale", 2), "Arrêté de protection": ("Arrêté de protection de biotope", 2),
           "Site Natura 2000": ("Site Natura 2000", 1), "Site acquis ou assimilé des conservatoires d'espaces naturels": ("Site du Conservatoire d'espaces naturels", 2),
           "Terrain du Conservatoire du Littoral": ("Terrain du Conservatoire du littoral", 2)}
for f in features("reserve"):
    p = f["properties"]
    if p["nature"] not in FR_KIND or not f.get("geometry"): continue
    if p["nature"] == "Site Natura 2000" and "Oiseaux" in (p.get("nature_detaillee") or ""): continue   # same perimeter twice
    kind, rule = FR_KIND[p["nature"]]
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(o, 0.0002)] for o, _ in rings(f["geometry"]) if in_bbox(o)]
    if out: RES.append({"name": p["toponyme"], "kind": kind, "rule": rule, "polys": out})
SITG_KIND = {"Réserves naturelles (GE)": ("Réserve naturelle genevoise", 3), "Réserves naturelles de statut public (RNPU) (VD)": ("Réserve naturelle vaudoise", 3),
             "Réserves forestières (VD)": ("Réserve forestière vaudoise", 1)}
for f in json.load(open(RAW / "ch" / "sitg_reserves.json"))["features"]:
    p = f["properties"]
    if p["type"] not in SITG_KIND or not f.get("geometry"): continue
    kind, rule = SITG_KIND[p["type"]]
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(o, 0.00005)] for o, _ in rings(f["geometry"]) if in_bbox(o)]
    if out: RES.append({"name": p["nom"].strip(), "kind": kind, "rule": rule, "polys": out})
CH_KIND = {"pronatura": ("Réserve Pro Natura", 3), "auen": ("Zone alluviale d'importance nationale", 2),
           "flachmoore": ("Bas-marais d'importance nationale", 2), "waldreservate": ("Réserve forestière genevoise", 1)}
seen = {}
for name, (kind, rule) in CH_KIND.items():
    for f in json.load(open(RAW / "ch" / f"{name}.json"))["results"]:
        label = (f["properties"].get("name") or f["properties"].get("label") or "").split(" (")[0]
        out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(o, 0.00005)] for o, _ in rings(f["geometry"]) if in_bbox(o)]
        if not out: continue
        if (name, label) in seen: seen[(name, label)]["polys"] += out
        else: seen[(name, label)] = {"name": label, "kind": kind, "rule": rule, "polys": out}; RES.append(seen[(name, label)])
RULE = np.zeros((NY, NX), np.uint8)
for level in (1, 2, 3):   # stricter rules drawn last
    m = raster_polys([poly([tuple(p) for p in pl[:-1]]) for r in RES if r["rule"] == level for pl in r["polys"] if len(pl) >= 4], lambda f: 1).astype(bool)
    RULE[m] = level
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": r["name"], "kind": r["kind"], "rule": r["rule"]},
           "geometry": {"type": "MultiPolygon", "coordinates": [[pl] for pl in r["polys"]]}} for r in RES]},
          open(DATA / "reserves.geojson", "w"), ensure_ascii=False, separators=(",", ":"))
FP = []
for f in features("forpub"):
    if not f.get("geometry"): continue
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(o, 0.0002)] for o, _ in rings(f["geometry"]) if in_bbox(o)]
    if out: FP.append({"name": f["properties"]["toponyme"], "kind": f["properties"]["nature"], "polys": out})
json.dump(FP, open(DATA / "forets_publiques.json", "w"), ensure_ascii=False, separators=(",", ":"))
border = []
for f in cantons:
    for o, _ in rings(f["geometry"]):
        xs = [p[0] for p in o]; ys = [p[1] for p in o]
        if max(xs) < W - 0.2 or min(xs) > E + 0.2 or max(ys) < S - 0.1 or min(ys) > N + 0.15: continue
        border.append([[round(x, 6), round(y, 6)] for x, y, *_ in simplify_ring(o, 0.00002)])
json.dump(border, open(DATA / "ch_border.json", "w"), separators=(",", ":"))
print("reserves", len(RES), "public forests", len(FP), "rule cells", {k: int((RULE == k).sum()) for k in range(4)})

# ------------------------------------------------------------------ place names (nearest village in the info card)
def centroid(ring):
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
places = []
for f in features("habit"):
    p = f["properties"]
    if p["nature"] != "Lieu-dit habité" or str(p.get("importance")) not in ("1", "2", "3") or not p.get("toponyme") or not f.get("geometry"): continue
    g = f["geometry"]; c = g["coordinates"]
    lon, lat = c[:2] if g["type"] == "Point" else centroid(c[0][0] if g["type"] == "MultiPolygon" else c[0])
    if W < lon < E and S < lat < N:
        places.append({"n": p["toponyme"], "t": "v", "r": int(p["importance"]), "lon": round(lon, 5), "lat": round(lat, 5)})
seenc = set()
for f in json.load(open(RAW / "ch" / "communes.json"))["results"]:
    p = f["properties"]; nm = p.get("gemname", "")
    if not p.get("is_current_jahr") or nm.startswith("Lac ") or nm in seenc: continue
    seenc.add(nm)
    lon, lat = centroid(max((o for o, _ in rings(f["geometry"])), key=len))
    if W < lon < E and S < lat < N:
        places.append({"n": nm.replace(" (GE)", ""), "t": "v", "r": 1 if nm == "Genève" else 3, "lon": round(lon, 5), "lat": round(lat, 5)})
json.dump(places, open(DATA / "places.json", "w"), ensure_ascii=False, separators=(",", ":"))

# ------------------------------------------------------------------ sectors: habitat summed per species and 100 m band
band = np.clip(np.round((ZEFF - 300) / 100), 0, 19).astype(int)
secs = json.load(open(os.path.join(os.path.dirname(__file__), "sectors_src.json")))
for sc in secs:
    m = np.hypot((LON - sc["lon"]) * 111.32 * math.cos(math.radians(MIDLAT)), (LAT - sc["lat"]) * 111.2) <= sc["r"]
    n = m.sum()
    sc["stats"] = [[round(float(H[..., k][m & (band == b)].sum() / n), 4) for b in range(20)] for k in range(5)]
    sc["zmin"], sc["zmax"] = int(np.percentile(DEM[m], 5)), int(np.percentile(DEM[m], 95))
    sc["forest"] = round(float(FOREST[m].mean()), 2)
    sc["rule3"] = round(float((RULE[m] == 3).mean()), 2)
    cl = np.bincount(CLS[m & FOREST], minlength=15) / max(1, (m & FOREST).sum())
    sc["mix"] = {int(k): round(float(v), 2) for k, v in enumerate(cl) if v >= 0.08}
json.dump(secs, open(DATA / "sectors.json", "w"), ensure_ascii=False, separators=(",", ":"))
for sc in secs: print(f"  {sc['id']:16s} {sc['zmin']}-{sc['zmax']} m forest {sc['forest']} mix {sc['mix']}")

# ------------------------------------------------------------------ export (rows linear in Web Mercator)
merc = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
y0, y1 = merc(N), merc(S)
rows = np.array([min(NY - 1, max(0, int((N - math.degrees(2 * math.atan(math.exp(y0 + (j + 0.5) / NY * (y1 - y0))) - math.pi / 2)) / (N - S) * NY))) for j in range(NY)])
habA = np.dstack([q(H[..., 0]), q(H[..., 1]), q(H[..., 2])])
habB = np.dstack([q(H[..., 3]), q(H[..., 4]), zcode])
mask = np.dstack([RULE * 80, CLS * 16, ((REG.astype(int) - 1) * 64 + GEO.astype(int) * 10).clip(0, 255)]).astype(np.uint8)
for name, arr in (("hab_a", habA), ("hab_b", habB), ("mask", mask)):
    Image.fromarray(np.ascontiguousarray(arr[rows]), "RGB").save(DATA / f"{name}.png", optimize=True)
json.dump({"bbox": [W, S, E, N], "nx": NX, "ny": NY, "dw": DW, "dh": DH}, open(DATA / "meta.json", "w"))
np.savez_compressed(BUILD / "layers.npz", CLS=CLS, GEO=GEO, REG=REG, DEM=DEM, FOREST=FOREST, ALLUV=ALLUV, RULE=RULE)
print("exported", {f: os.path.getsize(DATA / f) // 1024 for f in os.listdir(DATA)})
