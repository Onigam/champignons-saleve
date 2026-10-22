"""Imagery composite, trails/roads overlay, labels, reserves and the info mask.
Run after process.py.  Usage: python3 -I assets.py <scratchpad>
"""
import json, math, sys, glob, os
import numpy as np
from PIL import Image, ImageDraw

S = sys.argv[1]
DL = f"{S}/dl"; OUT = f"{S}/out/app"
W, E, SO, NO = 5.88, 6.40, 46.00, 46.36
N, NI = 2048, 4096
Image.MAX_IMAGE_PIXELS = None
L = np.load(f"{S}/out/layers.npz")
CLS, GEO, REG, DEM = L["CLS"], L["GEO"], L["REG"], L["DEM"]

def px(lon, lat, n):
    return ((lon - W) / (E - W) * n, (NO - lat) / (NO - SO) * n)

def mosaic(tag, n=NI):
    m = Image.new("RGBA", (n, n)); t = n // 4
    for j in range(4):
        for i in range(4):
            im = Image.open(f"{DL}/img/{tag}_{j}_{i}.png").convert("RGBA")
            m.paste(im if im.size == (t, t) else im.resize((t, t)), (i * t, j * t))
    return m

CH4 = np.asarray(Image.fromarray(REG).resize((NI, NI), Image.NEAREST)) <= 2

# ---------------------------------------------------------------- ortho composite
ign = np.asarray(Image.open(f"{S}/out/mosaic_ign.png").convert("RGB"))
ch = np.asarray(Image.open(f"{S}/out/mosaic_ch.png").convert("RGB"))
ign_white = ign.min(-1) >= 248  # IGN has no imagery outside France (Swiss part of the lake)
ortho = np.where((CH4 | ign_white)[..., None], ch, ign)
Image.fromarray(ortho).save(f"{OUT}/ortho.jpg", quality=74, optimize=True, progressive=True)
print("ortho", os.path.getsize(f"{OUT}/ortho.jpg") // 1024, "KB")

# ---------------------------------------------------------------- lines overlay
C_PATH = (255, 226, 140, 235)    # sentier
C_TRACK = (246, 240, 226, 200)   # chemin / route empierrée
C_ROAD = (255, 255, 255, 215)
C_MAIN = (255, 205, 90, 240)
C_HWY = (255, 140, 70, 245)
C_BORDER = (240, 90, 160, 230)
lines = Image.new("RGBA", (NI, NI), (0, 0, 0, 0))
dr = ImageDraw.Draw(lines)

# Switzerland: recolour the swissTLM3D roads raster
st = np.asarray(mosaic("strassen")).copy()
a = st[..., 3] > 90
grey = (np.abs(st[..., 0].astype(int) - st[..., 1]) < 6) & (np.abs(st[..., 1].astype(int) - st[..., 2]) < 6)
light = a & grey & (st[..., 0] > 140)
dark = a & grey & (st[..., 0] <= 140)
col = a & ~grey
ov = np.zeros((NI, NI, 4), np.uint8)
ov[light] = C_TRACK; ov[dark] = C_ROAD; ov[col] = C_MAIN
ov[~CH4] = 0
lines = Image.alpha_composite(lines, Image.fromarray(ov, "RGBA"))
dr = ImageDraw.Draw(lines)

def dashed(pts, fill, width, on=7, off=5):
    acc, drawing = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0); t = 0.0
        while t < seg:
            step = min((on if drawing else off) - acc, seg - t)
            if drawing:
                a0, a1 = t / seg, (t + step) / seg
                dr.line([(x0 + (x1 - x0) * a0, y0 + (y1 - y0) * a0), (x0 + (x1 - x0) * a1, y0 + (y1 - y0) * a1)], fill=fill, width=width)
            t += step; acc += step
            if acc >= (on if drawing else off) - 1e-9:
                acc, drawing = 0.0, not drawing

