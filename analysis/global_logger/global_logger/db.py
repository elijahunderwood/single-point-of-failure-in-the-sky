"""db.py - SQLite storage. Column names and units follow Elijah's Data Dictionary
(roti / roti_network tables, ts_utc ISO-8601 UTC strings) with an added `station`
column so many sites fit in one database."""
import sqlite3

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS stations(
  station TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, height_m REAL, geomag_lat REAL,
  band TEXT, receiver TEXT, antenna TEXT, interval_s REAL, archive TEXT);
CREATE TABLE IF NOT EXISTS roti(            -- per-satellite ROTI, per 5-min window
  window_start TEXT, station TEXT, sv INTEGER, roti REAL, n_samples INTEGER, mean_elev REAL,
  PRIMARY KEY(window_start, station, sv));
CREATE TABLE IF NOT EXISTS roti_network(    -- combined ROTI across satellites, per window
  window_start TEXT, station TEXT, roti_max REAL, roti_2nd REAL, roti_med REAL, roti_mean REAL,
  n_sats INTEGER, frac_gt05 REAL, PRIMARY KEY(window_start, station));
CREATE TABLE IF NOT EXISTS kp_index(ts_utc TEXT PRIMARY KEY, kp REAL, status TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS dst_index(ts_utc TEXT PRIMARY KEY, dst REAL, product TEXT);
CREATE TABLE IF NOT EXISTS station_days(    -- one row per station per UTC day: the resume log
  station TEXT, day TEXT, status TEXT, file TEXT, n_obs INTEGER, n_windows INTEGER,
  rot_rejected_pct REAL, message TEXT, updated_utc TEXT, PRIMARY KEY(station, day));
CREATE TABLE IF NOT EXISTS fetch_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts_utc TEXT, source TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_net_station ON roti_network(station, window_start);
"""

def connect(path):
    c = sqlite3.connect(path, timeout=60)
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript(SCHEMA)
    return c
