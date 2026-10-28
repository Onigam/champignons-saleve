"""Area and grid shared by the data scripts."""
import math
from pathlib import Path

# W, E, S, N in degrees (WGS84). South edge reaches the north end of Lake Annecy.
W, E, S, N = 5.88, 6.40, 45.86, 46.36
MIDLAT = (S + N) / 2
KM_X = (E - W) * 111.32 * math.cos(math.radians(MIDLAT))
KM_Y = (N - S) * 111.2
NX = 2048                                   # analysis grid columns (~20 m)
NY = int(round(NX * KM_Y / KM_X / 8)) * 8   # rows, same cell size
DW = 1024                                   # elevation lookup raster for the web app
DH = int(round(DW * KM_Y / KM_X / 8)) * 8

ROOT = Path(__file__).resolve().parents[1]
RAW, BUILD, DATA = ROOT / "raw", ROOT / "build", ROOT / "data"
