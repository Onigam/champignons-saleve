"""Export the habitat layers for the web map (MapLibre canvas source = Web Mercator rows).

Reads build/ (outputs of process.py / assets.py, plate carrée 2048²) and writes data/:
  hab_a.png  R cèpe, G autres bolets, B girolle        (0..252, step 4)
  hab_b.png  R trompette, G morilles, B altitude code   (code = (z_eff - 300) / 100 * 12, z_eff includes the aspect offset)
  mask.png   R rule*80 (0 none, 1 info, 2 to check, 3 forbidden), G forest class*16, B (region-1)*64 + geology*10
  dem.png    1024² plate carrée, decimetres in R/G (unchanged)
  reserves.geojson, ch_border.json
Usage: python3 -I scripts/export_web.py <project dir>
"""
import json, math, sys, shutil
import numpy as np
from PIL import Image

P = sys.argv[1]
B, D = f"{P}/build", f"{P}/data"
W, E, SO, NO = 5.88, 6.40, 46.00, 46.36
N = 2048

def merc(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

y0, y1 = merc(NO), merc(SO)
rows = []
for j in range(N):
    y = y0 + (j + 0.5) / N * (y1 - y0)
    lat = math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)
    rows.append(min(N - 1, max(0, int((NO - lat) / (NO - SO) * N))))
rows = np.array(rows)

L = np.load(f"{B}/layers.npz")
ha = np.asarray(Image.open(f"{B}/hab_a.png"))
hb = np.asarray(Image.open(f"{B}/hab_b.png"))
mk = np.asarray(Image.open(f"{B}/mask.png"))
zeff = L["DEM"] + (hb[..., 2].astype(np.float32) - 128) * 2
code = np.clip(np.round((zeff - 300) / 100 * 12), 0, 252).astype(np.uint8)
hb2 = np.dstack([hb[..., 0], hb[..., 1], code])
for name, arr in (("hab_a", ha), ("hab_b", hb2), ("mask", mk)):
    Image.fromarray(np.ascontiguousarray(arr[rows]), "RGB").save(f"{D}/{name}.png", optimize=True)
shutil.copy(f"{B}/dem.png", f"{D}/dem.png")

# reserves as GeoJSON (outer rings; holes are rare and small)
res = json.load(open(f"{B}/reserves.json"))
fc = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": r["name"], "kind": r["kind"], "rule": r["rule"]},
     "geometry": {"type": "MultiPolygon", "coordinates": [[pl] for pl in r["polys"]]}} for r in res]}
json.dump(fc, open(f"{D}/reserves.geojson", "w"), ensure_ascii=False, separators=(",", ":"))
print("reserves", len(fc["features"]))
