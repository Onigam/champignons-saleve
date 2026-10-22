"""Build the static layers for the Salève / bassin genevois mushroom map.

Inputs: scratchpad/dl/* (IGN WFS + WMS, swisstopo WMS, geo.admin identify, terrarium DEM).
Outputs: scratchpad/out/app/{ortho.jpg, lines.png, dem.png, hab_a.png, hab_b.png, mask.png, places.json, reserves.json}
Grid: plate carrée over W,E,S,N; row 0 = north.
"""
import json, math, sys, glob, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = sys.argv[1]
DL = f"{S}/dl"; OUT = f"{S}/out/app"; os.makedirs(OUT, exist_ok=True)
W, E, SO, NO = 5.88, 6.40, 46.00, 46.36
N = 2048      # analysis grid
NI = 4096     # imagery / lines grid
Image.MAX_IMAGE_PIXELS = None

def px(lon, lat, n):
    return ((lon - W) / (E - W) * n, (NO - lat) / (NO - SO) * n)

def rings(geom):
    """Yield polygons as (outer, [holes]) lists of (lon,lat)."""
    t, c = geom["type"], geom["coordinates"]
    polys = c if t == "MultiPolygon" else [c] if t == "Polygon" else []
    for p in polys:
        yield p[0], p[1:]

def raster_polys(features, n, value_of, base=None, dtype=np.uint8):
    """Rasterize polygons with holes; later features overwrite earlier ones."""
    out = np.zeros((n, n), dtype) if base is None else base
    for f in features:
        v = value_of(f)
        if v is None or not f.get("geometry"): continue
        for outer, holes in rings(f["geometry"]):
            pts = [px(x, y, n) for x, y, *_ in outer]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0, x1 = max(0, int(min(xs)) - 1), min(n, int(max(xs)) + 2)
            y0, y1 = max(0, int(min(ys)) - 1), min(n, int(max(ys)) + 2)
            if x1 <= x0 or y1 <= y0: continue
            m = Image.new("L", (x1 - x0, y1 - y0), 0)
            d = ImageDraw.Draw(m)
            d.polygon([(x - x0, y - y0) for x, y in pts], fill=1)
            for h in holes:
                d.polygon([(px(x, y, n)[0] - x0, px(x, y, n)[1] - y0) for x, y, *_ in h], fill=0)
            mk = np.asarray(m, bool)
            out[y0:y1, x0:x1][mk] = v
    return out

def load_mosaic(tag, n=NI):
    m = Image.new("RGBA", (n, n))
    t = n // 4
    for j in range(4):
        for i in range(4):
            im = Image.open(f"{DL}/img/{tag}_{j}_{i}.png").convert("RGBA")
            if im.size != (t, t): im = im.resize((t, t), Image.BILINEAR)
            m.paste(im, (i * t, j * t))
    return m

