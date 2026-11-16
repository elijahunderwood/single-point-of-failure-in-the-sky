"""pilib.py - shared helpers for mail_control and storm_alert (runs on the Pi).
The Gmail app password is read from ~/.msmtprc at run time and is never printed or logged."""
import os, re, subprocess, sqlite3, datetime as dt, shlex
from email.message import EmailMessage
from email.utils import make_msgid, formatdate

HOME = os.path.expanduser("~")
ADDRESS = os.environ.get("MAIL_ADDRESS", "").strip()  # set in the environment; not stored in this repository
SERVICES = {"gnss": "gnss-logger", "starlink": "starlink-logger", "spaceweather": "spaceweather-logger",
            "metar": "metar-logger", "weather": "weather-logger",
            "flare": "flare-logger"}
# units run by a timer (oneshot service): STATUS reports the timer state instead
TIMERS = {"flare": "flare-logger.timer"}
# same databases, queries and limits as ~/db_watchdog.sh
DBS = [("gnss", f"{HOME}/gnss-logger/gnss_tec.db", "SELECT MAX(ts_utc) FROM tec", 1200),
       ("starlink", f"{HOME}/starlink-logger/starlink_history.db", "SELECT MAX(ts_utc) FROM history", 1800),
       ("spaceweather", f"{HOME}/spaceweather-logger/spaceweather.db", "SELECT MAX(ts_utc) FROM solar_wind_mag", 3600),
       ("metar", f"{HOME}/weather-logger/metar.db", "SELECT MAX(ts_utc) FROM metar", 7200),
       ("weather", f"{HOME}/weather-logger/localweather.db", "SELECT MAX(ts_utc) FROM weather_current", 3600),
       ("global_logger", f"{HOME}/global_logger/data/global_roti.db",
        "SELECT MAX(updated_utc) FROM station_days WHERE status='ok'", 108000),
       ("flare", f"{HOME}/flare_logger/flare.db", "SELECT MAX(ts_utc) FROM xray_flux", 3600)]

FOOTER = """--
Remote control (email from your own Gmail to yourself):
  Subject:  PI <your PIN> <COMMAND>      e.g.  PI 123456 STATUS   (use your real PIN)
  Commands: STATUS | RESTART <gnss|starlink|spaceweather|metar|weather|flare|all> | RUN GLOBAL |
            CHECK | LOGS <gnss|starlink|spaceweather|metar|weather|flare|watchdog|storm|control> | DISK | REBOOT | HELP
  The PIN is in ~/mail_control/pin on the Pi. Max 10 commands per hour.
"""

def gmail_password():
    """Read the app password from ~/.msmtprc ('password' line or 'passwordeval')."""
    pw = None
    for line in open(os.path.join(HOME, ".msmtprc")):
        s = line.strip()
        if s.startswith("passwordeval"):
            pw = subprocess.run(s.split(None, 1)[1], shell=True, capture_output=True, text=True).stdout.strip()
        elif re.match(r"^password\s", s):
            pw = s.split(None, 1)[1].strip().strip('"')
    if not pw: raise RuntimeError("no password in ~/.msmtprc")
    return pw

def send_mail(subject, body, to=None, in_reply_to=None):
    if not ADDRESS:
        raise RuntimeError("Set MAIL_ADDRESS to the mailbox used for alerts (not stored in this repository).")
    if to is None:
        to = ADDRESS
    """Send through msmtp (which already has the account set up)."""
    m = EmailMessage()
    m["From"] = ADDRESS; m["To"] = to; m["Subject"] = subject
    m["Date"] = formatdate(localtime=True); m["Message-ID"] = make_msgid(domain=os.environ.get("MAIL_DOMAIN", "pi.example"))
    if in_reply_to: m["In-Reply-To"] = in_reply_to; m["References"] = in_reply_to
    m.set_content(body)
    r = subprocess.run(["msmtp", "-a", "gmail", to], input=m.as_bytes(), capture_output=True, timeout=120)
    if r.returncode != 0: raise RuntimeError("msmtp failed: " + r.stderr.decode()[-300:])

def run(cmd, timeout=60, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"(error: {e})"

def service_states():
    return {k: (run(["systemctl", "is-active", TIMERS[k]]) + " (timer)") if k in TIMERS else run(["systemctl", "is-active", u])
            for k, u in SERVICES.items()}

def db_ages():
    out, now = [], dt.datetime.now(dt.timezone.utc)
    for name, db, sql, lim in DBS:
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            ts = c.execute(sql).fetchone()[0]; c.close()
            t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
            age = (now - t).total_seconds()
            out.append(f"  {name:13s} newest {age/60:7.1f} min old  (limit {lim//60} min)  {'OK' if age <= lim else 'STALLED'}")
        except Exception as e:
            out.append(f"  {name:13s} ERROR reading db: {str(e)[:80]}")
    return "\n".join(out)

def logger_status_text():
    st = service_states()
    return "Logger services:\n" + "\n".join(f"  {k:13s} {SERVICES[k]:22s} {v}" for k, v in st.items()) + \
           "\n\nNewest record per database:\n" + db_ages()
