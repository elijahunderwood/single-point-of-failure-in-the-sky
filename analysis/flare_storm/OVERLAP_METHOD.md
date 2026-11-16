# Does a flare and a storm together hit GNSS harder than the two separately? How we measure it

*Method note for Elijah. Scripts: `scripts/10_overlap_select.py`, `ionex.py`, `12_overlap_analysis.py`, `13_overlap_roti_archive.py`, `14_overlap_figures.py`. All numbers below come from these scripts and the tables they write; nothing is estimated by hand.*

## Abbreviations
GNSS = Global Navigation Satellite System; TEC = total electron content (1 TECU = 10^16 electrons/m²); ROTI = rate of TEC index (TECU/min); SZA = solar zenith angle (0° = Sun overhead, 90° = Sun on the horizon); Kp = planetary 3-hour geomagnetic index; Dst = disturbance storm-time index (nT); C/N0 = carrier-to-noise density ratio; S4 / σφ = amplitude / phase scintillation indices; IONEX = IONosphere map EXchange format; UQRG = the Universitat Politècnica de Catalunya rapid global TEC maps (15-minute); CI = confidence interval; G3/G4/G5 = NOAA storm scale (Kp 7/8/9); M5+ = flare with peak X-ray flux of at least 5×10⁻⁵ W/m².

## The idea in one sentence
If the two effects simply **add up**, then (flare during a storm) = (what the storm does anyway) + (what the flare does on a quiet day). We measure all three pieces, subtract, and see whether anything is **left over**. The leftover is the "interaction"; a positive interaction means "together is worse than the sum".

## The five steps

1. **Find the cases.** From the 1996–2026 catalogues (GFZ Kp, OMNI Dst, GOES flares, GOES-R scale) take every G3+ storm since 1998 (when global TEC maps start being reliable) and sort it into:
   - **overlap**: an M5+ or X flare within about 3 h before onset or during the main phase (onset → Dst minimum): **13 storms**;
   - **flare-before-only**: an M5+ flare in the 3 days before, none during: **59 storms**;
   - **flare-free**: no M5+ flare from 3 days before to the end: **70 storms**.
   Separately, **storm-then-flare**: an M5+ flare 0–72 h after a G3+ storm ends: **48 cases**.

2. **Find fair comparisons ("matched controls").**
   - For each overlap storm, the 3 **flare-free storms** most similar in maximum Kp and minimum Dst (scaled distance). We look at the control storm at the **same time after onset** as the flare happened in the overlap storm, because a storm's own effect changes hour by hour (main phase vs recovery).
   - For each flare, 4 **flare-only controls**: the 4 flares closest in peak X-ray flux on quiet days (Kp ≤ 3 for ±24 h), within ±4 years so the solar cycle is similar.

