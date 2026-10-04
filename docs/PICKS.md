# NFL Locked Picks

Picks frozen at the line they were taken at. **Both books shown; bold = better price.** One row per bet. Paper only.

_Score = value in cents + 10x(hit% - 50%). It rewards a price that is off the market AND likely to land. It is a ranking device, not a probability._

> ⚠️ **Prices are 60h old** (lines 60h, props 53h). A starter announcement or scratch since capture is not in these numbers. Verify before betting.

## 2026-10-04

| Verdict | Score | Game | Market | Pick | Hit% | Books (best in bold) |
|---|---|---|---|---|---|---|
| STALE | — | _prices are 60h old — no PLAY can be issued. Run capture-odds, then regenerate._ | | | | |

#### Model Divergence — our number vs **no-vig** market (model says 60%+)

*Divergence means our number disagrees with the market — it does NOT mean the market is wrong. When we disagree the more likely explanation is that our number is worse. Model is calibrated 60-80% on 55,641 walk-forward player-games (60-70 -> 66.8%, 70-80 -> 75.6%); it is capped at 80% because above that it reads 73-75%.*

| Player | Market | Pick | Line | **Model** | No-vig | Diverg. | Price | Books | Result |
|---|---|---|---|---|---|---|---|---|---|
| _no prop where the model reaches 60% on 4+ games of 2026 data_ | | | | | | | | | |

*Divergence board calibration (all time): 0-0 (no settled rows yet). Calibration is not edge — the book is also well calibrated, so a gap is a hypothesis to grade, not a signal.*

#### Value Board — DK/FD vs **no-vig** market (calibration record, NOT bets)

*Value means one book is priced away from the other ten. It does NOT mean the market is wrong. Until this board beats its baseline, read a large number as a warning about our consensus, not an opportunity.*

| Game | Market | Pick | Line | Hit% | Value | Books | Result |
|---|---|---|---|---|---|---|---|
| NE @ BUF | ML | **Buffalo Bills** | — | 74% | -0.5¢ | **DK -290** / FD -340 | pending |
| MIA @ MIN | ML | **Minnesota Vikings** | — | 84% | -2.0¢ | **DK -600** / FD -650 | pending |
| TB @ DAL | ML | **Dallas Cowboys** | — | 82% | -2.2¢ | **DK -520** / FD -520 | pending |
| TEN @ BAL | ML | **Baltimore Ravens** | — | 85% | -2.7¢ | **DK -700** / FD -770 | pending |
| LAC @ SEA | ML | **Seattle Seahawks** | — | 76% | -3.8¢ | DK -380 / **FD -370** | pending |

*Value board calibration (all time): 0-0 (no settled rows yet)*

#### Probability Board — every bet at 70%+ to hit (5 game lines, 0 props)

*The 70-80% bucket is the best-calibrated range on this board: predicted 74.7%, actual 76.2% over 8,796 team-games.*

| Game | Market | Pick | Hit% | Value | Books | Result |
|---|---|---|---|---|---|---|
| TEN @ BAL | ML | **Baltimore Ravens** | 85% | -2.7¢ | **DK -700** / FD -770 | pending |
| MIA @ MIN | ML | **Minnesota Vikings** | 84% | -2.0¢ | **DK -600** / FD -650 | pending |
| TB @ DAL | ML | **Dallas Cowboys** | 82% | -2.2¢ | **DK -520** / FD -520 | pending |
| LAC @ SEA | ML | **Seattle Seahawks** | 76% | -3.8¢ | DK -380 / **FD -370** | pending |
| NE @ BUF | ML | **Buffalo Bills** | 74% | -0.5¢ | **DK -290** / FD -340 | pending |

*A high hit rate is not an edge — the price already reflects it. This board exists to test whether consensus probability is calibrated.*

#### Matchup Board — opponent strength vs the side (calibration record, NOT bets)

*Current-season play-by-play only. Prior-season defence explains 2-5% of current-season early-week defence, so it is excluded. The book already knows the opponent's ranking — this column answers 'who are they playing', not 'where is the edge'.*

| Game | Pick | Market | Opponent D | Tilt | Hit% | Value | Result |
|---|---|---|---|---|---|---|---|
| ARI @ NYG | **Cam Skattebo Over 2.5** | receptions | vs ARI pass D soft +10% | +10% | 51% | +0.3¢ | pending |
| LA @ PHI | **Dontayvion Wicks Under 3.5** | receptions | vs LA pass D tough -5% | +5% | 60% | +3.2¢ | pending |
| LAC @ SEA | **Tre Harris Under 2.5** | receptions | vs SEA pass D tough -10% | +10% | 42% | -2.0¢ | pending |
| LA @ PHI | **Makai Lemon Under 2.5** | receptions | vs LA pass D tough -5% | +5% | 43% | +2.6¢ | pending |
| DET @ CAR | **Sione Vaki Over 9.5** | rush yds | vs CAR rush D soft +13% | +13% | 51% | -5.2¢ | pending |
| DET @ CAR | **Jared Goff Over 1.5** | rush yds | vs CAR rush D soft +13% | +13% | 49% | -5.3¢ | pending |
| ATL @ NO | **Kendre Miller Under 24.5** | rush yds | vs ATL rush D tough -11% | +11% | 50% | -5.4¢ | pending |
| ATL @ NO | **Tyler Shough Under 16.5** | rush yds | vs ATL rush D tough -11% | +11% | 50% | -5.4¢ | pending |
| ATL @ NO | **Alvin Kamara Under 38.5** | rush yds | vs ATL rush D tough -11% | +11% | 51% | -5.4¢ | pending |
| NYJ @ CHI | **Kenyon Sadiq Over 4.5** | receptions | vs CHI pass D soft +8% | +8% | 44% | -2.5¢ | pending |
| ARI @ NYG | **Malachi Fields Over 23.5** | reception yds | vs ARI pass D soft +10% | +10% | 50% | -4.5¢ | pending |
| ARI @ NYG | **Cam Skattebo Over 17.5** | reception yds | vs ARI pass D soft +10% | +10% | 50% | -4.5¢ | pending |

