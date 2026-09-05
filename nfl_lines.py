#!/usr/bin/env python3
"""nfl_lines.py — opener capture, no-vig consensus, outlier screen, CLV grading.

WHY THIS EXISTS
  The backtest shows the projection carries no information against the
  CLOSING line (pooled slope +0.007, t=0.13, n=1,578). Two conclusions
  follow, and this file is built for both:

  1. If an edge exists it is against EARLY-WEEK prices, not the close.
     nflverse ships closing lines only — there is no opener column — so that
     hypothesis is currently untestable at any sample size. `snapshot` fixes
     that going forward. Every week not captured is lost permanently.

  2. Whatever the strategy, CLV is the only feasible validation metric.
     Detecting a 2% ROI from results needs ~17,700 bets. CLV converges in
     hundreds. `grade-clv` is the scoreboard, not the ATS record.

THE OUTLIER SCREEN requires no predictive skill. It does not ask whether a
team will cover; it asks whether one book is priced away from where every
other book has it. That is a market-relative claim and it is falsifiable on
a short horizon: if an outlier price does not predict the closing consensus,
the screen is worthless and grade-clv will say so.

CONFIG (env vars)
  ODDS_PROXY   Cloudflare worker base URL. The worker passes sport keys
               through, so `americanfootball_nfl` needs no worker change and
               draws on the existing key and credit pool.
  ODDS_REGION  default "us"

  No API key belongs in this file. The worker holds it.

USAGE
  python nfl_lines.py selftest          # verify the math offline, no credits
  python nfl_lines.py snapshot          # capture current board -> JSONL
  python nfl_lines.py screen --log      # outlier report, logged for CLV
  python nfl_lines.py grade-clv         # score captured prices vs the close
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SPORT = "americanfootball_nfl"
SNAP_PATH = "data/nfl_odds_snapshots.jsonl"
HITS_PATH = "data/nfl_screen_hits.jsonl"
PROXY = os.environ.get("ODDS_PROXY", "").rstrip("/")
REGION = os.environ.get("ODDS_REGION", "us")

# Route the worker exposes for odds. The deployed worker self-documents at its
# base URL and routes odds under /odds/{sport}/odds — NOT the raw Odds API
# path /v4/sports/{sport}/odds. Getting this wrong 404s every capture, so it
# is configurable rather than hardcoded.
ODDS_PATH = os.environ.get("ODDS_PATH_TEMPLATE", "/odds/{sport}/odds")
QUOTA_PATH = os.environ.get("ODDS_QUOTA_PATH", "/quota")


# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def american_to_prob(odds: float) -> float:
    """American odds -> implied probability, vig included."""
    return (-odds) / ((-odds) + 100) if odds < 0 else 100 / (odds + 100)


def prob_to_american(p: float) -> float:
    if not 0 < p < 1:
        raise ValueError(f"probability out of range: {p}")
    return -100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p


def devig(probs: list[float], method: str = "multiplicative") -> list[float]:
    """Strip the vig from a set of implied probabilities.

    multiplicative — divide by the overround. Fast, standard, and biased: it
      removes vig proportionally, which understates the favourite's true
      price on lopsided markets.
    additive — subtract the overround evenly across outcomes. Better on
      lopsided two-way markets, worse on balanced ones.

    Both are reported by compare_devig() because at -110/-110 they agree to a
    rounding error, while on a lopsided moneyline they differ by a full point
    of edge. Picking one silently is how a model manufactures EV out of a
    methodology choice.
    """
    s = sum(probs)
    if s <= 0:
        raise ValueError("no positive probabilities")
    if method == "multiplicative":
        return [p / s for p in probs]
    if method == "additive":
        over = (s - 1.0) / len(probs)
        out = [max(1e-6, p - over) for p in probs]
        t = sum(out)
        return [p / t for p in out]
    raise ValueError(f"unknown devig method: {method}")


def compare_devig(probs: list[float]) -> dict:
    m = devig(probs, "multiplicative")
    a = devig(probs, "additive")
    return {"multiplicative": m, "additive": a,
            "max_abs_diff": max(abs(x - y) for x, y in zip(m, a)),
            "overround": sum(probs) - 1.0}


def ev_at(price: float, true_prob: float) -> float:
    """Expected value per unit staked at American `price` given `true_prob`."""
    payout = (100 / abs(price)) if price < 0 else (price / 100)
    return true_prob * payout - (1 - true_prob)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def fetch_board(markets: str = "spreads,totals,h2h") -> list[dict]:
    if not PROXY:
        raise SystemExit(
            "ODDS_PROXY is not set. Point it at the Cloudflare worker, e.g.\n"
            "  export ODDS_PROXY=https://mlb.andrew-bocchino.workers.dev\n"
            "The worker holds the API key. No key belongs in this repo.")
    q = urllib.parse.urlencode({"regions": REGION, "markets": markets,
                                "oddsFormat": "american"})
    url = f"{PROXY}{ODDS_PATH.format(sport=SPORT)}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-model/2"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            remaining = resp.headers.get("x-requests-remaining")
            body = json.loads(resp.read().decode("utf8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SystemExit(
                f"404 from the worker at:\n  {url}\n\n"
                f"The worker routes odds under '{ODDS_PATH.format(sport=SPORT)}'. "
                f"If yours differs, set ODDS_PATH_TEMPLATE, e.g.\n"
                f"  export ODDS_PATH_TEMPLATE='/v4/sports/{{sport}}/odds'\n"
                f"Open the worker's base URL in a browser — it lists its own "
                f"endpoints.") from e
        if e.code in (401, 403):
            raise SystemExit(
                f"{e.code} from the worker. The API key is missing or rejected "
                f"inside Cloudflare. Check the worker's Settings -> Variables "
                f"and Secrets. The key does NOT go in this repo.") from e
        raise
    if not isinstance(body, list):
        raise SystemExit(
            f"Expected a list of games, got {type(body).__name__}. The worker "
            f"may not pass this sport through. Response head: {str(body)[:300]}")
    if remaining:
        print(f"[nfl_lines] Odds API credits remaining: {remaining}", file=sys.stderr)
    if not body:
        print("[nfl_lines] Worker returned an empty list — no NFL games priced "
              "right now, or the sport key is not passed through.", file=sys.stderr)
    return body


def _last_seen(path: str | None = None) -> dict:
    """Most recent price/point for each book+market+outcome already on disk.

    `path` resolves at CALL time, not import time. Binding SNAP_PATH as a
    default argument captures its value when the module loads, so any code
    that reassigns the global would silently read a different file than
    snapshot() writes to — and dedup would fail open, duplicating every row.
    """
    path = path or SNAP_PATH
    seen = {}
    if not os.path.exists(path):
        return seen
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            seen[(r["game_id"], r["market"], r["book"], r["outcome"])] = (
                r.get("price"), r.get("point"))
    return seen


def snapshot(markets: str = "spreads,totals,h2h", changes_only: bool = True) -> int:
    """Append a timestamped capture of the whole board.

    Run on a schedule from the moment lines post (Tuesday) through kickoff.
    Each row is one book/market/outcome at one instant. The opener is the
    first row for a game+market; the close is the last. This file is what
    makes the early-week hypothesis testable — nflverse cannot answer it
    because it ships closing lines only.

    `changes_only` writes a row only when a book's price or point actually
    moved. Most captures are identical to the one before, so writing every
    row every time inflates the log ~10x for no extra information. The
    first capture of any market is always written, so openers are never
    lost. Set False if you want a literal tick-by-tick archive and are
    prepared for the size.
    """
    board = fetch_board(markets)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(SNAP_PATH), exist_ok=True)
    seen = _last_seen() if changes_only else {}
    n = skipped = 0
    with open(SNAP_PATH, "a") as f:
        for game in board:
            for bk in game.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        key = (game.get("id"), mk.get("key"), bk.get("key"),
                               oc.get("name"))
                        cur = (oc.get("price"), oc.get("point"))
                        if changes_only and seen.get(key) == cur:
                            skipped += 1
                            continue
                        f.write(json.dumps({
                            "captured_at": ts,
                            "game_id": game.get("id"),
                            "commence_time": game.get("commence_time"),
                            "home_team": game.get("home_team"),
                            "away_team": game.get("away_team"),
                            "book": bk.get("key"),
                            "book_update": bk.get("last_update"),
                            "market": mk.get("key"),
                            "outcome": oc.get("name"),
                            "point": oc.get("point"),
                            "price": oc.get("price"),
                        }) + "\n")
                        n += 1
    print(f"[nfl_lines] wrote {n} changed rows ({skipped} unchanged) "
          f"to {SNAP_PATH} at {ts}")
    return n


def quota() -> dict:
    """Credits remaining. The worker exposes this and it costs nothing."""
    if not PROXY:
        raise SystemExit("ODDS_PROXY is not set.")
    req = urllib.request.Request(f"{PROXY}{QUOTA_PATH}",
                                 headers={"User-Agent": "nfl-model/2"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf8"))


def load_snapshots(path: str = SNAP_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Consensus + outlier screen
# ---------------------------------------------------------------------------

def consensus(rows: list[dict], min_books: int = 4) -> dict:
    """No-vig consensus per game/market/outcome, at the latest capture.

    Consensus is the MEDIAN no-vig probability across books, not the mean:
    the median is what makes an outlier an outlier rather than something
    that drags the benchmark toward itself.
    """
    # Dedup to the most recent capture per book PER OUTCOME. Keying on
    # (game, market, book) alone silently drops one side of every two-way
    # market, leaving nothing to devig — the screen then returns empty
    # rather than failing. Caught by selftest().
    latest = {}
    for r in rows:
        k = (r["game_id"], r["market"], r["book"], r["outcome"], r.get("point"))
        if k not in latest or r["captured_at"] > latest[k]["captured_at"]:
            latest[k] = r

    per_book = {}
    for r in latest.values():
        per_book.setdefault((r["game_id"], r["market"], r["book"]), []).append(r)

    fair = {}
    for (gid, mkt, book), outs in per_book.items():
        if len(outs) != 2:
            continue
        try:
            nv = devig([american_to_prob(o["price"]) for o in outs])
        except (ValueError, TypeError):
            continue
        for o, p in zip(outs, nv):
            fair.setdefault((gid, mkt, o["outcome"]), []).append(
                {"book": book, "fair": p, "price": o["price"], "point": o["point"]})

    out = {}
    for k, entries in fair.items():
        if len(entries) < min_books:
            continue
        out[k] = {"consensus": statistics.median(e["fair"] for e in entries),
                  "n_books": len(entries), "entries": entries}
    return out


def screen(rows: list[dict], min_ev: float = 0.02, min_books: int = 4) -> list[dict]:
    """Top-down: find books priced away from the consensus.

    No projection is involved. The claim is only that one book disagrees
    with every other book, which is falsifiable on a short horizon.
    """
    cons = consensus(rows, min_books=min_books)
    hits = []
    for (gid, mkt, outcome), c in cons.items():
        for e in c["entries"]:
            ev = ev_at(e["price"], c["consensus"])
            if ev >= min_ev:
                hits.append({"game_id": gid, "market": mkt, "outcome": outcome,
                             "book": e["book"], "price": e["price"],
                             "point": e["point"], "consensus_prob": c["consensus"],
                             "fair_price": round(prob_to_american(c["consensus"]), 1),
                             "ev": ev, "n_books": c["n_books"],
                             "flagged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                         time.gmtime())})
    return sorted(hits, key=lambda h: -h["ev"])


def grade_clv(rows: list[dict], hits_log: str = HITS_PATH) -> dict:
    """Score every flagged price against the CLOSING consensus.

    THIS IS THE SCOREBOARD. Not the ATS record — that needs ~17,700 bets to
    resolve a professional-grade edge. CLV converges in hundreds because it
    measures price against price, not against a 13-point-SD game outcome.

    beat_rate is the fraction of flagged prices better than the closing
    consensus. A valueless screen sits at ~50%.
    """
    if not os.path.exists(hits_log):
        return {"error": f"no hits log at {hits_log} — run `screen --log` first"}
    with open(hits_log) as f:
        hits = [json.loads(x) for x in f if x.strip()]
    close = consensus(rows)
    beat = n = 0
    deltas = []
    for h in hits:
        c = close.get((h["game_id"], h["market"], h["outcome"]))
        if not c:
            continue
        n += 1
        taken = american_to_prob(h["price"])
        # beat the close if the price taken implied a LOWER probability than
        # the market ultimately settled on for that same outcome
        d = c["consensus"] - taken
        deltas.append(d)
        beat += d > 0
    if not n:
        return {"error": "no flagged prices matched a closing consensus"}
    rate = beat / n
    se = (0.25 / n) ** 0.5
    return {"graded": n, "beat_close": beat, "beat_rate": rate,
            "mean_clv_prob_pts": round(statistics.mean(deltas) * 100, 3),
            "z_vs_50pct": round((rate - 0.5) / se, 2) if se else 0.0,
            "graduation_bar": "n>=800 AND 95% CI on beat_rate excludes 50%",
            "verdict": ("NO demonstrated CLV — a valueless screen sits at ~50%"
                        if abs(rate - 0.5) < 2 * se else
                        "beats the close" if rate > 0.5 else
                        "LOSES to the close — the screen is picking off stale "
                        "prices in the wrong direction")}


# ---------------------------------------------------------------------------
# Offline self-test — verifies the math without spending a credit
# ---------------------------------------------------------------------------

def selftest() -> int:
    fails = []

    def check(label, cond):
        if not cond:
            fails.append(label)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("odds conversion:")
    check("-110 -> 52.38%", abs(american_to_prob(-110) - 0.5238) < 1e-3)
    check("+150 -> 40.00%", abs(american_to_prob(150) - 0.40) < 1e-6)
    check("round-trip -110", abs(prob_to_american(american_to_prob(-110)) + 110) < 1e-6)

    print("devig:")
    std = [american_to_prob(-110), american_to_prob(-110)]
    check("-110/-110 devigs to 50/50", abs(devig(std)[0] - 0.5) < 1e-9)
    check("overround at -110/-110 is 4.76%", abs(sum(std) - 1 - 0.0476) < 1e-3)
    cmp_ = compare_devig([american_to_prob(-400), american_to_prob(320)])
    check("methods diverge on lopsided market", cmp_["max_abs_diff"] > 0.005)
    print(f"        -400/+320: mult {cmp_['multiplicative'][0]:.4f} vs "
          f"add {cmp_['additive'][0]:.4f} (diff {cmp_['max_abs_diff']:.4f}, "
          f"overround {cmp_['overround']:.2%})")

    print("EV:")
    check("fair price has zero EV", abs(ev_at(-110, american_to_prob(-110))) < 1e-9)
    check("+120 on a true 50% is +EV", ev_at(120, 0.5) > 0)
    check("-140 on a true 50% is -EV", ev_at(-140, 0.5) < 0)

    print("screen on synthetic board (one book off market):")
    synth = []
    for bk in ["a", "b", "c", "d", "outlier"]:
        home = -110 if bk != "outlier" else 105
        away = -110 if bk != "outlier" else -125
        for name, price in (("Home", home), ("Away", away)):
            synth.append({"captured_at": "2026-01-01T00:00:00Z", "game_id": "g1",
                          "commence_time": "", "home_team": "Home",
                          "away_team": "Away", "book": bk, "book_update": "",
                          "market": "spreads", "outcome": name, "point": -3.0,
                          "price": price})
    hits = screen(synth, min_ev=0.01)
    check("outlier book flagged", any(h["book"] == "outlier" for h in hits))
    check("no non-outlier flagged", all(h["book"] == "outlier" for h in hits))
    for h in hits:
        print(f"        {h['book']} {h['outcome']} {h['price']:+.0f} vs fair "
              f"{h['fair_price']:+.0f}  EV {h['ev']:+.2%} ({h['n_books']} books)")

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        return 1
    print("all checks passed — no API credits spent")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["selftest", "quota", "snapshot", "screen",
                                    "grade-clv"])
    ap.add_argument("--min-ev", type=float, default=0.02)
    ap.add_argument("--min-books", type=int, default=4)
    ap.add_argument("--log", action="store_true",
                    help="append screen hits to data/nfl_screen_hits.jsonl for CLV")
    args = ap.parse_args()

    if args.cmd == "selftest":
        sys.exit(selftest())
    if args.cmd == "quota":
        print(json.dumps(quota(), indent=2))
        return
    if args.cmd == "snapshot":
        snapshot()
        return
    rows = load_snapshots()
    if not rows:
        raise SystemExit(f"no snapshots at {SNAP_PATH} — run `snapshot` first")
    if args.cmd == "screen":
        hits = screen(rows, min_ev=args.min_ev, min_books=args.min_books)
        if not hits:
            print("No books priced beyond the threshold. That is a normal result "
                  "and is not a reason to lower the threshold.")
            return
        for h in hits:
            print(f"{h['market']:8s} {h['outcome']:24s} {h['book']:14s} "
                  f"{h['price']:+5.0f} vs fair {h['fair_price']:+6.1f}  "
                  f"EV {h['ev']:+.2%}  ({h['n_books']} books)")
        print("\nPAPER ONLY. These are logged for CLV grading, not authorized bets.")
        if args.log:
            os.makedirs("data", exist_ok=True)
            with open(HITS_PATH, "a") as f:
                for h in hits:
                    f.write(json.dumps(h) + "\n")
            print(f"logged {len(hits)} hits for CLV grading")
        return
    if args.cmd == "grade-clv":
        print(json.dumps(grade_clv(rows), indent=2))


if __name__ == "__main__":
    main()