order = {"Sentier": 0, "Chemin": 1, "Route empierrée": 1, "Route à 1 chaussée": 2, "Rond-point": 2, "Bretelle": 3, "Route à 2 chaussées": 4, "Type autoroutier": 4}
feats = []
for fn in sorted(glob.glob(f"{DL}/wfs/route_*.json")):
    for f in json.load(open(fn))["features"]:
        nat = f["properties"].get("nature")
        if nat in order and f["geometry"]:
            feats.append((order[nat], nat, f["properties"].get("importance"), f["geometry"]))
feats.sort(key=lambda t: t[0])
for o, nat, imp, g in feats:
    ls = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    for l in ls:
        pts = [px(x, y, NI) for x, y, *_ in l]
        if len(pts) < 2: continue
        if nat == "Sentier": dashed(pts, C_PATH, 2)
        elif o == 1: dr.line(pts, fill=C_TRACK, width=1)
        elif o == 2: dr.line(pts, fill=C_MAIN if str(imp) in ("1", "2", "3") else C_ROAD, width=3 if str(imp) in ("1", "2", "3") else 2)
        elif o == 3: dr.line(pts, fill=C_MAIN, width=2)
        else: dr.line(pts, fill=C_HWY, width=4)

# national border (outer rings of GE + VD)
for f in json.load(open(f"{DL}/wfs/ch_cantons.json"))["results"]:
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for p in polys:
        pts = [px(x, y, NI) for x, y, *_ in p[0]]
        dashed(pts, C_BORDER, 3, on=10, off=6)
lines.save(f"{OUT}/lines.png", optimize=True)
print("lines", os.path.getsize(f"{OUT}/lines.png") // 1024, "KB")

# ---------------------------------------------------------------- reserves
def simplify(pts, tol):
    """Douglas-Peucker on lon/lat (tol in degrees)."""
    if len(pts) < 5: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x0, y0), (x1, y1) = pts[a][:2], pts[b][:2]
        dx, dy = x1 - x0, y1 - y0; den = math.hypot(dx, dy) or 1e-12
        best, bi = 0, None
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x0) - dx * (pts[i][1] - y0)) / den
            if d > best: best, bi = d, i
        if bi is not None and best > tol:
            keep[bi] = True; stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]

def simplify_ring(ring, tol):
    """Closed ring: split at the vertex farthest from the start, simplify both halves."""
    if len(ring) < 5: return ring
    x0, y0 = ring[0][:2]
    k = max(range(len(ring)), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
    return simplify(ring[:k + 1], tol) + simplify(ring[k:], tol)[1:]

def in_bbox(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return max(xs) > W and min(xs) < E and max(ys) > SO and min(ys) < NO

RES = []  # {name, kind, rule, polys:[[ [lon,lat],... ] (outer only, holes ignored) ]}
FR_KIND = {"Réserve naturelle": ("Réserve naturelle nationale", 2), "Arrêté de protection": ("Arrêté de protection de biotope", 2),
           "Site Natura 2000": ("Site Natura 2000", 1), "Site acquis ou assimilé des conservatoires d'espaces naturels": ("Site du Conservatoire d'espaces naturels", 2),
           "Terrain du Conservatoire du Littoral": ("Terrain du Conservatoire du littoral", 2)}
for f in json.load(open(f"{DL}/wfs/reserve_0.json"))["features"]:
    p = f["properties"]
    if p["nature"] not in FR_KIND: continue
    kind, rule = FR_KIND[p["nature"]]
    if p["nature"] == "Site Natura 2000" and "Oiseaux" in (p.get("nature_detaillee") or ""): continue  # duplicate perimeters
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(pl[0], 0.0002)] for pl in polys if in_bbox(pl[0])]
    if out: RES.append({"name": p["toponyme"], "kind": kind, "rule": rule, "polys": out})
