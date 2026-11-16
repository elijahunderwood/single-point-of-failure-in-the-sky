"""01_inventory.py - what data exists, which copy is newer, gaps, duplicates.
Also converts the two gnss_tec SQL dumps into SQLite + a per-second CSV."""
import sqlite3, os, json, glob, sys
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *
rep = {}

# --- two space-weather DB copies
for name in ["spaceweather.db", "spaceweather copy.db"]:
    c = sqlite3.connect(f"file:{DATA}/{name}?mode=ro", uri=True)
    d = {}
    for t in ["kp_index", "dst_index", "solar_wind_plasma", "solar_wind_mag"]:
        n, a, b = c.execute(f"select count(*),min(ts_utc),max(ts_utc) from {t}").fetchone()
        d[t] = dict(rows=n, first=a, last=b)
    rep[name] = d
# are overlapping rows identical?
a = sqlite3.connect(f"file:{DATA}/spaceweather.db?mode=ro", uri=True)
b = sqlite3.connect(f"file:{DATA}/spaceweather copy.db?mode=ro", uri=True)
for t in ["kp_index", "dst_index", "solar_wind_mag"]:
    A = pd.read_sql(f"select * from {t}", a).set_index("ts_utc"); B = pd.read_sql(f"select * from {t}", b).set_index("ts_utc")
    common = A.index.intersection(B.index)
    diff = (A.loc[common].fillna(-999) != B.loc[common].fillna(-999)).any(axis=1)
    rep.setdefault("copy_vs_original", {})[t] = dict(common=len(common), differing=int(diff.sum()),
        only_in_original=len(A.index.difference(B.index)), only_in_copy=len(B.index.difference(A.index)))

# --- gnss_tec SQL dumps -> sqlite
for name, tag in [("gnss_tec.sql", "orig"), ("gnss_tec.sql copy", "copy")]:
    dbp = f"{OUT}/gnss_tec_{tag}.db"
    if not os.path.exists(dbp):
        c = sqlite3.connect(dbp)
        c.execute("create table tec(id,ts_utc,rcv_tow,gps_week,sv,elev_deg,azim_deg,code_tec,phase_tec,cno_l1,cno_l2,locktime_l2,slip)")
        c.execute("create table epoch_log(id,ts_utc,rcv_tow,n1,n2,status)")
        c.executescript("PRAGMA synchronous=OFF; BEGIN;\n" + open(f"{DATA}/{name}").read() + "\nCOMMIT;")
    c = sqlite3.connect(dbp)
    n, t0, t1 = c.execute("select count(*),min(ts_utc),max(ts_utc) from tec").fetchone()
    dup = c.execute("select count(*) from (select ts_utc,sv,count(*) k from tec group by 1,2 having k>1)").fetchone()[0]
    nsv = c.execute("select count(distinct sv) from tec").fetchone()[0]
    # gaps > 60 s in the epoch stream
    ts = pd.to_datetime(pd.read_sql("select distinct ts_utc from tec", c)["ts_utc"], utc=True, format="ISO8601").sort_values()
    g = ts.diff().dt.total_seconds()
    gaps = [(str(ts.iloc[i-1]), round(g.iloc[i]/60, 1)) for i in np.where(g > 60)[0]]
    rep[name] = dict(tec_rows=n, first=t0, last=t1, satellites=nsv, duplicate_sv_epochs=dup,
                     gaps_over_1min=gaps[:20], file_mtime=os.path.getmtime(f"{DATA}/{name}"))
    pd.read_sql("select ts_utc,sv,elev_deg,azim_deg,phase_tec,code_tec,cno_l1,cno_l2,locktime_l2,slip from tec", c)\
      .to_csv(f"{OUT}/home_{tag}_dump.csv", index=False)

