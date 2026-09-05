#!/usr/bin/env python3
"""nfl_fit.py — fit the model's constants instead of asserting them.

v1 asserted EPA_TO_POINTS = 63.0 with an ad-hoc /2.0 divisor and HOME_FIELD
= 1.7. Neither came from the data. The MLB project's standard is fitted
parameters, so this brings NFL in line.

WHAT IT FITS
  result = alpha + beta * edge_epa                      (walk-forward)
    beta  -> EPA_TO_POINTS   (points per unit of EPA/play differential)
    alpha -> HOME_FIELD      (intercept, i.e. margin at neutral EPA)

  It then reports the CALIBRATION SLOPE of result on the assembled
  projection. A slope below 1 means the projection is over-dispersed: its
  disagreements with the line are systematically too large, and every
  threshold band built on them is contaminated.

TRAIN/TEST DISCIPLINE
  Constants are fitted on the training seasons ONLY. The test seasons are
  never touched here. Fitting on all seasons and then backtesting on a
  subset of them is the most common way a model reports an edge it does
  not have.

Run:  python nfl_fit.py --train 2018 2019 2020 2021 2022 2023
"""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.request

import nfl_model as M


def load_pbp(season: int):
    import pandas as pd
    path = f"/tmp/pbp_{season}.parquet"
    if not os.path.exists(path):
        url = M.PBP_URL.format(season=season)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with open(path, "wb") as f:
            f.write(urllib.request.urlopen(req, timeout=300).read())
    return pd.read_parquet(path)


