#!/usr/bin/env python3
"""mail_control.py - control the Pi by email. Run every 2 min by mail-control.timer.

Security: a message is only obeyed if ALL of these are true
  1. it is in All Mail from the last day, not handled before (processed_ids.json), and its subject is
     'PI <PIN> <COMMAND>' (case-insensitive, extra spaces and Re:/Fwd: allowed; '[Pi] ... result' replies never match)
  2. the From address is exactly the MAIL_ADDRESS environment variable
  3. Gmail's own Authentication-Results header (added by mx.google.com) says dkim=pass for gmail.com,
     OR Gmail labelled it \\Sent (really sent from this logged-in account; self-sent mail has no DKIM result)
  4. the subject contains the correct 6-digit PIN (~/mail_control/pin)
  5. the command is on the fixed whitelist (no arbitrary shell commands, ever)
  6. fewer than 10 commands have run in the last hour
"""
import imaplib, email, os, re, sys, hmac, json, time, logging, subprocess, datetime as dt, shutil
from email.utils import parseaddr
from email.header import decode_header, make_header
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pilib

HERE = os.path.dirname(os.path.abspath(__file__)); HOME = pilib.HOME
CMDLOG = os.path.join(HERE, "commands.log")
logging.basicConfig(filename=os.path.join(HERE, "mail_control.log"), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger()
RATE = 10
LOGUNITS = dict(pilib.SERVICES, watchdog="db-watchdog", storm="storm-alert", control="mail-control")

def cmdlog(sender, cmd, outcome):
    with open(CMDLOG, "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\t{sender}\t{cmd}\t{outcome}\n")

def recent_count():
    if not os.path.exists(CMDLOG): return 0
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1); n = 0
    for line in open(CMDLOG):
        p = line.split("\t")
        if len(p) >= 4 and p[3].startswith("executed") and dt.datetime.fromisoformat(p[0]) > cut: n += 1
    return n

def dkim_ok(msg):
    """Use only the TOP Authentication-Results header, which Gmail's own server (mx.google.com) adds."""
    ar = msg.get_all("Authentication-Results") or []
    if not ar: return False, "no Authentication-Results header"
    top = re.sub(r"\s+", " ", str(ar[0]))
    if not top.strip().startswith("mx.google.com"): return False, "top Authentication-Results not from mx.google.com"
    if re.search(r"dkim=pass[^;]*header\.(i=@gmail\.com|d=gmail\.com)", top, re.I): return True, "dkim=pass gmail.com"
    return False, "dkim not pass for gmail.com"

def disk(): 
    u = shutil.disk_usage("/"); return f"Disk /: {u.free/1e9:.1f} GB free of {u.total/1e9:.1f} GB ({100*u.used/u.total:.0f}% used)"

def status():
    temp = pilib.run(["vcgencmd", "measure_temp"])
    gl = pilib.run([f"{HOME}/global_logger/venv/bin/python", "-m", "global_logger", "status"], timeout=120, cwd=f"{HOME}/global_logger") \
        if os.path.exists(f"{HOME}/global_logger/venv") else "(global_logger venv not found)"
    gl = "\n".join(l for l in gl.splitlines() if " INFO " not in l)[-2500:]
    return "\n".join([pilib.logger_status_text(), "", disk(), "Uptime: " + pilib.run(["uptime", "-p"]),
                      "Temperature: " + temp, "", "global_logger status:", gl])

def helptext():
    return ("Commands (subject line: PI <PIN> <COMMAND>):\n"
            "  STATUS            services, newest record per database, disk, uptime, temperature, global_logger\n"
            "  RESTART <name>    name = gnss | starlink | spaceweather | metar | weather | flare | all\n"
            "  RUN GLOBAL        run the global_logger daily job now (result emailed when it finishes)\n"
            "  CHECK             run db_watchdog.sh and report\n"
            "  LOGS <name>       last 30 journal lines: gnss|starlink|spaceweather|metar|weather|flare|watchdog|storm|control\n"
            "  DISK              free disk space\n"
            "  REBOOT            reboot the Pi (reply is sent first)\n"
            "  HELP              this list\n"
            "Rules: from your own Gmail only, max 10 commands per hour, PIN required (never put it in a reply).\n")

