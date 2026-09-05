"""NFL model framework (v2).

Ports the MLB project's INFRASTRUCTURE — honest grading, no-vig conversion,
EV ranking, calibration boards, CLV — to NFL, with a projection layer built
on play-by-play EPA.

=============================================================================
SIGN CONVENTION — READ THIS BEFORE TOUCHING ANY LINE ARITHMETIC
=============================================================================
nflverse `spread_line` is HOME-FAVOURED-POSITIVE. A home team favoured by 3
has spread_line = +3.0. This is the OPPOSITE of the sportsbook board
convention (where the home favourite shows at -3).

Verified empirically on 2,761 games (2016+):
    corr(result, spread_line)   = +0.443
    RMSE(result - spread_line)  = 12.70   <- correct
    RMSE(result + spread_line)  = 18.09   <- what you get if the sign flips
    mean spread_line = +1.82,  mean result = +1.93

Therefore, everywhere in this codebase:
    home covers                 <=>  result > spread_line
    model edge on the home side  =  projection - spread_line
    market error                 =  result - spread_line

v1 computed edge as `projection + spread_line`. Those two expressions have
OPPOSITE SIGNS whenever |line| > |projection| — roughly half of all games —
so every ATS record, correlation and band table produced before this fix is
void. Call assert_sign_convention() in any script that does line math.
=============================================================================

STATE OF THE EVIDENCE (2018-2025, 1,578 walk-forward games)
  Regression of (result - line) on (projection - line):
      pooled slope +0.007, t = 0.13, R² = 0.00001
  The projection carries NO measurable information against the closing line.
  Not anti-predictive — empty. Per-season slopes swing from +0.285 (2022,
  t=+2.04) to -0.396 (2024, t=-2.62); both are noise. A parameter sweep over
  EPA window, prior-season carry-forward and start week leaves the pooled
  slope at zero in every configuration.

  On effect sizes: a professional targets ~2% ROI on NFL sides. Detecting
  that at -110 with 80% power needs ~17,700 bets, roughly 130 seasons of
  betting half the card. Results-based validation of an NFL sides edge is
  not achievable in a human lifetime. CLV is therefore not the preferred
  validation metric here — it is the only feasible one.

  A note on published accuracy claims: several public NFL models report
  ~64% moneyline accuracy. NFL favourites win about 64% of games, so that
  figure is the base rate, not evidence of skill.
"""

from __future__ import annotations

import csv
import io
import math
import urllib.request

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.parquet")

# ---------------------------------------------------------------------------
# FITTED PARAMETERS — produced by nfl_fit.py, stamped with a training window.
# None are asserted. If you change the window, rerun the fit. Do not hand-edit.
# ---------------------------------------------------------------------------
PARAM_FIT_WINDOW = "2018-2023 train / 2024-2025 held out"  # nfl_fit.py, n=1164

# Fitted intercept of result ~ edge_epa. HFA fell from ~2.6 (2000-09) to
# ~1.7 (2018-25); a stale 3 would be a systematic error on every game.
HOME_FIELD = 1.68

# Points per unit of opponent-adjusted EPA-per-play differential.
# v1 asserted 63.0 with an ad-hoc /2.0 divisor, an effective 31.5. The fitted
# OLS slope is 15.38 (t=6.20) — v1's projection was scaled roughly 2x too
# large, which inflated every edge it reported.
EPA_TO_POINTS = 15.38

EPA_TO_POINTS_TOTAL = 63.0
LEAGUE_TOTAL = 44.5

# Fitted calibration slope of result on projection. Below 1 would mean the
# projection is over-dispersed and its edges systematically inflated.
PROJ_SHRINK = 1.00

MARGIN_SD = 13.2
TOTAL_SD = 10.4

# Empirical mass on each margin, 2018-2025 (n=2,227); 2000-2009 in comments.
#   3: 14.8% (was 15.9%)   7: 8.5% (was 9.5%)   6: 6.6% (was 5.1%)
#   1: 4.8% (was 3.6%)     2: 4.9% (was 3.5%)
# Seven has declined, six has risen, one and two are up ~35% — consistent
# with the rise in two-point attempts. Fitted to the modern era, not all-era.
KEY_NUMBERS = {3: 0.148, 7: 0.085, 6: 0.066, 14: 0.052, 2: 0.049,
               10: 0.048, 4: 0.048, 1: 0.048, 5: 0.042, 8: 0.033}


