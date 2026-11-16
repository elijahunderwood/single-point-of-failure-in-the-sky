#!/usr/bin/env python3
"""
Combined analysis: weather + space weather vs Starlink + GNSS
=============================================================

Fuses all the station's databases into one hourly table, then answers the
attribution question: when the Starlink link or the ionosphere degrades, what
was happening -- rain, geomagnetic activity, both, or neither?

Inputs (defaults match the station's layout):
  * starlink_history.db  -- per-second link quality (latency, drop rate)
  * spaceweather.db      -- Kp, IMF Bz, solar wind speed
  * localweather.db      -- hourly rainfall (mm) at the dish (Open-Meteo)
  * metar.db             -- observed rain at EGAA (cross-check)
  * roti(.db)            -- robust ionospheric turbulence index
                            (run compute_roti with --mask 30 first)

Output:
  * combined.db, table `hourly` -- one row per hour with everything aligned
  * printed analyses: rain buckets, Kp buckets, worst-hours attribution
  * optional CSV for plotting

Standard library only; all inputs opened read-only.
"""

import argparse
import os
import sqlite3
import statistics
import sys

H = 13  # length of 'YYYY-MM-DDTHH'


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def load_starlink(path):
    """hour -> (avg_latency_ms, drop_pct, seconds)"""
    out = {}
    with ro(path) as c:
        for hour, lat, drop, n in c.execute(
                f"SELECT substr(ts_utc,1,{H}), AVG(ping_latency_ms), "
                f"AVG(ping_drop_rate)*100, COUNT(*) FROM history GROUP BY 1"):
            out[hour] = (lat, drop, n)
    return out


def load_spaceweather(path):
    """Returns (kp_by_3h_window, hour -> (bz_min, sw_speed_avg))."""
    kp = {}
    sw = {}
    with ro(path) as c:
        for ts, k in c.execute("SELECT ts_utc, kp FROM kp_index"):
            kp[ts[:H]] = k                       # keyed by the 3-h window start hour
        rows = {}
        for hour, bz in c.execute(
                f"SELECT substr(ts_utc,1,{H}), MIN(bz_gsm) FROM solar_wind_mag GROUP BY 1"):
            rows[hour] = [bz, None]
        for hour, v in c.execute(
                f"SELECT substr(ts_utc,1,{H}), AVG(speed_kms) FROM solar_wind_plasma GROUP BY 1"):
            rows.setdefault(hour, [None, None])[1] = v
        sw = rows
    return kp, sw


