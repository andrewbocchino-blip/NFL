# NFL naive baselines

Everything below requires no model, no ratings and no projection. It is the floor. Any model result that does not clearly clear this floor is not a finding.

Sample: 2016-2025, 2761 games with results. All records exclude pushes; ROI is at -110; CIs are 3,000-sample bootstraps.

## Side and total baselines

| Strategy | Record | Win% | ROI | 95% CI | n |
|---|---|---|---|---|---|
| Bet every UNDER | 1397-1341 | 51.0% | -2.6% | -6.1% to +1.0% | 2738 |
| Bet every OVER | 1341-1397 | 49.0% | -6.5% | -10.0% to -3.0% | 2738 |
| Bet every HOME ATS | 1328-1368 | 49.3% | -6.0% | -9.6% to -2.4% | 2696 |
| Bet every AWAY ATS | 1368-1328 | 50.7% | -3.1% | -6.6% to +0.4% | 2696 |
| Bet every UNDERDOG ATS | 1383-1309 | 51.4% | -1.9% | -5.4% to +1.6% | 2692 |
| Bet every HOME DOG ATS | 520-504 | 50.8% | -3.1% | -8.8% to +2.9% | 1024 |
| Bet every FAVOURITE ATS | 1309-1383 | 48.6% | -7.2% | -10.7% to -3.6% | 2692 |

> Every one loses at -110. Note in particular that betting every under goes above 50% and still loses money — a win rate over 50% is not an edge, it is what the vig is for. Any headline ATS record from the model must be read against this column, not against 50%.

## The closing line itself

- games: **2761**
- closing-spread RMSE: **12.70** points
- home cover rate: **48.1%** · push rate 2.4%

> This is the accuracy the projection has to beat to have any claim on sides at close. It is also, separately, why the market's own record sits near 50% — the line is set to split the action, not to predict.

## Moneyline base rate

- favourites win **66.4%** of games (n=2747, ties and pick'em excluded)

> Public NFL models advertising ~64% moneyline accuracy are reporting this number. It requires no model. Any moneyline claim must be scored against **66.4%**, never against 50%.

## Key-number drift

| Era | n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 10 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2000-2009 | 2654 | 3.6% | 3.5% | 15.9% | 4.7% | 2.9% | 5.1% | 9.5% | 6.1% | 4.7% |
| 2010-2017 | 2136 | 4.0% | 3.9% | 14.4% | 5.3% | 3.9% | 6.6% | 8.9% | 5.3% | 4.8% |
| 2018-2025 | 2227 | 4.8% | 4.9% | 14.8% | 4.8% | 4.2% | 6.6% | 8.5% | 4.8% | 5.2% |

> Three is stable and dominant. **Seven has declined** (9.5% -> 8.5%) and **six has risen** (5.1% -> 6.6%); one and two are up roughly a third, consistent with the rise in two-point attempts. `KEY_NUMBERS` in nfl_model.py is fitted to the 2018-2025 row, not the full history — an all-era table misprices exactly the numbers that matter most.

## Home-field drift

| Era | n | mean home margin | mean spread_line | gap |
|---|---|---|---|---|
| 2000-2009 | 2654 | +2.62 | +2.57 | +0.05 |
| 2010-2017 | 2136 | +2.54 | +2.36 | +0.18 |
| 2018-2025 | 2227 | +1.72 | +1.73 | -0.01 |
| 2021-2025 | 1424 | +2.25 | +1.69 | +0.56 |

> HFA fell from ~2.6 points (2000-09) to ~1.7 (2018-25), and the market tracked it almost exactly. `HOME_FIELD = 1.68` is the fitted intercept, not an assertion; a stale 3 would be a systematic error on every game.

> **A trap worth naming.** The 2021-2025 row shows mean margin running above mean spread, which looks like a half-point HFA mispricing. It is not: t is about 1.6, and betting every home team ATS loses in the table above. A gap in means is not an edge.

## Detection limits at -110

| True ROI | Bets needed (80% power) | NFL seasons betting half the card |
|---|---|---|
| 2% | ~17,689 | ~131 |
| 3% | ~7,862 | ~58 |
| 5% | ~2,830 | ~21 |
| 10% | ~708 | ~5 |

> A professional targets ~2% ROI on NFL sides. That is ~17,700 bets to resolve — roughly 130 seasons. **Results-based validation of an NFL sides edge is not achievable in a human lifetime.** This is not a criticism of any particular backtest; it is a structural fact about the sport, and it is why CLV is not the preferred validation metric here but the only feasible one.