SITG_KIND = {"Réserves naturelles (GE)": ("Réserve naturelle genevoise", 3), "Réserves naturelles de statut public (RNPU) (VD)": ("Réserve naturelle vaudoise", 3),
             "Réserves forestières (VD)": ("Réserve forestière vaudoise", 1), "Réserves naturelles nationales (FR)": ("Réserve naturelle nationale", 2),
             "Réserves naturelles régionales (FR)": ("Réserve naturelle régionale", 2)}
for f in json.load(open(f"{DL}/wfs/sitg_reserves.json"))["features"]:
    p = f["properties"]
    if p["type"] not in SITG_KIND or not f.get("geometry"): continue
    kind, rule = SITG_KIND[p["type"]]
    if rule == 2: continue  # French national reserve already comes from BD TOPO
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(pl[0], 0.00005)] for pl in polys if in_bbox(pl[0])]
    if out: RES.append({"name": p["nom"].strip(), "kind": kind, "rule": rule, "polys": out})
CH_KIND = {"ch.pronatura.naturschutzgebiete": ("Réserve Pro Natura", 3), "ch.bafu.bundesinventare-auen": ("Zone alluviale d'importance nationale", 2),
           "ch.bafu.bundesinventare-flachmoore": ("Bas-marais d'importance nationale", 2), "ch.bafu.waldreservate": ("Réserve forestière genevoise", 1)}
seen = {}
for layer, (kind, rule) in CH_KIND.items():
    for f in json.load(open(f"{DL}/wfs/ch_{layer}.json"))["results"]:
        name = f["properties"].get("name") or f["properties"].get("label")
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(pl[0], 0.00005)] for pl in polys if in_bbox(pl[0])]
        if not out: continue
        key = (layer, name.split(" (")[0])
        if key in seen: seen[key]["polys"] += out
        else:
            seen[key] = {"name": key[1], "kind": kind, "rule": rule, "polys": out}; RES.append(seen[key])
