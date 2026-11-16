import sqlite3, csv, os, glob, datetime, tarfile
from collections import defaultdict
HOME=os.path.expanduser("~")
TEC=os.path.join(HOME,"gnss-logger","gnss_tec.db")
SW=os.path.join(HOME,"spaceweather-logger","spaceweather.db")
for p in (TEC,SW):
    if not os.path.exists(p): raise SystemExit("not found: "+p)
OUT=os.path.join(HOME,"storm_exports"); os.makedirs(OUT,exist_ok=True)
for f in glob.glob(OUT+"/*"): os.remove(f)
tc=sqlite3.connect(TEC); sw=sqlite3.connect(SW)
tmin,tmax=tc.execute("SELECT MIN(ts_utc),MAX(ts_utc) FROM tec").fetchone()
print("GNSS TEC coverage:",tmin[:16],"->",tmax[:16],"\n")
byday=defaultdict(list)
for ts,kp in sw.execute("SELECT ts_utc,kp FROM kp_index WHERE kp>=5 ORDER BY ts_utc"):
    byday[ts[:10]].append((ts,kp))
print("Kp>=5 storm days:")
for day in sorted(byday):
    eps=byday[day]; peak_ts,peak_kp=max(eps,key=lambda x:x[1])
    if day<tmin[:10] or day>tmax[:10]:
        print(f"  {day}  peak Kp {peak_kp}  -- NO TEC data, skipped"); continue
    c=datetime.datetime.fromisoformat(peak_ts)
    s=(c-datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    e=(c+datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    cur=tc.execute("SELECT ts_utc,sv,elev_deg,azim_deg,phase_tec,cno_l1,slip FROM tec "
                   "WHERE ts_utc>=? AND ts_utc<? AND elev_deg>20 ORDER BY sv,ts_utc",(s,e))
    fn=os.path.join(OUT,f"tec_{day}.csv"); n=0
    with open(fn,"w",newline="") as f:
        w=csv.writer(f); w.writerow([d[0] for d in cur.description])
        for r in cur: w.writerow(r); n+=1
    print(f"  {day}  peak Kp {peak_kp} @ {peak_ts[11:16]}UT  -> {n} rows")
for tbl,cols in [("kp_index","ts_utc,kp"),("dst_index","ts_utc,dst")]:
    cur=sw.execute(f"SELECT {cols} FROM {tbl} WHERE ts_utc>=? ORDER BY ts_utc",(tmin,))
    with open(os.path.join(OUT,tbl+".csv"),"w",newline="") as f:
        w=csv.writer(f); w.writerow([d[0] for d in cur.description]); w.writerows(cur)
b=os.path.join(HOME,"storms_bundle.tgz")
with tarfile.open(b,"w:gz") as t: t.add(OUT,arcname="storm_exports")
print(f"\nBUNDLE: {b}  ({os.path.getsize(b)/1e6:.1f} MB)")