def assert_sign_convention(games: list[dict], tol: float = 2.0) -> float:
    """Fail loudly if spread_line is not home-favoured-positive."""
    n, sq = 0, 0.0
    for g in games:
        sp, res = _f(g.get("spread_line")), _f(g.get("result"))
        if sp is None or res is None:
            continue
        n += 1
        sq += (res - sp) ** 2
    if n < 100:
        raise AssertionError(f"sign check needs >=100 games, got {n}")
    rmse = math.sqrt(sq / n)
    if abs(rmse - 12.7) > tol:
        raise AssertionError(
            f"spread_line SIGN CONVENTION CHECK FAILED: "
            f"RMSE(result - spread_line) = {rmse:.2f}, expected ~12.7. "
            f"If this is near 18, spread_line is no longer home-favoured-"
            f"positive and every edge calculation in this codebase is inverted.")
    return rmse


def fetch_games(min_season: int = 2016) -> list[dict]:
    """nflverse games.csv — schedule, results, and CLOSING market lines."""
    raw = urllib.request.urlopen(GAMES_URL, timeout=60).read().decode("utf8")
    out = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            if int(row.get("season") or 0) < min_season:
                continue
        except (TypeError, ValueError):
            continue
        out.append(row)
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def team_epa_ratings(pbp, through_week: int | None = None,
                     window: int = 10, prior: dict | None = None,
                     prior_weight: float = 0.0) -> dict:
    """Opponent-adjusted offensive and defensive EPA per play.

    `through_week` enforces the leak-free boundary: only plays strictly
    before that week are used. NOTE: at through_week=1 there are no prior
    plays, so this returns {} and no projection is possible. The model has
    no Week 1 capability without a prior-season carry-forward.

    `prior` carries forward end-of-prior-season ratings; `prior_weight` is
    in pseudo-weeks and decays as the current season accumulates.
    """
    df = pbp
    if through_week is not None:
        df = df[df["week"] < through_week]
    df = df[(df["pass"] == 1) | (df["rush"] == 1)]
    df = df.dropna(subset=["epa", "posteam", "defteam"])
    if df.empty:
        return {}

    if window:
        weeks = sorted(df["week"].unique())
        df = df[df["week"].isin(weeks[-window:])]

    off = df.groupby("posteam")["epa"].agg(["mean", "count"])
    de = df.groupby("defteam")["epa"].agg(["mean", "count"])
    lg = df["epa"].mean()

    opp_def = df.groupby("posteam")["defteam"].apply(
        lambda s: de.loc[s.unique(), "mean"].mean() if len(s) else lg)
    opp_off = df.groupby("defteam")["posteam"].apply(
        lambda s: off.loc[s.unique(), "mean"].mean() if len(s) else lg)

    n_weeks = int(df["week"].nunique())
    ratings = {}
    for t in set(off.index) | set(de.index):
        o = off["mean"].get(t, lg)
        d = de["mean"].get(t, lg)
        o_adj = o - (opp_def.get(t, lg) - lg)
        d_adj = d - (opp_off.get(t, lg) - lg)
        if prior and prior_weight > 0 and t in prior:
            w = prior_weight / (prior_weight + max(n_weeks, 1))
            o_adj = (1 - w) * o_adj + w * prior[t]["off_adj"]
            d_adj = (1 - w) * d_adj + w * prior[t]["def_adj"]
        ratings[t] = {"off_epa": o, "def_epa": d, "off_adj": o_adj,
                      "def_adj": d_adj,
                      "plays_off": int(off["count"].get(t, 0)),
                      "plays_def": int(de["count"].get(t, 0)),
                      "net": o_adj - d_adj}
    ratings["_league_epa"] = lg
    return ratings


def edge_epa(ratings: dict, away: str, home: str) -> float | None:
    """Raw opponent-adjusted EPA differential, home perspective."""
    ra, rh = ratings.get(away), ratings.get(home)
    if not ra or not rh:
        return None
    return (rh["off_adj"] - ra["def_adj"]) - (ra["off_adj"] - rh["def_adj"])


