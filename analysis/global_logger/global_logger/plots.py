"""plots.py - figures: ROTI against magnetic latitude and time for one storm."""
import os, json, datetime as dt
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

def storm_figure(conn, cfg, storm, quiet=None):
    s = next(x for x in cfg["storms"] if x["name"] == storm)
    days = [str(d) for d in s["days"]]; t0, t1 = days[0], (pd.Timestamp(days[-1]) + pd.Timedelta("1D")).strftime("%Y-%m-%d")
    st = pd.read_sql("select * from stations", conn).set_index("station")
    net = pd.read_sql("select * from roti_network where window_start >= ? and window_start < ?", conn, params=(t0, t1))
    net["t"] = pd.to_datetime(net.window_start, utc=True)
    roti = pd.read_sql("select station, window_start, roti from roti where window_start >= ? and window_start < ?", conn, params=(t0, t1))
    kp = pd.read_sql("select * from kp_index where ts_utc >= ? and ts_utc < ?", conn, params=(t0, t1)); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True)
    dst = pd.read_sql("select * from dst_index where ts_utc >= ? and ts_utc < ?", conn, params=(t0, t1)); dst["t"] = pd.to_datetime(dst.ts_utc, utc=True)
    stations = [x for x in st.sort_values("geomag_lat", ascending=False).index if x in set(net.station)]
    summary = {}
    if quiet:
        q = next(x for x in cfg["storms"] if x["name"] == quiet); qd = [str(d) for d in q["days"]]
        qr = pd.read_sql("select station, roti from roti where window_start >= ? and window_start < ?", conn,
                         params=(qd[0], (pd.Timestamp(qd[-1]) + pd.Timedelta("1D")).strftime("%Y-%m-%d")))
    for x in stations:
        r = roti[roti.station == x].copy(); r["day"] = r.window_start.str[:10]
        d = {day: round(float((g.roti > 0.5).mean()), 3) for day, g in r.groupby("day")}
        n = net[net.station == x].set_index("t").roti_med.rolling("1h").median()
        summary[x] = dict(geomag_lat=round(st.loc[x, "geomag_lat"], 1), frac_gt05_by_day=d,
                          peak_1h_median_roti=round(float(n.max()), 3), peak_time=str(n.idxmax()),
                          median_roti=round(float(r.roti.median()), 3))
        if quiet:
            qq = qr[qr.station == x]
            summary[x]["quiet_frac_gt05"] = round(float((qq.roti > 0.5).mean()), 3) if len(qq) else None
            summary[x]["quiet_median_roti"] = round(float(qq.roti.median()), 3) if len(qq) else None
    fig = plt.figure(figsize=(13, 10)); gs = fig.add_gridspec(3, 2, height_ratios=[1, 3, 2], width_ratios=[30, 1])
    a0 = fig.add_subplot(gs[0, 0]); a0.bar(kp.t, kp.kp, width=0.12, align="edge", color=["tab:red" if k >= 5 else "tab:green" for k in kp.kp])
    a0.set_ylabel("Kp (GFZ)"); a0.set_ylim(0, 9); a0b = a0.twinx(); a0b.plot(dst.t, dst.dst, "k"); a0b.set_ylabel("Dst nT (Kyoto)")
    a0.set_title(f"{storm}: {s.get('note', '')}", fontsize=10)
    a1 = fig.add_subplot(gs[1, 0], sharex=a0)
    grid = net.pivot_table(index="station", columns="t", values="roti_med").reindex(stations)
    im = a1.pcolormesh(grid.columns, np.arange(len(stations) + 1), grid.values, cmap="inferno", vmin=0, vmax=1.5, shading="flat") if False else \
         a1.imshow(grid.values, aspect="auto", cmap="inferno", vmin=0, vmax=1.5, interpolation="nearest",
                   extent=[matplotlib.dates.date2num(grid.columns[0]), matplotlib.dates.date2num(grid.columns[-1]), len(stations), 0])
    a1.set_yticks(np.arange(len(stations)) + 0.5); a1.set_yticklabels([f"{x}  {st.loc[x, 'geomag_lat']:+.0f}°" for x in stations])
    a1.set_ylabel("station (geomagnetic latitude)"); a1.xaxis_date()
    cb = fig.colorbar(im, cax=fig.add_subplot(gs[1, 1])); cb.set_label("network median ROTI (TECU/min)")
    a2 = fig.add_subplot(gs[2, 0])
    ml = [summary[x]["geomag_lat"] for x in stations]
    for day in days:
        a2.plot(ml, [100 * summary[x]["frac_gt05_by_day"].get(day, np.nan) for x in stations], "o-", label=day)
    if quiet: a2.plot(ml, [100 * (summary[x].get("quiet_frac_gt05") or np.nan) for x in stations], "s--", c="grey", label=f"quiet {qd[0]}")
    for x, m in zip(stations, ml): a2.annotate(x, (m, 0), fontsize=7, rotation=90, va="bottom")
    a2.set_xlabel("geomagnetic latitude (deg, IGRF-2025 dipole)"); a2.set_ylabel("% of satellite 5-min\nwindows with ROTI > 0.5")
    a2.legend(fontsize=8); a2.grid(alpha=.3)
    plt.tight_layout()
    out = os.path.join(cfg["paths"]["figures"], f"roti_maglat_time_{storm}.png"); plt.savefig(out, dpi=130); plt.close()
    json.dump(summary, open(os.path.join(cfg["paths"]["figures"], f"summary_{storm}.json"), "w"), indent=1)
    print("wrote", out); print(json.dumps(summary, indent=1))
