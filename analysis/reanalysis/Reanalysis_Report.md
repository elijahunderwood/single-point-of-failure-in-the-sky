# Independent Reanalysis of the Space-Weather Ground-Station Data

**Project:** "A Single Point of Failure in the Sky" (Elijah Underwood)
**What this is:** a from-scratch reanalysis of the raw data. New Python code was written for every step; none of the earlier results were copied. The new results are then compared, claim by claim, with *A_Single_Point_of_Failure_Results.docx*, called "the previous analysis" below.
**Date:** 10 October 2026
**Code:** `reanalysis/code/` (run `run_all.sh`)
**Figures:** `reanalysis/figures/`
**Numbers:** `reanalysis/output/*.json`

---

## 0. Summary

| Question | Previous analysis said | This reanalysis finds | Verdict |
|---|---|---|---|
| Was the ionosphere over the home site (~55°N) disturbed during the storms? | No. "< 1 % of the day disturbed"; storms no worse than the quiet day | No. In every storm window the network-median ROTI is within ±0.01 TECU/min of hour-matched quiet data. The **95 % upper limit** on any storm increase is **+0.014 TECU/min (about +18 %)**. The share of 5-min satellite windows with ROTI > 0.5 is 1.4–2.9 % in storms and 1.8–3.1 % on quiet days (30° mask). | **Agree on the conclusion.** The "< 1 %" figure is not reproduced and depends on the definition used. |
| Amplitude scintillation (S4) at home | Storms ≤ quiet day; "detection floor S4 ≈ 0.7–1.0" | Storms ≈ quiet days (median S4 proxy 0.108–0.112 in both; 99th percentile 0.36–0.41 in both). The *typical* floor is about 0.11. The 0.6–0.9 values are the **maximum** values, and these happen on quiet days too. | Agree on storms ≈ quiet. The "floor" is wrongly described. |
| Starlink during storms | "No storm-related degradation on any storm", ~30 ms | Only **2 of the 5** storm windows have Starlink data. Comparing Kp ≥ 5 with Kp < 5 blocks gives a latency difference of **+0.05 ms (95 % CI −1.05 to +1.16 ms)** and a drop-rate difference of **0.00 % (CI ±0.02 percentage points)**. Rain had a larger effect than Kp: **+2.6 ms (CI +2.0 to +3.2 ms)**. | Agree, now as a quantified bound. "Any storm" is over-stated. |
| High latitude (Tromsø, Ny-Ålesund) | Disturbed for 12–31 % of storm days vs 4.8 % on the quiet day; median ROTI 0.05 → 0.29 | Tromsø: 16–38 % of satellite windows with ROTI > 0.5 on storm days vs **5.8 %** quiet. Median 0.048 → up to 0.35. Ny-Ålesund: 17–39 % vs 11.6 % quiet. Strongest day 4 Oct at both stations. | **Agree** (numbers similar, slightly higher). A proper elevation mask from real orbits gives almost the same answer as the earlier signal-strength filter. |
| "October storms outrank August despite equal Kp: the equinox effect" | Claimed | The October days had **more total geomagnetic activity** (daily ΣKp 35 and 29 vs 19 and 27). Daily ΣKp alone explains the ranking (Spearman ρ = 0.94, p = 0.005 at Tromsø). With one control day, season cannot be separated. | **Not justified** from these data. |
| Equator (EMBRACE, Brazil) | S4 reaches 1.20 on 4 Oct; 5 Oct quiet; scintillation not tied to storms | Confirmed: BAVC S4 = 1.20, plus GOUR 1.42. **But the event was at 00:04–01:08 UTC on 4 Oct, the evening of 3 Oct local time, which is *before* the storm began** (first Kp ≥ 5 at 09 UTC on 4 Oct). During the storm night (5 Oct 00–06 UTC) S4 stayed below 0.32. | Agree, and the timing makes the point *stronger* than the previous analysis stated. |
| How many storms? | "Five storms, Kp 5.0–5.67" | Kp ≥ 5 occurred in **five separate storms**: 2 Aug, 8 Aug, **18 Aug**, 8 Sep, 4–5 Oct. The previous five counted 4 Oct and 5 Oct as two storms; they are one storm. It also left out 18 Aug, which fell in the logging outage. | **Error** in counting. Effectively 4 storms were tested, each with only 6–12 hours of home data. |
| 1/f² hypothesis | Ku-band is "~60× less sensitive" | Ionospheric **delay** scales as 1/f²: 55× smaller at 11.7 GHz than at L1. Scintillation does **not** follow 1/f². Measured from EMBRACE L1 vs L2: S4 ∝ f^−1.35 (95 % CI 1.28–1.43), so scintillation is only about **15× weaker** at Ku. Even the worst equatorial event (S4 = 1.42 at L1) would give S4 ≈ 0.10 at Ku, which is harmless. | **The conclusion holds, but the "60×" number applies to delay, not scintillation.** |