def project_spread(ratings: dict, away: str, home: str,
                   home_rest: float | None = None,
                   away_rest: float | None = None
                   ) -> tuple[float | None, list[str]]:
    """Projected margin, HOME perspective (positive = home favoured).

    Same sign convention as nflverse spread_line, so the model's edge on the
    home side is simply `project_spread(...) - spread_line`.
    """
    basis = []
    e = edge_epa(ratings, away, home)
    if e is None:
        return None, ["missing EPA rating for one side"]
    margin = e * EPA_TO_POINTS
    basis.append(f"opponent-adjusted EPA edge {e:+.4f}/play -> {margin:+.1f} pts")
    margin += HOME_FIELD
    basis.append(f"home field +{HOME_FIELD}")
    if home_rest is not None and away_rest is not None:
        diff = home_rest - away_rest
        if abs(diff) >= 3:
            adj = max(-1.5, min(1.5, diff * 0.20))
            margin += adj
            basis.append(f"rest {home_rest:.0f}d vs {away_rest:.0f}d -> {adj:+.1f}")
    if PROJ_SHRINK != 1.0:
        margin *= PROJ_SHRINK
        basis.append(f"calibration shrink x{PROJ_SHRINK:.2f}")
    return margin, basis


def project_total(ratings: dict, away: str, home: str,
                  league_total: float = LEAGUE_TOTAL,
                  roof: str | None = None,
                  wind: float | None = None) -> tuple[float | None, list[str]]:
    basis = []
    ra, rh = ratings.get(away), ratings.get(home)
    if not ra or not rh:
        return None, ["missing EPA rating for one side"]
    combined = (ra["off_adj"] + rh["def_adj"]) + (rh["off_adj"] + ra["def_adj"])
    total = league_total + combined * EPA_TO_POINTS_TOTAL
    basis.append(f"combined EPA {combined:+.4f}/play -> {total:.1f} projected")
    if roof and roof.lower() in ("dome", "closed"):
        total += 0.6
        basis.append("indoors +0.6")
    elif wind and wind >= 15:
        adj = -min(3.0, (wind - 12) * 0.18)
        total += adj
        basis.append(f"wind {wind:.0f}mph {adj:+.1f}")
    return total, basis


def cover_probability(projection: float, line: float,
                      sd: float = MARGIN_SD) -> float:
    """P(home covers), where `line` is nflverse spread_line (home-positive).

    v1 used `projection + line`, the sportsbook-board convention, which is
    INVERTED relative to the data source.
    """
    diff = projection - line
    p = 0.5 * (1 + math.erf(diff / (sd * math.sqrt(2))))
    return max(0.01, min(0.99, p))


def key_number_flag(projection: float, line: float) -> str | None:
    """Warn when projection and line straddle a key number (signed values)."""
    lo, hi = min(projection, line), max(projection, line)
    if hi - lo >= 3.0:
        return None
    for kn, mass in sorted(KEY_NUMBERS.items(), key=lambda kv: -kv[1]):
        for k in (kn, -kn):
            if lo <= k <= hi:
                return (f"projection {projection:+.1f} and line {line:+.1f} straddle "
                        f"key number {k:+d} ({mass:.1%} of NFL margins land exactly "
                        f"there) — small projection errors flip this bet")
    return None


def market_baseline_check(games: list[dict]) -> dict:
    """How well does the CLOSING LINE itself predict? The bar to beat."""
    n = cover_home = push = 0
    sq_err = 0.0
    for g in games:
        sp, res = _f(g.get("spread_line")), _f(g.get("result"))
        if sp is None or res is None:
            continue
        n += 1
        sq_err += (res - sp) ** 2
        if res == sp:
            push += 1
        elif res > sp:
            cover_home += 1
    if not n:
        return {}
    return {"games": n, "rmse": math.sqrt(sq_err / n),
            "home_cover_rate": cover_home / n, "push_rate": push / n}


def bets_needed(roi: float, price: int = -110, power: float = 0.80) -> int:
    """Bets required to distinguish an ROI from zero at 80% power, alpha=.05.

    At -110 the per-bet SD is ~0.95 units. A 2% ROI needs ~17,700 bets. This
    is why results-based validation of an NFL sides edge is not achievable
    and CLV is the only feasible ground truth.
    """
    z = {0.80: 2.80, 0.90: 3.24, 0.50: 1.96}[power]
    sd = 0.95 if price == -110 else 1.0
    return int(round((z * sd / roi) ** 2))
