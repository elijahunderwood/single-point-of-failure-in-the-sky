"""archives.py - talk to the data archives (all WITHOUT a login):

* Geoscience Australia GNSS Data Repository (data.gnss.ga.gov.au): a public REST API
  that serves daily 30-s RINEX for hundreds of IGS/EUREF/regional stations worldwide,
  plus the IGS broadcast navigation (orbit) files. Each API answer contains a
  temporary download link (a 'pre-signed' Amazon S3 URL) that we fetch straight away.
* GFZ Potsdam Kp web service (kp.gfz.de) - the official Kp index.
* Kyoto WDC for Geomagnetism (wdc.kugi.kyoto-u.ac.jp) - Dst (final, provisional or real-time).
"""
import json, time, re, os, gzip, logging, urllib.request, urllib.error, datetime as dt

log = logging.getLogger("global_logger")
GA_API = "https://data.gnss.ga.gov.au/api/v1/rinexFiles"
UA = {"User-Agent": "global_logger/1.0 (student space-weather project)"}

def http_get(url, timeout=120, retries=4, backoff=5):
    """GET with retries and exponential back-off (5 s, 10 s, 20 s ...)."""
    for k in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: raise
            err = e
        except Exception as e:
            err = e
        log.warning("GET failed (%s), retry %d/%d: %s", err, k + 1, retries, url[:120])
        time.sleep(backoff * 2**k)
    raise RuntimeError(f"giving up on {url[:120]}: {err}")

def _fname(loc):
    m = re.search(r"filename%3D%22(.+?)%22", loc)
    return m.group(1) if m else loc.split("?")[0].rsplit("/", 1)[-1]

def ga_list(station, day, file_type="obs"):
    """List the archive files for one station and one UTC day."""
    d0 = dt.datetime.combine(day, dt.time()); d1 = d0 + dt.timedelta(days=1)
    url = f"{GA_API}?stationId={station}&startDate={d0:%Y-%m-%dT%H:%M:%SZ}&endDate={d1:%Y-%m-%dT%H:%M:%SZ}&fileType={file_type}"
    try: items = json.loads(http_get(url, timeout=60))
    except urllib.error.HTTPError as e:
        if e.code == 404: return []
        raise
    out = []
    for x in items:
        if not x.get("startDate", "").startswith(day.isoformat()): continue
        out.append(dict(period=x.get("filePeriod"), version=str(x.get("rinexVersion")), name=_fname(x["fileLocation"]), url=x["fileLocation"]))
    return out

def choose_daily_obs(files, prefer_version="3"):
    """Pick the daily (01D) 30-s file; prefer RINEX 3, fall back to RINEX 2."""
    daily = [f for f in files if f["period"] == "01D" and ("30S" in f["name"] or f["version"] == "2")]
    daily.sort(key=lambda f: (f["version"] != prefer_version, "_MO" not in f["name"]))
    return daily[0] if daily else None

def download_obs(station, day, dest_dir):
    """Download one station-day of 30-s observations. Returns the local path or None."""
    os.makedirs(dest_dir, exist_ok=True)
    files = ga_list(station, day)
    f = choose_daily_obs(files)
    if f is None: return None
    path = os.path.join(dest_dir, f["name"])
    if not os.path.exists(path):
        data = http_get(f["url"])
        open(path + ".part", "wb").write(data); os.replace(path + ".part", path)
    return path

def download_nav(day, dest_dir):
    """IGS merged GPS broadcast navigation file (RINEX 2 'brdcDDD0.YYn') for one day."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"brdc{day:%j}0.{day:%y}n.gz")
    if os.path.exists(path): return path
    for f in ga_list("BRDC", day, "nav"):
        if f["name"].lower().endswith("n.gz"):
            data = http_get(f["url"]); open(path, "wb").write(data); return path
    raise RuntimeError(f"no GPS broadcast nav for {day}")

# ---------------------------------------------------------------- indices
def gfz_kp(start, end):
    """Definitive/nowcast Kp from GFZ. Returns list of (ts_utc ISO, kp, status)."""
    url = f"https://kp.gfz.de/app/json/?start={start:%Y-%m-%d}T00:00:00Z&end={end:%Y-%m-%d}T23:59:59Z&index=Kp&status=all"
    j = json.loads(http_get(url, timeout=60))
    st = j.get("status", ["?"] * len(j["Kp"]))
    return [(t.replace("Z", "+00:00"), float(k), s) for t, k, s in zip(j["datetime"], j["Kp"], st)]

def kyoto_dst(year, month):
    """Hourly Dst for one month from Kyoto: tries final, then provisional, then real-time.
    Returns (product, [(ts_utc ISO, dst), ...])."""
    for kind in ("dst_final", "dst_provisional", "dst_realtime"):
        try:
            html = http_get(f"https://wdc.kugi.kyoto-u.ac.jp/{kind}/{year}{month:02d}/index.html", timeout=60, retries=2).decode("latin1")
            break
        except Exception:
            continue
    else:
        raise RuntimeError("Kyoto Dst not reachable")
    body = html.split("DAY", 1)[1] if "DAY" in html else html
    out = []
    for line in body.splitlines():
        m = re.match(r"^\s?(\d{1,2})\s", line)
        if not m or len(line) < 40: continue
        day = int(m.group(1))
        vals = re.findall(r"-?\d+", line[3:].replace("-", " -"))
        for h, v in enumerate(vals[:24]):
            if v in ("9999", "99999") or abs(int(v)) > 2000: continue   # fill values / glued digits
            out.append((f"{year}-{month:02d}-{day:02d}T{h:02d}:00:00+00:00", int(v)))
    return kind, out