**Bottom line:** the main conclusion survives an independent check. Moderate storms (Kp ≤ 5.67) did not disturb the ionosphere over the home site, and they did not measurably affect the Starlink Ku-band link. The same storms clearly disturbed the Arctic ionosphere. The new contribution is that the null results are now **numbers with error bars** (upper limits). Several specific claims need correcting (sections 9–10).

---

## 1. Data inventory and quality (`01_inventory.py`, `output/inventory.json`)

### 1.1 What was provided

| File | Contents | Coverage (UTC) | Notes |
|---|---|---|---|
| `spaceweather.db` | Kp (3-h), Dst (1-h), solar-wind plasma & field (1-min) | 22 Jul – **23 Sep** 2026 | **The newer, more complete copy** |
| `spaceweather copy.db` | same tables | 22 Jul – **17/18 Sep** | Despite the later file date (9 Oct), it is an **older, smaller snapshot**. Every row is also in the original, with identical values (464/464 Kp, 1375/1375 Dst, 56 260/56 260 field rows). It adds nothing. |
| `gnss_tec.sql` | SQL dump of the GNSS `tec` + `epoch_log` tables | 22 Sep 03:28 – 23 Sep 02:33 (662 226 rows, 28 satellites) | Only the **last ~23 h** of the database, not the whole record. |
| `gnss_tec.sql copy` | same | 17 Sep 02:46 – 18 Sep 02:39 (683 530 rows) | Again an **older** tail-dump despite the later file date. The two dumps don't overlap. Both turned out useful as extra quiet-day controls. |
| `storm_exports/tec_YYYY-MM-DD.csv` | per-second phase TEC, elevation, C/N0, slip (no code TEC) | 6-h windows: 2 Aug 12–18, 8 Aug 15–21, 8 Sep 03–09, 4 Oct 15–21, 5 Oct 00–06 | `tec_2026-08-18.csv` and `-08-19.csv` are **empty** (logging outage). |
| `gnss_storm_0708sep.csv` | per-second TEC incl. code TEC & L2 | 7 Sep 21:00 – 8 Sep 03:00 | |
| `storm05oct.tar` | GNSS + Starlink + Kp/Dst for 5 Oct | 5 Oct 00–06 | The GNSS file is **identical** to `storm_exports/tec_2026-10-05.csv` (a duplicate). |
| `quiet_ctrl.tar` | 2 Oct quiet day, 00–06 and 12–18 | | The filename says "night" but the file covers 00:00–06:00 (the earlier `head`/`tail` look was misleading because the rows are unsorted, see below). |
| `starlink_0708sep.csv`, `starlink_05oct.csv` | per-second latency/drops | 7 Sep 21 – 8 Sep 03; 5 Oct 00–06 | 7 and 10 missing seconds; no counter resets; no duplicates. |
| `storm_exports/kp_index.csv`, `dst_index.csv` | Kp, Dst | 31 Jul – 10 Oct | No gaps. Identical to the database where they overlap. |
| `hilat_rinex.tar` | 30-s RINEX 3, TRO1 (Tromsø) & NYA2 (Ny-Ålesund) | 2 Aug, 8 Aug, 8 Sep, 2 Oct, 4 Oct, 5 Oct (full days) | TRO1 changed signal types between Aug and Sep (L2W/L2X → L2S/L2W). |
| `embrace_scint.db` | 1-min S4/φ60 on L1, L2, L5 from BAVC, GOUR, MTSR | storm days only (no 2 Oct control) | 669 866 rows. MTSR only on 8 Sep; BAVC has no 8 Sep. |

### 1.2 Quality issues found

1. **None of the per-second CSV files are in time order.** Rows are grouped in an odd storage order. This is the "storage-order artefact" the project mentions. All code here sorts by satellite and time before doing anything. If a script does not sort, ROT values computed across the jumps are nonsense.
2. **No duplicate rows** were found in any home file. But two files are complete duplicates of each other (5 Oct).
3. **Dst single-hour spikes.** 17 hours differ from both neighbours by more than 10 nT. Most of them fall **exactly at 00:00 UTC**: −81 nT on 9 Aug 00:00 (neighbours −63/−51), −62 on 4 Aug 00:00, −73 on 5 Oct 04:00 (neighbours −60/−54). The midnight clustering suggests a quirk of the real-time (provisional) Kyoto Dst feed. I used a 3-hour running median ("robust Dst"). **The 5 Oct −73 nT value quoted in the storm files is probably one of these spikes; the robust value is −60 nT.**
4. **Logging outage 17–31 Aug.** It hid a whole Kp 5.33 storm (18 Aug).
5. **Absolute (code) TEC is not usable as-is.** 96 % of code-TEC values are negative, and code minus levelled-phase TEC has a scatter of 13.5 TECU. The receiver's hardware delay (DCB) is uncalibrated. That doesn't matter for ROTI, which uses *changes* in phase TEC. But any absolute-TEC or eclipse-depth claim needs DCB calibration against global maps first.
6. **Coverage is thin.** Each storm has only 6 hours of home GNSS data (12 h for 7–8 Sep). The previous analysis spoke of "fraction of the **day**" at the home site, but no full storm day exists in the supplied files.
7. **Weather data were not included** in the bundle (no `localweather.db` / `metar.db`). For the rain control I downloaded hourly model rainfall for Belfast from the public Open-Meteo historical-forecast API (54.60°N, 5.93°W). Those are model data, not a rain gauge.