def execute(cmd):
    """Return (reply_text, after_action). Only whitelisted commands."""
    w = cmd.upper().split()
    if not w: return None, None
    if w == ["STATUS"]: return status(), None
    if w == ["HELP"]: return helptext(), None
    if w == ["DISK"]: return disk() + "\n\n" + pilib.run(["df", "-h"]), None
    if w[0] == "RESTART" and len(w) == 2 and (w[1].lower() in pilib.SERVICES or w[1] == "ALL"):
        names = list(pilib.SERVICES) if w[1] == "ALL" else [w[1].lower()]
        out = [f"{n}: " + (pilib.run(["sudo", "-n", "systemctl", "restart", pilib.SERVICES[n]], timeout=120) or "restart issued") for n in names]
        time.sleep(10)
        return "\n".join(out) + "\n\n" + pilib.logger_status_text(), None
    if w == ["RUN", "GLOBAL"]:
        unit = f"global-run-{int(time.time())}"
        out = pilib.run(["sudo", "-n", "systemd-run", f"--unit={unit}", f"--uid={os.getuid()}", f"--setenv=HOME={HOME}",
                         f"--working-directory={HOME}/global_logger", f"{HERE}/run_global.sh"])
        return f"Started global_logger daily run as systemd unit {unit}.\nYou'll get a second email with the result when it finishes.\n{out}", None
    if w == ["CHECK"]:
        out = pilib.run(["bash", f"{HOME}/db_watchdog.sh"], timeout=300)
        flags = sorted(os.listdir(f"{HOME}/.watchdog_state")) if os.path.isdir(f"{HOME}/.watchdog_state") else []
        return ("db_watchdog.sh ran" + (f" (output: {out})" if out else "") + ".\nIt only emails on a change, so here is the current picture:\n"
                f"Active watchdog flags: {', '.join(flags) or 'none (everything OK)'}\n\n" + pilib.logger_status_text() + "\n" + disk()), None
    if w[0] == "LOGS" and len(w) == 2 and w[1].lower() in LOGUNITS:
        return pilib.run(["sudo", "-n", "journalctl", "-u", LOGUNITS[w[1].lower()], "-n", "30", "--no-pager"]), None
    if w == ["REBOOT"]: return "Rebooting now. The Pi should be back in about 1-2 minutes; send PI <PIN> STATUS to check.", "reboot"
    return None, None

STATE = os.path.join(HERE, "processed_ids.json")
SUBJ_RE = re.compile(r"^\s*(?:(?:re|fwd?|aw|wg)\s*:\s*)*pi\s+(\d{4,8})\s+(.+?)\s*$", re.I)

def load_state():
    try: return set(json.load(open(STATE)))
    except Exception: return set()

def save_state(ids):
    tmp = STATE + ".tmp"; json.dump(sorted(ids)[-2000:], open(tmp, "w")); os.replace(tmp, STATE)

def parse_subject(subj):
    """Return (pin, command) or None. Case-insensitive 'PI', tolerant of spaces and Re:/Fwd:.
    Our own replies ('[Pi] ... result') never match because they start with '['."""
    subj = re.sub(r"\s+", " ", subj).strip()
    if subj.startswith("["): return None
    m = SUBJ_RE.match(subj)
    return (m.group(1), m.group(2)) if m else None

def main(seed=False):
    pin = open(os.path.join(HERE, "pin")).read().strip()
    M = imaplib.IMAP4_SSL("imap.gmail.com", timeout=60)
    try:
        M.login(pilib.ADDRESS, pilib.gmail_password())
    except Exception as e:
        log.warning("IMAP login failed: %s", e); return
    done = load_state(); reboot = False
    try:
        # Self-sent mail arrives already marked READ and labelled Inbox+Sent, so search All Mail
        # for the last day regardless of the Seen flag, and remember Message-IDs we've handled.
        M.select('"[Gmail]/All Mail"')
        since = (dt.date.today() - dt.timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = M.search(None, "SINCE", since, "SUBJECT", '"PI"')
        ids = data[0].split() if data and data[0] else []
        n_new = 0
        for i in ids:
            typ, d = M.fetch(i, "(X-GM-LABELS BODY.PEEK[HEADER])")
            meta = d[0][0]; msg = email.message_from_bytes(d[0][1])
            mid = (msg.get("Message-ID") or f"noid-{i.decode()}").strip()
            if mid in done: continue
            subj = str(make_header(decode_header(msg.get("Subject", "")))).strip()
            p = parse_subject(subj)
            if p is None: continue                         # not a command mail
            done.add(mid); save_state(done); n_new += 1      # never process the same mail twice
            if seed: continue
            sender = parseaddr(msg.get("From", ""))[1].lower()
            mpin, cmd = p; shown = "PI <pin> " + cmd
            if sender != pilib.ADDRESS: cmdlog(sender, shown, "rejected: sender"); continue
            ok, why = dkim_ok(msg)
            if not ok and b"\\Sent" in meta:
                ok, why = True, "sent from this Gmail account (Sent label)"
            if not ok: cmdlog(sender, shown, f"rejected: {why}"); continue
            if not hmac.compare_digest(mpin, pin): cmdlog(sender, shown, "rejected: bad PIN"); continue
            if recent_count() >= RATE: cmdlog(sender, shown, "rejected: rate limit"); continue
            reply, action = execute(cmd)
            if reply is None: cmdlog(sender, shown, "rejected: not on whitelist"); continue
            cmdlog(sender, shown, f"executed ({why})")
            try:
                pilib.send_mail(f"[Pi] {cmd.upper()} result", reply + "\n\n" + pilib.FOOTER, in_reply_to=msg.get("Message-ID"))
            except Exception as e:
                log.error("reply failed: %s", e)
            if action == "reboot": reboot = True
        log.info("checked All Mail since %s: %d PI candidates, %d new%s", since, len(ids), n_new, " (seeded)" if seed else "")
    finally:
        try: M.close(); M.logout()
        except Exception: pass
    if reboot:
        time.sleep(5); subprocess.run(["sudo", "-n", "systemctl", "reboot"])

if __name__ == "__main__":
    main(seed="--seed" in sys.argv)