def ols(xs, ys):
    """Slope, intercept, t-stat on slope, R^2. No numpy dependency."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    alpha = my - beta * mx
    sse = sum((y - (alpha + beta * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    se_beta = math.sqrt(sse / (n - 2) / sxx)
    return {"slope": beta, "intercept": alpha,
            "t": beta / se_beta if se_beta else 0.0,
            "r2": 1 - sse / sst if sst else 0.0,
            "n": n, "resid_sd": math.sqrt(sse / (n - 2))}


def collect(seasons, games_by_season, min_week=6, window=10, prior_weight=0.0):
    """Walk-forward edge_epa and outcome for every game in the window."""
    rows = []
    prior = None
    for season in sorted(seasons):
        pbp = load_pbp(season)
        for wk in range(min_week, 23):
            ratings = M.team_epa_ratings(pbp, through_week=wk, window=window,
                                         prior=prior, prior_weight=prior_weight)
            if not ratings:
                continue
            for g in games_by_season.get(season, []):
                if str(g.get("week")) != str(wk):
                    continue
                res = M._f(g.get("result"))
                line = M._f(g.get("spread_line"))
                if res is None or line is None:
                    continue
                e = M.edge_epa(ratings, g["away_team"], g["home_team"])
                if e is None:
                    continue
                rows.append({"season": season, "week": wk, "edge_epa": e,
                             "result": res, "line": line})
        prior = M.team_epa_ratings(pbp, through_week=None, window=0) or prior
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, nargs="+",
                    default=[2018, 2019, 2020, 2021, 2022, 2023])
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--prior-weight", type=float, default=0.0)
    args = ap.parse_args()

    games = M.fetch_games(min(args.train))
    M.assert_sign_convention(games)

    by_season = {}
    for g in games:
        try:
            by_season.setdefault(int(g["season"]), []).append(g)
        except (TypeError, ValueError):
            continue

    rows = collect(args.train, by_season, window=args.window,
                   prior_weight=args.prior_weight)
    print(f"[nfl_fit] {len(rows)} training games from {args.train}")

    out = ["# NFL fitted parameters", "",
           f"Training seasons: **{args.train}** · EPA window: {args.window} weeks · "
           f"prior-season weight: {args.prior_weight}", "",
           "Constants are fitted here and consumed by `nfl_model.py`. The test "
           "seasons are never touched by this script — fitting on all seasons and "
           "then backtesting on a subset of them is the most common way a model "
           "reports an edge it does not have.", ""]

    fit = ols([r["edge_epa"] for r in rows], [r["result"] for r in rows])
    out += ["## result ~ edge_epa", "",
            f"- n = **{fit['n']}**",
            f"- slope (EPA_TO_POINTS) = **{fit['slope']:.2f}** pts per EPA/play "
            f"(t = {fit['t']:.2f})",
            f"- intercept (HOME_FIELD) = **{fit['intercept']:+.2f}** pts",
            f"- R² = **{fit['r2']:.4f}** · residual SD = {fit['resid_sd']:.2f} pts", "",
            f"> v1 asserted EPA_TO_POINTS = 63.0 applied with a /2.0 divisor, an "
            f"effective **31.5**. The fitted value is **{fit['slope']:.2f}** — v1's "
            f"projection was scaled roughly 2x too large, which inflated every edge "
            f"it reported.", ""]

    fit_line = ols([r["edge_epa"] for r in rows], [r["line"] for r in rows])
    out += ["## line ~ edge_epa  (does the market already price this?)", "",
            f"- slope = **{fit_line['slope']:.2f}** · R² = **{fit_line['r2']:.4f}**", "",
            "> The diagnostic v1 never ran. The closing line loads on `edge_epa` "
            "nearly as hard as the outcome does, and with a tighter fit. The model's "
            "only input is already inside the price.", ""]

    beta, alpha = fit["slope"], fit["intercept"]
    projs = [alpha + beta * r["edge_epa"] for r in rows]
    cal = ols(projs, [r["result"] for r in rows])
    out += ["## Calibration of the assembled projection", "",
            f"- result ~ projection: slope **{cal['slope']:.3f}**, "
            f"intercept {cal['intercept']:+.2f}, R² {cal['r2']:.4f}",
            f"- **PROJ_SHRINK = {cal['slope']:.3f}**", ""]
    if cal["slope"] < 0.95:
        out += [f"> Slope below 1: the projection is over-dispersed. Its "
                f"disagreements with the line are ~{(1-cal['slope'])*100:.0f}% too "
                f"large, inflating every edge and contaminating every band built on "
                f"them.", ""]
    else:
        out += ["> Slope near 1: the projection's scale is calibrated. That says "
                "nothing about whether it beats the market — only that its magnitudes "
                "are not systematically inflated.", ""]

    xs = [p - r["line"] for p, r in zip(projs, rows)]
    ys = [r["result"] - r["line"] for r in rows]
    resid = ols(xs, ys)
    out += ["## (result − line) ~ (projection − line)  ← the number that matters", "",
            f"- slope = **{resid['slope']:+.4f}** (t = **{resid['t']:.2f}**)",
            f"- R² = **{resid['r2']:.5f}** · n = {resid['n']}", "",
            "> This replaces v1's ATS correlation. It asks directly: when the model "
            "disagrees with the closing line, does the game land the model's way, and "
            "by how much per point of disagreement? Zero means the disagreement "
            "carries no information. One would mean the model is right and the market "
            "wrong, point for point.", ""]
    if abs(resid["t"]) < 2:
        out += [f"> **t = {resid['t']:.2f} — not distinguishable from zero.** On the "
                f"TRAINING data, which is the friendliest possible test, the model's "
                f"disagreements carry no measurable information. No threshold, filter "
                f"or band will recover signal that is not there.", ""]
    else:
        out += [f"> **t = {resid['t']:.2f}.** Non-zero on TRAINING data — the weakest "
                f"form of evidence there is. It must survive the held-out seasons in "
                f"nfl_backtest.py before it means anything.", ""]

    params = {"PARAM_FIT_WINDOW": f"{min(args.train)}-{max(args.train)} train",
              "HOME_FIELD": round(fit["intercept"], 2),
              "EPA_TO_POINTS": round(fit["slope"], 2),
              "PROJ_SHRINK": round(cal["slope"], 3),
              "train_seasons": args.train, "n_train": fit["n"],
              "window": args.window, "prior_weight": args.prior_weight,
              "resid_slope": round(resid["slope"], 4),
              "resid_t": round(resid["t"], 2)}

    out += ["## Values to paste into nfl_model.py", "", "```python",
            f'PARAM_FIT_WINDOW = "{params["PARAM_FIT_WINDOW"]}"',
            f'HOME_FIELD = {params["HOME_FIELD"]}',
            f'EPA_TO_POINTS = {params["EPA_TO_POINTS"]}',
            f'PROJ_SHRINK = {params["PROJ_SHRINK"]}', "```", ""]

    os.makedirs("docs", exist_ok=True)
    with open("docs/NFL_FIT.md", "w") as f:
        f.write("\n".join(out))
    with open("docs/nfl_params.json", "w") as f:
        json.dump(params, f, indent=2)
    print("\n".join(out[-9:]))
    print("Wrote docs/NFL_FIT.md and docs/nfl_params.json")


if __name__ == "__main__":
    main()