json.dump(RES, open(f"{OUT}/reserves.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("reserves", len(RES), os.path.getsize(f"{OUT}/reserves.json") // 1024, "KB")

FP = []
for f in json.load(open(f"{DL}/wfs/forpub_0.json"))["features"]:
    g = f["geometry"]
    if not g: continue
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = [[[round(x, 5), round(y, 5)] for x, y, *_ in simplify_ring(pl[0], 0.0002)] for pl in polys if in_bbox(pl[0])]
    if out: FP.append({"name": f["properties"]["toponyme"], "kind": f["properties"]["nature"], "polys": out})
json.dump(FP, open(f"{OUT}/forets_publiques.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("public forests", len(FP), os.path.getsize(f"{OUT}/forets_publiques.json") // 1024, "KB")

# rule raster: 0 none, 1 info, 2 réglementé, 3 interdit (draw in increasing rule order)
RULE = np.zeros((N, N), np.uint8)
for r in sorted(RES, key=lambda r: r["rule"]):
    for pl in r["polys"]:
        m = Image.new("L", (N, N), 0)
        ImageDraw.Draw(m).polygon([px(x, y, N) for x, y in pl], fill=1)
        RULE[np.asarray(m, bool)] = np.maximum(RULE[np.asarray(m, bool)], r["rule"])
B = ((REG.astype(int) - 1) * 64 + GEO.astype(int) * 10).clip(0, 255).astype(np.uint8)
Image.fromarray(np.dstack([RULE * 80, CLS * 16, B]).astype(np.uint8), "RGB").save(f"{OUT}/mask.png", optimize=True)
print("mask saved")

# ---------------------------------------------------------------- labels
def elev(lon, lat):
    x, y = px(lon, lat, N)
    return float(DEM[min(N - 1, max(0, int(y))), min(N - 1, max(0, int(x)))])

def centroid(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)

places = []
for f in json.load(open(f"{DL}/wfs/habit_0.json"))["features"]:
    p = f["properties"]
    if p["nature"] != "Lieu-dit habité" or str(p.get("importance")) not in ("1", "2", "3") or not p.get("toponyme"): continue
    g = f["geometry"]; c = g["coordinates"]
    if g["type"] == "Point": lon, lat = c[:2]
    else:
        ring = (c[0][0] if g["type"] == "MultiPolygon" else c[0]); lon, lat = centroid(ring)
    if W < lon < E and SO < lat < NO:
        places.append({"n": p["toponyme"], "t": "v", "r": int(p["importance"]), "lon": round(lon, 5), "lat": round(lat, 5)})
cur = {}
for f in json.load(open(f"{DL}/wfs/ch_communes.json"))["results"]:
    p = f["properties"]
    if not p.get("is_current_jahr") or p.get("objektart") not in (None, 0, 11) and "Lac" in p.get("gemname", ""): continue
    nm = p["gemname"]
    if nm.startswith("Lac ") or nm in cur: continue
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    ring = max((pl[0] for pl in polys), key=len); lon, lat = centroid(ring)
    if W < lon < E and SO < lat < NO:
        cur[nm] = {"n": nm.replace(" (GE)", ""), "t": "v", "r": 1 if nm == "Genève" else 3, "lon": round(lon, 5), "lat": round(lat, 5)}
places += list(cur.values())
for f in json.load(open(f"{DL}/wfs/oro_0.json"))["features"]:
    p = f["properties"]
    if p["nature"] not in ("Sommet", "Col", "Montagne") or not p.get("toponyme") or str(p.get("importance")) not in ("1", "2", "3", "4"): continue
    c = f["geometry"]["coordinates"]
    while isinstance(c[0], list): c = c[0]
    lon, lat = c[:2]
    if W < lon < E and SO < lat < NO:
        places.append({"n": p["toponyme"], "t": "c" if p["nature"] == "Col" else "s", "r": int(p["importance"]), "lon": round(lon, 5), "lat": round(lat, 5)})
for pl in places: pl["z"] = round(elev(pl["lon"], pl["lat"]))
json.dump(places, open(f"{OUT}/places.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("places", len(places))

# ---------------------------------------------------------------- sector statistics
# per sector, species and 100 m band (effective elevation incl. aspect offset): summed habitat / sector cells
ha = np.asarray(Image.open(f"{OUT}/hab_a.png"), np.float32) / 252
hb = np.asarray(Image.open(f"{OUT}/hab_b.png"), np.float32)
H = np.dstack([ha[..., 0], ha[..., 1], ha[..., 2], hb[..., 0] / 252, hb[..., 1] / 252])
zeff = DEM + (hb[..., 2] - 128) * 2
band = np.clip(np.round((zeff - 300) / 100), 0, 19).astype(int)
jj, ii = np.mgrid[0:N, 0:N]
LON = W + (ii + 0.5) / N * (E - W); LAT = NO - (jj + 0.5) / N * (NO - SO)
secs = json.load(open(f"{S}/build/sectors.json"))
for sc in secs:
    dkm = np.hypot((LON - sc["lon"]) * 77.1, (LAT - sc["lat"]) * 111.2)
    m = dkm <= sc["r"]
    n = m.sum()
    st = []
    for k in range(5):
        st.append([round(float(H[..., k][m & (band == b)].sum() / n), 4) for b in range(20)])
    sc["stats"] = st
    sc["zmin"], sc["zmax"] = int(np.percentile(DEM[m], 5)), int(np.percentile(DEM[m], 95))
    sc["forest"] = round(float((CLS[m] > 0).mean()), 2)
    sc["rule3"] = round(float((RULE[m] == 3).mean()), 2)
json.dump(secs, open(f"{OUT}/sectors.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("sectors", len(secs), [(s["id"], s["zmin"], s["zmax"], s["forest"], round(sum(map(sum, s["stats"])), 2)) for s in secs])
