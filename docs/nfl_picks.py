#!/usr/bin/env python3
"""nfl_picks.py — the whole board in one file.

Writes docs/PICKS.md: locked picks, value board, probability board, matchup
board, and the results of everything previously published.

DELIBERATELY SELF-CONTAINED. It imports nfl_lines (already in the repo) and
pandas, and nothing else. The prop model's distributions are implemented
here with math.erf and lgamma rather than scipy, so requirements.txt does
not change and the capture workflow cannot fail on a missing dependency.

THREE QUESTIONS, THREE COLUMNS
  Hit%    no-vig consensus across all books — how often it lands.
  Value   EV of the DK/FD price against that consensus, in cents.
  Model   our own estimate, independent of price (props only).

WHAT IS AND IS NOT DEMONSTRATED
  Spread projection vs closing line: slope +0.007, t = 0.13, n = 1,578.
  Totals: slope -0.107, t = -2.77. Both zero or worse.
  Prop model calibration, walk-forward on 66,527 player-game-lines:
  60-70% reads 62.9% actual, 70-80% reads 77.5%. Calibrated in that band,
  overconfident by 4-11 points below it, and wrong above 80%.
  Nothing here has a graded betting record yet.

Run:  python nfl_picks.py --days 7 --top 15 --out docs/PICKS.md
      python nfl_picks.py --game Bears --out docs/GAME.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.request
from collections import defaultdict

import nfl_lines as L

SNAP = "data/nfl_odds_snapshots.jsonl"
PROPS = "data/nfl_props_snapshots.jsonl"
PICKLOG = "data/nfl_board_picks.jsonl"
BOOKS = {"draftkings": "DK", "fanduel": "FD"}
MKT = {"spreads": "Spread", "totals": "Total", "h2h": "ML"}

MIN_PLAY_PROB = 0.70      # market probability floor for a PLAY
MODEL_PLAY_PROB = 0.60    # model floor; below this the model is not calibrated
STALE_PLAY_HOURS = 8      # no PLAY may be issued on prices older than this
SEASON = int(os.environ.get("NFL_SEASON", "2026"))

# Minimum CURRENT-season games before the model may speak. Measured week 4
# of 2026: at 3 games the blended mean is dominated by LAST season while the
# market prices this one — Chuba Hubbard's model mean was 34 yards against
# 2026 games of 49/53/82 and a line of 65.5, so the model called "Under 80%".
# Nine of twelve rows were Unders at a uniform +25-33% divergence. That is a
# stale average, not an edge. Six is roughly week 7.
MIN_GAMES = int(os.environ.get("NFL_PROJ_MIN_GAMES", "6"))

SHRINK_K = 3.0
VAR_INFLATE = 1.55
MAX_CLAIM = 0.80          # model reads 73-75% in its 80-90% bucket; cap it

# Favourite-longshot bias, measured on 8,796 team-games 2010-2025.
# Proportional de-vigging overstates underdogs and understates favourites.
CALIB = [(0.00, 0.20, -0.015), (0.20, 0.30, -0.013), (0.30, 0.40, +0.011),
         (0.40, 0.60, 0.000), (0.60, 0.70, -0.011), (0.70, 1.01, +0.013)]

MARKET_STAT = {"player_receptions": "receptions",
               "player_reception_yds": "rec_yds",
               "player_rush_attempts": "carries",
               "player_rush_yds": "rush_yds",
               "player_pass_yds": "pass_yds",
               "player_pass_completions": "completions"}
COUNT_STATS = {"receptions", "carries", "completions"}
CAT = {"player_rush_yds": "rush", "player_rush_attempts": "rush",
       "player_reception_yds": "pass", "player_receptions": "pass",
       "player_pass_yds": "pass", "player_pass_completions": "pass"}

TEAM = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


# --------------------------------------------------------------------------
# small stats, stdlib only
# --------------------------------------------------------------------------

def norm_sf(x, mu, sd):
    """P(X > x) for a normal. math.erf, so no scipy."""
    if sd <= 0:
        return None
    return 0.5 * math.erfc((x - mu) / (sd * math.sqrt(2)))


def nbinom_sf(k, r, p):
    """P(X > k) for a negative binomial, summed directly.

    Prop lines are small integers, so the sum is a few terms. lgamma handles
    the non-integer r that comes out of moment-matching.
    """
    k = int(math.floor(k))
    if k < 0:
        return 1.0
    total = 0.0
    for i in range(k + 1):
        lp = (math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1)
              + r * math.log(p) + i * math.log1p(-p))
        total += math.exp(lp)
    return max(0.0, min(1.0, 1.0 - total))


def calibrate(p):
    for lo, hi, adj in CALIB:
        if lo <= p < hi:
            return min(0.99, max(0.01, p + adj))
    return p


def age_hours(ts):
    if not ts:
        return 999.0
    try:
        t = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return 999.0
    return max(0.0, (time.mktime(time.gmtime()) - t) / 3600)


def load(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def fmt(p):
    return f"{p:+.0f}" if p is not None else "—"


# --------------------------------------------------------------------------
# nflverse play-by-play: game logs, defence factors, usage
# --------------------------------------------------------------------------

def _pbp(season):
    import pandas as pd
    p = f"/tmp/pbp_{season}.parquet"
    if not os.path.exists(p):
        u = (f"https://github.com/nflverse/nflverse-data/releases/download/pbp/"
             f"play_by_play_{season}.parquet")
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        open(p, "wb").write(urllib.request.urlopen(req, timeout=300).read())
    return pd.read_parquet(p)


def _roster(season):
    import pandas as pd
    f = f"/tmp/roster_{season}.parquet"
    if not os.path.exists(f):
        u = (f"https://github.com/nflverse/nflverse-data/releases/download/"
             f"weekly_rosters/roster_weekly_{season}.parquet")
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        open(f, "wb").write(urllib.request.urlopen(req, timeout=180).read())
    return pd.read_parquet(f, columns=["gsis_id", "full_name", "team"])


def name_to_id(season):
    """Full name -> gsis_id.

    KEYED ON ID, NOT NAME. Play-by-play writes 'J.Williams', and in 2026
    that covers a Dallas receiver and a Detroit one — nine short names span
    multiple teams. Pooling them gave one player a 14-game log he never
    earned and mispriced a dozen props.
    """
    out = {}
    for yr in (season, season - 1):
        try:
            r = _roster(yr)
        except Exception:
            continue
        for nm, gid, tm in zip(r.full_name, r.gsis_id, r.team):
            if nm and gid:
                out.setdefault(str(nm), str(gid))
                out.setdefault(f"{nm}|{tm}", str(gid))
    return out


def game_logs(season):
    """{gsis_id: {stat: [per-game values], '_cur_n': {...}, '_prior': {...}}}

    Current season backfilled with the prior REGULAR season. nflverse carries
    playoffs as weeks 19-22; including them made "the last six weeks" mostly
    postseason that few teams played, which silently gave Drake London two
    prior games instead of twelve.
    """
    out, prior = {}, {}

    def add(frame, idcol, cols, store):
        g = frame.dropna(subset=[idcol]).groupby(["week", idcol]).agg(**cols)
        for (_wk, pid), row in g.iterrows():
            d = out.setdefault(pid, {})
            for stat in cols:
                d.setdefault(stat, []).append(float(row[stat]))
            if store is not None:
                q = store.setdefault(pid, {})
                for stat in cols:
                    q.setdefault(stat, []).append(float(row[stat]))

    for yr in (season - 1, season):
        try:
            df = _pbp(yr)
        except Exception:
            continue
        if df.empty:
            continue
        if yr != season:
            df = df[df["week"] <= 18]
        st = prior if yr != season else None
        add(df, "receiver_player_id",
            {"receptions": ("complete_pass", "sum"),
             "rec_yds": ("receiving_yards", "sum")}, st)
        add(df[df["rush_attempt"] == 1], "rusher_player_id",
            {"carries": ("rush_attempt", "sum"),
             "rush_yds": ("rushing_yards", "sum")}, st)
        add(df[df["pass_attempt"] == 1], "passer_player_id",
            {"pass_yds": ("passing_yards", "sum"),
             "completions": ("complete_pass", "sum")}, st)

    for pid, d in out.items():
        pr = prior.get(pid, {})
        stats = [k for k in d if not k.startswith("_")]
        d["_cur_n"] = {k: max(0, len(d[k]) - len(pr.get(k, []))) for k in stats}
        d["_prior"] = {k: statistics.mean(v) for k, v in pr.items() if v}
        for k in stats:
            d[k] = d[k][-14:]
    return out


def model_p(pid, market, line, side, logs, def_factor=1.0):
    """Calibrated P(the bet hits), or None when the player has no current role."""
    stat = MARKET_STAT.get(market)
    if not stat or line is None:
        return None, 0
    rec = logs.get(pid) or {}
    h = rec.get(stat)
    if not h:
        return None, 0
    cur_n = (rec.get("_cur_n") or {}).get(stat, 0)
    if cur_n < MIN_GAMES:
        return None, cur_n
    n = len(h)
    m = statistics.mean(h)
    target = (rec.get("_prior") or {}).get(stat, m)
    m = (n * m + SHRINK_K * target) / (n + SHRINK_K) * def_factor
    if m <= 0:
        return None, cur_n
    infl = VAR_INFLATE * (1 + 1 / n)
    if stat in COUNT_STATS:
        v = max(statistics.variance(h) if n > 1 else m, m * 1.01) * infl
        r = m * m / max(v - m, 1e-6)
        po = nbinom_sf(line, r, r / (r + m))
    else:
        sd = (statistics.stdev(h) if n > 1 else 0) * math.sqrt(infl)
        po = norm_sf(line, m, sd)
    if po is None:
        return None, cur_n
    p = po if str(side).lower() == "over" else 1 - po
    return float(min(MAX_CLAIM, max(1 - MAX_CLAIM, p))), cur_n


def defense_factors(season, shrink_games=6.0):
    """{(cat, TEAM): factor}, >1 = softer. Current season only.

    Prior-season defence explains 2% of current-season early-week rushing
    defence and 5% of passing (r = +0.14 / +0.23, 2019-2025), so it is not
    used. Shrunk toward 1.0 by games played.
    """
    try:
        df = _pbp(season)
    except Exception:
        return {}, 0
    out, ng = {}, 0
    for cat, flag, col in (("rush", "rush_attempt", "rushing_yards"),
                           ("pass", "pass_attempt", "passing_yards")):
        s = df[df[flag] == 1].dropna(subset=["defteam", col])
        if s.empty:
            continue
        lg = s[col].mean()
        gp = s.groupby("defteam")["week"].nunique()
        ng = max(ng, int(gp.max()))
        for t, v in s.groupby("defteam")[col].mean().items():
            n = int(gp.get(t, 0))
            w = n / (n + shrink_games)
            out[(cat, t)] = 1.0 + w * ((v / lg if lg else 1.0) - 1.0)
    return out, ng


def usage_map(season):
    try:
        df = _pbp(season)
    except Exception:
        return {}
    t = df.dropna(subset=["receiver_player_id", "posteam"])
    g = t.groupby(["posteam", "receiver_player_id"]).agg(
        tgt=("pass_attempt", "sum"), yds=("receiving_yards", "sum"),
        ay=("air_yards", "mean")).reset_index()
    tot = g.groupby("posteam")["tgt"].sum()
    return {r.receiver_player_id: {
        "tgt": r.tgt, "yds": r.yds,
        "ay": r.ay if r.ay == r.ay else 0.0,
        "share": r.tgt / tot[r.posteam] if tot[r.posteam] else 0}
        for _, r in g.iterrows()}


def player_teams(season):
    try:
        df = _pbp(season)
    except Exception:
        return {}
    m = {}
    for col in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
        t = df.dropna(subset=[col, "posteam"])
        for pid, tm in t.groupby(col)["posteam"].agg(
                lambda s: s.value_counts().index[0]).items():
            m.setdefault(pid, tm)
    return m


# --------------------------------------------------------------------------
# board
# --------------------------------------------------------------------------

def main_line_only(rows):
    """Keep each book's quote at the MAIN number only.

    Books post alternate spreads and totals; pooled in, the consensus mixes a
    -3.5 quote with a -5 alternate and prices neither correctly.
    """
    latest = {}
    for r in rows:
        k = (r["game_id"], r["market"], r["book"], r["outcome"], r.get("point"))
        if k not in latest or r["captured_at"] > latest[k]["captured_at"]:
            latest[k] = r
    rows = list(latest.values())
    bypoint = defaultdict(set)
    for r in rows:
        bypoint[(r["game_id"], r["market"], abs(r.get("point") or 0))].add(r["book"])
    best = {}
    for (gid, mkt, ap), bks in bypoint.items():
        if mkt == "h2h":
            continue
        if (gid, mkt) not in best or len(bks) > len(best[(gid, mkt)][1]):
            best[(gid, mkt)] = (ap, bks)
    keep = []
    for r in rows:
        if r["market"] == "h2h":
            keep.append(r)
        else:
            b = best.get((r["game_id"], r["market"]))
            if b and abs(r.get("point") or 0) == b[0]:
                keep.append(r)
    return keep


def verdict(p, stale_h):
    # A PLAY claims DK/FD are off the market RIGHT NOW. On stale prices that
    # claim cannot be supported, so the board refuses rather than warns.
    if stale_h > STALE_PLAY_HOURS:
        return "STALE"
    mp = p.get("model_p")
    if mp is not None and mp >= MODEL_PLAY_PROB and p["ev"] >= -0.01 \
            and (p.get("diverg") or 0) > 0.03:
        return "PLAY"
    if p["ev"] >= 0.01 and p["prob"] >= MIN_PLAY_PROB:
        return "PLAY"
    if p["ev"] >= 0.0 and p["prob"] >= 0.55:
        return "LEAN"
    return "PASS"


def build(days, only, season):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cut = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(time.time() + days * 86400))
    G = [r for r in load(SNAP) if now < (r.get("commence_time") or "") < cut]
    P = [r for r in load(PROPS) if now < (r.get("commence_time") or "") < cut]
    if only:
        k = only.lower()
        hit = lambda r: k in (r.get("away_team", "") + " " +
                              r.get("home_team", "")).lower()
        G, P = [r for r in G if hit(r)], [r for r in P if hit(r)]
    if not G:
        return None
    games = {r["game_id"]: (r["away_team"], r["home_team"]) for r in G}
    age_g = max((r["captured_at"] for r in G), default="")
    age_p = max((r["captured_at"] for r in P), default="")

    fac, ngames = defense_factors(season)
    logs = game_logs(season) if P else {}
    ids = name_to_id(season) if P else {}
    pteam = player_teams(season) if P else {}
    usage = usage_map(season) if P else {}

    picks, all_prices = [], defaultdict(dict)

    for (gid, mkt, out, pt), c in L.consensus(main_line_only(G), min_books=4).items():
        a, h = games[gid]
        cp = calibrate(c["consensus"])
        bet = out + ("" if pt is None else f" {pt:+g}")
        for e in c["entries"]:
            if e["book"] not in BOOKS:
                continue
            all_prices[(gid, MKT.get(mkt, mkt), bet)][BOOKS[e["book"]]] = e["price"]
            picks.append(dict(gid=gid, game=f"{TEAM.get(a,a)} @ {TEAM.get(h,h)}",
                              bet=bet, kind=MKT.get(mkt, mkt), book=BOOKS[e["book"]],
                              price=e["price"], prob=cp, raw_prob=c["consensus"],
                              ev=L.ev_at(e["price"], cp), nb=c["n_books"],
                              model_p=None, diverg=None, mnote="", opp=None,
                              model_n=0))

    try:
        import nfl_props as NP
        pcons = NP.consensus(P, min_books=3) if P else {}
        one_way = getattr(NP, "ONE_WAY", {"player_anytime_td"})
    except Exception:
        pcons, one_way = {}, set()

    for (gid, mkt, player, side, pt), c in pcons.items():
        if mkt in one_way or gid not in games:
            continue
        a, h = games[gid]
        ac, hc = TEAM.get(a, a), TEAM.get(h, h)
        pid = ids.get(f"{player}|{ac}") or ids.get(f"{player}|{hc}") \
            or ids.get(str(player))
        own = pteam.get(pid)
        opp = hc if own == ac else ac if own == hc else None
        cat = CAT.get(mkt)
        tilt, note = 0.0, ""
        if opp and cat:
            f = fac.get((cat, opp))
            if f is not None:
                raw = f - 1.0
                tilt = raw if str(side).lower() == "over" else -raw
                note = (f"{cat} D avg" if abs(raw) < 0.02 else
                        f"{cat} D {'soft' if raw > 0 else 'tough'} {raw:+.0%}")
        mp, cur_n = model_p(pid, mkt, pt, side, logs, 1.0 + 0.5 * tilt)
        bet = f"{player} {side}" + ("" if pt is None else f" {pt:g}")
        kind = mkt.replace("player_", "").replace("_", " ")
        for e in c["entries"]:
            if e["book"] not in BOOKS:
                continue
            all_prices[(gid, kind, bet)][BOOKS[e["book"]]] = e["price"]
            pay = (e["price"] / 100) if e["price"] > 0 else (100 / abs(e["price"]))
            picks.append(dict(gid=gid, game=f"{ac} @ {hc}", bet=bet, kind=kind,
                              book=BOOKS[e["book"]], price=e["price"],
                              prob=c["consensus"], raw_prob=c["consensus"],
                              ev=L.ev_at(e["price"], c["consensus"]),
                              nb=c["n_books"], model_p=mp, model_n=cur_n,
                              diverg=(mp - c["consensus"]) if mp else None,
                              model_ev=(mp * pay - (1 - mp)) if mp else None,
                              mnote=note, mtilt=tilt, opp=opp,
                              usage=usage.get(pid)))

    best = {}
    for p in picks:
        k = (p["gid"], p["kind"], p["bet"])
        if k not in best or p["ev"] > best[k]["ev"]:
            best[k] = p
    return list(best.values()), all_prices, age_g, age_p, ngames, len(games)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def book_cell(p, all_prices):
    d = all_prices.get((p["gid"], p["kind"], p["bet"]), {})
    if not d:
        return f"**{p['book']} {fmt(p['price'])}**"
    bb = max(d, key=lambda b: L.ev_at(d[b], 0.5))
    return " / ".join(f"**{b} {fmt(v)}**" if b == bb else f"{b} {fmt(v)}"
                      for b, v in sorted(d.items()))


def _key(p):
    return f"{p['game']}|{p['kind']}|{p['bet']}"


def load_history(path):
    """Result strings already recorded, so a regenerated board keeps them."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        if line.startswith("|") and ("✅" in line or "❌" in line):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 3:
                out[f"{c[0]}|{c[1]}|{c[2]}"] = c[-1]
    return out


