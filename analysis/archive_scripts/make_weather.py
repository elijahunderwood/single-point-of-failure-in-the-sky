#!/usr/bin/env python3
"""Extract hourly weather (METAR + local station) to a small CSV for the timeline.
Introspects each DB; standard library only; opens read-only."""
import csv, os, re, sqlite3, statistics
from collections import defaultdict, Counter

def ro(p): return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
def tabs(c): return [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
def cols(c,t): return [(r[1],r[2]) for r in c.execute(f"PRAGMA table_info('{t}')")]

def pick_ts(names):
    for pref in ("ts_utc","ts","obs_time","valid","time","timestamp","datetime","date"):
        for n in names:
            if n.lower()==pref: return n
    for n in names:
        if n.lower().endswith("_utc") or "time" in n.lower() or "date" in n.lower(): return n
    return None

def main_table(c):
    best,bn=-1,None
    for t in tabs(c):
        names=[n for n,_ in cols(c,t)]
        if pick_ts(names) is None: continue
        n=c.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        if n>best: best,bn=n,t
    return bn

# METAR present-weather precip codes -> rough intensity score
PRECIP=re.compile(r'(?P<int>[-+]?)(?:VC)?(?P<ph>DZ|RA|SN|SG|PL|GR|GS|SHRA|SHSN|TSRA|TS)')
VIS=re.compile(r'\b(\d{4})\b')  # 4-digit metres visibility group

def precip_from_text(s):
    if not s: return None,None
    m=PRECIP.search(s.upper())
    if not m: return 0,""
    lvl={'-':1,'':2,'+':3}.get(m.group('int'),2)
    return lvl, m.group(0)

def summarise(path, tag):
    if not os.path.exists(path):
        print(f"  {tag}: file not found ({path})"); return {}
    c=ro(path); t=main_table(c)
    if not t: print(f"  {tag}: no table with a timestamp column"); return {}
    cs=cols(c,t); names=[n for n,_ in cs]; ts=pick_ts(names)
    print(f"  {tag}: table='{t}'  ts='{ts}'  cols={names}")
    numeric=[n for n,ty in cs if ty.upper() in ('REAL','FLOAT','INTEGER','INT','NUMERIC') and n!=ts]
    text=[n for n,ty in cs if ty.upper() in ('TEXT','CHAR','VARCHAR','CLOB') and n!=ts]
    rows=c.execute(f"SELECT * FROM '{t}'").fetchall()
    idx={d[0]:i for i,d in enumerate(c.execute(f"SELECT * FROM '{t}' LIMIT 1").description)}
    buck=defaultdict(lambda: defaultdict(list)); rawcol=None
    # guess a raw-METAR column: text col whose sample contains typical tokens
    for n in text:
        sample=str(rows[len(rows)//2][idx[n]]) if rows else ""
        if re.search(r'\b(METAR|SPECI|AUTO|KT|Q\d{4}|\d{4}Z)\b', sample.upper()): rawcol=n
    print(f"  {tag}: numeric={numeric} raw_metar_col={rawcol}")
    for r in rows:
        tv=r[idx[ts]]
        if not tv: continue
        hr=str(tv)[:13]
        for n in numeric:
            v=r[idx[n]]
            if isinstance(v,(int,float)) and v>-9998: buck[hr][n].append(v)
        if rawcol:
            lvl,_=precip_from_text(str(r[idx[rawcol]]))
            if lvl is not None: buck[hr]["precip_lvl"].append(lvl)
    out={}
    for hr,d in buck.items():
        row={}
        for k,vals in d.items():
            row[f"{tag}_{k}"]= (max(vals) if k=="precip_lvl" else statistics.mean(vals))
        out[hr]=row
    c.close(); return out

def main():
    home=os.path.expanduser("~")
    print("Introspecting weather DBs:")
    m=summarise(f"{home}/weather-logger/metar.db","metar")
    l=summarise(f"{home}/weather-logger/localweather.db","local")
    hrs=sorted(set(m)|set(l))
    allcols=sorted({k for d in list(m.values())+list(l.values()) for k in d})
    out=f"{home}/weather_hourly.csv"
    with open(out,"w",newline="") as f:
        w=csv.writer(f); w.writerow(["hour"]+allcols)
        for hr in hrs:
            row=dict(); row.update(m.get(hr,{})); row.update(l.get(hr,{}))
            w.writerow([hr]+[row.get(c,"") for c in allcols])
    print(f"\nWrote {out}  ({len(hrs)} hourly rows, cols: {allcols})\n-> upload weather_hourly.csv")

if __name__=="__main__": main()
