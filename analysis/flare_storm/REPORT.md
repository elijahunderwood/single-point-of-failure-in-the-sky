# Solar flares, geomagnetic storms and the "double whammy": what Elijah's data can and cannot show

**Prepared:** 25 October 2026 (analysis notes for Elijah's own write-up; the wording of the report, logbook and poster must be his).
**All event times are UTC** (Coordinated Universal Time). Belfast is on GMT (UTC+0) from 25 October.
**Folder:** `analysis/flare_storm/` in this repository (scripts here; numbers in `tables/`, figures in `figures/`).

## Abbreviations (spelled out on first use)
GNSS = global navigation satellite systems (GPS, Galileo, GLONASS, BeiDou); GPS = Global Positioning System; TEC = total electron content (TECU = 10^16 electrons per m², about 16 cm of extra range delay at the GPS L1 frequency per TECU overhead); ROTI = rate of TEC index (how "rough" the ionosphere is, TECU per minute); C/N0 = carrier-to-noise-density ratio (signal strength, dB-Hz); S4 and σφ (sigma-phi) = amplitude and phase scintillation indices; Kp = planetary K-index (0–9, three-hourly); Dst = disturbance storm-time index (nT; more negative = bigger storm); G1–G5 = NOAA (National Oceanic and Atmospheric Administration) geomagnetic storm scale (G3 = Kp 7−, G4 = Kp 8−, G5 = Kp 9− or more); GOES = Geostationary Operational Environmental Satellite (measures solar X-rays); M5+ = flare with peak 0.1–0.8 nm X-ray flux ≥ 5×10⁻⁵ W m⁻²; X = flux ≥ 10⁻⁴ W m⁻²; SZA = solar zenith angle (0° = Sun overhead); CME = coronal mass ejection; SBAS = satellite-based augmentation system (WAAS in the USA, EGNOS in Europe); RTK = real-time kinematic positioning; HF = high-frequency radio (3–30 MHz); CI = confidence interval; LEO = low Earth orbit.

---

## 1. Summary in plain English

1. **Flares at Belfast (own receiver): no measurable effect.** Across 9 sunlit M-class flares (Sep–Oct 2026), the receiver showed no change in signal strength, satellites tracked, or LEO broadband latency that stood out from the "control" days. The size of any TEC jump was too small to measure against the noise. This is a **null result with upper limits**, and is expected: the low autumn Sun at Belfast (SZA 59–78° for these flares) and only M-class flares (no X-class since logging began).
2. **Flares worldwide (same method, 17 stations): detectable but small.** M5–M9 flares produced a credible TEC jump at **38% of station-flares** (8 of 21; 95% CI 21–59%), compared with **4.5%** for M1–M5 flares and **0 of 9** control windows. Typical jumps were **0.3–0.9 TECU** (5–15 cm of range) starting about 2–12 minutes after the X-ray peak. Morpeth (England, nearest Belfast in latitude) saw **0.57 TECU** for the M8.2 flare on 20 Aug and **0.79 TECU** for the M6.8 on 8 Oct.
3. **Storms (own and worldwide data): the effect depends on storm size and latitude.** At Arctic stations, 20–60% of satellites were "rough" (ROTI > 0.5) on every G3–G5 storm day, compared with 1–6% on quiet days. At **Morpeth**, the figure was **13–16% on the two G5 days of May 2024 and 14% on 10 Oct 2024**, but only 0–3% on G4 days and **0.7% for Elijah's own G3 storm on 10 Oct 2026** (quiet: 0%). Belfast's own receiver showed only a small rise in the G3 storm (2.6% vs 0.65% of satellite windows, from one storm only). LEO broadband latency showed **no storm effect** (−1.4 ms, 95% CI −3.5 to +0.1 ms, 30 storm hours).
4. **The double whammy is common, and it is NOT just chance.** Over 1996–2026 (150 G3+ storms, 873 M5+ flares):
   - **48% of G3+ storms** (72 of 150) had an M5+ flare in the 3 days before onset, against **20% expected by chance** (2.4×; p < 0.001).
   - For bigger storms the link is stronger: **69% of G4+** (38 of 55) and **14 of 15 G5 storms** had an M5+ flare in the 3 days before.
   - **"Both at once":** in **10% of G3+ storms** (15 of 150) an M5+ flare happened *during* the storm (chance 4.5%). Examples: Halloween 2003, July 2000, November 2004, May 2024, and **Elijah's own storm on 10 Oct 2026** (M6.6 flare at 15:10, in the same 3-hour block as the storm onset).
   - **Is "both at once" worse than the two separately?** Tested in section 5.4: **cannot tell** for a flare during a storm (extra +1.1 TECU, 95% CI −0.5 to +3.5, n = 13); **no different** for a flare after a storm (+0.01 TECU, −0.32 to +0.34, n = 48).
   - **"Storm followed by a flare":** 32% of G3+ storms had an M5+ flare in the 3 days after the storm ended (chance 20%).
   - In the 8 solar-maximum years (2000–05, 2024–25), **51 of 87 G3+ storms (59%)** had an M5+ flare before or during them, about **6 compound events per year**. 19 of the 31 years had at least one.
5. **But the link is one-way and incomplete.** Only **26% of X flares** (94 of 358) were followed by a G3+ storm within 3 days. So **3 in 4 big flares bring no big storm** (example: Oct 2014, six X flares, Kp never above 5). And **47% of G3+ storms had no M5+ flare** within 3 days either side (examples: St Patrick's Day 2015, G4 from a C9.1 flare; April 2023, G4 from an M1.7).
6. **Verdict on the key message.** "Compound or sequential flare-and-storm events are common enough over a solar cycle that planners should treat them as expected, not exotic." **This is supported** for storms of G3 and above, and most strongly for G4–G5. It needs two qualifiers:
   - the effects of a flare and a storm usually arrive at different times (flare: minutes, sunlit side; storm: 1–3 days later, hours long, worst at high latitude);
   - a flare is a poor predictor of a storm.

---

## 2. Data inventory (task A)

| Data set | Coverage (UTC) | Notes |
|---|---|---|
| Belfast receiver, 1 Hz TEC/C/N0 (`gnss_tec.db`) | 30 Jul – 25 Oct 2026 | **Gaps:** 14–31 Aug (logging outage); **new overnight gaps of about 14 h** on 23/24 Oct (23:20–13:40) and 25 Oct (01:10–14:54). The 20 Hz raw files cover these hours completely (0 missed epochs), so only the 1 Hz database is affected. **Worth checking (see §9).** |
| Belfast ROTI (`roti.db`) | 30 Jul – 25 Oct 2026 | 5-minute ROTI per satellite |
| Belfast 20 Hz scintillation (`scint.db`) | 23 Oct 16:37 – 25 Oct 2026 | Quiet conditions only (Kp ≤ 4.3), so there is no storm or flare test yet |
| LEO broadband dish (`starlink_history.db`) | 28 Jul – 25 Oct 2026 | 1 s latency and drop; hourly analysis used 1,689 h |
| GOES flares (`flare.db`) | 30 Jul – 25 Oct 2026 | 225 B, 356 C, **26 M, 0 X** flares |
| Kp, Dst, solar wind (`spaceweather.db`) | 22 Jul – 25 Oct 2026 | Kp ≥ 5 on 23 Jul, 2 Aug, 8 Aug, 18–19 Aug, 8 Sep, 4–5 Oct, **10 Oct (G3: Kp 7.0 in the local feed, 7.33 GFZ)** |
| Global archive (`global_roti.db`, 17 stations) | Storm days 2023–2026 plus Oct 2026 daily | Apr 2023 G4, May 2024 G5, Aug 2024 G4, Oct 2024, Jun 2025 G4, Nov 2025, Oct 2026, plus 12 quiet days (daily maximum Kp ≤ 3) |
| Weather (`localweather.db`, `metar.db`) | 27 Jul – 25 Oct 2026 | Hourly rain (model) used as the LEO broadband control |
| **Public catalogues (fetched 25 Oct 2026)** | 1996 – 24 Oct 2026 | See §7 for sources. **No flare list covers 1 Jan – 8 Feb 2017**, so storms within 4 days of that gap are excluded |

**M-class flares in Elijah's data window:**
- **Belfast sunlit, with receiver data:** 4 Sep M1.2; 5 Sep M1.0; 6 Oct M1.9; **8 Oct M6.8 (15:48)**; 9 Oct M1.4; 10 Oct M1.2; **10 Oct M6.6 (15:10)**; 16 Oct M1.3; 19 Oct M1.6.
- **Biggest overall:** **M8.2 on 20 Aug** and **M7.1 on 25 Aug**, both in the Belfast logging gap but measured at global stations.

The full list is in `tables/belfast_flare_event_metrics.csv` and `flare.db`.

---

## 3. Flare impacts (task B)

### 3.1 Belfast: superposed-epoch study (`scripts/03_flare_belfast.py`, Figure 2)
- **Method.** For each flare, I took a window from 60 minutes before to 90 minutes after the X-ray peak, and two windows with no flare:
  - the same clock time 24 hours earlier;
  - **one sidereal day earlier** (23 h 56 min). The GPS satellites are then in the same places, so multipath repeats and cancels out.
- **Quality rule (fixed before looking).** Only elevations of 30° or more are used. TEC arcs with residual noise above 0.5 TECU are rejected.
- **Effect.** The effect is (flare-window change) minus (control-window change). I report the median over events, with a bootstrap 95% CI.

| Metric (M flares, sunlit, vs sidereal control) | Median effect | 95% CI | Events |
|---|---|---|---|
| TEC jump, vertical (TECU) | +0.07 | −0.13 to +0.65 | 4 (only flares with clean arcs on both days) |
| C/N0 L1 (dB-Hz) | −0.11 | −0.14 to +0.10 | 9 |
| C/N0 L2 (dB-Hz) | +0.03 | −0.04 to +0.10 | 9 |
| GPS L1/L2 pairs tracked | −0.16 | −0.47 to +0.19 | 9 |
| LEO broadband latency (ms) | +0.87 | −1.5 to +5.7 | 8 |
| LEO broadband ping drop (percentage points) | +0.002 | −0.02 to +0.06 | 8 |

- **Detections.** With a "jump > 3× noise" rule, there were **0 detections in 14 usable flare windows** and 1 in 23 control windows. The flare logger's own (looser) rule gave 2 of 9 flares and 0 of 9 controls.
- **Conclusion.** A Belfast flare signal is marginal at best and depends on the detection method.
- **Night check.** The M flares that happened in Belfast darkness show no effect either (as physics predicts: the X-rays and EUV only reach the sunlit side).
- **Upper limits to quote:**
  - C/N0 drop no larger than about **0.15 dB-Hz** for M1–M7 flares at SZA 59–78°;
  - LEO broadband latency change no larger than about **+6 ms**;
  - satellites tracked fell by less than about **0.5**.
- **Decay time.** I could **not measure a TEC decay time at Belfast**, because no jump was detected. The literature gives "rises in minutes, decays over tens of minutes to about 3 h for the largest events" (Tsurutani et al. 2005; see `autonomy/flare_autonomy_research.md`).
- **Correction to an earlier result.** The 3–4 dB raw C/N0 "dips" near the 9–10 Oct flare peaks (`autonomy/flare/cno_check.json`) also appear on the sidereal control day. They are **multipath from satellite geometry, not the flare**. Please do not quote them as a flare effect.

### 3.2 Worldwide stations (`scripts/05_global_flare.py`, Figure 3)
The flare logger's response table has 282 usable station-flare results for 26 M flares at 18 stations (17 archive stations plus Belfast). I counted a detection as "credible" if the TEC peak came 0–15 minutes after the X-ray peak with SZA < 85°. Polar-cap and noisy stations were excluded from the rates.

| Group | Station-flares | Credible detections | % (95% CI) | Median jump (TECU) |
|---|---|---|---|---|
| M1–M2 | 110 | 5 | 4.5 (2.0–10.2) | 0.45 |
| M2–M5 | 22 | 1 | 4.5 (0.8–21.8) | 0.49 |
| **M5–M9** | 21 | 8 | **38.1 (20.8–59.1)** | 0.47 |
| SZA < 50° | 27 | 5 | 18.5 (8.2–36.7) | 0.57 |
| SZA 50–70° | 69 | 6 | 8.7 (4.0–17.7) | 0.46 |
| SZA 70–85° | 45 | 3 | 6.7 (2.3–17.9) | 0.48 |
| SZA 85–90° | 12 | 0 | 0 (0–24) | – |
| Controls (24 h earlier, Belfast) | 9 | 0 | 0 (0–30) | – |

- **Main finding.** Bigger flares and a higher Sun give more detections, but even M5–M9 flares give only about **0.3–0.9 TECU** (5–15 cm at L1, vertical).
- **Why it barely matters for ordinary receivers.** That is small compared with normal single-frequency GPS errors (metres). For dual-frequency receivers it cancels out.
- **Why it can matter for RTK.** RTK and SBAS rely on corrections, so a *rapid* change across many satellites at once is the concern. Elijah's earlier flare-scaling work (`autonomy/flare/flare_extrapolation.csv`) extrapolates to about 0.7 TECU for X1 and about 7 TECU for X10 (factor-3 band).

### 3.3 What a flare does that Elijah's equipment cannot measure (from the literature)
- **Solar radio bursts at L-band** can cut C/N0 by up to about 17–20 dB and cause loss of lock for minutes. Examples: 6 Dec 2006, when WAAS lost vertical guidance for about 15 minutes; the Cerruti et al. 2008 measurements.
- **HF radio blackouts** last tens of minutes to hours, according to the NOAA R-scale.
- None of the 2026 flares were in this class. Elijah's equipment would show a burst as a simultaneous C/N0 drop on all satellites, and **none was seen**.

---

## 4. Storm impacts (task C)

### 4.1 Worldwide storm days (`scripts/04_storms.py`, Figure 4, `tables/global_storm_days_pct_roti_gt05.csv`)
The table gives the % of satellite 5-minute windows with ROTI > 0.5 TECU/min, as a daily mean.

| Station (magnetic latitude) | Quiet median | Apr 2023 G4 | May 2024 G5 (11th) | Oct 2024 (10th) | Nov 2025 (12th) | **10 Oct 2026 G3 (own)** |
|---|---|---|---|---|---|---|
| Tromsø (67.5°) | 6.1 | 40.4 | 50.9 | 38.7 | 61.6 | 27.6 |
| Kiruna (65.6°) | 2.2 | 35.6 | 56.8 | 36.1 | 54.8 | 23.0 |
| **Morpeth (57.2°, ≈ Belfast)** | **0.0** | 2.7 | **15.8** | **14.3** | 8.4 | **0.7** |
| Herstmonceux (52.7°) | 0.0 | 0.5 | 1.1 | 3.0 | 2.3 | 0.0 |
| Brussels (52.0°) | 0.0 | 0.3 | 1.1 | 3.2 | 1.7 | 0.0 |

- **Auroral and polar stations** are disturbed in **every** G3+ storm.
- **Morpeth (Belfast's latitude)** is clearly disturbed only in the very biggest storms: Kp 8.7–9, with Dst below about −300 nT.
- **This agrees with the earlier threshold result.** In `autonomy/analysis/results_autonomy.json`, Kp50 is the Kp at which half of 3-hour blocks exceed the tractor-RTK error tolerance:
  - **Morpeth: Kp50 ≈ 5.8** (95% CI 5.3–6.4);
  - **Herstmonceux: 7.6** (95% CI 7.0–8.6);
  - **Brussels: 7.4** (95% CI 6.9–8.1).
  - That is the source of the "about Kp 7.5" figure for southern England and Belgium. For Morpeth the earlier result is lower, about Kp 6.
- **Storm-only versus compound.** The April 2023 G4 (no flare above M1.7) disturbed the Arctic as much as the flare-rich storms did. So **the storm level, not whether there was a big flare, controls the storm-time ionosphere.**

### 4.2 Belfast receiver vs Kp (Jul–Oct 2026; `tables/belfast_roti_vs_kp.csv`, Figure 8)
- **% of satellite windows with ROTI > 0.5 (elevation ≥ 30°):**
  - Kp 0–2: 0.65% (CI 0.59–0.71);
  - Kp 3–4: 0.72%;
  - Kp 5 to 6−: 0.39%;
  - **Kp 6+ (only the 10 Oct storm, two 3-hour blocks): 2.6%.**
- This is one storm, so there is no real uncertainty estimate.
- The earlier storm analysis (`storm_20261010/final/results_final.json`) used a different ROTI calculation and window. It found 4.7% (storm) vs 4.0% (quiet), with overlapping CIs. Both say **at most a small rise at G3**.
- **Scintillation:** the 20 Hz system has seen only quiet conditions so far:
  - S4 median 0.056 (95th percentile 0.090);
  - σφ median 0.035 rad.
- The first storm will be the first real test.

### 4.3 LEO broadband (hourly, with rain and time-of-day controls; `tables/starlink_storm_rain_regression.json`)
- **Storm (Kp ≥ 5) effect on latency: −1.4 ms (95% CI −3.5 to +0.1)**. On dropped pings it was −0.006 percentage points (CI −0.04 to +0.04). That is from **30 storm hours, 6 of them at G3**.
- **No harmful storm effect is detectable.**
- **Correction to an earlier claim.** The 10 Oct 2026 reanalysis found that rain raised latency by +2.6 ms. In this longer hourly analysis, rain gave **−0.4 ms (CI −0.9 to 0.0)**, so **that rain effect is not reproduced**.
  - The two analyses used different periods and resolutions: the earlier one used 5-minute blocks over a shorter period, this one uses model rain per hour.
  - Treat "rain matters more than storms" as **not established**. Neither shows a measurable effect at Belfast.

---

## 5. Double whammy and how common it is (task D; `scripts/01_build_catalogues.py`, `02_double_whammy.py`)

### 5.1 Method
- **Storm.** A run of 3-hour GFZ Kp ≥ 7− (6.667; G3). G4 means ≥ 8− and G5 ≥ 9−. Runs less than 24 h apart are merged into one storm. This gives **150 G3+, 55 G4+ and 15 G5 storms** for 1996–2026.
- **Strong flare.** M5+ (873 flares) or X (358), on the **GOES-R ("true flux") scale**.
  - Pre-2017 classes were divided by 0.7. NOAA removed the old GOES 8–15 scaling factor, so the familiar "X9.3" of September 2017 is X14.6 on this scale.
  - The sensitivity run on the classes as published at the time is in the `*_reported.csv` files. **The conclusions do not change.**
- **Windows.** Each storm is classed as having a flare 3 days **before** onset, **during** the storm, or 3 days **after** it ended. The 1- and 2-day windows are also in the tables.
- **Chance baseline.** Each storm is moved to a random time within ±6 months, which keeps the solar-cycle activity level. The statistic is recomputed 5,000 times. The p-value is the share of shuffles that reach the observed value.
  - This is the honest test. Both flares and storms are more frequent at solar maximum, so a naive comparison would exaggerate the link.

### 5.2 Results (3-day windows; `tables/storm_flare_association_goesr.csv`, Figure 5)

| Storms | Flare | Before (obs. / chance) | During (obs. / chance) | After (obs. / chance) |
|---|---|---|---|---|
| G3+ (150) | M5+ | **48% / 20%** (p<0.001) | **10% / 4.5%** (p=0.002) | 32% / 20% (p<0.001) |
| G4+ (55) | M5+ | **69% / 22%** | 15% / 4.3% | 42% / 22% |
| G5 (15) | M5+ | **93% / 23%** | 20% / 4.9% | 67% / 23% |
| G3+ (150) | X | 35% / 11% | 6.7% / 2.2% | 22% / 11% |
| G4+ (55) | X | 58% / 12% | 9.1% / 2.1% | 33% / 12% |
| G5 (15) | X | 87% / 13% | 20% / 2.4% | 47% / 13% |

- **Dst check.** Repeating the test with Dst ≤ −100 nT storms instead of Kp (134 storms): 46% had an M5+ flare before or during, against 24% by chance (p < 0.001).
- **Flare → storm** (`tables/flare_followed_by_storm_goesr.csv`, Figure 7):

| Flares | Followed within 3 days by | Observed | Chance |
|---|---|---|---|
| X (358) | a G3+ storm | **26%** (94) | 6.7% |
| X (358) | a G4+ storm | 17% (60) | 2.7% |
| M5+ (873) | a G3+ storm | 19% (166) | 6.3% |

- **Per solar cycle** (`tables/per_cycle_counts_goesr.csv`), G3+ storms with an M5+ flare in the 3 days before or during:
  - **Cycle 23** (1996–2008): **45 of 91**;
  - **Cycle 24** (2008–2019, a weak cycle): **6 of 23**;
  - **Cycle 25** (Dec 2019 to Oct 2026): **21 of 35** so far, including **all 4 G5 storms**: May 2024, Oct 2024, Nov 2025 and Jan 2026.
- **Per year** (`tables/per_year_counts_goesr.csv`, Figure 6):
  - **2024** had 81 days with an M5+ flare and 14 G3+ storm days. **12 of those 14** had an M5+ flare that day or in the 3 days before. **91 days (one in four) had at least one of the two.**
  - Quiet years (2008–09, 2019–20) had none.

### 5.3 Named cases checked against the catalogues (`tables/named_cases_from_catalogues.csv`)

| Event | Strong flares (as published) | Max Kp (GFZ) | Min Dst (nT) | Type |
|---|---|---|---|---|
| Halloween 2003 | X17.2 (28 Oct, 19 h before storm), **X10 during storm** (29 Oct 20:49) | 9.0 | −383 | Flare→storm **and** both at once |
| Nov 2004 | X2.0 (7 Nov), **X2.5 during** (10 Nov) | 8.7 | −374 | Both |
| Dec 2006 | X9.0, X6.5, X3.4 (13 Dec) | 8.3 | −162 | Flare→storm (flare radio burst itself caused a GPS outage on 6 Dec) |
| Sep 2017 | X9.3/X8.2 (X14.6/X12.9 GOES-R scale) | 8.3 | −148 | Flare→storm→flare |
| May 2024 | 12 X flares; **X5.8 at 01:23 on 11 May during G5** | 9.0 | −406 | Both |
| Oct 2024 | X9.0 (3 Oct), X1.8 (9 Oct, storm source) | 8.7 | −333 | Flare→storm |
| Nov 2025 | X5.1/X5.2 (11 Nov) | 8.7 | −217 | Flare→storm |
| Jan 2026 | X1.9 (18 Jan) | 8.7 | −236 | Flare→storm |
| **Oct 2026 (own data)** | **M6.8 (8 Oct 15:48), M6.6 (10 Oct 15:10)** | 7.3 | −95 (OMNI); −85 (own real-time feed) | **Flare→storm and both at once** |
| **Counter:** Oct 2014 | 6 X flares | 5.0 | −57 | Big flares, no storm |
| **Counter:** Mar 2015 | none above M1.6 (driver C9.1) | 7.7 | −234 | G4 storm, no big flare |
| **Counter:** Apr 2023 | none above M1.7 | 8.3 | −213 | G4 storm, no big flare |
| **Counter:** Feb 2022 | M1.1 | 5.3 | −66 | Minor storm, yet 38 new LEO broadband satellites lost (drag) |

**Elijah's own event (Figure 1):**
- An M6.8 flare on 8 Oct.
- An interplanetary shock seen in the solar wind upstream of Earth at 14:34 on 10 Oct (speed jump of about +108 km/s). Dst jumped from −12 nT (14:00 hour) to +25 nT (15:00) and +39 nT (16:00): the storm sudden commencement.
- An **M6.6 flare peaking at 15:10, in the same 3-hour block as the storm onset**.
- Kp 7.33 (G3) for 15:00–18:00.

**What I cannot say from his data:** whether the 8 Oct flare's CME caused the storm. I did not find a CME attribution for it.

Belfast's worst "second-worst satellite" ROTI of that afternoon (0.78 TECU/min) came at 15:10, when the flare and the storm onset coincided. **The two cannot be separated in his data.** This is exactly the attribution problem a "common-mode" argument has to admit.

---

### 5.4 Does a flare *during* a storm do more than the two separately? (Figures 9–11; full method in `OVERLAP_METHOD.md`)

**How we measured it.** If the effects just add, (flare during storm) = (storm alone) + (flare alone). For each of the **13 G3+ storms since 1998 with an M5+/X flare within 3 h before onset or in the main phase**, we measured the sunlit-side (solar zenith angle < 60°) total electron content (TEC) jump in the 30 min after the flare from the public UQRG global maps (1,343 days downloaded). We compared it with the same 30-minute step in 3 matched **flare-free storms** (similar Kp and Dst, same time after onset) and with 4 **same-size flares on quiet days**. The leftover (measured − storm-only − flare-only) is the interaction, bootstrapped for a 95% confidence interval (CI). Decision rules were fixed beforehand: "worse" = CI entirely above 0; "no different" = CI inside ±0.5 TECU; "cannot tell" = CI includes 0 but is wider than that.

**Results.**
- **Flare during storm: cannot tell.** Extra jump +1.1 TECU (95% CI −0.5 to +3.5), median −0.1, 6 of 13 cases positive. Without Halloween 2003 (+10.7 TECU): +0.3 (−0.8 to +1.6). Every magnetic-latitude band: CI includes 0.
- **Storm then flare (0–72 h after): no different.** n = 48: +0.01 TECU (−0.32 to +0.34) compared with same-size quiet-day flares.
- **Whole-storm disturbance (first 12 h, after allowing for Kp), 142 storms:** overlap storms −0.3 percentage points (−4.5 to +3.6) relative to flare-free storms; flare-before-only storms −1.0 (−3.0 to +0.9). No sign of "worse"; cannot tell.
- **Sample size:** about **101 overlap storms** would be needed to detect an extra 1 TECU (80% power); only 13 occurred in 28 years.
- **Own data, 10 Oct 2026 (M6.6 at 15:10):** sunlit sub-auroral stations (Morpeth, Herstmonceux, Brussels) stayed at 0% of windows with rate of TEC index (ROTI) > 0.5 TECU/min before and after; Belfast's peak (0.78 TECU/min at 15:10) cannot be split between flare and storm onset.

**Caveats.** Loss of lock, carrier-to-noise ratio (C/N0) and scintillation (S4/σφ) are not available for historical storms; global maps are smoothed (2.5° × 5°, 15 min) and weak at high latitudes and over oceans; a storm's own 30-minute TEC swings (several TECU) are larger than flare jumps.

## 6. Related systems: measured vs documented (task E)
Source marks:
- **[D]** = Elijah's own data or own-pipeline global stations;
- **[V]** = a published source read in full or at the relevant page (see `autonomy/*.md`);
- **[S]** = abstract or summary only.

| System | Flare effect | Storm effect | Source |
|---|---|---|---|
| GNSS position, dual-frequency (Belfast) | None measurable for M1–M7 at SZA 59–78° | Small at G3; mid-latitude ROTI is clearly raised only at Kp ≈ 9 (Morpeth) | [D] |
| GNSS TEC, worldwide | 0.3–0.9 TECU jumps for M5–M9, more with a high Sun | Arctic 20–60% of satellites rough on every G3+ day | [D] |
| GNSS signal / radio bursts | Burst can cut C/N0 17–20 dB and cause loss of lock for minutes (Dec 2006) | – | [V] Cerruti et al. 2008 |
| SBAS (WAAS/EGNOS) | WAAS vertical guidance lost about 15 min (Dec 2006); EGNOS availability −10% dayside (Sep 2017) | WAAS vertical guidance lost 15 h and 11 h (Oct 2003); LPV200 lost about 16 h (Oct 2024) | [V] RAEng 2013; Berdermann et al. 2018; NOAA 2004; STCE 2024 |
| RTK (farm machinery) | Extrapolated: an X10 flare could exceed the tractor tolerance (Elijah's model, factor-3 band) | May 2024: GPS-guided tractors veered off course or stopped; a farm-equipment manufacturer's RTK system advised switching off | [D] model; [V] NASA 2025; [S] dealer advisory |
| Timing / 4G-5G | Burst outages last minutes, well within holdover | UK planning assumes GNSS loss of 1–3 days in an extreme storm; no documented mobile-network outage from space weather | [V] RAEng 2013; `timing_dependency_checks.md` |
| HF radio | R2 (M5): tens of min; R3 (X1): about 1 h; R5: hours, sunlit side | Post-storm HF depression; polar absorption with solar energetic particles | [V] NOAA scales; STCE 2024 |
| LEO satellite broadband (Belfast dish) | No latency or drop effect for M flares (upper limit about +6 ms) | No effect at G1–G3 (latency −1.4 ms, CI −3.5 to +0.1) | [D] |
| LEO satellite broadband (fleet) | – | Feb 2022: 38 of 49 new satellites lost after a *minor* storm (drag plus low orbit) | [V] Kataoka et al. 2022 |

---

## 7. Sources for the long catalogues

- Global TEC maps: UPC-IonSAT UQRG rapid 15-minute IONEX maps, https://chapman.upc.es/tomion/rapid/ (public), used for section 5.4.
- **Flares 1996–2016:** NOAA NCEI, GOES XRS event reports `goes-xrs-report_YYYY.txt`, https://www.ngdc.noaa.gov/stp/space-weather/solar-data/solar-features/solar-flares/x-rays/goes/xrs/
- **Flares 2017–2026:** NOAA NCEI GOES-R XRS Level 2 science-quality flare summaries. GOES-16 `sci_xrsf-l2-flsum_g16_s20170209_e20250407_v2-2-2.nc` (used to 6 Apr 2025) and GOES-19 `sci_xrsf-l2-flsum_g19_s20240920_e20261024_v2-2-2.nc` (from 7 Apr 2025), https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/
- **Kp:** GFZ Potsdam, `Kp_ap_Ap_SN_F107_since_1932.txt`, https://kp.gfz.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt. Cite Matzka et al. (2021), *Space Weather* 19, e2020SW002641. CC BY 4.0.
- **Dst:** NASA OMNIWeb hourly OMNI2, https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/ (Dst from WDC Kyoto). Recent months are provisional or real-time.
- **Case details and impacts:** `autonomy/storm_flare_cases.md`, using the [V]/[S] marks given there.

---

## 8. What we can and cannot claim

**Can claim (supported by data):**
- In 1996–2026, about **half of G3+ storms, two-thirds of G4+ and 14 of 15 G5 storms** had a strong (M5+) flare in the 3 days before. This is **2–4 times more often than chance**, even after allowing for the solar cycle.
- Strong flares **during** a storm ("both at once") occurred in about **1 in 10 G3+ storms** and **3 of 15 G5 storms**. Elijah recorded one himself on 10 Oct 2026.
- In solar-maximum years, there were about **6 compound G3+ events per year**.
- Mid-latitude GNSS (Morpeth, ≈ Belfast) is clearly disturbed only in the biggest storms (Kp ≈ 9). The Arctic is disturbed in every G3+ storm.
- At Belfast, no measurable effect on GNSS signal strength, tracking or LEO broadband latency was found from M flares or G1–G3 storms, **with numerical upper limits**.

**Cannot claim:**
- That flares *cause* storms. The CME causes the storm. Flares and CMEs often come from the same active region, which is why they cluster.
- That a flare *predicts* a storm: 74% of X flares were not followed by a G3+ storm within 3 days.
- That the flare and storm effects add up at Belfast. His data show neither effect clearly at his location in 2026.
- That more constellations protect against a radio burst. The noise comes from the Sun, so it affects all satellites at once.
- Any flare TEC "decay time" from his own data.

---

## 9. Limitations
- **Belfast, autumn and winter Sun.** SZA 59–78° for the sunlit M flares means flare effects are weakest. **No X flares** have occurred since logging began.
- **Small samples.**
  - Only 9 sunlit M flares and 2 above M5 had Belfast data. The TEC test had only 4 clean paired events.
  - Only **one G3 storm** has Belfast data. Storm-time Belfast statistics rest on 2 three-hour blocks.
- **Data gaps.**
  - The receiver was not logging on 14–31 Aug, so the M8.2 and M7.1 flares were missed at Belfast.
  - **The 1 Hz database has about 14-hour overnight gaps on 23/24 and 25 Oct**, after the 20 Hz upgrade. The raw 20 Hz files are complete, so this should be checked.
- **ROTI threshold.** The 0.5 TECU/min threshold is a convention. ROTI from 1 Hz (Belfast) and 30 s (archive) data are not identical, which is why the Belfast and Morpeth numbers differ in absolute terms.
- **Catalogue details.**
  - GOES flare classes changed scale in 2017. I handled this by rescaling and ran a sensitivity check.
  - Flares on the far side of the Sun and behind the limb are missed. CMEs from the back of the Sun cannot cause Earth storms, but limb flares can be under-classed.
  - The 39-day flare-list gap in early 2017 was excluded.
- **Kp scales.** GFZ definitive Kp sometimes differs from NOAA's real-time Kp. For example, the Oct 2024, Nov 2025 and Jan 2026 storms reach Kp 9− (G5) in GFZ data but were announced as G4 by NOAA at the time.
- **Shuffle baseline.** Shifting storms by ±6 months keeps the activity level but not the 27-day solar rotation. The p-values are approximate, though the effect sizes (2–6 times) are large.
- **Weather control.** The rain control uses hourly model rain (Open-Meteo), not a rain gauge.

## 10. Reproduce
```
cd analysis/flare_storm
python3 scripts/01_build_catalogues.py           # needs catalogues/ (downloaded 25 Oct 2026)
python3 scripts/02_double_whammy.py goesr        # and: ... reported   (sensitivity)
python3 scripts/03_flare_belfast.py              # needs data/win/*.csv from scripts/pi_extract_flare_windows.py (run on the Pi, read-only)
python3 scripts/04_storms.py; python3 scripts/05_global_flare.py; python3 scripts/06_figures.py; python3 scripts/07_named_cases.py
# Section 5.4 (overlap test):
python3 scripts/10_overlap_select.py; bash scripts/11_fetch_uqrg.sh   # downloads ~1.9 GB of public UQRG maps
python3 scripts/12_overlap_analysis.py; python3 scripts/13_overlap_roti_archive.py; python3 scripts/14_overlap_figures.py
python3 scripts/08_build_docx.py
```
- Pi databases were copied with `sqlite3 -readonly ... .backup` to `/tmp` on the Pi and analysed on a separate computer.
- Nothing on the Pi was modified.
- The fixed random seeds are in the scripts.