3. **Measure the same thing in all of them.**
   - **Flare jump D** (TECU): from the 15-minute global UQRG maps, take the change from a quiet-day baseline (median of up to 5 of the previous 15 days with daily Kp < 4.67, same UT). D = mean change in the 30 min after the flare peak minus the mean change 15–45 min before, averaged (area-weighted) over the **sunlit side only (SZA < 60°)**, because a flare only acts on the sunlit side.
   - **Storm impact S**: mean sunlit-side (SZA < 80°) |change from quiet| over the first 12 h of the storm, in TECU and as % of the quiet value.
   - Both are also worked out separately by **magnetic-latitude band**: low (<20°), mid (20–45°, includes most of Europe's south), sub-auroral (45–60°, includes Belfast at about 54° magnetic), high (>60°).
   - **Receiver-level metrics** (where available): % of 5-minute windows with ROTI > 0.5 TECU/min, and the network "second-worst satellite" ROTI, from the project's own 30-second station archive (`data/global_roti.db`) and the Belfast/Morpeth receivers.

4. **Test "do they just add?"** For each overlap storm: interaction I = D(overlap) − median D(storm-only controls) − median D(flare-only controls). Average over the 13 cases. Uncertainty by **bootstrap** (resample the cases 10,000 times; per-case CIs by resampling that case's controls). For storm impact S we fit S = a + b·Kp_max + c·(overlap) + d·(flare-before-only) and bootstrap c and d (3,000 resamples of the 142 storms). Sample size needed: n ≈ ((1.96 + 0.84) × SD / δ)², the number of overlap storms to detect an extra effect δ with 80% power at the 5% level.

5. **Decide with pre-set rules.** Practical size = **0.5 TECU** for a flare jump (roughly a typical M5–X sunlit jump on a quiet day, i.e. "doubling" the flare effect), and 5 percentage points for storm impact.
   - **Worse**: the whole 95% CI is above 0.
   - **No different**: the CI includes 0 **and** lies inside ±practical size (so any hidden effect must be too small to matter).
   - **Cannot tell**: the CI includes 0 but is wider than ±practical size (data are compatible with both "nothing" and "a lot").

## What we could not measure (be upfront about this)
- **Loss of lock, satellite-count drops, C/N0, S4/σφ** do not exist historically for these storms; Elijah's own receivers cover only one overlap event (10 Oct 2026). Scintillation was not measurable for the historical test.
- **Global TEC maps are smoothed** (2.5° × 5°, 15 min). They see large-scale TEC jumps but not the small-scale irregularities that cause loss of lock; high-latitude and ocean areas are poorly constrained by stations.
- A storm's own TEC can swing several TECU in 30 min, which is far bigger than a flare jump (~0.3–0.9 TECU). This "storm noise" is why the test needs many cases.

## Results (run 25 Oct 2026)

| Question | n | Effect (95% CI) | Verdict |
|---|---|---|---|
| Flare **during** storm: extra sunlit TEC jump beyond storm + flare added (all latitudes) | 13 storms (39 storm-control slots using 19 different flare-free storms; 52 flare-control slots using 45 different quiet-day flares) | **+1.1 TECU (−0.5 to +3.5)**; median −0.1; 6 of 13 positive | **Cannot tell** |
| … same, leaving out Halloween 2003 (X14.3, +10.7 TECU) | 12 | +0.3 TECU (−0.8 to +1.6) | Cannot tell |
| … low / mid / sub-auroral / high magnetic latitude | 13 / 13 / 13 / 11 | +0.5 (−0.5 to +2.5) / +2.0 (−0.9 to +5.3) / +0.6 (−1.0 to +2.1) / −0.2 (−2.1 to +1.6) | Cannot tell in every band |
| Storm **then** flare (0–72 h after): flare jump vs same-size quiet-day flares | 48 flares | +0.01 TECU (−0.32 to +0.34) | **No different** (on average; post-storm jumps are much more scattered) |
| Whole-storm sunlit disturbance, first 12 h, after allowing for Kp: overlap storms vs flare-free | 142 storms (13 / 59 / 70) | −0.3 percentage points (−4.5 to +3.6); in TECU −1.5 (−3.5 to +0.5) | Cannot tell (no sign of "worse") |
| … flare-before-only storms vs flare-free | same | −1.0 points (−3.0 to +0.9); in TECU +0.9 (−0.2 to +2.0) | Cannot tell / no sign of "worse" |

**Sample size.** The case-to-case spread of the interaction is 3.6 TECU (all latitudes), so detecting an extra 1 TECU with 80% power needs about **101 overlap storms** (45–250 depending on band). There were 13 in 1998–2026 (about 0.45 per year), so the historical record cannot settle this; at that rate 101 cases would take about two centuries. The storm's own 30-minute TEC swings (the "storm-only" bars in Figure 9 range from −2.3 to +2.6 TECU) are larger than the flare jumps themselves.

**Receiver-level check (own archive, descriptive only; `tables/overlap_roti_archive_metrics.csv`).** Only two overlap storms (May 2024, 10 Oct 2026) and one similar flare-free storm (Apr 2023, Kp 8.33) are in the station archive.
- 10 Oct 2026, M6.6 at 15:10: sunlit stations MORP, HERS, BRUX (sub-auroral), MAS1, PIE1 (mid) and KOUR (low) had **0% → 0%** of windows with ROTI > 0.5 in the 30 min after vs before; only REYK (high latitude) rose (0% → 18.8%). At Belfast the afternoon's worst second-worst-satellite ROTI (0.78 TECU/min) came at 15:10, but flare and storm onset coincide, so they cannot be separated.
- May 2024, X5.8 at 01:23 on 11 May: HOB2 rose 7.9% → 60.4%, YELL 22.2% → 35.4%, DARW stayed at 0%. In the flare-free Apr 2023 storm at the same phase, sunlit stations changed by −12.7 to +20.8 points over the same kind of 30-minute step with no flare at all. So these jumps cannot be credited to the flare.

## Coaching notes for writing it up
- Say what the test *can* conclude: "With 13 events, a flare during a storm was not measurably worse than the sum of the two; the uncertainty is too wide to rule out a large extra effect." That is a real result, not a failure.
- Show Figure 9 and point at Halloween 2003: one event drives most of the average. Ask the judges' question yourself: "Is that the flare, or the storm doing something at the same moment?"
- The "storm-then-flare" result is the cleanest: n = 48 and a narrow CI.
- For the common-mode argument, the practical point stands either way: the storm dominates the GNSS risk; a flare adds a short, sunlit-side, fairly small jump.
