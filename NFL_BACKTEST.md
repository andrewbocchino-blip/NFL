# NFL model backtest

Walk-forward and leak-free: each week's projection uses only plays from PRIOR weeks, scored against the closing line that was actually posted.

Parameters: `2018-2023 train / 2024-2025 held out` · HOME_FIELD 1.68 · EPA_TO_POINTS 15.38 · window 10wk · min_week 6 · prior-season weight 0.0

Sign convention check passed: RMSE(result − spread_line) = **12.79** (expected ~12.7; near 18 would mean spread_line had flipped and every edge below was inverted).

**Coverage caveat:** min_week=6, so weeks 1–5 are NOT tested here. The model cannot produce a Week 1 projection at all without prior-season carry-forward — there are no prior plays to rate teams on.

## Spread

- games scored (walk-forward, leak-free): **1578**
- model RMSE: **14.13** points
- closing line RMSE: **12.70** points
- market more accurate by **1.43** points

## (result − line) ~ (projection − line)  ← the number that matters

- slope = **+0.0067** (t = **0.13**)
- R² = **0.00001** · n = 1578
- mean |disagreement| = 5.02 pts

> Read the slope as: per point the model disagrees with the closing line, the game lands this many points the model's way. Zero means the disagreement carries no information about which side covers. One would mean the model is right and the market wrong, point for point.

> **t = 0.13 — not distinguishable from zero.** The size of a disagreement predicts nothing measurable. No threshold, filter or band will recover signal that is not present.

### Per-season stability of that slope

| Season | n | slope | t | model RMSE | line RMSE |
|---|---|---|---|---|---|
| 2018 | 178 | +0.114 | +0.62 | 13.62 | 12.89 |
| 2019 | 178 | +0.078 | +0.59 | 14.61 | 12.98 |
| 2020 | 192 | +0.076 | +0.51 | 14.65 | 13.28 |
| 2021 | 205 | +0.011 | +0.08 | 15.57 | 13.96 |
| 2022 | 204 | +0.285 | +2.04 ⚠️ | 12.27 | 11.66 |
| 2023 | 207 | +0.052 | +0.34 | 13.40 | 12.33 |
| 2024 | 207 | -0.396 | -2.62 ⚠️ | 14.45 | 12.36 |
| 2025 | 207 | -0.157 | -1.21 | 14.22 | 12.12 |

> ⚠️ Seasons [2022, 2024] clear |t| ≥ 2 individually while the pooled slope is +0.0067 (t = 0.13). A single NFL season is ~200 scored games and swings far enough to read as significant in EITHER direction by chance. Any conclusion drawn from one season — including a flattering one — is variance.

## ATS record

- betting every disagreement >0.5 pts: **755-691** (52.2%), 38 push
- ROI at -110: **-0.3%** · break-even is 52.4%
- ROI 95% CI: **-5.2% to +4.4%** (z vs break-even = -0.14)

> **Detection limit.** This record rests on 1446 bets. Resolving a 2% ROI — what a professional targets on NFL sides — needs ~17,689 bets; a 5% ROI needs ~2,830. At this sample neither a winning nor a losing record is informative. The regression slope above is the better-powered test, and CLV is the only metric that can settle this.

> The interval straddles zero: **indistinguishable from luck**, however the headline reads.

### By size of disagreement

| Model edge vs line | n | ATS | Win% |
|---|---|---|---|
| 0.5-3 pts | 454 | 240-214 | 52.9% |
| 3-6 pts | 468 | 251-217 | 53.6% |
| 6-10 pts | 360 | 180-180 | 50.0% |
| 10+ pts | 164 | 84-80 | 51.2% |

> If the biggest disagreements do not win at the highest rate, the model is finding noise rather than mispricing.

> ⚠️ **Not monotonic** (53% → 54% → 50% → 51%). A record that jumps around across bands is variance being sliced, not edge being found — the pattern that makes a threshold sweep produce a flattering number by accident.

## Totals

- games: **1578** · model RMSE **16.39** vs closing total RMSE **13.26**
- betting disagreements: **735-824** (47.1%)
- (total − line) ~ (proj − line): slope **-0.1072** (t = -2.77), R² 0.00486

> Read against NFL_BASELINES.md first. Betting every under went 51.0% over 2016-25 and still lost money at -110.