---

## 2. Method, step by step (what you need to be able to defend)

### 2.1 From the receiver to TEC
A dual-frequency receiver measures the carrier phase on L1 (1575.42 MHz) and L2 (1227.60 MHz). The ionosphere delays the two by different amounts (∝ 1/f²). Everything else (distance, clocks, troposphere) is the same on both, so it cancels in the difference:

STEC = K · (L1·λ1 − L2·λ2), where K = f1²f2² / (40.3 (f1² − f2²)) / 10¹⁶ = **9.52 TECU per metre**.

Phase TEC is very smooth (noise ≈ 0.02 TECU) but has an unknown constant offset on each continuous "arc". The offset cancels when we take differences, which is why ROTI uses phase TEC.

### 2.2 Arcs and cycle slips
A cycle slip is when the receiver loses count of whole wavelengths. One L1 cycle is a jump of about 1.8 TECU. If you difference across a slip you get a fake huge ROT. A **new arc** starts when any of the following happens:
- the receiver flags a slip (the `slip` column, from L2 lock time; in RINEX, the loss-of-lock indicator)
- there is a time gap (> 2.5 s at home, > 45 s in RINEX)
- the phase TEC jumps by more than 1 TECU in 1 s (home) or 5 TECU in 30 s (RINEX)

Any |ROT| > 10 TECU/min left over is discarded. Only 0–0.09 % of ROT values were discarded. The results barely change if the jump threshold is 0.5, 1, 2 TECU or switched off: quiet-day median 0.0729 in every case, fraction > 0.5 between 0.9 % and 1.9 %.

### 2.3 Elevation masks
Low satellites give multipath (ground reflections) that look like ionospheric "roughness". I used **20°** (as before) and **30°** (stricter). At Tromsø and Ny-Ålesund there is no elevation in the RINEX files, so I **computed real elevations from IGS broadcast orbits**. I downloaded them from Geoscience Australia's public archive and coded the standard GPS orbit equations myself (`swlib.sat_ecef`). The previous analysis used a signal-strength filter instead.

