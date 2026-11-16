"""Command line:  python -m global_logger <command> [options]   (see README.md)"""
import argparse, logging, os, sys, datetime as dt
import yaml
import pandas as pd
from . import db, pipeline, archives

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_cfg(cfgdir):
    cfg = yaml.safe_load(open(os.path.join(cfgdir, "settings.yaml")))
    cfg["stations"] = yaml.safe_load(open(os.path.join(cfgdir, "stations.yaml")))["stations"]
    cfg["storms"] = yaml.safe_load(open(os.path.join(cfgdir, "storms.yaml")))["storms"]
    cfg["_names"] = {s["code"]: s.get("name", "") for s in cfg["stations"]}
    for k in ("db", "raw", "logs", "figures"):
        if not os.path.isabs(cfg["paths"][k]): cfg["paths"][k] = os.path.join(HERE, cfg["paths"][k])
    os.makedirs(os.path.dirname(cfg["paths"]["db"]), exist_ok=True)
    for k in ("raw", "logs", "figures"): os.makedirs(cfg["paths"][k], exist_ok=True)
    return cfg

def setup_logging(cfg):
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=[
        logging.StreamHandler(sys.stdout), logging.FileHandler(os.path.join(cfg["paths"]["logs"], "global_logger.log"))])

def pick_stations(cfg, arg):
    allc = [s["code"] for s in cfg["stations"] if s.get("enabled", True)]
    return arg.split(",") if arg else allc

def storm_days(cfg, name):
    s = next((x for x in cfg["storms"] if x["name"] == name), None)
    if s is None: sys.exit(f"unknown storm '{name}'. Known: {[x['name'] for x in cfg['storms']]}")
    return s, [d if isinstance(d, dt.date) else dt.date.fromisoformat(d) for d in s["days"]]

def main():
    ap = argparse.ArgumentParser(prog="global_logger")
    ap.add_argument("--config", default=os.path.join(HERE, "config"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="download+process every day of a storm from storms.yaml")
    b.add_argument("--storm", required=True); b.add_argument("--stations"); b.add_argument("--force", action="store_true")
    d = sub.add_parser("daily", help="yesterday's data for all stations + latest Kp/Dst")
    d.add_argument("--date"); d.add_argument("--stations"); d.add_argument("--force", action="store_true")
    c = sub.add_parser("check", help="check archive availability (no download)")
    c.add_argument("--storm"); c.add_argument("--stations")
    i = sub.add_parser("indices", help="fetch Kp and Dst"); i.add_argument("--start", required=True); i.add_argument("--end", required=True)
    h = sub.add_parser("import-home", help="process the home station gnss_tec.db with the same code")
    h.add_argument("--db", required=True, nargs="+", help="gnss_tec.db and/or per-second CSV exports"); h.add_argument("--start"); h.add_argument("--end")
    p = sub.add_parser("plot", help="ROTI vs magnetic latitude and time"); p.add_argument("--storm", required=True); p.add_argument("--quiet")
    sub.add_parser("summary", help="cross-storm figures + Kp threshold fit")
    sub.add_parser("status", help="what has been processed")
    a = ap.parse_args()
    cfg = load_cfg(a.config); setup_logging(cfg); log = logging.getLogger("global_logger")
    conn = db.connect(cfg["paths"]["db"])

    if a.cmd == "backfill":
        s, days = storm_days(cfg, a.storm)
        pipeline.update_indices(conn, days[0] - dt.timedelta(days=1), days[-1] + dt.timedelta(days=1))
        for day in days:
            for st in pick_stations(cfg, a.stations):
                pipeline.process_station_day(conn, st, day, cfg, force=a.force)
    elif a.cmd == "daily":
        day = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
        pipeline.update_indices(conn, day - dt.timedelta(days=2), dt.datetime.now(dt.timezone.utc).date())
        for st in pick_stations(cfg, a.stations):
            pipeline.process_station_day(conn, st, day, cfg, force=a.force)
    elif a.cmd == "check":
        days = storm_days(cfg, a.storm)[1] if a.storm else [dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)]
        for st in pick_stations(cfg, a.stations):
            res = []
            for day in days:
                f = archives.choose_daily_obs(archives.ga_list(st, day))
                res.append(f"{day}:{'RINEX' + f['version'] if f else 'MISSING'}")
            print(st, " ".join(res), flush=True)
    elif a.cmd == "indices":
        pipeline.update_indices(conn, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    elif a.cmd == "import-home":
        for f in a.db: pipeline.import_home(conn, f, a.start, a.end, cfg=cfg)
    elif a.cmd == "plot":
        from . import plots
        plots.storm_figure(conn, cfg, a.storm, a.quiet)
    elif a.cmd == "summary":
        from . import summary
        X, res = summary.run(conn, cfg)
        print(X.to_string()); print(pd.DataFrame(res).to_string())
    elif a.cmd == "status":
        print(pd.read_sql("select station, status, count(*) days, min(day) first, max(day) last from station_days group by 1,2 order by 1", conn).to_string())
        print(pd.read_sql("select count(*) kp_rows, min(ts_utc), max(ts_utc) from kp_index", conn).to_string())

if __name__ == "__main__":
    main()
