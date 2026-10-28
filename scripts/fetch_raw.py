"""Download the raw layers for the area in config.py into raw/ (skips files already there).

Sources: IGN Géoplateforme WFS (BD Forêt V2, BD TOPO), geo.admin.ch (cantons, communes, protected areas,
forest mask and mix, water, riparian vegetation), SITG (Geneva/Vaud reserves), AWS Terrain Tiles.
Usage: python3 -I scripts/fetch_raw.py
"""
import json, math, sys, time, urllib.parse, urllib.request
from config import W, E, S, N, NX, NY, RAW

UA = {"User-Agent": "champignons-saleve/1.0 (personal, non-commercial)"}

def get(url, path, tries=4):
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                path.write_bytes(r.read())
            return path
        except Exception as e:  # network hiccups: retry with backoff
            if k == tries - 1:
                raise
            print("  retry", path.name, e)
            time.sleep(2 * (k + 1))

def dem_tiles(z=12):
    tx = lambda lon: int((lon + 180) / 360 * 2 ** z)
    ty = lambda lat: int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    for x in range(tx(W), tx(E) + 1):
        for y in range(ty(N), ty(S) + 1):
            get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", RAW / "dem" / f"{z}_{x}_{y}.png")

def wfs(layer, name):
    bbox = f"{S},{W},{N},{E},urn:ogc:def:crs:EPSG::4326"
    i = start = 0
    while True:
        q = urllib.parse.urlencode({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": layer, "BBOX": bbox,
                                    "count": 5000, "startIndex": start, "outputFormat": "application/json", "srsName": "EPSG:4326"})
        p = get(f"https://data.geopf.fr/wfs/ows?{q}", RAW / "wfs" / f"{name}_{i}.json")
        n = len(json.load(open(p))["features"])
        print(f"  {name} page {i}: {n}")
        if n < 5000:
            break
        i += 1; start += 5000

def identify(layer, name):
    q = urllib.parse.urlencode({"geometryType": "esriGeometryEnvelope", "geometry": f"{W},{S},{E},{N}", "sr": 4326, "layers": f"all:{layer}",
                                "tolerance": 0, "returnGeometry": "true", "geometryFormat": "geojson", "limit": 200, "lang": "fr"})
    get(f"https://api3.geo.admin.ch/rest/services/api/MapServer/identify?{q}", RAW / "ch" / f"{name}.json")

def wms(layer, tag, cols=4):
    """Mosaic of 1024 px tiles; rows chosen so pixels stay about square on the ground."""
    rows = math.ceil(cols * NY / NX)
    for j in range(rows):
        for i in range(cols):
            w = W + (E - W) * i / cols; e = W + (E - W) * (i + 1) / cols
            n = N - (N - S) * j / rows; s = N - (N - S) * (j + 1) / rows
            q = urllib.parse.urlencode({"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "", "CRS": "EPSG:4326",
                                        "FORMAT": "image/png", "TRANSPARENT": "TRUE", "BBOX": f"{s},{w},{n},{e}", "WIDTH": 1024, "HEIGHT": 1024})
            get(f"https://wms.geo.admin.ch/?{q}", RAW / "wms" / f"{tag}_{j}_{i}.png")
    json.dump({"cols": cols, "rows": rows}, open(RAW / "wms" / f"{tag}.json", "w"))

if __name__ == "__main__":
    print("DEM tiles"); dem_tiles()
    print("IGN WFS")
    for layer, name in [("LANDCOVER.FORESTINVENTORY.V2:formation_vegetale", "bdforet"), ("BDTOPO_V3:parc_ou_reserve", "reserve"),
                        ("BDTOPO_V3:foret_publique", "forpub"), ("BDTOPO_V3:zone_d_habitation", "habit"), ("BDTOPO_V3:cours_d_eau", "cours")]:
        wfs(layer, name)
    print("geo.admin.ch")
    for layer, name in [("ch.swisstopo.swissboundaries3d-kanton-flaeche.fill", "cantons"), ("ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill", "communes"),
                        ("ch.bafu.bundesinventare-auen", "auen"), ("ch.pronatura.naturschutzgebiete", "pronatura"),
                        ("ch.bafu.waldreservate", "waldreservate"), ("ch.bafu.bundesinventare-flachmoore", "flachmoore")]:
        identify(layer, name)
    get("https://vector.sitg.ge.ch/arcgis/rest/services/Hosted/AGGLO_NAT_PERI_PRO_RESERVES/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson",
        RAW / "ch" / "sitg_reserves.json")
    for layer, tag in [("ch.swisstopo.swisstlm3d-gewaessernetz", "water"), ("ch.swisstopo.swisstlm3d-wald", "wald"),
                       ("ch.bafu.landesforstinventar-waldmischungsgrad", "mix"), ("ch.bafu.gewaesser-uferbestockung_vegetation", "ufer")]:
        print("WMS", tag); wms(layer, tag)
    print("done")
