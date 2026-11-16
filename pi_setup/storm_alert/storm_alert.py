#!/usr/bin/env python3
"""storm_alert.py - email Elijah when NOAA SWPC forecasts, warns of, or observes a G3+ (Kp>=7)
geomagnetic storm. Run every 3 h by storm-alert.timer. Re-alerts only if the level goes UP.
If NOAA can't be reached it just logs and exits quietly."""
import json, re, os, sys, logging, urllib.request, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.expanduser("~/mail_control"))
import pilib

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
UK = ZoneInfo("Europe/London"); UTC = dt.timezone.utc
logging.basicConfig(filename=os.path.join(HERE, "storm_alert.log"), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger()
SRC_FC = "https://services.swpc.noaa.gov/text/3-day-forecast.txt"
SRC_AL = "https://services.swpc.noaa.gov/products/alerts.json"
SRC_KP = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pi-storm-alert"}), timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def g_of_kp(kp): return max(0, min(5, int(kp + 1e-6) - 4))   # Kp7=G3, 8=G4, 9=G5
def uk(t): return t.astimezone(UK).strftime("%a %d %b %H:%M %Z")

def forecast_events(now):
    txt = get(SRC_FC); ev = []
    m = re.search(r"NOAA Kp index breakdown (.+?)\n\s*\n(.*?)\n\s*\n", txt, re.S)
    if not m: return ev
    block = m.group(2).splitlines()
    year = now.year
    dates = re.findall(r"([A-Z][a-z]{2})\s+(\d{1,2})", block[0])
    days = []
    for mon, d in dates:
        t = dt.datetime.strptime(f"{year} {mon} {d}", "%Y %b %d").replace(tzinfo=UTC)
        if (t - now).days < -200: t = t.replace(year=year + 1)
        days.append(t)
    for line in block[1:]:
        mm = re.match(r"\s*(\d\d)-(\d\d)UT\s+(.*)", line)
        if not mm: continue
        vals = re.findall(r"(\d+(?:\.\d+)?)(?:\s*\(G\d\))?", mm.group(3))
        for d0, v in zip(days, vals):
            kp = float(v); start = d0 + dt.timedelta(hours=int(mm.group(1)))
            if kp >= 7 and start + dt.timedelta(hours=3) >= now:
                ev.append(dict(level=g_of_kp(kp), kind="forecast", src=SRC_FC,
                               text=f"Forecast Kp {kp:g} (G{g_of_kp(kp)}) for {uk(start)} - {uk(start + dt.timedelta(hours=3))}"))
    return ev

def alert_events(now):
    ev = []
    for a in json.loads(get(SRC_AL)):
        msg = a.get("message", ""); t = dt.datetime.strptime(a["issue_datetime"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        head = " ".join(l for l in msg.splitlines() if re.match(r"^(WATCH|WARNING|ALERT|EXTENDED WARNING)", l))
        lvl = 0
        g = re.search(r"Category G(\d)", msg); k = re.search(r"K-index of (\d)", head)
        if head.startswith("WATCH") and g: lvl = int(g.group(1)); maxage = 72
        elif re.match(r"(WARNING|EXTENDED WARNING|ALERT)", head) and k: lvl = g_of_kp(int(k.group(1))); maxage = 36
        else: continue
        if lvl >= 3 and now - t <= dt.timedelta(hours=maxage):
            ev.append(dict(level=lvl, kind=head.split(":")[0].lower(), src=SRC_AL,
                           text=f"{head.strip()} (issued {uk(t)})"))
    return ev

def observed_events(now):
    j = json.loads(get(SRC_KP)); ev = []
    rows = j[1:] if isinstance(j[0], list) else [[r.get("time_tag"), r.get("Kp", r.get("kp_index"))] for r in j]
    for r in rows:
        t = dt.datetime.fromisoformat(str(r[0]).replace("Z", "")[:19]).replace(tzinfo=UTC); kp = float(r[1])
        if kp >= 7 and now - t <= dt.timedelta(hours=24):
            ev.append(dict(level=g_of_kp(kp), kind="observed", src=SRC_KP, text=f"OBSERVED Kp {kp:g} (G{g_of_kp(kp)}) for 3 h from {uk(t)}"))
    return ev

def main(test=False):
    now = dt.datetime.now(UTC); events = []; errors = []
    for f in (forecast_events, alert_events, observed_events):
        try: events += f(now)
        except Exception as e: errors.append(f"{f.__name__}: {e}"); log.warning("NOAA fetch failed %s: %s", f.__name__, e)
    if errors and not events and not test:
        log.info("NOAA unreachable or unparsable - quiet exit"); return
    level = max([e["level"] for e in events], default=0)
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    sent_level = state.get("level", 0)
    if state.get("time") and now - dt.datetime.fromisoformat(state["time"]) > dt.timedelta(hours=72): sent_level = 0
    log.info("max level G%d, previously sent G%d, %d events", level, sent_level, len(events))
    if not test and (level < 3 or level <= sent_level): return
    lines = [f"Storm ALERT: G{level} geomagnetic storm conditions (Kp>={level+4}) at {uk(now)}", ""] if not test else \
            ["*** TEST EMAIL - this is NOT a real storm alert. It shows what an alert will look like. ***", "",
             f"Current NOAA status: highest G-level found = G{level} (alerts only go out for G3 or higher).", ""]
    det = [f"  - [{e['kind']}] {e['text']}" for e in sorted(events, key=lambda e: -e["level"])]
    lines += ["Details (times in UK local time):"] + (det or ["  (no G3+ items right now)"])
    lines += ["", "Sources: NOAA SWPC", f"  {SRC_FC}", f"  {SRC_AL}", f"  {SRC_KP}"]
    if errors: lines += ["", "Fetch problems: " + "; ".join(errors)]
    lines += ["", "Tip: check every logger is running so you capture the storm!", "", pilib.logger_status_text(), "", pilib.FOOTER]
    subj = (f"TEST - Storm ALERT: G{max(level,3)} (test message, no real storm)" if test else f"Storm ALERT: G{level} geomagnetic storm")
    pilib.send_mail(subj, "\n".join(lines))
    if not test:
        json.dump({"level": level, "time": now.isoformat()}, open(STATE, "w"))
    log.info("sent: %s", subj)

if __name__ == "__main__":
    main(test="--test" in sys.argv)