def down(a, f):  # block mean
    h, w = a.shape[:2]
    return a.reshape(h // f, f, w // f, f, *a.shape[2:]).mean(axis=(1, 3))

# ------------------------------------------------------------------ grid coords
jj, ii = np.mgrid[0:N, 0:N]
LON = W + (ii + 0.5) / N * (E - W)
LAT = NO - (jj + 0.5) / N * (NO - SO)

# ------------------------------------------------------------------ DEM (terrarium z12)
z = 12; X0, Y0 = 2114, 1451
mos = np.zeros((7 * 256, 7 * 256), np.float32)
for f in glob.glob(f"{DL}/dem/12_*.png"):
    _, x, y = os.path.basename(f)[:-4].split("_")
    a = np.asarray(Image.open(f).convert("RGB"), np.float32)
    mos[(int(y) - Y0) * 256:(int(y) - Y0 + 1) * 256, (int(x) - X0) * 256:(int(x) - X0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

def dem_sample(lon, lat):
    X = (lon + 180) / 360 * 2 ** z * 256 - X0 * 256 - 0.5
    r = np.radians(lat)
    Y = (1 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2 * 2 ** z * 256 - Y0 * 256 - 0.5
    x0 = np.floor(X).astype(int); y0 = np.floor(Y).astype(int)
    fx = X - x0; fy = Y - y0
    g = lambda yy, xx: mos[np.clip(yy, 0, mos.shape[0] - 1), np.clip(xx, 0, mos.shape[1] - 1)]
    return (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy) + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy)

DEM = dem_sample(LON, LAT).astype(np.float32)
DEM = np.maximum(DEM, 330)
print("DEM range", DEM.min(), DEM.max())
# heightmap for the 3D mesh: 1024², decimetres in R (high) / G (low)
j2, i2 = np.mgrid[0:1024, 0:1024]
dm = dem_sample(W + (i2 + 0.5) / 1024 * (E - W), NO - (j2 + 0.5) / 1024 * (NO - SO))
dm = np.clip(np.round(np.maximum(dm, 330) * 10), 0, 65535).astype(np.uint16)
Image.fromarray(np.dstack([(dm >> 8).astype(np.uint8), (dm & 255).astype(np.uint8), np.zeros_like(dm, np.uint8)]), "RGB").save(f"{OUT}/dem.png", optimize=True)

# slope / aspect on the analysis grid
cell_x = (E - W) / N * 111320 * math.cos(math.radians(46.18))
cell_y = (NO - SO) / N * 111200
gy, gx = np.gradient(DEM.astype(np.float64))
dzdx = gx / cell_x            # +east
dzdy = -gy / cell_y           # +north (rows go south)
SLOPE = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
# downslope direction: facing = -gradient; southness = component of facing toward south
south = np.where(SLOPE > 0.5, dzdy / np.maximum(np.hypot(dzdx, dzdy), 1e-9), 0)  # +1 if terrain rises northward => faces south
print("cell m", cell_x, cell_y)

# ------------------------------------------------------------------ regions (GE=1 VD=2 Ain=3 HS=4)
cant = json.load(open(f"{DL}/wfs/ch_cantons.json"))["results"]
REG = raster_polys(cant, N, lambda f: {"Genève": 1, "Vaud": 2}.get(f["properties"].get("name")))
fr = REG == 0
rh = np.interp(LON, [5.86, 5.90, 5.93, 5.96, 5.98, 6.00], [46.115, 46.118, 46.13, 46.145, 46.155, 46.17])
ain = fr & (LON < 6.17) & (((LON < 6.0) & (LAT > rh)) | ((LON >= 6.0) & (LAT > 46.17)))
REG[ain] = 3; REG[fr & ~ain] = 4
CH4096 = np.asarray(Image.fromarray(REG).resize((NI, NI), Image.NEAREST)) <= 2

# ------------------------------------------------------------------ water
water4 = np.asarray(load_mosaic("water"))
lake4 = (water4[..., 3] > 100) & (np.abs(water4[..., 0].astype(int) - 158) < 12) & (np.abs(water4[..., 2].astype(int) - 255) < 4)
WATER = down(lake4.astype(np.float32), 2) > 0.5

# ------------------------------------------------------------------ forest classes
# 1 feuillus mélangés, 2 chênes, 3 hêtre, 4 châtaignier, 5 mixte feuillus+, 6 mixte conifères+,
# 7 sapin/épicéa, 8 pins, 9 autres conifères, 10 peupleraie, 11 lande/pelouse,
# 12 feuillus (CH), 13 mixte (CH), 14 conifères (CH)
TFV = {"FF1-00": 1, "FF1-00-00": 1, "FF1-49-49": 1, "FO1": 1, "FF1G01-01": 2, "FF1-09-09": 3, "FF1-10-10": 4,
       "FF31": 5, "FO3": 5, "FF32": 6, "FF2G61-61": 7, "FF2-52-52": 8, "FF2G53-53": 8, "FF2-80-80": 8,
       "FF2-00": 9, "FF2-00-00": 9, "FF2-64-64": 9, "FF2-90-90": 9, "FF2-63-63": 9, "FO2": 9,
       "FP": 10, "LA4": 11, "LA6": 11, "FF0": 11}
bdf = json.load(open(f"{DL}/wfs/bdforet_0.json"))["features"]
OPEN_FOREST = raster_polys(bdf, N, lambda f: 1 if f["properties"]["code_tfv"].startswith("FO") else None)
CLS = raster_polys(bdf, N, lambda f: TFV.get(f["properties"]["code_tfv"]))
CLS[REG <= 2] = 0  # BD Forêt is France only; ignore slivers on the border
wald4 = np.asarray(load_mosaic("wald"))[..., 3] > 100
mix4 = np.asarray(load_mosaic("mix"))
waldN = down(wald4.astype(np.float32), 2) > 0.5
mixop = down((mix4[..., 3] > 100).astype(np.float32), 2)
mixG = down(np.where(mix4[..., 3] > 100, mix4[..., 1], 0).astype(np.float32), 2) / np.maximum(mixop, 1e-6)
conif = np.clip((255 - mixG) / (255 - 76), 0, 1)
chf = (REG <= 2) & waldN
CLS[chf] = 12
CLS[chf & (mixop > 0.25) & (conif >= 0.3)] = 13
CLS[chf & (mixop > 0.25) & (conif >= 0.7)] = 14
CLS[WATER] = 0
FOREST = (CLS > 0) & (CLS != 11)
print("forest frac", FOREST.mean(), {k: int((CLS == k).sum()) for k in range(15)})

# ------------------------------------------------------------------ geology
# 1 calcaire, 2 grès/flysch acide, 3 moraine/molasse, 4 alluvions, 5 calcaire à sols décarbonatés (plateau du Salève)
def poly_feat(pts):
    return {"geometry": {"type": "Polygon", "coordinates": [pts + [pts[0]]]}}

GEO = np.full((N, N), 3, np.uint8)
jura_line_lon = [5.86, 5.90, 5.93, 5.955, 5.99, 6.04, 6.10, 6.17]
jura_line_lat = [46.12, 46.13, 46.16, 46.20, 46.26, 46.315, 46.345, 46.38]
jura_side = LAT > np.interp(LON, jura_line_lon, jura_line_lat) - 0.0
GEO[jura_side & (DEM >= 560)] = 1
vuache = raster_polys([poly_feat([(5.86, 46.13), (5.925, 46.13), (5.95, 46.08), (5.93, 46.02), (5.90, 46.00), (5.86, 46.00)])], N, lambda f: 1).astype(bool)
GEO[vuache & (DEM >= 600)] = 1
# Salève: band around the crest line, ~2 km NW (cliff foot) to ~2.5 km SE (dip slope down to the Bornes molasse)
crest = [(6.240, 46.186), (6.224, 46.169), (6.217, 46.154), (6.180, 46.139), (6.170, 46.118), (6.140, 46.094), (6.126, 46.077), (6.107, 46.065), (6.088, 46.050)]
kse = [0.5, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.5]
se_edge = [(x + 0.0256 * k, y - 0.0139 * k) for (x, y), k in zip(crest, kse)]
nw_edge = [(x - 0.024, y + 0.013) for x, y in crest]
saleve = raster_polys([poly_feat(nw_edge + se_edge[::-1])], N, lambda f: 1).astype(bool)
GEO[saleve & (DEM >= 650)] = 1
GEO[saleve & (DEM >= 1050) & (SLOPE < 12)] = 5
voirons = raster_polys([poly_feat([(6.29, 46.29), (6.34, 46.30), (6.41, 46.24), (6.41, 46.15), (6.33, 46.15), (6.30, 46.20)])], N, lambda f: 1).astype(bool)
GEO[voirons & (DEM >= 750)] = 2
prealps = raster_polys([poly_feat([(6.29, 45.99), (6.41, 45.99), (6.41, 46.06), (6.33, 46.045)])], N, lambda f: 1).astype(bool)
GEO[prealps & (DEM >= 900)] = 1

# alluvial corridors along the main rivers
RIVERS = {"le Rhône", "l'Arve", "l'Allondon", "la Versoix", "la Laire", "l'Aire", "le Foron", "la Menoge", "l'Annaz",
          "l'Hermance", "les Usses", "la Valserine", "le London", "le Sion"}
riv_img = Image.new("L", (N, N), 0); dr = ImageDraw.Draw(riv_img)
for f in json.load(open(f"{DL}/wfs/cours_0.json"))["features"]:
    if (f["properties"].get("toponyme") or "") not in RIVERS: continue
    g = f["geometry"]; lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    for ln in lines:
        dr.line([px(x, y, N) for x, y, *_ in ln], fill=1, width=2)
riv = np.asarray(riv_img, bool) & ~WATER
relev = np.where(riv, DEM, np.inf).astype(np.float32)
known = riv.copy()
for _ in range(8):  # ~160 m
    best = relev.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0: continue
            best = np.minimum(best, np.roll(np.roll(relev, dy, 0), dx, 1))
    newk = ~known & np.isfinite(best)
    relev[newk] = best[newk]; known |= newk
ufer4 = np.asarray(load_mosaic("ufer"))[..., 3] > 100
ufer = down(ufer4.astype(np.float32), 2) > 0.3
ALLUV = (known & (DEM - relev < 8) & (SLOPE < 12)) | ufer
GEO[ALLUV & (GEO != 1)] = 4
GEO[ALLUV & (GEO == 1) & (DEM < 700)] = 4
print("geo counts", {k: int((GEO == k).sum()) for k in range(6)})

# ------------------------------------------------------------------ edges (forest interior distance)
fimg = Image.fromarray((FOREST * 255).astype(np.uint8))
DIN = np.zeros((N, N), np.uint8); cur = fimg
for k in range(1, 5):
    cur = cur.filter(ImageFilter.MinFilter(3))
    DIN += (np.asarray(cur) > 0).astype(np.uint8)
EDGE = FOREST & (DIN <= 1)          # within ~40 m of a forest edge
NEARF = (np.asarray(fimg.filter(ImageFilter.MaxFilter(3))) > 0) & ~FOREST & ~WATER  # 1 cell outside

# ------------------------------------------------------------------ habitat model
SP = ["cepe", "bolet", "girolle", "trompette", "morille"]
HOST = np.array([  # rows = class 0..14 ; cols = species
    [0, 0, 0, 0, 0],
    [0.65, 0.75, 0.60, 0.75, 0.35],   # 1 feuillus mélangés
    [0.80, 0.95, 0.75, 0.60, 0.20],   # 2 chênes
    [0.90, 0.70, 0.80, 1.00, 0.25],   # 3 hêtre
    [0.95, 0.95, 0.85, 0.50, 0.10],   # 4 châtaignier
    [0.95, 0.85, 0.85, 0.90, 0.40],   # 5 mixte feuillus+
    [1.00, 0.80, 0.85, 0.70, 0.45],   # 6 mixte conifères+
    [0.95, 0.70, 0.75, 0.35, 0.40],   # 7 sapin / épicéa
    [0.60, 0.85, 0.55, 0.15, 0.15],   # 8 pins
    [0.55, 0.60, 0.45, 0.20, 0.30],   # 9 autres conifères
    [0.05, 0.35, 0.05, 0.10, 0.80],   # 10 peupleraie
    [0.05, 0.10, 0.05, 0.00, 0.10],   # 11 lande / pelouse
    [0.70, 0.85, 0.65, 0.70, 0.35],   # 12 feuillus (CH)
    [0.90, 0.85, 0.80, 0.75, 0.35],   # 13 mixte (CH)
    [0.80, 0.75, 0.65, 0.30, 0.30],   # 14 conifères (CH)
], np.float32)
GEOF = np.array([
    [0, 0, 0, 0, 0],
    [0.75, 0.80, 0.55, 1.00, 0.90],   # 1 calcaire
    [1.00, 0.85, 1.00, 0.70, 0.35],   # 2 grès / flysch acide
    [0.90, 0.90, 0.85, 0.80, 0.60],   # 3 moraine / molasse
    [0.20, 0.40, 0.15, 0.40, 1.00],   # 4 alluvions
    [0.90, 0.80, 0.80, 0.90, 0.70],   # 5 calcaire, sols décarbonatés
], np.float32)

def ramp(x, a, b):  # 1 below a, 0 above b
    return np.clip((b - x) / (b - a), 0, 1)

ELEVF = np.stack([
    ramp(DEM, 1650, 1900),
    0.6 + 0.4 * ramp(DEM, 1000, 1500),
    ramp(DEM, 1550, 1850),
    ramp(DEM, 1350, 1650),
    0.5 + 0.5 * ramp(DEM, 1300, 1700),
], -1)
SLOPEF = np.where(SLOPE > 40, 0.2, np.where(SLOPE > 30, 0.7, 1.0))[..., None]
ASPF = np.stack([np.ones_like(south), 1 + 0.10 * south, 1 - 0.05 * south, 1 - 0.15 * south, 1 + 0.05 * south], -1) \
       * (np.minimum(SLOPE, 20) / 20)[..., None] + (1 - np.minimum(SLOPE, 20) / 20)[..., None]
EDGEF = np.where(EDGE[..., None], np.array([1.15, 1.15, 1.10, 0.95, 1.10]), 1.0)
OPENF = np.where(OPEN_FOREST.astype(bool)[..., None], np.array([0.8, 0.9, 0.7, 0.6, 0.9]), 1.0)

H = HOST[CLS] * GEOF[GEO] * ELEVF * SLOPEF * ASPF * EDGEF * OPENF
# morels in riparian broadleaf: floodplain ash/poplar/alder stands
riparian = ALLUV & np.isin(CLS, [1, 2, 5, 10, 12, 13])
H[..., 4] = np.where(riparian, np.maximum(H[..., 4], 0.95), H[..., 4])
# a thin halo outside the forest edge (lisières, prés boisés)
halo = np.zeros_like(H)
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        halo = np.maximum(halo, np.roll(np.roll(H, dy, 0), dx, 1))
H = np.where(NEARF[..., None], 0.35 * halo, H)
H[WATER] = 0
H = np.clip(H, 0, 1)
print("hab mean (forest)", H[FOREST].mean(0))

q = lambda a: (np.clip(np.round(a * 63), 0, 63) * 4).astype(np.uint8)  # 64 levels keep the PNGs small
thermal = (np.clip(np.round((-150 * south * np.minimum(SLOPE, 20) / 20) / 2 / 8), -15, 15) * 8 + 128).astype(np.uint8)
thermal[H.max(-1) == 0] = 128
Image.fromarray(np.dstack([q(H[..., 0]), q(H[..., 1]), q(H[..., 2])]), "RGB").save(f"{OUT}/hab_a.png", optimize=True)
Image.fromarray(np.dstack([q(H[..., 3]), q(H[..., 4]), thermal]), "RGB").save(f"{OUT}/hab_b.png", optimize=True)

np.savez_compressed(f"{S}/out/layers.npz", CLS=CLS, GEO=GEO, REG=REG, DEM=DEM, FOREST=FOREST, ALLUV=ALLUV)
print("saved layers")
