# NFL model — status

**No demonstrated edge. Nothing here is authorized for real money.**

Pooled 2018-2025 (n=1,578 games), regression of market error on model
disagreement: **slope +0.007, t = +0.13, R² = 0.00001**. The model's
disagreements with the closing line carry no measurable information. This
holds under every window, start-week and prior-season weight tested.

## v1 -> v2: what was wrong

nflverse `spread_line` is **home-favoured-positive** (home favoured by 3 =
`+3.0`), the opposite of the sportsbook board convention. v1 computed model
edge as `proj + line`; the correct expression is `proj - line`. Those have
opposite signs whenever `|line| > |proj|` — about half of all games — so
v1's ATS record (207-182), correlation and band table were built on a partly
inverted pick direction and are void. `assert_sign_convention()` now runs
before any line arithmetic and fails loudly if the upstream convention flips.

Also fixed: `EPA_TO_POINTS` was asserted at 63.0 with an ad-hoc /2.0 divisor
(effective 31.5). The fitted OLS slope is **15.38** — v1's projection was
scaled ~2x too large. `KEY_NUMBERS` was an all-era table; it is now fitted to
2018-2025 (7 has declined to 8.5%, 6 has risen to 6.6%).

## Files

| File | Purpose |
|---|---|
| `nfl_model.py` | Ratings, projection, pricing. All constants fitted, none asserted. |
| `nfl_fit.py` | Fits HOME_FIELD, EPA_TO_POINTS, PROJ_SHRINK on a train window. Test seasons untouched. |
| `nfl_backtest.py` | Walk-forward leak-free backtest + per-season stability table. |
| `nfl_baselines.py` | Naive baselines, key-number drift, detection limits. The floor. |
| `nfl_lines.py` | Opener capture, no-vig consensus, outlier screen, CLV grading. |

Order: `nfl_baselines.py` -> `nfl_fit.py` -> `nfl_backtest.py`.

## The constraint that governs everything

Detecting a 2% ROI at -110 with 80% power needs **~17,700 bets** — roughly
130 NFL seasons betting half the card. Results-based validation of an NFL
sides edge is not achievable. **CLV is the only feasible scoreboard.**

## Not ready for Week 1

- `team_epa_ratings(through_week=1)` rates **0 teams**. The model cannot
  produce a Week 1 projection.
- The backtest has scored **0 games in weeks 1-5**. All 1,578 are week 6+.
- Deploy `nfl_lines.py snapshot` only. Paper-log the screen. Bet nothing.

## Graduation criteria (pre-registered)

- **Screen:** >=800 graded prices, beat-close rate 95% CI excluding 50%.
- **Projection:** slope on `(result-line) ~ (proj-line)` with |t| > 2 on a
  season the parameters were never fitted on. It has never done this.
- **An ATS record is not a reason.** 2022 read +2.04; 2024 read -2.62. Noise.