def kp_for_hour(kp, hour):
    """Map an hour to its covering 3-h Kp window (00,03,06,...)."""
    date, hh = hour.split("T")
    wh = (int(hh) // 3) * 3
    return kp.get(f"{date}T{wh:02d}")


def load_rain(path):
    """hour -> precipitation_mm (model, at the dish)."""
    out = {}
    with ro(path) as c:
        for ts, mm in c.execute("SELECT ts_utc, precipitation_mm FROM weather_hourly"):
            out[ts[:H]] = mm
    return out


def load_metar(path):
    """hour -> (any_rain 0/1, max intensity text)."""
    rank = {None: 0, "light": 1, "moderate": 2, "heavy": 3}
    inv = {0: None, 1: "light", 2: "moderate", 3: "heavy"}
    out = {}
    with ro(path) as c:
        for ts, is_rain, inten in c.execute("SELECT ts_utc, is_rain, intensity FROM metar"):
            h = ts[:H]
            prev = out.get(h, (0, 0))
            out[h] = (max(prev[0], is_rain or 0), max(prev[1], rank.get(inten, 0)))
    return {h: (r, inv[i]) for h, (r, i) in out.items()}


def load_roti(path):
    """hour -> (avg roti_2nd, max roti_2nd, windows)."""
    out = {}
    with ro(path) as c:
        for hour, avg2, mx2, n in c.execute(
                f"SELECT substr(window_start,1,{H}), AVG(roti_2nd), MAX(roti_2nd), COUNT(*) "
                f"FROM roti_network WHERE roti_2nd IS NOT NULL GROUP BY 1"):
            out[hour] = (avg2, mx2, n)
    return out


def rain_bucket(mm, metar_rain):
    if (mm is None or mm <= 0.05) and not metar_rain:
        return "dry"
    if mm is None:
        return "rain (obs only)"
    if mm < 1.0:
        return "light (<1mm)"
    if mm < 4.0:
        return "moderate (1-4mm)"
    return "heavy (>=4mm)"


def kp_bucket(kp):
    if kp is None:
        return None
    if kp < 2.0:
        return "quiet (Kp<2)"
    if kp < 4.0:
        return "unsettled (2-4)"
    return "active (Kp>=4)"


def fmt(v, spec=".2f", none="-"):
    return format(v, spec) if v is not None else none


def bucket_table(rows, key_fn, title, order):
    """Aggregate hourly rows by a bucket function and print a table."""
    agg = {}
    for r in rows:
        b = key_fn(r)
        if b is None:
            continue
        agg.setdefault(b, []).append(r)
    print(f"\n== {title} ==")
    print(f"{'bucket':<18}{'hours':>6}{'latency':>9}{'drop%':>8}{'roti_avg':>10}{'roti_max':>10}")
    for b in order:
        if b not in agg:
            continue
        rs = agg[b]
        lat = [r['latency'] for r in rs if r['latency'] is not None]
        drp = [r['drop_pct'] for r in rs if r['drop_pct'] is not None]
        ra = [r['roti_avg'] for r in rs if r['roti_avg'] is not None]
        rm = [r['roti_max'] for r in rs if r['roti_max'] is not None]
        print(f"{b:<18}{len(rs):>6}"
              f"{fmt(statistics.mean(lat) if lat else None, '.1f'):>9}"
              f"{fmt(statistics.mean(drp) if drp else None, '.3f'):>8}"
              f"{fmt(statistics.mean(ra) if ra else None, '.3f'):>10}"
              f"{fmt(max(rm) if rm else None, '.3f'):>10}")


def main():
    home = os.path.expanduser("~")
    p = argparse.ArgumentParser(description="Combined weather/space-weather vs Starlink/GNSS analysis.")
    p.add_argument("--starlink", default=f"{home}/starlink-logger/starlink_history.db")
    p.add_argument("--spaceweather", default=f"{home}/spaceweather-logger/spaceweather.db")
    p.add_argument("--weather", default=f"{home}/weather-logger/localweather.db")
    p.add_argument("--metar", default=f"{home}/weather-logger/metar.db")
    p.add_argument("--roti", default=f"{home}/gnss-logger/roti30.db",
                   help="Output of compute_roti (use the --mask 30 run)")
    p.add_argument("--out", default=f"{home}/combined.db")
    p.add_argument("--csv", help="Optional CSV of the hourly table")
    p.add_argument("--worst", type=int, default=10, help="How many worst Starlink hours to attribute")
    args = p.parse_args()

    sl = load_starlink(args.starlink)
    kp, sw = load_spaceweather(args.spaceweather)
    rain = load_rain(args.weather)
    metar = load_metar(args.metar)
    roti = load_roti(args.roti)

    hours = sorted(set(sl) | set(roti))          # analysis needs at least one outcome stream
    rows = []
    for h in hours:
        s = sl.get(h)
        r = roti.get(h)
        w = sw.get(h, (None, None))
        m = metar.get(h, (0, None))
        rows.append({
            "hour": h,
            "rain_mm": rain.get(h),
            "metar_rain": m[0], "metar_intensity": m[1],
            "kp": kp_for_hour(kp, h),
            "bz_min": w[0], "sw_speed": w[1],
            "latency": s[0] if s else None,
            "drop_pct": s[1] if s else None,
            "sl_seconds": s[2] if s else None,
            "roti_avg": r[0] if r else None,
            "roti_max": r[1] if r else None,
        })

    # ---- write combined.db ----
    out = sqlite3.connect(args.out, timeout=30)
    out.executescript("""
        DROP TABLE IF EXISTS hourly;
        CREATE TABLE hourly (
            hour TEXT PRIMARY KEY, rain_mm REAL, metar_rain INTEGER,
            metar_intensity TEXT, kp REAL, bz_min REAL, sw_speed REAL,
            latency_ms REAL, drop_pct REAL, sl_seconds INTEGER,
            roti_avg REAL, roti_max REAL);
    """)
    out.executemany(
        "INSERT INTO hourly VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["hour"], r["rain_mm"], r["metar_rain"], r["metar_intensity"], r["kp"],
          r["bz_min"], r["sw_speed"], r["latency"], r["drop_pct"], r["sl_seconds"],
          r["roti_avg"], r["roti_max"]) for r in rows])
    out.commit()
    out.close()

    if args.csv:
        with open(args.csv, "w") as f:
            cols = ["hour", "rain_mm", "metar_rain", "metar_intensity", "kp", "bz_min",
                    "sw_speed", "latency", "drop_pct", "roti_avg", "roti_max"]
            f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")

    # ---- summary ----
    n_rainy = sum(1 for r in rows if rain_bucket(r["rain_mm"], r["metar_rain"]) != "dry")
    print(f"Hours analysed: {len(rows)}   ({rows[0]['hour']} -> {rows[-1]['hour']})")
    print(f"Rainy hours: {n_rainy}   Hours with Kp>=4: "
          f"{sum(1 for r in rows if r['kp'] is not None and r['kp'] >= 4)}")

    disagree = sum(1 for r in rows
                   if r["rain_mm"] is not None and r["rain_mm"] <= 0.05 and r["metar_rain"])
    print(f"Rain-source disagreement (model dry, airport observed rain): {disagree} hours")

    bucket_table(rows, lambda r: rain_bucket(r["rain_mm"], r["metar_rain"]),
                 "Starlink & GNSS vs RAIN",
                 ["dry", "light (<1mm)", "moderate (1-4mm)", "heavy (>=4mm)", "rain (obs only)"])
    bucket_table(rows, lambda r: kp_bucket(r["kp"]),
                 "Starlink & GNSS vs GEOMAGNETIC ACTIVITY",
                 ["quiet (Kp<2)", "unsettled (2-4)", "active (Kp>=4)"])

    # ---- attribution of the worst Starlink hours ----
    bad = sorted((r for r in rows if r["drop_pct"] is not None),
                 key=lambda r: r["drop_pct"], reverse=True)[:args.worst]
    print(f"\n== WORST {len(bad)} STARLINK HOURS: what was happening? ==")
    print(f"{'hour':<15}{'drop%':>7}{'lat':>7}{'rain':>7}{'metar':>10}{'Kp':>5}{'roti':>7}  verdict")
    for r in bad:
        wet = (r["rain_mm"] or 0) > 0.05 or r["metar_rain"]
        storm = r["kp"] is not None and r["kp"] >= 4
        iono = r["roti_max"] is not None and r["roti_max"] >= 0.5
        verdict = ("rain+geomag" if wet and storm else
                   "rain" if wet else
                   "geomagnetic" if storm else
                   "ionospheric" if iono else "unexplained")
        print(f"{r['hour']:<15}{fmt(r['drop_pct'], '.3f'):>7}{fmt(r['latency'], '.1f'):>7}"
              f"{fmt(r['rain_mm'], '.1f'):>7}{(r['metar_intensity'] or '-'):>10}"
              f"{fmt(r['kp'], '.1f'):>5}{fmt(r['roti_max'], '.2f'):>7}  {verdict}")

    print("\nInterpretation guide: if drop% rises down the RAIN buckets but is flat")
    print("across Kp buckets (and roti stays flat under rain), the week's story is:")
    print("rain affects the link, geomagnetic activity affected neither -- each stream")
    print("responding only to its own physics is itself evidence the pipeline is sound.")


if __name__ == "__main__":
    main()