# --- home-station CSV exports
files = sorted(glob.glob(f"{DATA}/storm_exports/tec_*.csv")) + [f"{DATA}/gnss_storm_0708sep.csv",
        f"{X}/gnss_storm_05oct.csv", f"{X}/quiet_ctrl/quiet_02oct_day.csv", f"{X}/quiet_ctrl/quiet_02oct_night.csv"]
ex = {}
for f in files:
    df = pd.read_csv(f)
    if df.empty: ex[os.path.basename(f)] = "EMPTY (header only)"; continue
    t = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601")
    ordered = bool(t.is_monotonic_increasing)
    ex[os.path.basename(f)] = dict(rows=len(df), first=str(t.min()), last=str(t.max()),
        hours=round((t.max()-t.min()).total_seconds()/3600, 2), satellites=int(df.sv.nunique()),
        time_ordered=ordered, exact_dupes=int(df.duplicated().sum()), columns=list(df.columns))
rep["home_exports"] = ex
# identical file check
import hashlib
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
rep["storm_exports_tec_10-05_equals_gnss_storm_05oct_rows"] = None
a5 = pd.read_csv(f"{DATA}/storm_exports/tec_2026-10-05.csv"); b5 = pd.read_csv(f"{X}/gnss_storm_05oct.csv")
rep["storm_exports_tec_10-05_equals_gnss_storm_05oct_rows"] = bool(len(a5) == len(b5) and np.allclose(a5.phase_tec.values, b5.phase_tec.values))

# --- Kp / Dst exports vs DB consistency
kp = pd.read_csv(f"{DATA}/storm_exports/kp_index.csv"); dst = pd.read_csv(f"{DATA}/storm_exports/dst_index.csv")
A = pd.read_sql("select ts_utc,kp from kp_index", a).merge(kp, on="ts_utc", suffixes=("_db", "_exp"))
D = pd.read_sql("select ts_utc,dst from dst_index", a).merge(dst, on="ts_utc", suffixes=("_db", "_exp"))
rep["kp_export_vs_db"] = dict(common=len(A), differing=int((A.kp_db != A.kp_exp).sum()),
                              export_range=[kp.ts_utc.min(), kp.ts_utc.max()])
dd = D[D.dst_db != D.dst_exp]
rep["dst_export_vs_db"] = dict(common=len(D), differing=len(dd), examples=dd.head(10).values.tolist(),
                               export_range=[dst.ts_utc.min(), dst.ts_utc.max()])
# Kp gaps in export
kt = pd.to_datetime(kp.ts_utc, utc=True); kg = kt.diff().dt.total_seconds()/3600
rep["kp_export_gaps_h"] = [(str(kt.iloc[i-1]), kg.iloc[i]) for i in np.where(kg > 3.01)[0]]
dt_ = pd.to_datetime(dst.ts_utc, utc=True); dg = dt_.diff().dt.total_seconds()/3600
rep["dst_export_gaps_h"] = [(str(dt_.iloc[i-1]), dg.iloc[i]) for i in np.where(dg > 1.01)[0]]

# --- EMBRACE
c = sqlite3.connect(f"file:{DATA}/embrace_scint.db?mode=ro", uri=True)
rep["embrace"] = pd.read_sql("select station, substr(ts_utc,1,10) day, count(*) n from scint group by 1,2", c).values.tolist()
# --- Starlink
for f in [f"{DATA}/starlink_0708sep.csv", f"{X}/starlink_05oct.csv"]:
    s = pd.read_csv(f); t = pd.to_datetime(s.ts_utc, utc=True)
    rep[os.path.basename(f)] = dict(rows=len(s), first=str(t.min()), last=str(t.max()),
        missing_seconds=int((t.max()-t.min()).total_seconds()+1-len(s)), dup_ts=int(t.duplicated().sum()),
        counter_resets=int((s.counter.diff() < 0).sum()))
json.dump(rep, open(f"{OUT}/inventory.json", "w"), indent=1, default=str)
print(json.dumps(rep, indent=1, default=str)[:12000])