### 2.4 ROT and ROTI
- Take one sample every **30 s** within an arc. ROT = ΔTEC/Δt in TECU per minute.
- ROTI = standard deviation of ROT inside each **5-minute** window, per satellite. At least 5 ROT values are needed.
- *Why 30 s and not 1 s?* Differencing 1-s samples turns phase noise into fake ROT. On the quiet 22 Sep day the median ROTI is **0.89 TECU/min with a 1-s base**, 0.13 with 10 s, **0.073 with 30 s** and 0.050 with 60 s. With a 1-s base, every satellite would look "disturbed" all the time. (The code documentation's "~3 TECU/min floor" for 1 s is too high; I measure ~0.9.)

### 2.5 Network index
For every 5-minute window, across all satellites:
- the **median**
- the **2nd-highest** value. This needs two satellites to agree, so one satellite with multipath can't trigger it.
- the fraction of satellites above **0.5 TECU/min**, the usual "disturbed" threshold.

### 2.6 Statistics
- **Moving-block bootstrap** for confidence intervals. Neighbouring 5-minute values are correlated, so ordinary formulas would give falsely narrow error bars. The bootstrap resamples whole 30-minute blocks.
- **Wilson intervals** for proportions such as "x % of windows > 0.5". They work even when x = 0.
- **Spearman rank correlation with a block-permutation p-value.** Rank correlation is not fooled by outliers, and the permutation keeps the time-correlation.
- **Upper limit:** when nothing is detected, the upper end of the 95 % confidence interval is reported. It means "any effect is smaller than this."

### 2.7 Validation on synthetic data (`07_validation.py`, Figure 1)
I made 2 hours of fake 1-Hz phase TEC:
- one quiet satellite
- one with a 45-minute irregularity burst **plus a deliberate 1.8-TECU cycle slip**

The pipeline gave:
- **2.0 TECU/min** inside the burst
- 0.053–0.055 outside it and on the quiet satellite (maximum outside the burst 0.12)
- no false alarm from the slip

![Synthetic test](figures/01_synthetic_validation.png)

---

## 3. Home station results (`02_home_roti.py`)

### 3.1 Per window (30° mask unless stated)

| Window | Time (UTC) | Kp max | Dst min in window | Median sat ROTI | Median net-2nd | % sat-windows > 0.5 (20° mask) [95 % CI] | same, 30° mask | S4 proxy median | S4 p99 | S4 max |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 02 Aug | 12:00–18:00 | 5.67 | −2 | 0.078 | 0.098 | 4.3 [2.8–6.5] | 2.4 [1.2–4.5] | 0.109 | 0.38 | 0.58 |
| S2 08 Aug | 15:00–21:00 | 5.67 | −52 | 0.079 | 0.097 | 3.6 [2.2–5.7] | 1.4 [0.6–3.2] | 0.109 | 0.36 | 0.81 |
| S3 07–08 Sep | 21:00–09:00 | 5.0 | −48 | 0.075 | 0.083 | 5.2 [3.8–7.1] | 2.9 [1.8–4.6] | 0.110 | 0.41 | 0.72 |
| S4 04 Oct | 15:00–21:00 | 5.67 | −55 | 0.075 | 0.090 | 4.2 [2.7–6.4] | 2.5 [1.3–4.6] | 0.108 | 0.38 | 0.62 |
| S5 05 Oct | 00:00–06:00 | 5.33 | −73 (spike; robust −60) | 0.076 | 0.081 | 3.9 [2.4–6.5] | 2.9 [1.5–5.5] | 0.112 | 0.40 | 0.94 |
| Q 02 Oct day | 12:00–18:00 | 0.67 | −4 | 0.080 | 0.094 | **6.7** [4.7–9.3] | 3.1 [1.7–5.4] | 0.113 | 0.41 | 0.63 |
| Q 02 Oct night | 00:00–06:00 | 1.0 | −10 | 0.072 | 0.076 | 3.4 [1.9–5.8] | 2.9 [1.5–5.5] | 0.107 | 0.36 | 0.74 |
| Q 17–18 Sep | 24 h | 3.0 | −17 | 0.077 | 0.089 | 4.8 [3.9–5.9] | 1.8 [1.2–2.6] | 0.113 | 0.41 | 0.83 |
| Q 22–23 Sep | 23 h | 0.67 | −9 | 0.073 | 0.085 | 3.4 [2.7–4.4] | 1.9 [1.3–2.8] | 0.107 | 0.37 | 0.78 |

![Home ROTI](figures/02_home_roti_timeseries.png)

The isolated red spikes are single 5-minute windows. They appear on quiet days too: 1.2 TECU/min on 2 Oct 03:15, and four spikes on 17 Sep. So they are local or instrumental effects, not storm effects.

### 3.2 Storm minus quiet, with confidence intervals
Each storm is compared with all quiet data (2 Oct, 17 Sep, 22 Sep; Kp ≤ 3) **from the same UTC hours**, because ROTI depends on time of day.

| Storm | Network median: storm − quiet (TECU/min) [95 % CI] | Network 2nd-highest: storm − quiet [95 % CI] | % sat-windows > 0.5: storm (95 % upper) vs quiet |
|---|---|---|---|
| S1 02 Aug | −0.002 [−0.006, +0.004] | +0.005 [−0.007, +0.011] | 2.4 % (≤ 4.5 %) vs 2.0 % |
| S2 08 Aug | +0.003 [−0.005, +0.014] | +0.008 [−0.003, +0.022] | 1.4 % (≤ 3.2 %) vs 1.6 % |
| S3 07–08 Sep | +0.002 [−0.001, +0.008] | +0.003 [−0.002, +0.012] | 2.9 % (≤ 4.6 %) vs 2.3 % |
| S4 04 Oct | −0.001 [−0.007, +0.006] | +0.001 [−0.009, +0.007] | 2.5 % (≤ 4.6 %) vs 1.6 % |
| S5 05 Oct | −0.000 [−0.006, +0.011] | +0.001 [−0.009, +0.014] | 2.9 % (≤ 5.5 %) vs 2.9 % |

![Storm minus quiet](figures/03_home_storm_minus_quiet.png)

**What you can say:** every confidence interval contains zero. The largest possible storm increase allowed by the data is **+0.014 TECU/min in the median and +0.022 in the 2nd-highest index**. That is about 1/35 of the 0.5 "disturbed" threshold. At the 95 % confidence level, these storms raised the home-site ROTI by less than ~20 %.

Correlations agree. Across all 1 140 home 5-minute windows:
- Kp vs network median ROTI: Spearman ρ = 0.07 (p = 0.20)
- Dst vs network median ROTI: ρ = −0.05 (p = 0.35)

Neither is significant.

### 3.3 Amplitude scintillation (S4) proxy
S4 is computed from 1-Hz C/N0 (signal strength in whole dB-Hz): intensity I = 10^(C/N0/10), and S4 = std(I)/mean(I) over 60 s, for elevation ≥ 30°. Storms and quiet periods look the same:
- median 0.107–0.113
- 99th percentile 0.36–0.41
- maxima 0.58–0.94; the quiet days reach 0.83

![S4 proxy](figures/04_home_s4_proxy.png)

**Correction to the previous analysis.** It said the "detection floor" is S4 ≈ 0.7–1.0. The typical noise level is ~0.11. What reaches 0.7–0.9 is the **occasional maximum**, which shows up equally on quiet days. The right statement is: "occasional single-minute values up to ~0.9 occur from multipath and quantisation even on quiet days, so only sustained, multi-satellite S4 above ~0.5 could be called real scintillation with this receiver."

Real S4 needs 50-Hz raw amplitude. A 1-Hz C/N0 proxy can **miss** fast fading, so this is a weak test. Also, the previous text called the home station "single-frequency"; the receiver is dual-frequency, but C/N0 is only reported in whole dB.

---

## 4. Starlink (`03_starlink.py`)

| | 7–8 Sep (21–03 UTC) | 5 Oct (00–06 UTC) |
|---|---|---|
| Kp during window | **4.33 only** (Kp 5 came later, at 06–09 UTC on 8 Sep) | 4.0 then 5.33 |
| Median / 95th-pct latency | 30.3 / 45.5 ms | 32.3 / 47.5 ms |
| Mean drop rate | 0.033 % | 0.048 % |
| Fully dropped seconds | 0 | 0 |
| Model rainfall | 0.0 mm | 0.3 mm |

**Effect sizes** (5-min blocks, block bootstrap):
- Latency, Kp ≥ 5 minus Kp < 5: **+0.05 ms [−1.05, +1.16]**. Upper limit about 1.2 ms, or **~4 % of the 30 ms median**.
- Drop rate, Kp ≥ 5 minus Kp < 5: **0.000 [−0.0002, +0.0002]**, i.e. less than 0.02 percentage points.
- Rain (> 0.1 mm/h) minus dry: latency **+2.6 ms [+2.0, +3.2]** and drops +0.03 percentage points [+0.01, +0.06]. Rain is the only factor with a detectable effect, and it is small. This is only 12 wet 5-min blocks from one rainy hour, so treat it with care.
- Regression of latency on Kp + rain + window offset: Kp coefficient **−0.95 ms per Kp unit [−2.16, +0.03]**. There is no positive (harmful) Kp effect after allowing for rain.
- Correlations (block permutation):
  - ROTI vs latency: ρ = −0.02 (p = 0.88)
  - ROTI vs drops: ρ = −0.11 (p = 0.25)
  - rain vs latency: ρ = +0.33 (p = 0.02)

![Starlink](figures/05_starlink_vs_drivers.png)

**Caveats.** There are only 12 hours of Starlink data and only 3 hours at Kp ≥ 5. There is **no quiet-day Starlink file** in the bundle, so "storm vs quiet" for Starlink can only be done *within* the storm windows. The claim that Starlink was unaffected "on any storm" applies to 2 of the 5 windows. The statement that is fully supported is: "on the two storm windows with Starlink data, any Kp-related latency change was smaller than about 1 ms and any drop-rate change smaller than 0.02 percentage points."

---

## 5. High latitude: Tromsø and Ny-Ålesund (`04_highlat.py`)

20° mask, real orbit-based elevations, each station compared with its **own** 2 Oct quiet day.

| Station / day | Daily ΣKp | % sat-windows ROTI > 0.5 [95 % CI] | Median ROTI | Network median: storm − quiet [95 % CI] | ratio |
|---|---|---|---|---|---|
| TRO1 02 Oct (quiet) | 6.0 | **5.8** [4.9–6.9] | 0.048 | – | – |
| TRO1 02 Aug | 19.3 | 15.7 [14.3–17.2] | 0.071 | +0.014 [+0.001, +0.039] | 1.3 |
| TRO1 08 Aug | 27.3 | 19.5 [17.9–21.2] | 0.116 | +0.028 [+0.005, +0.193] | 1.7 |
| TRO1 08 Sep | 32.0 | 25.2 [23.5–27.1] | 0.246 | +0.189 [+0.148, +0.222] | 5.3 |
| TRO1 04 Oct | 35.0 | **38.1** [36.1–40.1] | 0.353 | +0.276 [+0.188, +0.443] | 7.3 |
| TRO1 05 Oct | 28.7 | 26.4 [24.6–28.2] | 0.254 | +0.259 [+0.111, +0.316] | 6.9 |
| NYA2 02 Oct (quiet) | 6.0 | **11.6** [10.4–13.0] | 0.187 | – | – |
| NYA2 02 Aug | 19.3 | 22.4 | 0.245 | +0.055 [−0.011, +0.122] | 1.3 |
| NYA2 08 Aug | 27.3 | 16.6 | 0.222 | +0.033 [−0.024, +0.088] | 1.2 |
| NYA2 08 Sep | 32.0 | 23.4 | 0.268 | +0.123 [+0.048, +0.187] | 1.7 |
| NYA2 04 Oct | 35.0 | **39.4** | 0.393 | +0.217 [+0.138, +0.300] | 2.2 |
| NYA2 05 Oct | 28.7 | 34.9 | 0.339 | +0.188 [+0.120, +0.266] | 2.1 |

![High latitude](figures/06_highlat_roti_by_hour.png)

**Comparison with the previous analysis:**
- **Tromsø quiet median 0.048** (previous: 0.05). **Agree.**
- Storm-day disturbed fraction: 16–38 % here, 12–31 % before. Same pattern, slightly higher values. The exact numbers depend on the definition ("fraction of satellite-windows" here; the previous definition isn't stated).
- The signal-strength-filter method (no elevation mask) gives almost the same numbers (e.g. TRO1 4 Oct 40.2 % vs 38.1 %). So the previous shortcut didn't bias the result much. Its own caveat holds.
- At **Ny-Ålesund the August storm days are not significantly different from the quiet day** (CIs include 0). The "same pattern at both stations" statement is only true for September and October.
- Disturbance tracks **daily total activity**. Spearman ρ between daily ΣKp and disturbed fraction is **0.94 (p = 0.005)** at Tromsø and **0.89 (p = 0.02)** at Ny-Ålesund (n = 6 days each).
- **The "equinox effect" claim is not supported.** October had more total activity than August. The quiet control is from October. Summer (24-h sunlight) and equinox conditions differ for reasons other than Russell–McPherron coupling. With one control day and 2–3 storms per season, the equinox effect cannot be separated from storm size. It is fine to mention as a possible explanation, not as a finding.

---

## 6. Equatorial check: EMBRACE, Brazil (`05_embrace_freq.py`)

S4 on L1 for elevation ≥ 30°. "Night" = 22–06 UTC, about 18–02 local time, when equatorial plasma bubbles form.

| Station / UTC day | Max S4 (time) | Night minutes with S4 > 0.5 | Night % with S4 > 0.3 |
|---|---|---|---|
| BAVC 02 Aug | 0.20 | 0 | 0.0 |
| BAVC 08 Aug | 0.66 (03:44) | 16 | 0.9 |
| **BAVC 04 Oct** | **1.20 (00:04)** | 64 | 1.4 |
| BAVC 05 Oct | 0.22 (daytime) | 0 | 0.0 |
| GOUR 02 Aug / 08 Aug / 08 Sep | 0.27 / 0.31 / 0.19 | 0 | 0.0 |
| **GOUR 04 Oct** | **1.42 (01:08)** | 67 | 4.4 |
| GOUR 05 Oct | 0.32 (daytime) | 0 | 0.0 |
| MTSR 08 Sep | 0.55 (10:16, daytime) | 0 | 0.0 |

![EMBRACE](figures/07_embrace_s4_by_hour.png)

- The strong event (S4 1.2–1.4) happened at **00–01 UTC on 4 Oct**. That is the evening of **3 Oct** local time, **8–9 hours before the first Kp ≥ 5** (09 UTC, 4 Oct). On the actual storm night (5 Oct 00–06 UTC, Kp 4–5.3, Dst down to −60 nT) S4 stayed at or below 0.32 and the night values were ≤ 0.10.
- So the previous conclusion ("scintillation exists but doesn't follow the storms") is **confirmed and strengthened**. The biggest equatorial event came *before* the storm, and the storm night was quiet. That fits known physics: storm-time "disturbance dynamo" electric fields often *suppress* bubbles.
- Missing: no quiet-day (2 Oct) EMBRACE data were supplied, so an equatorial quiet baseline can't be computed. MTSR and BAVC are not present on all days. Daytime maxima (e.g. MTSR 0.55 at 10 UTC) are probably multipath, not bubbles.

---

## 7. The frequency (1/f²) hypothesis, tested quantitatively

EMBRACE receivers measure S4 on three frequencies at once, which allows a direct test. For weak-to-moderate scintillation (0.3 ≤ S4_L1 ≤ 0.7), with S4 ∝ f^−n:

| Pair | Points | Median S4 ratio | If n = 1.5 | If n = 2 | Measured n [95 % CI] |
|---|---|---|---|---|---|
| L2 / L1 | 266 | 1.40 | 1.45 | 1.65 | **1.35 [1.28, 1.43]** |
| L5 / L1 | 329 | 1.36 | 1.55 | 1.79 | 1.06 [1.03, 1.10] |

![Frequency scaling](figures/08_frequency_scaling.png)

- Scintillation clearly gets **stronger at lower frequency**, as the hypothesis needs. The rate is close to the weak-scatter theory value **n ≈ 1.5**, and **not 2**. (L5 gives a lower value. Selecting points by their L1 value biases the ratio low, and L5 tracking differs, so trust the L2 value more.)
- **Extrapolating to Starlink Ku-band (~11.7 GHz):**
  - **Delay** (1/f²): 55× smaller than at L1. A 50-TECU path gives 8.1 m at L1 but only ~0.15 m at Ku.
  - **Scintillation** (f^−1.35): only about **15× smaller**. The strongest equatorial value seen (S4 = 1.42 at L1) becomes **S4 ≈ 0.10 at Ku**, which a link easily tolerates.
- So the hypothesis is **supported quantitatively**. Ku-band is effectively immune to the scintillation levels measured anywhere in these data. But the protection factor for scintillation is ~15×, not ~60×. The previous text ("scintillation weakens with frequency roughly as 1/f²… about 60× less sensitive") **mixed up delay and scintillation**. The Starlink link that *could* share GPS's weakness is direct-to-cell (~2 GHz), which would have S4 only ~1.4× smaller than GPS L1.
- Phase scintillation (σφ) theoretically scales as 1/f. It wasn't fitted here, but `phi60` columns are in the database for a follow-up.

---

## 8. Superposed-epoch analysis (`06_sea_correlations.py`)

Storm onset is defined as the first 3-hour block with Kp ≥ 5. Blocks within 24 h are merged into one storm.

| Onset (UTC) | Kp max | Dst min raw / robust (nT) | Min hourly Bz (nT) | Max Vsw (km/s) | Home GNSS hours within −24…+48 h |
|---|---|---|---|---|---|
| 02 Aug 15:00 | 5.67 | −62 / −50 | −11.9 | 426 | 6 |
| 08 Aug 12:00 | 5.67 | −81 / −65 | −15.9 | 447 | 6 |
| 18 Aug 03:00 | 5.33 | −47 / −37 | (outage) | (outage) | **0** |
| 08 Sep 06:00 | 5.0 | −48 / −40 | −5.5 | 594 | 12 |
| 04 Oct 09:00 | 5.67 | −73 / −60 | (no solar-wind data after 23 Sep) | – | 12 |

![SEA drivers](figures/09_sea_drivers.png)

The superposed mean shows a classic moderate storm:
- Bz turns southward (mean about −10 nT) right at onset
- solar wind speeds up from ~300 to ~450 km/s
- robust Dst bottoms out near −35 nT on average, 10–20 h after onset

A superposed-epoch analysis of the **home ionosphere** is limited to the exported windows (Figure 10). Every available point stays inside the quiet-day 5–95 % range. A proper analysis needs the *continuous* GNSS database (24–48 h around each onset), which wasn't in the bundle.

![SEA home](figures/10_sea_home_roti.png)

Note: the **S1 (2 Aug) home window (12–18 UTC) ends before Dst reached its minimum** (−47 nT at 23 UTC on 3 Aug) and saw Dst of only −2 nT. That window tests the onset, not the main phase.

---

## 9. Errors, unjustified claims and weaknesses in the previous analysis

1. **Storm count.** "Five storms" double-counts 4 Oct and 5 Oct, which are one storm (Kp 5.67 → 4.67 → 4.0 → 5.33 with no quiet gap). It also misses the 18 Aug storm (Kp 5.33), which fell in the logging outage. The honest description is "4 storms tested (6–12 h of home data each); a 5th occurred during an outage."
2. **"< 1 % of the day disturbed" at the home site is not reproduced.**
   - 1.4–2.9 % of satellite-windows exceed 0.5 with a 30° mask (3.6–5.2 % with 20°).
   - The robust network index exceeds 0.5 in 0–4 % of windows.
   - Quiet days give the same values. The *conclusion* (no storm effect) stands; the number should be replaced, with its definition stated.
   - Also, only 6-hour windows exist, so "of the day" is wrong.
3. **"Detection floor S4 ≈ 0.7–1.0"** describes the occasional maximum, not a floor. The typical level is ~0.11.
4. **"Single-frequency station"** is inconsistent: the receiver is dual-frequency (ZED-F9P, L1+L2). The limitation is 1-Hz, whole-dB C/N0, not single frequency.
5. **"Scintillation weakens roughly as 1/f²", "~60× less sensitive".** Delay scales as 1/f² (55× at 11.7 GHz). Scintillation measured here scales as f^−1.35, so ~15×. The conclusion is unchanged but the physics statement is wrong.
6. **"Equinox effect"** is not shown: it is confounded with total storm activity (ΣKp) and season, and there is a single control day.
7. **Starlink "no degradation on any storm".** Starlink data exist for only 2 storm windows. The 7–8 Sep window never reached Kp 5 (Kp 4.33). There is no quiet-day Starlink comparison. The effect is now bounded at ≤ ~1.2 ms latency and ≤ 0.02 percentage points drops.
8. **Representative storm "Dst −48 nT, Kp above 4" (7–8 Sep).** Correct for that window, but Kp only reached 5 at 06 UTC on 8 Sep. That hour is in the GNSS file (until 09 UTC) but not in the Starlink file.
9. **Dst values quoted from single-hour spikes** (−81 nT on 9 Aug, −73 nT on 5 Oct). Robust values are −65 and −60 nT.
10. **Equatorial timing.** The 4 Oct S4 = 1.20 event was *before* storm onset. That isn't wrong in the previous text, but it should be stated, because it is the strongest evidence for the "not storm-driven" argument. Also GOUR (S4 1.42) wasn't mentioned.
11. **No confidence intervals or significance tests** anywhere in the previous results. Every "no effect" was a visual judgement, and "indistinguishable" was never quantified. This reanalysis supplies the numbers (sections 3–5).
12. **Single quiet control (2 Oct)** for everything. Seasonal and diurnal mismatch is possible, e.g. August storms vs an October control at Tromsø. Here, the 17 Sep and 22 Sep dumps were added and UTC hours were matched at the home site.
13. **ROTI from a 1-Hz consumer receiver vs 30-s geodetic RINEX** are not directly comparable in absolute terms (different noise). Comparing each site with its *own* control (as both analyses did) is the right approach.
14. **The "fraction of the day disturbed" definition is never stated** in the previous text. Here, three definitions are reported: per-satellite windows, network median and network 2nd-highest.

## 10. What could not be done with the supplied data
- **Home-site full storm days and a continuous superposed-epoch analysis.** Only 6–12 h windows plus two 24-h quiet dumps were supplied; the full `gnss_tec.db` would allow it.
- **Weather from the station's own loggers** (`localweather.db`, `metar.db`) was not included. Open-Meteo model rain for Belfast was used instead.
- **Starlink quiet-day data** and Starlink during the other storms.
- **EMBRACE quiet-day baseline** (no 2 Oct data). BAVC has no 8 Sep, and MTSR has one day only.
- **Solar wind after 23 Sep** (needed for the 4–5 Oct storm). The newer `spaceweather.db` stops on 23 Sep.
- **Absolute TEC validation against IGS global maps (IONEX)** and the eclipse analysis. Code TEC has an uncalibrated receiver bias, and IONEX download from NASA CDDIS needs a login, which I don't have.
- **The previous analysis' own scripts** (`compute_roti.py` etc.) were not in the bundle, only described in Code_Documentation. Everything was re-implemented from those descriptions and standard methods.

## 11. Suggested next steps
1. Export the **full** `gnss_tec.db` and Starlink history for ±2 days around each storm and quiet days in Aug–Oct. Then rerun `02_home_roti.py` and `06_sea_correlations.py` for a true superposed-epoch analysis with quiet days matched by season.
2. Add one or two **nearby UK/Irish reference stations** (e.g. from the EUREF network) through `04_highlat.py`. The RINEX reader and orbit code already work, so this tests the home receiver directly.
3. Replace quick-look Dst with **Kyoto provisional/final Dst** and Kp with **GFZ definitive Kp**.
4. State results as **upper limits**, e.g. "storm-time ROTI increase < 0.014 TECU/min (95 %)" and "Starlink latency change < 1.2 ms (95 %)". This is how professional papers report null results.

---

### Figure list
1. `figures/01_synthetic_validation.png`: pipeline test on synthetic data
2. `figures/02_home_roti_timeseries.png`: home ROTI, all storm and quiet windows
3. `figures/03_home_storm_minus_quiet.png`: effect sizes with 95 % CIs
4. `figures/04_home_s4_proxy.png`: S4 proxy distributions
5. `figures/05_starlink_vs_drivers.png`: Starlink vs Kp, Dst, ROTI, rain
6. `figures/06_highlat_roti_by_hour.png`: Tromsø and Ny-Ålesund storm vs quiet
7. `figures/07_embrace_s4_by_hour.png`: equatorial S4 by hour
8. `figures/08_frequency_scaling.png`: S4 L2/L5 vs L1, frequency exponent
9. `figures/09_sea_drivers.png`: superposed-epoch analysis of Kp, Dst, Bz, solar-wind speed
10. `figures/10_sea_home_roti.png`: home ROTI relative to storm onsets

### Code list (`reanalysis/code/`)
- `swlib.py`: all core functions (TEC/ROT/ROTI, S4 proxy, bootstrap, Wilson interval, block-permutation Spearman, RINEX reader, GPS orbit/elevation)
- `01_inventory.py` … `07_validation.py`: one script per section
- `run_all.sh`: reruns everything

*AI disclosure:* this reanalysis and report were produced with AI assistance (Grok Bot) for Elijah to check, understand and own. Each method is explained above so it can be defended in person.
