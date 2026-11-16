#!/usr/bin/env python3
"""
Live dashboard generator ("A Single Point of Failure in the Sky").

Reads the loggers' SQLite databases READ-ONLY, works out a handful of plain-English
numbers, and writes one self-contained web page (www/index.html, no external files)
plus data.json.  Standard library only.  Run once a minute from a systemd timer.

    generate.py              write www/index.html + www/data.json
    generate.py --snapshot   print a "saved snapshot" copy of the page to stdout
    generate.py --backfill   fill the 24-hour history (one-off, run niced)

It never writes to any logger database.  Its own history lives in history.db here.
"""
import json, math, os, sqlite3, statistics, sys, time, resource
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "www")
UK = ZoneInfo("Europe/London")
UTC = timezone.utc

DB = {
    "tec": f"{HOME}/gnss-logger/gnss_tec.db",
    "timing": f"{HOME}/gnss-logger/gnss_timing.db",
    "space": f"{HOME}/spaceweather-logger/spaceweather.db",
    "flare": f"{HOME}/flare_logger/flare.db",
    "leo": f"{HOME}/starlink-logger/starlink_history.db",
    "wx": f"{HOME}/weather-logger/localweather.db",
    "metar": f"{HOME}/weather-logger/metar.db",
}
ROTI_CSV = f"{HOME}/gnss-logger/roti_network.csv"

# ---- project facts -------------------------------------------------------
KP_THRESHOLD = 7.7           # from Elijah's fit; 95 % range 7.4-8.0
KP_CI = (7.4, 8.0)
ROTI_DISTURBED = 0.5         # TECU/min
STORM_KP_10OCT = 7.33

# ---- helpers ---------------------------------------------------------------
NOW = datetime.now(UTC)


def ro(key):
    c = sqlite3.connect(f"file:{DB[key]}?mode=ro", uri=True, timeout=5)
    c.execute("PRAGMA query_only=1")
    return c


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse(ts):
    if ts is None:
        return None
    d = datetime.fromisoformat(ts)
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def uk(dt, fmt="%H:%M"):
    return dt.astimezone(UK).strftime(fmt)


def fmt(x, d=1):
    return "–" if x is None else f"{x:.{d}f}"


def age_min(dt):
    return None if dt is None else (NOW - dt).total_seconds() / 60.0


def floor5(dt):
    return dt.replace(minute=dt.minute - dt.minute % 5, second=0, microsecond=0)