def prior_sections(path, today):
    """History below today's block. Regenerating the same day REPLACES it —
    the board runs every three hours and would otherwise stack duplicates."""
    if not os.path.exists(path):
        return []
    txt = open(path).read().split("\n")
    for i, ln in enumerate(txt):
        if ln.startswith("## 20") and ln.strip() != f"## {today}":
            return txt[i:]
    return []


def render(res, top, title, out_path):
    picks, all_prices, age_g, age_p, ngames, n_games = res
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    day = time.strftime("%Y-%m-%d", time.gmtime())
    stale = max(age_hours(age_g), age_hours(age_p) if age_p else 0)
    hist = load_history(out_path)

    for p in picks:
        p["score"] = p["ev"] * 100 + 10 * (p["prob"] - 0.5)
        p["verdict"] = verdict(p, stale)
    ranked = sorted(picks, key=lambda p: -p["score"])

    o = [f"# {title}", "",
         "Picks frozen at the price they were read at. **Both books shown; "
         "bold = better price.** Paper only.", "",
         f"{n_games} games · {len(picks)} DK/FD prices · lines {age_hours(age_g):.0f}h old"
         + (f" · props {age_hours(age_p):.0f}h old" if age_p else " · no props"), "",
         "| Column | Means |", "|---|---|",
         "| **Hit%** | no-vig consensus across all books |",
         "| **Value** | EV of the DK/FD price vs that consensus, in cents |",
         "| **Model** | our own estimate, independent of price (props only) |",
         ""]
    if stale > STALE_PLAY_HOURS:
        o += [f"> ⚠️ **Prices are {stale:.0f}h old — no PLAY can be issued.** "
              f"Run capture-odds, then regenerate.", ""]
    o += [f"## {day}", ""]

    # 1. plays
    plays = [p for p in ranked if p["verdict"] == "PLAY"][:top]
    leans = [] if stale > STALE_PLAY_HOURS else \
        [p for p in ranked if p["verdict"] == "LEAN"][:6]
    o += ["| Verdict | Score | Game | Market | Pick | Hit% | Books (best bold) |",
          "|---|---|---|---|---|---|---|"]
    if stale > STALE_PLAY_HOURS:
        o.append("| STALE | — | _prices too old to issue a play_ | | | | |")
    elif plays:
        for p in plays:
            o.append(f"| **PLAY** | {p['score']:.1f} | {p['game']} | {p['kind']} "
                     f"| {p['bet']} | {p['prob']:.0%} | {book_cell(p, all_prices)} |")
    else:
        o.append("| PASS | — | _no DK/FD price clears the bar on this board_ | | | | |")
    for p in leans:
        o.append(f"| LEAN | {p['score']:.1f} | {p['game']} | {p['kind']} "
                 f"| {p['bet']} | {p['prob']:.0%} | {book_cell(p, all_prices)} |")
    o.append("")

    # 2. model divergence
    div = sorted([p for p in picks if p.get("model_p")
                  and p["model_p"] >= MODEL_PLAY_PROB],
                 key=lambda p: -(p["diverg"] or 0))
    o += ["#### Model Divergence — our number vs **no-vig** market", "",
          "*Divergence means our number disagrees with the market — it does "
          "NOT mean the market is wrong. When we disagree the more likely "
          "explanation is that our number is worse. Model is calibrated "
          "60-80% (walk-forward n=66,527: 60-70 reads 62.9%, 70-80 reads "
          "77.5%) and capped at 80%.*", "",
          "| Player | Market | Line | **Model** | No-vig | Diverg. | Books | Result |",
          "|---|---|---|---|---|---|---|---|"]
    if div:
        for p in div[:top]:
            o.append(f"| {p['bet']} | {p['kind']} | — | **{p['model_p']:.0%}** "
                     f"({p['model_n']}g) | {p['prob']:.0%} | {p['diverg']:+.1%} "
                     f"| {book_cell(p, all_prices)} | {hist.get(_key(p),'pending')} |")
    else:
        o.append(f"| _no prop with {MIN_GAMES}+ current-season games reaches "
                 f"{MODEL_PLAY_PROB:.0%}_ | | | | | | | |")
    o += ["", f"*Requires {MIN_GAMES} current-season games. Below that the "
          f"model's mean is dominated by last season while the market prices "
          f"this one, which produced a uniform Under bias in week 4.*", ""]

    # 3. value
    o += ["#### Value Board — DK/FD furthest off the market", "",
          "| Game | Market | Pick | Hit% | Value | Books | Result |",
          "|---|---|---|---|---|---|---|"]
    for p in sorted([x for x in picks if x["prob"] >= 0.55],
                    key=lambda x: -x["ev"])[:top]:
        o.append(f"| {p['game']} | {p['kind']} | **{p['bet']}** | {p['prob']:.0%} "
                 f"| {p['ev']*100:+.1f}¢ | {book_cell(p, all_prices)} "
                 f"| {hist.get(_key(p),'pending')} |")
    o += ["", "*Value means one book is priced away from the others. Negative "
          "is their hold — normal on a settled market.*", ""]

    # 4. probability
    o += [f"#### Probability Board — every bet at {MIN_PLAY_PROB:.0%}+ to hit", "",
          "*The 70-80% range is the best-calibrated band on the board: "
          "predicted 74.7%, actual 76.2% over 8,796 team-games.*", "",
          "| Game | Market | Pick | **Hit%** | Value | Books | Result |",
          "|---|---|---|---|---|---|---|"]
    hp = sorted([p for p in picks if p["prob"] >= MIN_PLAY_PROB],
                key=lambda p: -p["prob"])[:top]
    if hp:
        for p in hp:
            o.append(f"| {p['game']} | {p['kind']} | **{p['bet']}** "
                     f"| **{p['prob']:.0%}** | {p['ev']*100:+.1f}¢ "
                     f"| {book_cell(p, all_prices)} | {hist.get(_key(p),'pending')} |")
    else:
        o.append(f"| _nothing reaches {MIN_PLAY_PROB:.0%}_ | | | | | | |")
    o.append("")

    # 5. matchup
    mu = sorted([p for p in picks if p.get("mnote") and abs(p.get("mtilt", 0)) > 0.03],
                key=lambda p: -(p["mtilt"] + p["ev"]))[:top]
    o += ["#### Matchup Board — opponent strength (current season only)", "",
          f"*{ngames} games of {SEASON} data, shrunk by sample size. "
          "Prior-season defence explains 2-5% of current-season defence, so "
          "it is excluded. The book already knows the ranking — this answers "
          "'who are they playing'.*", "",
          "| Game | Pick | Opponent D | Tilt | Hit% | Value | Books |",
          "|---|---|---|---|---|---|---|"]
    if mu:
        for p in mu:
            o.append(f"| {p['game']} | **{p['bet']}** | vs {p['opp']} {p['mnote']} "
                     f"| {p['mtilt']:+.0%} | {p['prob']:.0%} | {p['ev']*100:+.1f}¢ "
                     f"| {book_cell(p, all_prices)} |")
    else:
        o.append("| _no matchup differs enough from average_ | | | | | | |")
    o.append("")

    # 6. reasoning
    o += ["<details>", "<summary><b>How each number was built</b></summary>", ""]
    for p in ranked[:top]:
        bits = []
        if abs(p.get("raw_prob", p["prob"]) - p["prob"]) > 0.001:
            bits.append(f"calibration: raw de-vig {p['raw_prob']:.1%} -> "
                        f"{p['prob']:.1%} (favourite-longshot bias, 8,796 games)")
        bits.append(f"market: {p['prob']:.1%} across {p['nb']} books -> fair "
                    f"{fmt(L.prob_to_american(p['prob']))}")
        bits.append(f"price: {p['book']} {fmt(p['price'])} -> "
                    f"value {p['ev']*100:+.1f}¢")
        if p.get("model_p"):
            bits.append(f"model: {p['model_p']:.1%} on {p['model_n']} current-"
                        f"season games, divergence {p['diverg']:+.1%}")
        if p.get("mnote"):
            bits.append(f"matchup: vs {p['opp']} {p['mnote']}")
        u = p.get("usage")
        if u:
            bits.append(f"usage: {u['tgt']:.0f} targets ({u['share']:.0%} of "
                        f"team), aDOT {u['ay']:.1f}")
        w = []
        if stale > 6:
            w.append(f"prices {stale:.0f}h old")
        if p["nb"] < 5:
            w.append(f"thin consensus, {p['nb']} books")
        if p["ev"] < 0:
            w.append("negative value — this is the book's hold")
        w.append("no demonstrated projection edge: spreads t=+0.13, "
                 "totals t=-2.77")
        o.append(f"- **{p['bet']}** ({p['kind']}, {p['game']}): "
                 + " · ".join(bits) + " · " + " · ".join("⚠️ " + x for x in w))
    o += ["", "</details>", ""]

    # log what was published, stamped with the CAPTURE time so CLV has a
    # forward window — wall-clock would leave none, since the board runs
    # after the sweep.
    os.makedirs("data", exist_ok=True)
    with open(PICKLOG, "a") as f:
        for i, p in enumerate(ranked[:top], 1):
            f.write(json.dumps({"published_at": age_g or now, "board_ran_at": now,
                                "rank": i, "game_id": p["gid"], "matchup": p["game"],
                                "market": p["kind"], "bet": p["bet"],
                                "book": p["book"], "price": p["price"],
                                "prob": round(p["prob"], 4),
                                "ev": round(p["ev"], 5)}) + "\n")
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--game", default=None)
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--title", default="NFL Locked Picks")
    ap.add_argument("--out", default="docs/PICKS.md")
    a = ap.parse_args()

    res = build(a.days, a.game, a.season)
    if res is None:
        print("no upcoming games matched — nothing written")
        return
    o = render(res, a.top, a.title, a.out)
    o += prior_sections(a.out, time.strftime("%Y-%m-%d", time.gmtime()))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w").write("\n".join(o))
    print(f"Wrote {a.out} — {len(res[0])} DK/FD prices ranked")


if __name__ == "__main__":
    main()
