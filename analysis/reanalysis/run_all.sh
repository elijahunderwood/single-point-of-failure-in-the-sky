#!/bin/bash
# Re-runs the whole reanalysis from the raw files (about 2 minutes).
# Needs: python3 with numpy, pandas, scipy, matplotlib, hatanaka.
# Set SPACE_WEATHER_DATA and optionally NAV_DIR or REPO_ROOT if your data are not in data/raw.
set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
export REPO_ROOT
D="${SPACE_WEATHER_DATA:-$REPO_ROOT/data/raw}"
mkdir -p "$D/x" && cd "$D/x"
for t in ../quiet_ctrl.tar ../storm05oct.tar ../hilat_rinex.tar; do tar xf "$t" 2>/dev/null; done
for f in hilat_rinex/*.crx.gz; do r="${f%.crx.gz}.rnx"; [ -f "$r" ] || python3 -c "import hatanaka,sys;open(sys.argv[2],'wb').write(hatanaka.decompress(open(sys.argv[1],'rb').read()))" "$f" "$r"; done
cd - >/dev/null
# broadcast orbits (needed for satellite elevations at Tromso / Ny-Alesund) from Geoscience Australia's public archive
python3 - <<'NAVPY'
import json, urllib.request, datetime, gzip, os
from pathlib import Path
REPO_ROOT = Path(os.environ["REPO_ROOT"])
NAV = Path(os.environ.get("NAV_DIR", str(REPO_ROOT / "data" / "nav")))
os.makedirs(NAV, exist_ok=True)
for doy in [214, 220, 251, 275, 277, 278]:
    p = NAV / f"brdc{doy}.n"
    if p.exists():
        continue
    d = datetime.date(2026, 1, 1) + datetime.timedelta(doy - 1)
    u = (f"https://data.gnss.ga.gov.au/api/v1/rinexFiles?stationId=BRDC"
         f"&startDate={d}T00:00:00Z&endDate={d+datetime.timedelta(1)}T00:00:00Z&fileType=nav")
    for x in json.load(urllib.request.urlopen(u, timeout=60)):
        if x["startDate"].startswith(str(d)) and "n.gz" in x["fileLocation"].split("filename%3D%22")[1]:
            p.write_bytes(gzip.decompress(urllib.request.urlopen(x["fileLocation"], timeout=120).read()))
NAVPY
mkdir -p "$SCRIPT_DIR/output"
for s in 01_inventory.py 02_home_roti.py 03_starlink.py 04_highlat.py 05_embrace_freq.py 06_sea_correlations.py 07_validation.py; do
  echo "== $s"; python3 "$SCRIPT_DIR/$s" > "$SCRIPT_DIR/output/${s%.py}.log" 2>&1
done
echo done