def safe(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:  # a missing/locked source must never break the page
        return None, f"{type(e).__name__}: {e}"


# ---- ROTI (same method as gnss-logger/compute_roti.py) -----------------------
def rot_samples(rows, mask=20.0, interval=30.0, max_gap=90.0, rot_max=10.0):
    """rows: (sv,id,tow,ts,phase,slip,elev,cno) sorted by sv,id -> (ts,sv,rot,elev,cno)."""
    out, prev, psv = [], None, None
    for sv, _id, tow, ts, phase, slip, elev, cno in rows:
        if sv != psv:
            prev, psv = None, sv
        if slip == 1 or phase is None or tow is None:
            prev = None if (phase is None or tow is None) else (tow, phase)
            continue
        if prev is None:
            prev = (tow, phase)
            continue
        dt = tow - prev[0]
        if dt < interval:
            continue
        if dt <= max_gap and elev is not None and elev >= mask:
            rot = (phase - prev[1]) / dt * 60.0
            if abs(rot) <= rot_max:
                out.append((ts, sv, rot, elev, cno))
        prev = (tow, phase)
    return out


def tec_rows(conn, t0, t1):
    rows = conn.execute(
        "SELECT sv,id,rcv_tow,ts_utc,phase_tec,slip,elev_deg,cno_l1 FROM tec "
        "WHERE ts_utc>=? AND ts_utc<?", (iso(t0), iso(t1))).fetchall()
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def roti_per_sv(samples, min_n=5):
    by = {}
    for ts, sv, rot, elev, cno in samples:
        by.setdefault(sv, []).append((rot, elev))
    res = {}
    for sv, v in by.items():
        if len(v) >= min_n:
            res[sv] = (statistics.stdev([x[0] for x in v]), sum(x[1] for x in v) / len(v))
    return res


def net_stats(per_sv):
    vals = sorted((v[0] for v in per_sv.values()), reverse=True)
    if not vals:
        return dict(n=0, n_dist=0, r2=None, rmax=None, rmed=None)
    return dict(n=len(vals), n_dist=sum(1 for v in vals if v > ROTI_DISTURBED),
                r2=vals[1] if len(vals) > 1 else None, rmax=vals[0],
                rmed=statistics.median(vals))


# ---- history (our own small DB) ----------------------------------------------
def hist_db():
    c = sqlite3.connect(os.path.join(HERE, "history.db"), timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS m5(
        w TEXT PRIMARY KEY, roti_2nd REAL, roti_med REAL, roti_max REAL, n_sats INTEGER,
        n_dist INTEGER, cno REAL, tacc REAL, jam REAL, nsv REAL, lat REAL, drop_pct REAL)""")
    return c


def compute_windows(starts):
    """starts: sorted list of 5-min window start datetimes (contiguous run). -> list of rows."""
    t0, t1 = starts[0], starts[-1] + timedelta(minutes=5)
    rows = []
    tec = ro("tec")
    samples = rot_samples(tec_rows(tec, t0 - timedelta(seconds=45), t1))
    cno_rows = tec.execute(
        "SELECT ts_utc,cno_l1,elev_deg FROM tec WHERE ts_utc>=? AND ts_utc<? AND elev_deg>=20 "
        "AND cno_l1 IS NOT NULL", (iso(t0), iso(t1))).fetchall()
    tec.close()
    tim = ro("timing")
    trows = tim.execute(
        "SELECT ts_utc,t_acc_ns,rf0_jam_ind,num_sv FROM timing_1hz WHERE ts_utc>=? AND ts_utc<?",
        (iso(t0), iso(t1))).fetchall()
    tim.close()
    leo = ro("leo")
    lrows = leo.execute(
        "SELECT ts_utc,ping_latency_ms,ping_drop_rate FROM history WHERE ts_utc>=? AND ts_utc<?",
        (iso(t0), iso(t1))).fetchall()
    leo.close()

    def key(ts):
        m = int(ts[14:16])
        return ts[:14] + f"{m - m % 5:02d}:00"
    sb, cb, tb, lb = {}, {}, {}, {}
    for s in samples:
        sb.setdefault(key(s[0]), []).append(s)
    for r in cno_rows:
        cb.setdefault(key(r[0]), []).append(r[1])
    for r in trows:
        tb.setdefault(key(r[0]), []).append(r)
    for r in lrows:
        lb.setdefault(key(r[0]), []).append(r)
    for w in starts:
        k = iso(w)
        ns = net_stats(roti_per_sv(sb.get(k, [])))
        cn = cb.get(k)
        tr = tb.get(k)
        lr = lb.get(k)
        lat = [r[1] for r in lr if r[1] is not None] if lr else []
        rows.append((k + "+00:00", ns["r2"], ns["rmed"], ns["rmax"], ns["n"], ns["n_dist"],
                     statistics.mean(cn) if cn else None,
                     statistics.median([r[1] for r in tr if r[1] is not None]) if tr else None,
                     max([r[2] for r in tr if r[2] is not None]) if tr else None,
                     statistics.median([r[3] for r in tr if r[3] is not None]) if tr else None,
                     statistics.median(lat) if lat else None,
                     100.0 * statistics.mean([r[2] for r in lr if r[2] is not None]) if lr else None))
    return rows


def update_history(limit):
    """Fill missing completed 5-min windows of the last 24 h (at most `limit` per run)."""
    h = hist_db()
    last = floor5(NOW - timedelta(minutes=6)) - timedelta(minutes=5)   # window must end >= 6 min ago
    first = floor5(NOW - timedelta(hours=24))
    have = {r[0][:19] for r in h.execute("SELECT w FROM m5 WHERE w>=?", (iso(first),))}
    todo, w = [], last
    while w >= first and len(todo) < limit:       # newest first, so the page fills from "now" back
        if iso(w) not in have:
            todo.append(w)
        w -= timedelta(minutes=5)
    todo.sort()
    # process contiguous runs
    runs, cur = [], []
    for w in todo:
        if cur and w - cur[-1] > timedelta(minutes=5):
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)
    n = 0
    for run in runs:
        rows = compute_windows(run)
        h.executemany("INSERT OR REPLACE INTO m5 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        h.commit()
        n += len(rows)
    h.execute("DELETE FROM m5 WHERE w<?", (iso(NOW - timedelta(hours=30)),))
    h.commit()
    series = h.execute("SELECT * FROM m5 WHERE w>=? ORDER BY w", (iso(NOW - timedelta(hours=24)),)).fetchall()
    h.close()
    return n, series


def typical_roti():
    """Median network ROTI (2nd-highest satellite) by UTC hour of day over all past days."""
    path = os.path.join(HERE, "typical.json")
    try:
        if time.time() - os.path.getmtime(path) < 20 * 3600:
            return {int(k): v for k, v in json.load(open(path)).items()}
    except Exception:
        pass
    by = {}
    with open(ROTI_CSV) as f:
        next(f)
        for line in f:
            p = line.strip().split(",")
            if len(p) >= 3 and p[2]:
                by.setdefault(int(p[0][11:13]), []).append(float(p[2]))
    res = {h: statistics.median(v) for h, v in by.items() if v}
    json.dump(res, open(path, "w"))
    return res


# ---- data gathering ------------------------------------------------------------
def g_scale(kp):
    if kp is None:
        return None
    for lim, g in ((8.67, 5), (7.67, 4), (6.67, 3), (5.67, 2), (4.67, 1)):
        if kp >= lim:
            return g
    return 0


def flare_class(flux):
    if flux is None or flux <= 0:
        return "–", None
    for lim, c in ((1e-4, "X"), (1e-5, "M"), (1e-6, "C"), (1e-7, "B"), (1e-8, "A")):
        if flux >= lim:
            return f"{c}{flux / lim:.1f}", c
    return f"A{flux / 1e-8:.1f}", "A"


def fetch_ok(conn, source=None):
    if source:
        r = conn.execute("SELECT ts_utc FROM fetch_log WHERE source=? AND status='ok' ORDER BY id DESC LIMIT 1", (source,)).fetchone()
    else:
        r = conn.execute("SELECT ts_utc FROM fetch_log WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return parse(r[0]) if r else None


def get_space():
    c = ro("space")
    d = {}
    kp = c.execute("SELECT ts_utc,kp FROM kp_index WHERE ts_utc>=? ORDER BY ts_utc",
                   (iso(NOW - timedelta(hours=30)),)).fetchall()
    last = c.execute("SELECT ts_utc,kp FROM kp_index ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["kp"] = last[1] if last else None
    d["kp_ts"] = parse(last[0]) if last else None
    d["kp_series"] = [(parse(a), b) for a, b in kp if b is not None]
    d["kp_fetch"] = fetch_ok(c, "kp")
    dst = c.execute("SELECT ts_utc,dst FROM dst_index ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["dst"] = dst[1] if dst else None
    p = c.execute("SELECT ts_utc,density,speed_kms FROM solar_wind_plasma WHERE speed_kms IS NOT NULL ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["sw_ts"] = parse(p[0]) if p else None
    d["density"], d["speed"] = (p[1], p[2]) if p else (None, None)
    m = c.execute("SELECT ts_utc,bt,bz_gsm FROM solar_wind_mag WHERE bz_gsm IS NOT NULL ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["bt"], d["bz"] = (m[1], m[2]) if m else (None, None)
    d["mag_ts"] = parse(m[0]) if m else None
    pl = c.execute("SELECT ts_utc,speed_kms FROM solar_wind_plasma WHERE ts_utc>=? AND speed_kms IS NOT NULL ORDER BY ts_utc",
                   (iso(NOW - timedelta(hours=24)),)).fetchall()
    d["speed_series"] = bin_series([(parse(a), b) for a, b in pl], 15)
    bzs = c.execute("SELECT AVG(bz_gsm) FROM solar_wind_mag WHERE ts_utc>=? AND bz_gsm IS NOT NULL",
                    (iso(NOW - timedelta(minutes=30)),)).fetchone()
    d["bz30"] = bzs[0] if bzs else None
    d["fetch"] = fetch_ok(c)
    c.close()
    return d


def bin_series(pts, minutes):
    out, b = {}, {}
    for t, v in pts:
        k = floor_to(t, minutes)
        b.setdefault(k, []).append(v)
    return sorted((k, sum(v) / len(v)) for k, v in b.items())


def floor_to(dt, minutes):
    s = int(dt.timestamp() // (minutes * 60) * (minutes * 60))
    return datetime.fromtimestamp(s, UTC)


def get_flare():
    c = ro("flare")
    d = {}
    r = c.execute("SELECT ts_utc,flux_long FROM xray_flux WHERE flux_long IS NOT NULL ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["ts"] = parse(r[0]) if r else None
    d["flux"] = r[1] if r else None
    rows = c.execute("SELECT ts_utc,flux_long FROM xray_flux WHERE ts_utc>=? AND flux_long IS NOT NULL ORDER BY ts_utc",
                     (iso(NOW - timedelta(hours=24)),)).fetchall()
    pts = [(parse(a), b) for a, b in rows]
    d["max24"] = max(pts, key=lambda x: x[1]) if pts else (None, None)
    # downsample to 10-minute maxima for the sparkline
    b = {}
    for t, v in pts:
        k = floor_to(t, 10)
        b[k] = max(b.get(k, 0), v)
    d["series"] = sorted(b.items())
    d["fetch"] = fetch_ok(c, "xrays-1-day.json") or fetch_ok(c)
    c.close()
    return d


def get_nav():
    d = {}
    c = ro("tec")
    t1 = NOW + timedelta(minutes=1)
    rows = tec_rows(c, NOW - timedelta(minutes=5, seconds=45), t1)
    c.close()
    last = (max(r[3] for r in rows),) if rows else None
    c30, c10 = iso(NOW - timedelta(seconds=30)), iso(NOW - timedelta(seconds=10))
    cl = [r[7] for r in rows if r[3] >= c30 and r[6] is not None and r[6] >= 20 and r[7] is not None]
    cn = (sum(cl) / len(cl), len(cl)) if cl else (None, 0)
    pairs = (len({r[0] for r in rows if r[3] >= c10}),)
    d["ts"] = parse(last[0]) if last else None
    cut = iso(NOW - timedelta(minutes=5))
    per = roti_per_sv([s for s in rot_samples(rows) if s[0] >= cut])
    d["per_sv"] = per
    d.update(net_stats(per))
    d["cno"], d["n_cno"] = cn if cn else (None, 0)
    d["pairs"] = pairs[0] if pairs else None
    return d


def get_timing():
    c = ro("timing")
    cols = ("ts_utc,status,fix_type,num_sv,t_acc_ns,p_dop,st_spoof_det,rf0_jam_ind,rf0_jam_state,"
            "rf0_ant_status,time_ok,no_valid_run_s,utc_valid")
    r = c.execute(f"SELECT {cols} FROM timing_1hz ORDER BY id DESC LIMIT 1").fetchone()
    d = dict(zip(cols.split(","), r)) if r else {}
    d["ts"] = parse(d.get("ts_utc"))
    h = c.execute("SELECT COUNT(*),SUM(time_ok) FROM timing_1hz WHERE ts_utc>=?", (iso(NOW - timedelta(hours=1)),)).fetchone()
    d["ok_hour"] = (100.0 * h[1] / h[0]) if h and h[0] else None
    c.close()
    return d


def get_leo():
    c = ro("leo")
    d = {}
    last = c.execute("SELECT ts_utc FROM history ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["ts"] = parse(last[0]) if last else None
    r = c.execute("SELECT ping_latency_ms,ping_drop_rate FROM history WHERE ts_utc>=?", (iso(NOW - timedelta(minutes=15)),)).fetchall()
    lat = [x[0] for x in r if x[0] is not None]
    d["lat"] = statistics.median(lat) if lat else None
    d["drop"] = 100.0 * statistics.mean([x[1] for x in r if x[1] is not None]) if r else None
    s = c.execute("SELECT ts_utc,state,fraction_obstructed FROM status_snapshot ORDER BY ts_utc DESC LIMIT 1").fetchone()
    d["state"], d["obstr"] = (s[1], s[2]) if s else (None, None)
    c.close()
    return d


WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers",
       81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
       95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}
WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


def get_weather():
    d = {}
    c = ro("wx")
    r = c.execute("SELECT ts_utc,temperature_c,humidity_pct,precipitation_mm,cloud_cover_pct,wind_speed_kmh,"
                  "wind_gusts_kmh,weather_code FROM weather_current ORDER BY ts_utc DESC LIMIT 1").fetchone()
    if r:
        d.update(ts=parse(r[0]), temp=r[1], hum=r[2], precip=r[3], cloud=r[4], wind=r[5], gust=r[6], code=r[7])
    d["fetch"] = fetch_ok(c)
    h = c.execute("SELECT ts_utc,precipitation_mm,temperature_c FROM weather_hourly WHERE ts_utc>=? ORDER BY ts_utc",
                  (iso(NOW - timedelta(hours=24)),)).fetchall()
    d["hourly"] = [(parse(a), b, t) for a, b, t in h]
    c.close()
    m = ro("metar")
    r = m.execute("SELECT ts_utc,icao,wx_string,is_precip,temp_c,wind_speed_kt,visibility FROM metar ORDER BY ts_utc DESC LIMIT 1").fetchone()
    if r:
        d["metar"] = dict(ts=parse(r[0]), icao=r[1], wx=r[2], precip=r[3], temp=r[4], wind_kt=r[5], vis=r[6])
    d["metar_fetch"] = fetch_ok(m)
    m.close()
    return d


# ---- SVG charts ---------------------------------------------------------------------
C_OK, C_WARN, C_BAD, C_STALE = "#3ddc97", "#ffb020", "#ff5d5d", "#7c8aa5"


def spark(series, ymin, ymax, color, lines=(), bars=False, w=300, h=64, log=False, fill=True):
    """series: [(datetime, value|None)] over the last 24 h; lines: [(y, colour)] dashed thresholds."""
    t0, t1 = NOW - timedelta(hours=24), NOW

    def X(t):
        return (t - t0).total_seconds() / 86400.0 * w

    def Y(v):
        if log:
            v = math.log10(max(v, 1e-12))
        f = (v - ymin) / (ymax - ymin)
        return h - 3 - max(0.0, min(1.0, f)) * (h - 6)
    out = [f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img">']
    for hh in range(0, 25, 6):                         # faint 6-hour grid
        x = hh / 24.0 * w
        out.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h}" stroke="#ffffff" stroke-opacity=".07"/>')
    for y, col in lines:
        yy = Y(y)
        out.append(f'<line x1="0" y1="{yy:.1f}" x2="{w}" y2="{yy:.1f}" stroke="{col}" stroke-width="1.5" '
                   f'stroke-dasharray="5 4" vector-effect="non-scaling-stroke" opacity=".9"/>')
    pts = [(t, v) for t, v in series if v is not None and t0 <= t <= t1 + timedelta(minutes=10)]
    if not pts:
        out.append(f'<text x="{w/2}" y="{h/2}" fill="#7c8aa5" font-size="12" text-anchor="middle">no data yet</text>')
    elif bars:
        bw = max(2.0, w * 3 * 3600 / 86400.0 - 3)
        for t, v in pts:
            x = X(t)
            col = v if isinstance(v, str) else color
            y = Y(v)
            out.append(f'<rect x="{x+1:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h-3-y:.1f}" rx="2" fill="{color(v) if callable(color) else color}"/>')
    else:
        segs, cur = [], []
        prev = None
        for t, v in pts:
            if prev is not None and (t - prev).total_seconds() > 1800:
                segs.append(cur)
                cur = []
            cur.append((X(t), Y(v)))
            prev = t
        segs.append(cur)
        for s in segs:
            if len(s) == 1:
                out.append(f'<circle cx="{s[0][0]:.1f}" cy="{s[0][1]:.1f}" r="2" fill="{color}"/>')
                continue
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in s)
            if fill:
                out.append(f'<path d="{d} L{s[-1][0]:.1f},{h} L{s[0][0]:.1f},{h} Z" fill="{color}" opacity=".16"/>')
            out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" '
                       f'vector-effect="non-scaling-stroke"/>')
        lx, ly = segs[-1][-1]
        out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="{color}" vector-effect="non-scaling-stroke"/>')
    out.append("</svg>")
    return "".join(out)


def kp_color(v):
    return C_BAD if v >= 6.67 else (C_WARN if v >= 4.67 else C_OK)


def kp_gauge(kp):
    W, H = 400, 74
    x = lambda v: 10 + v / 9.0 * 380
    o = [f'<svg class="gauge" viewBox="0 0 {W} {H}" role="img">']
    segs = [(0, 4.67, C_OK), (4.67, 6.67, C_WARN), (6.67, 9, C_BAD)]
    for a, b, col in segs:
        o.append(f'<rect x="{x(a):.1f}" y="30" width="{x(b)-x(a):.1f}" height="16" fill="{col}" opacity=".85"/>')
    o.append(f'<rect x="10" y="30" width="380" height="16" rx="8" fill="none" stroke="#0b1226" stroke-width="3"/>')
    # his threshold band + marker
    o.append(f'<rect x="{x(KP_CI[0]):.1f}" y="26" width="{x(KP_CI[1])-x(KP_CI[0]):.1f}" height="24" fill="#fff" opacity=".35"/>')
    o.append(f'<line x1="{x(KP_THRESHOLD):.1f}" y1="22" x2="{x(KP_THRESHOLD):.1f}" y2="54" stroke="#fff" stroke-width="3"/>')
    o.append(f'<text x="394" y="15" fill="#fff" font-size="13" font-weight="700" text-anchor="end">'
             f'GPS trouble starts ≈ Kp {KP_THRESHOLD}</text>')
    for v in range(0, 10):
        o.append(f'<text x="{x(v):.1f}" y="68" fill="#9fb0d0" font-size="12" text-anchor="middle">{v}</text>')
    if kp is not None:
        px = x(max(0, min(9, kp)))
        o.append(f'<path d="M{px:.1f},48 l-9,-17 h18 z" fill="#fff" stroke="#0b1226" stroke-width="2"/>')
    o.append("</svg>")
    return "".join(o)


# ---- tiles ------------------------------------------------------------------------------
LEVELS = {"ok": ("t-ok", None), "warn": ("t-warn", None), "bad": ("t-bad", None), "stale": ("t-stale", "NO DATA")}


def tile(title, badge, level, chip, big, unit, subs, viz, cap, mean, stale_note=None):
    cls = LEVELS[level][0]
    subs_html = "".join(f"<div>{s}</div>" for s in subs if s)
    stale = f'<div class="stalenote">⚠ {escape(stale_note)}</div>' if stale_note else ""
    return f"""<section class="tile {cls}">
<div class="th"><h2>{title}</h2><span class="chip">{escape(chip)}</span></div>
<div class="src">{badge}</div>
<div class="big">{big}<span class="unit">{unit}</span></div>
<div class="sub">{subs_html}</div>{stale}
<div class="viz">{viz}</div>
<div class="cap">{cap}</div>
<p class="mean"><b>What this means:</b> {mean}</p>
</section>"""


SPACE_BADGE = "Space agency data"
OWN_BADGE = "Measured by our equipment"


def build(snapshot=False):
    t_start = time.process_time()
    errs, stale = {}, []
    # history first (so tiles can use the 24 h series)
    hres, e = safe(update_history, 12 if not BACKFILL else 400)
    if e:
        errs["history"] = e
    hseries = hres[1] if hres else []
    typ, e = safe(typical_roti)
    typ = typ or {}

    sp, e = safe(get_space)
    errs.update({"space": e} if e else {})
    fl, e = safe(get_flare)
    errs.update({"flare": e} if e else {})
    nav, e = safe(get_nav)
    errs.update({"nav": e} if e else {})
    tm, e = safe(get_timing)
    errs.update({"timing": e} if e else {})
    leo, e = safe(get_leo)
    errs.update({"leo": e} if e else {})
    wx, e = safe(get_weather)
    errs.update({"weather": e} if e else {})

    def parse_series(idx):
        return [(parse(r[0]), r[idx]) for r in hseries]

    tiles, worst = [], 0   # worst: 0 ok, 1 warn, 2 bad
    details = {}

    def lvl_num(l):
        return {"ok": 0, "warn": 1, "bad": 2}.get(l, 0)

    def check(name, ts, limit_min, fetch=None):
        """Staleness: use the most recent of the data timestamp and the last successful fetch."""
        best = max([t for t in (ts, fetch) if t is not None], default=None)
        a = age_min(best)
        if a is None:
            stale.append(f"{name}: no data")
            return f"no data for {name}"
        if a > limit_min:
            stale.append(f"{name}: last data {fmt_age(a)} ago")
            return f"last data {fmt_age(a)} ago"
        return None

    # 1. Storm level (Kp) -----------------------------------------------------------------
    kp_level, kp_word, kp_chip = "stale", "No data", "NO DATA"
    if sp and sp.get("kp") is not None:
        kp = sp["kp"]
        g = g_scale(kp)
        kp_level = "bad" if kp >= 6.67 else ("warn" if kp >= 4.67 else "ok")
        kp_word = ("Quiet" if kp < 3.67 else "Unsettled" if kp < 4.67 else "Minor storm" if kp < 6.67 else "Strong storm")
        kp_chip = {"ok": "QUIET" if kp < 3.67 else "UNSETTLED", "warn": "STORM", "bad": "STRONG STORM"}[kp_level]
        sn = check("Kp", None, 60, sp.get("kp_fetch"))
        gtxt = f"Storm scale G{g}" if g else "No storm (scale G0)"
        w0 = sp["kp_ts"]
        pk = max([v for t, v in sp["kp_series"] if t >= NOW - timedelta(hours=24)] or [kp])
        sub = [f"{gtxt} · {uk(w0)}–{uk(w0 + timedelta(hours=3))} UK",
               f"24 h peak: Kp {pk:.1f} · 10 Oct storm: Kp {STORM_KP_10OCT}"]
        series = [(t, v) for t, v in sp["kp_series"]]
        viz = kp_gauge(kp)
        tiles.append(tile("Storm level (Kp)", SPACE_BADGE, kp_level, kp_chip, fmt(kp, 1), "Kp", sub, viz,
                          "White marker = our GPS-trouble threshold (95 % range 7.4–8.0)",
                          "A 0–9 score for how disturbed Earth's magnetic field is. Our data say navigation suffers near 7.7.", sn))
    else:
        tiles.append(tile("Storm level (Kp)", SPACE_BADGE, "stale", "NO DATA", "–", "Kp", [], kp_gauge(None), "",
                          "Kp is a 0–9 score for how disturbed Earth's magnetic field is.", "no Kp data"))
        stale.append("Kp: no data")
    worst = max(worst, lvl_num(kp_level))
    details["kp"] = sp.get("kp") if sp else None

    # 2. Solar wind --------------------------------------------------------------------------
    if sp and sp.get("speed") is not None:
        sp_s, bz = sp["speed"], sp.get("bz")
        lv = "ok"
        if sp_s >= 600 or (bz is not None and bz <= -10):
            lv = "bad"
        elif sp_s >= 450 or (bz is not None and bz <= -5):
            lv = "warn"
        sn = check("Solar wind", sp["sw_ts"], 40, sp.get("fetch"))
        word = {"ok": "CALM", "warn": "FAST / ACTIVE", "bad": "VERY FAST"}[lv]
        sub = [f"Magnetic field Bz: <b>{fmt(bz, 1).replace('-', '−')} nT</b> " + ("(southward: strong link)" if bz is not None and bz < -5 else
                                                              "(weak link to Earth)" if bz is not None and bz > -2 else "(slight link)"),
               f"Density: {fmt(sp.get('density'), 1)} particles per cm³"]
        tiles.append(tile("Solar wind", SPACE_BADGE, lv, word, f"{sp_s:.0f}", "km/s", sub,
                          spark(sp["speed_series"], 250, 800, C_OK if lv == "ok" else C_WARN if lv == "warn" else C_BAD,
                                lines=[(500, "#ffb020")]),
                          "Last 24 hours · dashed line = 500 km/s (fast)",
                          "The Sun's stream of charged particles, seen by a spacecraft 1.5 million km sunward. Fast wind with negative Bz builds storms.", sn))
        worst = max(worst, 0)
    else:
        tiles.append(tile("Solar wind", SPACE_BADGE, "stale", "NO DATA", "–", "km/s", [], spark([], 0, 1, C_STALE), "",
                          "The Sun's stream of charged particles.", "no solar-wind data"))
        stale.append("Solar wind: no data")

    # 3. Flares ----------------------------------------------------------------------------------
    fl_level = "stale"
    if fl and fl.get("flux") is not None:
        cls, letter = flare_class(fl["flux"])
        mx_cls, mx_letter = flare_class(fl["max24"][1])
        fl_level = {"X": "bad", "M": "warn"}.get(letter, "ok")
        peak_level = {"X": 2, "M": 1}.get(mx_letter, 0)
        worst = max(worst, {"bad": 2, "warn": 1, "ok": 0}[fl_level])
        sn = check("X-ray flares", fl["ts"], 20, fl.get("fetch"))
        mx_t = fl["max24"][0]
        word = {"bad": "MAJOR FLARE", "warn": "FLARE", "ok": "NO BIG FLARE" if mx_letter in ("A", "B", "C") else "QUIET"}[fl_level]
        sub = [f"Strongest in last 24 h: <b>{mx_cls}</b> at {uk(mx_t)} UK" if mx_t else "",
               "Scale: A, B, C small · M strong · X extreme"]
        tiles.append(tile("Solar flares", SPACE_BADGE, fl_level, word, cls, "now", sub,
                          spark([(t, v) for t, v in fl["series"]], -8, -3.5, C_OK if fl_level == "ok" else C_WARN if fl_level == "warn" else C_BAD,
                                lines=[(1e-6, "#8aa0c8"), (1e-5, "#ffb020")], log=True),
                          "Last 24 hours of X-rays (log scale) · dashed lines = C and M class",
                          "A burst of X-rays from the Sun. Strong ones can briefly disturb radio and GPS on the sunlit side of Earth.", sn))
    else:
        tiles.append(tile("Solar flares", SPACE_BADGE, "stale", "NO DATA", "–", "", [], spark([], 0, 1, C_STALE), "",
                          "A flare is a burst of X-rays from the Sun.", "no flare data"))
        stale.append("Flares: no data")

    # 4. Ionosphere ripples (ROTI) ------------------------------------------------------------
    roti_level = "stale"
    uk_hour = NOW.hour
    typ_now = typ.get(uk_hour)
    if nav and nav.get("n", 0) >= 1:
        r2 = nav["r2"] if nav["r2"] is not None else nav["rmax"]
        roti_level = "bad" if nav["n_dist"] >= 2 else ("warn" if (r2 is not None and r2 >= 0.3) or nav["n_dist"] == 1 else "ok")
        worst = max(worst, {"bad": 2, "warn": 1, "ok": 0}[roti_level])
        sn = check("Receiver (ROTI)", nav["ts"], 5)
        word = {"ok": "CALM", "warn": "RIPPLING", "bad": "DISTURBED"}[roti_level]
        sub = [f"<b>{nav['n_dist']} of {nav['n']}</b> satellites above the {ROTI_DISTURBED} 'disturbed' line",
               f"Usual at this time of day: {fmt(typ_now, 2)}" if typ_now is not None else ""]
        tiles.append(tile("Ionosphere ripples (ROTI)", OWN_BADGE, roti_level, word, fmt(r2, 2), "TECU/min", sub,
                          spark(parse_series(1), 0, 1.0, C_OK if roti_level == "ok" else C_WARN if roti_level == "warn" else C_BAD,
                                lines=[(ROTI_DISTURBED, "#ff5d5d")]),
                          "Last 24 hours · red dashed line = 0.5 (disturbed)",
                          "How bumpy the ionosphere (Earth's charged upper layer) is. ROTI = Rate Of TEC Index; above 0.5 counts as disturbed.", sn))
    else:
        tiles.append(tile("Ionosphere ripples (ROTI)", OWN_BADGE, "stale", "NO DATA", "–", "TECU/min", [],
                          spark(parse_series(1), 0, 1, C_STALE, lines=[(ROTI_DISTURBED, "#ff5d5d")]), "",
                          "ROTI (Rate Of TEC Index) says how bumpy the ionosphere is.", "no satellite data"))
        stale.append("Receiver: no data")

    # 5. Satellite navigation health ---------------------------------------------------------------
    if nav and tm and tm.get("num_sv") is not None:
        nsv = tm["num_sv"]
        cno = nav.get("cno")
        lv = "ok"
        if nsv < 8 or (cno is not None and cno < 35):
            lv = "warn"
        if nsv < 4:
            lv = "bad"
        if nav.get("n", 0) and nav["n_dist"] >= 2:
            lv = "bad" if lv != "bad" else lv
        sn = check("Navigation receiver", tm["ts"], 5)
        word = {"ok": "HEALTHY", "warn": "WEAKER", "bad": "DEGRADED"}[lv]
        sig = ("strong" if cno is not None and cno >= 42 else "good" if cno is not None and cno >= 38 else "weak")
        sub = [f"Signal strength: <b>{fmt(cno, 0)} dB-Hz</b> ({sig})" if cno is not None else "",
               f"{nav.get('pairs') if nav.get('pairs') is not None else '–'} measured on two frequencies (for ionosphere)"]
        tiles.append(tile("Satellite navigation, Belfast", OWN_BADGE, lv, word, str(nsv), "satellites tracked", sub,
                          spark(parse_series(6), 30, 55, C_OK if lv == "ok" else C_WARN, fill=True),
                          "Signal strength, last 24 hours (higher is better)",
                          "How many navigation satellites our receiver uses and how strong their signals are. Fewer or weaker would signal trouble.", sn))
        worst = max(worst, 0)
    else:
        tiles.append(tile("Satellite navigation, Belfast", OWN_BADGE, "stale", "NO DATA", "–", "satellites tracked", [],
                          spark([], 0, 1, C_STALE), "", "How many navigation satellites our receiver is using.", "no receiver data"))
        stale.append("Navigation receiver: no data")

    # 6. LEO broadband -----------------------------------------------------------------------------------
    if leo and leo.get("lat") is not None:
        lat, drop = leo["lat"], leo.get("drop")
        lv = "ok"
        if (drop is not None and drop >= 2) or lat > 80 or (leo.get("state") not in (None, "CONNECTED")):
            lv = "warn"
        if (drop is not None and drop >= 10) or lat > 200:
            lv = "bad"
        sn = check("Satellite broadband", leo["ts"], 12)
        word = {"ok": "WORKING WELL", "warn": "DEGRADED", "bad": "BADLY AFFECTED"}[lv]
        latser = [(t, v) for t, v in parse_series(10)]
        sub = [f"Connection lost: <b>{fmt(drop, 1)} %</b> of the last 15 minutes",
               f"Link state: {(leo.get('state') or '–').title()}"]
        tiles.append(tile("LEO satellite broadband", OWN_BADGE, lv, word, fmt(lat, 0), "ms delay", sub,
                          spark(latser, 15, 80, C_OK if lv == "ok" else C_WARN if lv == "warn" else C_BAD,
                                lines=[(50, "#8aa0c8")]),
                          "Delay (latency), last 24 hours · lower is better",
                          "A home dish talking to low-Earth-orbit (LEO) satellites. A storm could slow it or drop the link.", sn))
    else:
        tiles.append(tile("LEO satellite broadband", OWN_BADGE, "stale", "NO DATA", "–", "ms delay", [], spark([], 0, 1, C_STALE), "",
                          "A home internet dish talking to low-Earth-orbit (LEO) satellites.", "no broadband data"))
        stale.append("Satellite broadband: no data")

    # 7. Timing receiver ----------------------------------------------------------------------------------
    if tm and tm.get("t_acc_ns") is not None:
        ok = bool(tm.get("time_ok")) and tm.get("status") == "ok"
        spoof = tm.get("st_spoof_det")
        jam = tm.get("rf0_jam_state") or 0
        lv = "ok"
        if (tm["t_acc_ns"] > 200) or jam >= 2 or spoof in (2, 3):
            lv = "warn"
        if not ok:
            lv = "bad"
        sn = check("Timing receiver", tm["ts"], 5)
        word = {"ok": "LOCKED", "warn": "CHECK", "bad": "TIME LOST"}[lv]
        spoof_txt = {0: "unknown", 1: "none detected", 2: "possible!", 3: "detected!"}.get(spoof, "–")
        sub = ["Clock locked to satellite time" if ok else "Clock NOT locked to satellite time",
               f"Interference: {'none' if jam < 1 else 'warning' if jam == 1 else 'critical'} · fake signals: {spoof_txt}",
               f"Valid {fmt(tm.get('ok_hour'), 1)} % of the last hour" if tm.get("ok_hour") is not None else ""]
        tiles.append(tile("Satellite timing", OWN_BADGE, lv, word, f"{tm['t_acc_ns']:.0f}", "ns clock accuracy", sub,
                          spark(parse_series(7), 0, 150, C_OK if lv == "ok" else C_WARN if lv == "warn" else C_BAD),
                          "Accuracy estimate in ns (nanoseconds, billionths of a second), last 24 hours · lower is better",
                          "Phone masts, banks and power grids set their clocks from satellites. This shows our receiver still has trustworthy time.", sn))
    else:
        tiles.append(tile("Satellite timing", OWN_BADGE, "stale", "NO DATA", "–", "", [], spark([], 0, 1, C_STALE), "",
                          "Phone masts and power grids set their clocks from satellites.", "no timing data"))
        stale.append("Timing receiver: no data")

    # 8. Local weather ----------------------------------------------------------------------------------------
    if wx and wx.get("temp") is not None:
        mt = wx.get("metar")
        raining = (wx.get("code") in WET) or (wx.get("precip") or 0) > 0.05
        if mt and age_min(mt["ts"]) is not None and age_min(mt["ts"]) < 100 and mt.get("precip"):
            raining = True
        lv = "warn" if raining else "ok"
        sn = check("Weather", wx["ts"], 60, wx.get("fetch"))
        desc = WMO.get(wx.get("code"), "–")
        word = "RAINING" if raining else "DRY"
        wind_mph = (wx["wind"] or 0) * 0.621371
        sub = [f"{desc} · cloud cover {fmt(wx.get('cloud'), 0)} %",
               f"Wind {wind_mph:.0f} mph · rain now {fmt(wx.get('precip'), 1)} mm"]
        hourly = [(t, p) for t, p, _ in wx["hourly"]]
        tiles.append(tile("Local weather", "Weather service + airport reports", lv, word, f"{wx['temp']:.0f}", "°C", sub,
                          spark(hourly, 0, max(2.0, max([p for _, p in hourly if p is not None] or [2.0])), "#5aa9ff", bars=True, h=64),
                          "Rain per hour, last 24 hours",
                          "Heavy rain can weaken satellite signals, so we check it is not the cause of anything unusual.", sn))
    else:
        tiles.append(tile("Local weather", "Weather service", "stale", "NO DATA", "–", "°C", [], spark([], 0, 1, C_STALE), "",
                          "Heavy rain can weaken satellite signals.", "no weather data"))
        stale.append("Weather: no data")

    # headline ------------------------------------------------------------------------------------------------
    if kp_level == "stale":
        head_cls, head_word = "t-stale", "Unknown"
    else:
        head_cls = {0: "t-ok", 1: "t-warn", 2: "t-bad"}[worst]
        head_word = kp_word
        if worst == 2 and kp_level != "bad":
            head_word = "Disturbed"
        elif worst == 1 and kp_level == "ok":
            head_word = "Active"
    if nav and nav.get("n", 0) >= 1:
        if nav["n_dist"] >= 2:
            line2 = f"Our Belfast receiver is seeing a <b>disturbed ionosphere</b>: {nav['n_dist']} of {nav['n']} satellites affected."
        elif roti_level == "warn":
            line2 = "Our Belfast receiver sees a slightly <b>rippling</b> ionosphere, below the disturbed line."
        else:
            line2 = f"Our Belfast receiver sees a <b>calm ionosphere</b>: {nav['n_dist']} of {nav['n']} satellites disturbed."
    else:
        line2 = "Our Belfast receiver has no recent ionosphere reading."
    kp_txt = f"Kp {sp['kp']:.1f}" if sp and sp.get("kp") is not None else "Kp unknown"
    line1 = (f"{kp_txt} on the 0–9 scale. Our measurements say satellite navigation starts to be disturbed at about "
             f"<b>Kp {KP_THRESHOLD}</b>.")

    gen = NOW
    data = dict(generated_utc=gen.isoformat(timespec="seconds"), generated_uk=uk(gen, "%d %b %Y %H:%M"),
                headline=head_word, kp=sp.get("kp") if sp else None, roti=nav.get("r2") if nav else None,
                sats_tracked=tm.get("num_sv") if tm else None, n_disturbed=nav.get("n_dist") if nav else None,
                leo_latency_ms=leo.get("lat") if leo else None, leo_drop_pct=leo.get("drop") if leo else None,
                timing_acc_ns=tm.get("t_acc_ns") if tm else None, stale=stale, errors=errs)
    data["cpu_seconds"] = round(time.process_time() - t_start, 3)
    page = render_page(head_cls, head_word, line1, line2, tiles, stale, gen, snapshot)
    return page, data


def fmt_age(m):
    if m < 90:
        return f"{m:.0f} min"
    if m < 60 * 36:
        return f"{m/60:.1f} h"
    return f"{m/1440:.1f} days"


# ---- page ---------------------------------------------------------------------------------------------------
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:radial-gradient(1200px 700px at 80% -10%,#1a2a5e 0%,#0a1024 55%,#060914 100%);color:#e8eefc;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;display:flex;flex-direction:column;
padding:clamp(8px,1.1vw,18px);gap:clamp(8px,.9vw,14px);overflow-x:hidden;min-height:100vh}
header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}
.title h1{font-size:clamp(16px,1.65vw,28px);font-weight:700;letter-spacing:.2px}
.title p{font-size:clamp(11px,.95vw,15px);color:#9fb0d0;margin-top:2px}
.clock{text-align:right;font-size:clamp(12px,1.05vw,17px);color:#cfd9f5}
.clock b{font-size:clamp(14px,1.3vw,22px);color:#fff}
.clock small{display:block;color:#7f90b3;font-size:clamp(10px,.8vw,13px)}
.banner{display:flex;align-items:center;gap:clamp(12px,1.6vw,26px);padding:clamp(6px,1.2vh,16px) clamp(14px,1.6vw,26px);border-radius:18px;
background:linear-gradient(90deg,color-mix(in srgb,var(--c) 28%,#0d1630) 0%,#0d1630 70%);border:2px solid var(--c);box-shadow:0 0 28px color-mix(in srgb,var(--c) 30%,transparent)}
.banner .dot{width:clamp(26px,min(3vw,5vh),50px);height:clamp(26px,min(3vw,5vh),50px);border-radius:50%;background:var(--c);box-shadow:0 0 22px var(--c);flex:none}
.banner .lead{font-size:clamp(11px,.9vw,14px);text-transform:uppercase;letter-spacing:2px;color:#b7c6e6}
.banner .word{font-size:clamp(26px,min(3.6vw,6.4vh),60px);font-weight:800;line-height:1.05;color:var(--c)}
.banner .txt{font-size:clamp(13px,1.3vw,21px);line-height:1.35;color:#e8eefc;margin-left:auto;max-width:56%}
.banner .txt div+div{margin-top:3px;color:#c9d6f3}
.grid{flex:1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:minmax(max-content,1fr);gap:clamp(8px,.9vw,14px)}
.tile{--c:#7c8aa5;position:relative;background:linear-gradient(180deg,#121c3b 0%,#0e1631 100%);border:1px solid #243257;border-top:5px solid var(--c);
border-radius:16px;padding:clamp(6px,1vh,12px) clamp(10px,1vw,16px);display:flex;flex-direction:column}
.t-ok{--c:#3ddc97}.t-warn{--c:#ffb020}.t-bad{--c:#ff5d5d}.t-stale{--c:#7c8aa5}
.th{display:flex;align-items:center;justify-content:space-between;gap:8px}
.th h2{font-size:clamp(13px,1.2vw,20px);font-weight:700;color:#fff}
.chip{font-size:clamp(10px,.8vw,13px);font-weight:800;letter-spacing:.8px;color:#08101f;background:var(--c);padding:3px 9px;border-radius:99px;white-space:nowrap}
.src{font-size:clamp(9px,.7vw,11px);color:#7f90b3;text-transform:uppercase;letter-spacing:1px;margin-top:1px}
.big{font-size:clamp(30px,min(3.9vw,6.8vh),64px);font-weight:800;line-height:1.05;color:var(--c);margin-top:clamp(0px,.4vh,6px);white-space:nowrap}
.unit{font-size:clamp(12px,1.1vw,18px);font-weight:600;color:#9fb0d0;margin-left:8px}
.sub{font-size:clamp(11px,.95vw,15px);color:#cfd9f5;line-height:1.35;margin-top:2px}
.sub b{color:#fff}
.stalenote{font-size:clamp(11px,.9vw,14px);color:#ffb020;font-weight:700;margin-top:3px}
.viz{margin-top:auto;padding-top:6px}
.spark,.gauge{width:100%;display:block}
.spark{height:clamp(32px,6.4vh,72px);background:#0a1126;border-radius:8px}
.gauge{height:clamp(50px,8.5vh,92px);margin-bottom:2px}
.cap{font-size:clamp(9px,.72vw,11.5px);color:#7f90b3;margin-top:3px}
.mean{font-size:clamp(11px,.9vw,14px);line-height:1.28;color:#b9c7e6;margin-top:4px;padding-top:4px;border-top:1px solid #243257}
.mean b{color:#fff}
footer{font-size:clamp(10px,.8vw,13px);color:#8393b6;line-height:1.45;display:flex;gap:18px;justify-content:space-between;align-items:flex-start}
footer .key b{color:#b9c7e6}
.warnbox{color:#ffb020;font-weight:700}
.okbox{color:#3ddc97}
#old{display:none;background:#ff5d5d;color:#1a0505;font-weight:800;text-align:center;padding:8px;border-radius:10px;font-size:clamp(13px,1.2vw,18px)}
.snap{background:#ffb020;color:#241600;font-weight:800;text-align:center;padding:8px;border-radius:10px;font-size:clamp(13px,1.2vw,18px)}
@media (max-width:1100px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:auto}.tile{min-height:340px}.banner{flex-wrap:wrap}.banner .txt{max-width:100%;margin-left:0}}
@media (max-width:600px){.grid{grid-template-columns:1fr}}
"""

JS = """
var GEN=%(gen)d*1000;
function tick(){var a=(Date.now()-GEN)/60000;var e=document.getElementById('age');
if(e){e.textContent=a<1?'just now':(a<90?Math.round(a)+' min ago':(a/60).toFixed(1)+' h ago');}
var o=document.getElementById('old');if(o){o.style.display=a>6?'block':'none';
o.textContent='⚠ This page has not updated for '+Math.round(a)+' minutes – the live feed or the connection may be down. Figures below may be out of date.';}}
tick();setInterval(tick,5000);
%(reload)s
"""


def render_page(head_cls, head_word, line1, line2, tiles, stale, gen, snapshot):
    if stale:
        st = '<span class="warnbox">⚠ Delayed or missing data: ' + escape("; ".join(stale)) + ".</span>"
    else:
        st = '<span class="okbox">✔ Every data feed is up to date.</span>'
    reload_js = "" if snapshot else "setTimeout(function(){location.reload()},60000);"
    meta_refresh = "" if snapshot else '<meta http-equiv="refresh" content="75">'
    snap_banner = (f'<div class="snap">SAVED SNAPSHOT from {uk(gen, "%d %b %Y, %H:%M")} (UK time) – not live. '
                   f'Opened later, these figures are out of date. <a href="index.html" style="color:#241600">← Back to the demo menu</a></div>') if snapshot else ""
    old = "" if snapshot else '<div id="old"></div>'
    updated = uk(gen, "%H:%M")
    date = uk(gen, "%A %d %B %Y")
    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">{meta_refresh}
<title>Space weather now: {escape(head_word)} – live feed</title>
<style>{CSS}</style></head><body>
{snap_banner}{old}
<header>
<div class="title"><h1>A Single Point of Failure in the Sky</h1>
<p>Live feed: space weather and what it does to satellite navigation and satellite broadband · Belfast</p></div>
<div class="clock"><b>Last updated {updated} (UK time)</b><small>{date} · <span id="age"></span> · {'saved copy, not updating' if snapshot else 'refreshes every minute'}</small></div>
</header>
<div class="banner {head_cls}" style="--c:var(--hc)">
<div class="dot"></div>
<div><div class="lead">Space weather now</div><div class="word">{escape(head_word)}</div></div>
<div class="txt"><div>{line1}</div><div>{line2}</div></div>
</div>
<main class="grid">
{''.join(tiles)}
</main>
<footer>
<div class="key"><b>Key:</b> Kp = planetary K-index (0–9, how disturbed Earth's magnetic field is) ·
TEC = Total Electron Content · ROTI = Rate Of TEC Index, in TECU/min (TEC units per minute) · dB-Hz = signal strength ·
ns = nanoseconds (billionths of a second) · LEO = low Earth orbit · GPS = Global Positioning System ·
Bz = north–south direction of the Sun's magnetic field at Earth · All times UK.</div>
<div style="text-align:right;white-space:nowrap">{st}</div>
</footer>
<script>{JS % dict(gen=int(gen.timestamp()), reload=reload_js)}</script>
</body></html>"""


BACKFILL = "--backfill" in sys.argv


def main():
    snapshot = "--snapshot" in sys.argv
    page, data = build(snapshot=snapshot)
    # the banner takes its colour from its own class
    page = page.replace('style="--c:var(--hc)"', "")
    if snapshot:
        sys.stdout.write(page)
        return
    os.makedirs(WWW, exist_ok=True)
    data["cpu_seconds"] = round(time.process_time(), 3)
    for name, content in (("index.html", page), ("data.json", json.dumps(data, indent=1, default=str))):
        tmp = os.path.join(WWW, "." + name + ".tmp")
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, os.path.join(WWW, name))
    if BACKFILL or "--verbose" in sys.argv:
        print(json.dumps(data, indent=1, default=str))


if __name__ == "__main__":
    main()
