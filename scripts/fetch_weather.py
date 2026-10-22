"""Fetch weather for the mushroom map and write the db document (weather.json).

Open-Meteo forecast API: 60 past days + 16 forecast days at five reference points.
Open-Meteo seasonal API (ECMWF ensemble mean): extends temperatures and rain to +45 days.
Usage: python3 -I fetch_weather.py <out.json>
"""
import json, sys, urllib.request, datetime as dt, statistics

POINTS = [
    {"id": "bassin", "name": "Bassin genevois", "lat": 46.20, "lon": 6.10, "z": 420},
    {"id": "bornes", "name": "Pied du Salève / Bornes", "lat": 46.07, "lon": 6.20, "z": 800},
    {"id": "jura", "name": "Jura gessien", "lat": 46.30, "lon": 6.02, "z": 1000},
    {"id": "saleve", "name": "Plateau du Salève", "lat": 46.13, "lon": 6.18, "z": 1150},
    {"id": "voirons", "name": "Voirons", "lat": 46.22, "lon": 6.35, "z": 1300},
]
UA = {"User-Agent": "saleve-champignons/1.0 (personal)"}

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return json.load(r)

lat = ",".join(str(p["lat"]) for p in POINTS); lon = ",".join(str(p["lon"]) for p in POINTS)
elev = ",".join(str(p["z"]) for p in POINTS)
fc = get("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&elevation=%s"
         "&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,snowfall_sum"
         "&hourly=soil_temperature_6cm,soil_moisture_3_to_9cm&past_days=60&forecast_days=16&timezone=Europe%%2FZurich" % (lat, lon, elev))
days = fc[0]["daily"]["time"]

def daily_mean(h, key, n):
    v = h[key]; out = []
    for d in range(n):
        xs = [x for x in v[d * 24:(d + 1) * 24] if x is not None]
        out.append(round(sum(xs) / len(xs), 2) if xs else None)
    return out

doc = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "today": dt.date.today().isoformat(), "source": "Open-Meteo (meilleur modèle disponible) + tendance saisonnière ECMWF",
       "points": POINTS, "days": days, "tmax": [], "tmin": [], "tmean": [], "precip": [], "snow": [], "soilT": [], "soilM": [],
       "seasonal": {"days": [], "tmax": [], "tmin": [], "precip": []}}
for loc in fc:
    d = loc["daily"]
    doc["tmax"].append(d["temperature_2m_max"]); doc["tmin"].append(d["temperature_2m_min"])
    doc["tmean"].append(d["temperature_2m_mean"]); doc["precip"].append(d["precipitation_sum"])
    doc["snow"].append(d["snowfall_sum"])
    doc["soilT"].append(daily_mean(loc["hourly"], "soil_temperature_6cm", len(days)))
    doc["soilM"].append(daily_mean(loc["hourly"], "soil_moisture_3_to_9cm", len(days)))

# seasonal ensemble mean, kept only for the days after the deterministic forecast
last = dt.date.fromisoformat(days[-1])
try:
    for p in POINTS:
        s = get("https://seasonal-api.open-meteo.com/v1/seasonal?latitude=%s&longitude=%s&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&forecast_days=60" % (p["lat"], p["lon"]))
        sd = s["daily"]; t = sd["time"]
        def ens(var):
            keys = [k for k in sd if k.startswith(var)]
            out = []
            for i in range(len(t)):
                xs = [sd[k][i] for k in keys if sd[k][i] is not None]
                out.append(round(statistics.mean(xs), 2) if xs else None)
            return out
        tx, tn, pr = ens("temperature_2m_max"), ens("temperature_2m_min"), ens("precipitation_sum")
        keep = [i for i, x in enumerate(t) if last < dt.date.fromisoformat(x) <= last + dt.timedelta(days=30)]
        dz = (p["z"] - s.get("elevation", p["z"])) * -0.0055   # lapse-rate correction to the point's elevation
        if not doc["seasonal"]["days"]: doc["seasonal"]["days"] = [t[i] for i in keep]
        doc["seasonal"]["tmax"].append([None if tx[i] is None else round(tx[i] + dz, 2) for i in keep])
        doc["seasonal"]["tmin"].append([None if tn[i] is None else round(tn[i] + dz, 2) for i in keep])
        doc["seasonal"]["precip"].append([pr[i] for i in keep])
except Exception as e:  # the seasonal extension is optional
    print("seasonal skipped:", e)
json.dump(doc, open(sys.argv[1], "w"), separators=(",", ":"))
print("ok", len(days), "days,", len(doc["seasonal"]["days"]), "seasonal days; first", days[0], "last", days[-1])