<details>
<summary><b>How each number was built (click to expand)</b></summary>

- **Dontayvion Wicks Under 3.5** (receptions, LA @ PHI): market: no-vig consensus 59.8% across 5 books -> fair -149 · price: FD -138 implies 58.0% -> value +3.2c · matchup: vs LA pass D tough -5% (tilt +5%, 3g of 2026 data, shrunk toward league average) · usage: 10 targets (18% of team), aDOT 14.8, 147 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Makai Lemon Under 2.5** (receptions, LA @ PHI): market: no-vig consensus 43.5% across 4 books -> fair +130 · price: FD +136 implies 42.4% -> value +2.6c · matchup: vs LA pass D tough -5% (tilt +5%, 3g of 2026 data, shrunk toward league average) · usage: 5 targets (9% of team), aDOT 2.6, 9 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ thin consensus — only 4 books at this number · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Buffalo Bills** (ML, NE @ BUF): calibration: raw de-vig 72.7% -> 74.0% (favourite-longshot bias, measured on 8,796 team-games) · market: no-vig consensus 74.0% across 11 books -> fair -284 · price: DK -290 implies 74.4% -> value -0.5c · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ negative value — this is the book's hold, not an edge · ⚠️ heavy favourite — high hit rate is priced in, not an edge · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Brenton Strange Over 3.5** (receptions, JAX @ CIN): market: no-vig consensus 48.0% across 5 books -> fair +108 · price: FD +112 implies 47.2% -> value +1.7c · matchup: vs CIN pass D soft +3% (tilt +3%, 3g of 2026 data, shrunk toward league average) · usage: 10 targets (13% of team), aDOT 8.3, 72 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Minnesota Vikings** (ML, MIA @ MIN): calibration: raw de-vig 82.7% -> 84.0% (favourite-longshot bias, measured on 8,796 team-games) · market: no-vig consensus 84.0% across 11 books -> fair -524 · price: DK -600 implies 85.7% -> value -2.0c · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ negative value — this is the book's hold, not an edge · ⚠️ heavy favourite — high hit rate is priced in, not an edge · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Dallas Cowboys** (ML, TB @ DAL): calibration: raw de-vig 80.7% -> 82.0% (favourite-longshot bias, measured on 8,796 team-games) · market: no-vig consensus 82.0% across 5 books -> fair -457 · price: DK -520 implies 83.9% -> value -2.2c · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ negative value — this is the book's hold, not an edge · ⚠️ heavy favourite — high hit rate is priced in, not an edge · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Travis Kelce Over 4.5** (receptions, KC @ LV): market: no-vig consensus 45.4% across 5 books -> fair +120 · price: DK +123 implies 44.8% -> value +1.3c · matchup: vs LV pass D avg (tilt +1%, 3g of 2026 data, shrunk toward league average) · usage: 18 targets (20% of team), aDOT 6.6, 231 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Baltimore Ravens** (ML, TEN @ BAL): calibration: raw de-vig 83.8% -> 85.1% (favourite-longshot bias, measured on 8,796 team-games) · market: no-vig consensus 85.1% across 11 books -> fair -572 · price: DK -700 implies 87.5% -> value -2.7c · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ negative value — this is the book's hold, not an edge · ⚠️ heavy favourite — high hit rate is priced in, not an edge · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Darren Waller Under 2.5** (receptions, DET @ CAR): market: no-vig consensus 45.2% across 4 books -> fair +121 · price: FD +124 implies 44.6% -> value +1.2c · matchup: vs DET pass D avg (tilt -1%, 3g of 2026 data, shrunk toward league average) · usage: 13 targets (12% of team), aDOT 6.9, 112 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ thin consensus — only 4 books at this number · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **TreVeyon Henderson Under 1.5** (receptions, NE @ BUF): market: no-vig consensus 59.5% across 5 books -> fair -147 · price: DK -148 implies 59.7% -> value -0.4c · matchup: vs BUF pass D avg (tilt -1%, 3g of 2026 data, shrunk toward league average) · usage: 1 targets (1% of team), aDOT 4.0, 6 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ negative value — this is the book's hold, not an edge · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Carnell Tate Under 4.5** (receptions, TEN @ BAL): market: no-vig consensus 55.0% across 4 books -> fair -122 · price: FD -122 implies 55.0% -> value +0.0c · matchup: vs BAL pass D tough -4% (tilt +4%, 3g of 2026 data, shrunk toward league average) · usage: 20 targets (25% of team), aDOT 10.9, 123 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ thin consensus — only 4 books at this number · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error
- **Cam Skattebo Over 2.5** (receptions, ARI @ NYG): market: no-vig consensus 50.6% across 5 books -> fair -103 · price: FD -102 implies 50.5% -> value +0.3c · matchup: vs ARI pass D soft +10% (tilt +10%, 3g of 2026 data, shrunk toward league average) · usage: 8 targets (10% of team), aDOT 3.8, 59 yds on the season · ⚠️ prices are 60h old — a scratch or starter change since capture is not in them · ⚠️ matchup is 3 games of data — the factor is shrunk heavily and should move almost nothing · ⚠️ no demonstrated projection edge: spreads t=+0.13, totals t=-2.77, matchup improves accuracy 0.04 yds on a 27-yd error

</details>

_Matchup factors from 2026 play-by-play, 3 games per team, shrunk toward league average by sample size. Prior-season defence explains 2-5% of current-season early-week defence, so it is not used._
