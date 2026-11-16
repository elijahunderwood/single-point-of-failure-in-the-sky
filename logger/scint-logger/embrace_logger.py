#!/usr/bin/env python3
"""EMBRACE ionospheric-scintillation logger (YSTE 2027). Downloads real S4 and
Phi60 indices from https://embracedata.inpe.br into SQLite. Data: EMBRACE/INPE,
INCT GNSS-NavAer/UNESP, NSSC/CAS - non-commercial, acknowledge per their readme."""
import os
import sqlite3, os, sys, time, re, urllib.request, datetime
BASE = "https://embracedata.inpe.br/scintillation/stations"
DB   = os.path.expanduser("~/scint-logger/embrace_scint.db")
UA = os.environ.get("HTTP_USER_AGENT", "Sentinus-YI0046-student-project")
PRIORITY = ["BAVC","STBV","FRTZ","UFBA","CEEU","MABB","STAR","GOUR","MTSR","ROJI"]
MAX_STATIONS_PER_DAY = 2
def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS scint(
        ts_utc TEXT, station TEXT, svid INTEGER, az REAL, el REAL,
        s4 REAL, phi60 REAL, tec REAL, s4_l2 REAL, phi60_l2 REAL,
        s4_l5 REAL, phi60_l5 REAL,
        PRIMARY KEY(ts_utc, station, svid))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_scint_ts ON scint(ts_utc)"); con.commit()
def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8","replace")
def f(x):
    x = x.strip()
    return None if x=="" or x.lower()=="nan" else float(x)
def stations_for(date):
    doy = date.timetuple().tm_yday
    try: html = get(f"{BASE}/{date.year}/{doy:03d}/")
    except Exception as e: print(f"  {date}: cannot list ({e})"); return []
    found = re.findall(r'href="([A-Z0-9]{4})/"', html)
    return [s for s in PRIORITY if s in found] + [s for s in found if s not in PRIORITY]
def fetch_day(con, station, date):
    doy = date.timetuple().tm_yday; ymd = date.strftime("%Y%m%d")
    folder = f"{BASE}/{date.year}/{doy:03d}/{station}/"; nf = nr = 0
    for i in range(96):
        hhmm = f"{(i*15)//60:02d}{(i*15)%60:02d}"
        try: txt = get(folder + f"{station}_{ymd}_{hhmm}.dat")
        except Exception: continue
        rows = []
        for line in txt.splitlines():
            c = line.split(",")
            if len(c) < 27: continue
            try: svid = int(float(c[1]))
            except ValueError: continue
            rows.append((c[0].strip(), station, svid, f(c[2]), f(c[3]),
                         f(c[4]), f(c[6]), f(c[9]), f(c[13]), f(c[15]), f(c[20]), f(c[22])))
        if rows:
            con.executemany("INSERT OR REPLACE INTO scint VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            nf += 1; nr += len(rows)
        time.sleep(0.05)
    con.commit(); print(f"  {station} {date}: {nf}/96 files, {nr} rows"); return nr
def run(dates):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB); init_db(con)
    for d in dates:
        for st in stations_for(d)[:MAX_STATIONS_PER_DAY]:
            fetch_day(con, st, d)
    tot = con.execute("SELECT COUNT(*) FROM scint").fetchone()[0]
    sp = con.execute("SELECT MIN(ts_utc),MAX(ts_utc) FROM scint").fetchone()
    print(f"DB: {tot} rows, {sp[0]} -> {sp[1]}")
def main():
    a = sys.argv[1:]
    if a and a[0]=="--backfill-storms":
        dates=[datetime.date(2026,8,2),datetime.date(2026,8,8),datetime.date(2026,9,8),
               datetime.date(2026,10,4),datetime.date(2026,10,5)]
    elif a and a[0]=="--date": dates=[datetime.date.fromisoformat(a[1])]
    elif a and a[0]=="--range":
        d0=datetime.date.fromisoformat(a[1]); d1=datetime.date.fromisoformat(a[2])
        dates=[d0+datetime.timedelta(days=i) for i in range((d1-d0).days+1)]
    else:
        t=datetime.date.today(); dates=[t-datetime.timedelta(days=1), t]
    run(dates)
if __name__=="__main__": main()
