#!/usr/bin/env python3
"""Robust weather extractor: prints each DB's schema, auto-selects the OBSERVATION
table (most content columns, not the fetch-log), writes hourly CSV with numeric
fields + parsed precip level. Stdlib only, read-only."""
import csv, os, re, sqlite3, statistics
from collections import defaultdict

STOP = {"id","rowid","rows_new","n_new","num_new","status","source","fetch","inserted","seq","pk"}
PRECIP = re.compile(r'(?P<i>[-+]?)(?:VC|MI|BC|PR|DR|BL|SH|TS|FZ)*(?P<p>DZ|RA|SN|SG|IC|PL|GR|GS|UP)')

def ro(p): return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
def tbls(c): return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
def info(c,t): return [(r[1],r[2]) for r in c.execute(f"PRAGMA table_info('{t}')")]
def find_ts(names):
    for pref in ("ts_utc","obs_time","observation_time","valid_time","valid","time","timestamp","datetime","date"):
        for n in names:
            if n.lower()==pref: return n
    for n in names:
        if "time" in n.lower() or n.lower().endswith("_utc") or "date" in n.lower(): return n
    return None
def obs_table(c):
    best=bestts=None; bs=-1
    for t in tbls(c):
        names=[n for n,_ in info(c,t)]; ts=find_ts(names)
        if not ts: continue
        score=len([n for n in names if n.lower() not in STOP and n!=ts])
        if score>bs: bs,best,bestts=score,t,ts
    return best,bestts
def precip_lvl(s):
    if s is None: return None
    m=PRECIP.search(str(s).upper())
    if not m: return 0
    return {'-':1,'':2,'+':3}.get(m.group('i'),2)
def dump(path, tag):
    if not os.path.exists(path):
        print(f"[{tag}] not found: {path}"); return {}
    c=ro(path)
    print(f"\n===== {tag} SCHEMA =====")
    for t in tbls(c):
        cs=info(c,t); n=c.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        print(f"  {t} ({n} rows): " + ", ".join(f"{nm}:{ty}" for nm,ty in cs))
    t,ts=obs_table(c)
    print(f"[{tag}] -> using observation table: {t} (ts='{ts}')")
    if not t: c.close(); return {}
    names=[n for n,_ in info(c,t)]
    raw=None
    for n in names:
        r=c.execute(f"SELECT {n} FROM '{t}' WHERE {n} IS NOT NULL LIMIT 1").fetchone()
        if r and re.search(r'\d{6}Z|KT|METAR|SPECI|Q\d{4}|A\d{3,4}', str(r[0]).upper()): raw=n
    num=[n for n,ty in info(c,t) if ty.upper() in ("REAL","FLOAT","INTEGER","INT","NUMERIC") and n.lower() not in STOP and n!=ts]
    print(f"[{tag}] numeric fields: {num}   raw-METAR col: {raw}")
    buck=defaultdict(lambda: defaultdict(list)); rawb=defaultdict(list)
    for row in c.execute(f"SELECT * FROM '{t}'"):
        d=dict(zip(names,row)); tv=d.get(ts)
        if not tv: continue
        hr=str(tv)[:13].replace(" ","T")
        for n in num:
            v=d[n]
            if isinstance(v,(int,float)) and v>-9998: buck[hr][n].append(v)
        if raw:
            pl=precip_lvl(d[raw])
            if pl is not None: rawb[hr].append(pl)
    c.close()
    out={}
    for hr in set(list(buck)+list(rawb)):
        r={f"{tag}_{k}":statistics.mean(v) for k,v in buck.get(hr,{}).items()}
        if hr in rawb: r[f"{tag}_precip"]=max(rawb[hr])
        out[hr]=r
    return out
def main():
    home=os.path.expanduser("~")
    base=os.environ.get("WX_BASE", f"{home}/weather-logger")
    m=dump(f"{base}/metar.db","metar")
    l=dump(f"{base}/localweather.db","local")
    hrs=sorted(set(m)|set(l))
    cols=sorted({k for d in list(m.values())+list(l.values()) for k in d})
    out=f"{home}/weather_hourly2.csv"
    with open(out,"w",newline="") as f:
        w=csv.writer(f); w.writerow(["hour"]+cols)
        for hr in hrs:
            r={}; r.update(m.get(hr,{})); r.update(l.get(hr,{}))
            w.writerow([hr]+[r.get(cc,"") for cc in cols])
    print(f"\nWrote {out} ({len(hrs)} rows). Columns: {cols}")
if __name__=="__main__": main()
