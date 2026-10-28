#!/usr/bin/env python3
"""Viral memecoin alerts.

Watches free sources (DexScreener, GeckoTerminal, CoinGecko, Google Trends,
Google News, Reddit, your own Discord channels, any RSS feed), scores what is
heating up, and pushes alerts to your phone.

Run once:        python3 viral_alerts.py
Keep running:    python3 viral_alerts.py --loop --every 10
Preview only:    python3 viral_alerts.py --dry-run
Test your phone: python3 viral_alerts.py --test-notify

Standard library only. Settings come from config.json and/or environment
variables (see README.md). Alerts are signals, not financial advice.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "viral-alerts/1.0 (personal alert bot)"

DEFAULTS = {
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "discord_webhook_url": "",
    "discord_bot_token": "",
    "discord_channel_ids": [],
    "subreddits": ["memecoins", "CryptoMoonShots", "SatoshiStreetBets", "solana"],
    "rss_feeds": [],
    "news_query": 'memecoin OR "meme coin"',
    "trends_geo": "US",
    "trends_min_traffic": 100000,
    "min_liquidity_usd": 20000,
    "alert_score": 5,
    "unicorn_score": 8,
    "buzz_min_mentions": 3,
    "realert_hours": 6,
    "max_alerts_per_run": 8,
    "state_file": os.path.join(HERE, "state.json"),
}

# GeckoTerminal network id -> DexScreener chain id
GT_TO_DEX_CHAIN = {
    "solana": "solana",
    "eth": "ethereum",
    "base": "base",
    "bsc": "bsc",
    "arbitrum": "arbitrum",
    "polygon_pos": "polygon",
    "avax": "avalanche",
    "ton": "ton",
    "sui-network": "sui",
}

# Tickers that are too big or too generic to signal a new viral coin.
IGNORE_TICKERS = {
    "USD", "USDT", "USDC", "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE",
    "TRX", "TON", "AVAX", "LINK", "DOT", "MATIC", "LTC", "SPY", "QQQ",
}

TICKER_RE = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9]{1,9})\b")


def log(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- config

def load_config(path=None, env=None):
    """DEFAULTS, then config.json, then environment variables (UPPER_CASE keys)."""
    env = os.environ if env is None else env
    cfg = dict(DEFAULTS)
    path = path or os.path.join(HERE, "config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    for key, default in DEFAULTS.items():
        raw = env.get(key.upper())
        if raw is None or raw == "":
            continue
        if isinstance(default, list):
            cfg[key] = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(default, int):
            cfg[key] = int(raw)
        else:
            cfg[key] = raw
    return cfg


# ---------------------------------------------------------------- http

class Http:
    """Tiny HTTP client. Pass `fetch` to replace the network in tests."""

    def __init__(self, fetch=None, timeout=20):
        self.fetch = fetch or self._urlopen
        self.timeout = timeout

    def _urlopen(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def get(self, url, headers=None):
        return self.fetch(url, None, {"User-Agent": USER_AGENT, **(headers or {})})

    def get_json(self, url, headers=None):
        return json.loads(self.get(url, {"Accept": "application/json", **(headers or {})}))

    def post_json(self, url, payload, headers=None):
        body = json.dumps(payload).encode("utf-8")
        hdrs = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
        return self.fetch(url, body, hdrs)


# ---------------------------------------------------------------- data

@dataclass
class Post:
    source: str
    title: str
    url: str
    text: str = ""
    engagement: int = 0


@dataclass
class Token:
    chain: str
    address: str
    symbol: str = ""
    name: str = ""
    url: str = ""
    liquidity: float = 0.0
    market_cap: float = 0.0
    volume_h1: float = 0.0
    volume_h24: float = 0.0
    change_h1: float = 0.0
    buys_h1: int = 0
    sells_h1: int = 0
    created_ms: int = 0
    tags: set = field(default_factory=set)


@dataclass
class Alert:
    key: str
    emoji: str
    ntfy_tag: str
    title: str
    message: str
    url: str
    priority: int
    score: int


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- sources: tokens

def token_key(chain, address):
    """EVM addresses are case-insensitive; Solana's are not."""
    return chain, address.lower() if address.startswith("0x") else address


def fetch_dex_candidates(http, tokens):
    """Tokens people are paying to promote, plus newly listed token profiles."""
    for url, tag in (
        ("https://api.dexscreener.com/token-boosts/top/v1", "paid_boost"),
        ("https://api.dexscreener.com/token-profiles/latest/v1", "new_profile"),
    ):
        for item in http.get_json(url) or []:
            chain, address = item.get("chainId"), item.get("tokenAddress")
            if chain and address:
                key = token_key(chain, address)
                tok = tokens.setdefault(key, Token(chain=chain, address=key[1]))
                tok.tags.add(tag)


def fetch_gt_trending(http, tokens):
    """GeckoTerminal trending pools across all networks."""
    data = http.get_json("https://api.geckoterminal.com/api/v2/networks/trending_pools")
    for pool in data.get("data", []):
        token_id = (((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
        if "_" not in token_id:
            continue
        network, address = token_id.rsplit("_", 1)
        chain = GT_TO_DEX_CHAIN.get(network)
        if chain:
            key = token_key(chain, address)
            tok = tokens.setdefault(key, Token(chain=chain, address=key[1]))
            tok.tags.add("gt_trending")


def fetch_cg_trending(http):
    """Lowercased symbols and names on CoinGecko's trending list."""
    data = http.get_json("https://api.coingecko.com/api/v3/search/trending")
    names = set()
    for entry in data.get("coins", []):
        item = entry.get("item", {})
        for value in (item.get("symbol"), item.get("name")):
            if value:
                names.add(value.lower())
    return names


def enrich_with_dexscreener(http, tokens):
    """Fill in price, volume and trade stats from each token's most liquid pair."""
    by_chain = {}
    for (chain, address) in tokens:
        by_chain.setdefault(chain, []).append(address)
    for chain, addresses in by_chain.items():
        for i in range(0, len(addresses), 30):
            chunk = addresses[i:i + 30]
            url = f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(chunk)}"
            try:
                pairs = http.get_json(url) or []
            except Exception as exc:  # one bad chain shouldn't stop the run
                log(f"dexscreener {chain}: failed ({exc})")
                continue
            best = {}
            for pair in pairs:
                base = pair.get("baseToken") or {}
                addr = base.get("address", "")
                liq = _num((pair.get("liquidity") or {}).get("usd"))
                key = addr.lower()
                if key and (key not in best or liq > best[key][0]):
                    best[key] = (liq, pair)
            for address in chunk:
                found = best.get(address.lower())
                if not found:
                    continue
                liq, pair = found
                base = pair.get("baseToken") or {}
                tok = tokens[(chain, address)]
                h1 = (pair.get("txns") or {}).get("h1") or {}
                tok.symbol = base.get("symbol", "") or tok.symbol
                tok.name = base.get("name", "") or tok.name
                tok.url = pair.get("url", "") or tok.url
                tok.liquidity = liq
                tok.market_cap = _num(pair.get("marketCap") or pair.get("fdv"))
                tok.volume_h1 = _num((pair.get("volume") or {}).get("h1"))
                tok.volume_h24 = _num((pair.get("volume") or {}).get("h24"))
                tok.change_h1 = _num((pair.get("priceChange") or {}).get("h1"))
                tok.buys_h1 = int(_num(h1.get("buys")))
                tok.sells_h1 = int(_num(h1.get("sells")))
                tok.created_ms = int(_num(pair.get("pairCreatedAt")))


def rugcheck_dangers(http, mint):
    """Names of RugCheck 'danger' risks for a Solana token (empty list = none found)."""
    data = http.get_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary")
    return [r.get("name", "risk") for r in data.get("risks", []) if r.get("level") == "danger"]


# ---------------------------------------------------------------- sources: posts and trends

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(elem, name):
    for child in elem:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def parse_feed(xml_bytes, source):
    """Parse RSS or Atom into Posts (namespace-agnostic)."""
    root = ET.fromstring(xml_bytes)
    posts = []
    for elem in root.iter():
        kind = _local(elem.tag)
        if kind not in ("item", "entry"):
            continue
        title = _child_text(elem, "title")
        link = _child_text(elem, "link")
        if not link:  # Atom puts the URL in an attribute
            for child in elem:
                if _local(child.tag) == "link" and child.get("href"):
                    link = child.get("href")
                    break
        text = _child_text(elem, "description") or _child_text(elem, "summary") or _child_text(elem, "content")
        if title:
            posts.append(Post(source=source, title=title, url=link, text=text[:1000]))
    return posts


def fetch_news(http, query):
    params = urllib.parse.urlencode({"q": f"{query} when:1h", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    return parse_feed(http.get(f"https://news.google.com/rss/search?{params}"), "news")


def fetch_rss(http, feeds):
    posts = []
    for feed in feeds:
        try:
            posts.extend(parse_feed(http.get(feed), "rss"))
        except Exception as exc:
            log(f"rss {feed}: failed ({exc})")
    return posts


def fetch_reddit(http, subreddits):
    posts = []
    for sub in subreddits:
        try:
            data = http.get_json(f"https://www.reddit.com/r/{sub}/new.json?limit=50")
        except Exception as exc:
            log(f"reddit r/{sub}: failed ({exc})")
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append(Post(
                source="reddit",
                title=d.get("title", ""),
                url="https://www.reddit.com" + d.get("permalink", ""),
                text=(d.get("selftext") or "")[:1000],
                engagement=int(_num(d.get("score"))) + int(_num(d.get("num_comments"))),
            ))
    return posts


def fetch_discord(http, bot_token, channel_ids):
    """Recent messages from channels in a server you own (your bot must be in it)."""
    headers = {"Authorization": f"Bot {bot_token}"}
    posts = []
    for channel_id in channel_ids:
        try:
            channel = http.get_json(f"https://discord.com/api/v10/channels/{channel_id}", headers)
            messages = http.get_json(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=50", headers)
        except Exception as exc:
            log(f"discord {channel_id}: failed ({exc})")
            continue
        if not isinstance(messages, list):
            log(f"discord {channel_id}: unexpected response {str(messages)[:100]}")
            continue
        guild_id = channel.get("guild_id", "@me")
        for msg in messages:
            parts = [msg.get("content", "")]
            for embed in msg.get("embeds", []):
                parts += [embed.get("title", ""), embed.get("description", "")]
            text = "\n".join(p for p in parts if p)
            if text:
                posts.append(Post(
                    source="discord",
                    title=text.splitlines()[0][:150],
                    url=f"https://discord.com/channels/{guild_id}/{channel_id}/{msg.get('id', '')}",
                    text=text[:1000],
                ))
    return posts


def parse_traffic(label):
    """'200K+' -> 200000, '1M+' -> 1000000, '2,000+' -> 2000."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", label or "")
    if not m:
        return 0
    value = float(m.group(1).replace(",", ""))
    return int(value * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


def fetch_trends(http, geo):
    """Google Trends 'trending now' searches: list of (term, traffic)."""
    root = ET.fromstring(http.get(f"https://trends.google.com/trending/rss?geo={geo}"))
    trends = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        term = _child_text(item, "title")
        if term:
            trends.append((term, parse_traffic(_child_text(item, "approx_traffic"))))
    return trends


# ---------------------------------------------------------------- analysis

def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def count_buzz(posts):
    """$TICKER -> {'count', 'sources', 'posts'} across all posts."""
    buzz = {}
    for post in posts:
        seen = set()
        for ticker in TICKER_RE.findall(f"{post.title}\n{post.text}"):
            ticker = ticker.upper()
            if ticker in IGNORE_TICKERS or ticker in seen:
                continue
            seen.add(ticker)
            entry = buzz.setdefault(ticker, {"count": 0, "sources": set(), "posts": []})
            entry["count"] += 1
            entry["sources"].add(post.source)
            entry["posts"].append(post)
    return buzz


def match_trend(token, trends):
    """Return the trending term this token is named after, if any."""
    name, symbol = norm(token.name), norm(token.symbol)
    for term, _traffic in trends:
        t = norm(term)
        if len(t) < 3:
            continue
        if t in (name, symbol) or (len(t) >= 5 and t in name):
            return term
    return None


def score_token(token, cfg, buzz, cg_names, trends):
    """Return (score, reasons), or None if the token is too illiquid to bother with."""
    if token.liquidity < cfg["min_liquidity_usd"]:
        return None
    score, reasons = 0, []

    avg_hourly = token.volume_h24 / 24 if token.volume_h24 else 0
    accel = token.volume_h1 / avg_hourly if avg_hourly else 0
    if accel >= 6:
        score += 3
        reasons.append(f"volume is {accel:.0f}x its normal hourly pace")
    elif accel >= 3:
        score += 2
        reasons.append(f"volume is {accel:.0f}x its normal hourly pace")

    if token.change_h1 >= 50:
        score += 2
        reasons.append(f"up {token.change_h1:.0f}% in the last hour")
    elif token.change_h1 >= 20:
        score += 1
        reasons.append(f"up {token.change_h1:.0f}% in the last hour")
    elif token.change_h1 <= -30:
        score -= 2
        reasons.append(f"down {abs(token.change_h1):.0f}% in the last hour (dumping)")

    if token.buys_h1 >= 50 and token.buys_h1 >= 1.5 * max(token.sells_h1, 1):
        score += 1
        reasons.append(f"buyers outnumber sellers {token.buys_h1 / max(token.sells_h1, 1):.1f} to 1")
    if token.buys_h1 + token.sells_h1 >= 500:
        score += 1
        reasons.append(f"{token.buys_h1 + token.sells_h1} trades in the last hour")

    if "gt_trending" in token.tags:
        score += 1
        reasons.append("trending on GeckoTerminal")
    if cg_names and ({token.symbol.lower(), token.name.lower()} & cg_names):
        score += 2
        reasons.append("trending on CoinGecko")

    mentions = buzz.get(token.symbol.upper())
    if mentions:
        score += min(len(mentions["sources"]) + (1 if mentions["count"] >= 5 else 0), 3)
        reasons.append(f"${token.symbol.upper()} mentioned {mentions['count']}x on {', '.join(sorted(mentions['sources']))}")

    trend = match_trend(token, trends)
    if trend:
        score += 2
        reasons.append(f"named after a Google trend: '{trend}'")

    if token.created_ms:
        age_h = (time.time() * 1000 - token.created_ms) / 3_600_000
        if 0 <= age_h < 24:
            reasons.append(f"launched {age_h:.0f}h ago (very new = very risky)")
    if "paid_boost" in token.tags:
        reasons.append("has a paid DexScreener boost (that's an ad, not organic hype)")
    return score, reasons


def _money(value):
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def build_alerts(cfg, tokens, posts, cg_names, trends, http=None):
    alerts = []
    buzz = count_buzz(posts)
    matched_tickers = set()

    for token in tokens.values():
        if not token.symbol:
            continue
        result = score_token(token, cfg, buzz, cg_names, trends)
        if result is None:
            continue
        score, reasons = result
        if score < cfg["alert_score"]:
            continue
        if http and token.chain == "solana":
            try:
                dangers = rugcheck_dangers(http, token.address)
                if dangers:
                    score -= 2
                    reasons.append("RugCheck danger: " + ", ".join(dangers[:3]))
                else:
                    reasons.append("RugCheck: no danger-level risks found")
            except Exception:
                reasons.append("RugCheck safety check unavailable, check it yourself")
            if score < cfg["alert_score"]:
                continue
        matched_tickers.add(token.symbol.upper())
        unicorn = score >= cfg["unicorn_score"]
        header = f"{token.name} on {token.chain}, mcap {_money(token.market_cap)}, liquidity {_money(token.liquidity)}"
        alerts.append(Alert(
            key=f"token:{token.chain}:{token.address}",
            emoji="🦄" if unicorn else "🔥",
            ntfy_tag="unicorn" if unicorn else "fire",
            title=f"{'Unicorn candidate' if unicorn else 'Heating up'}: ${token.symbol.upper()} (score {score})",
            message=header + "\n- " + "\n- ".join(reasons) + "\nNot financial advice. Check the chart and RugCheck before buying.",
            url=token.url,
            priority=5 if unicorn else 4,
            score=score,
        ))

    for ticker, entry in buzz.items():
        if ticker in matched_tickers or entry["count"] < cfg["buzz_min_mentions"]:
            continue
        top = sorted(entry["posts"], key=lambda p: p.engagement, reverse=True)[:3]
        alerts.append(Alert(
            key=f"buzz:{ticker}",
            emoji="📣",
            ntfy_tag="loudspeaker",
            title=f"Buzz: ${ticker} mentioned {entry['count']}x",
            message=f"Seen on {', '.join(sorted(entry['sources']))}:\n- " + "\n- ".join(p.title[:120] for p in top),
            url=top[0].url,
            priority=4 if len(entry["sources"]) >= 2 else 3,
            score=entry["count"],
        ))

    for term, traffic in trends:
        if traffic < cfg["trends_min_traffic"]:
            continue
        alerts.append(Alert(
            key=f"trend:{norm(term)}",
            emoji="📈",
            ntfy_tag="chart_with_upwards_trend",
            title=f"Viral now: {term} ({traffic:,}+ searches)",
            message="Huge search spike right now. Memecoins often launch around viral moments, "
                    f"so watch DexScreener for coins named after '{term}'.",
            url="https://www.google.com/search?q=" + urllib.parse.quote(term),
            priority=3,
            score=traffic // 100000,
        ))
    return alerts


# ---------------------------------------------------------------- state and notify

def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"alerted": {}}


def save_state(path, state, now):
    cutoff = now - 3 * 24 * 3600
    state["alerted"] = {k: v for k, v in state["alerted"].items() if v["ts"] >= cutoff}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def filter_new(alerts, state, cfg, now):
    """Drop alerts sent recently, unless the score jumped by 2+."""
    fresh = []
    for alert in alerts:
        prev = state["alerted"].get(alert.key)
        window = 24 * 3600 if alert.key.startswith("trend:") else cfg["realert_hours"] * 3600
        if prev and now - prev["ts"] < window and alert.score < prev["score"] + 2:
            continue
        fresh.append(alert)
    return fresh


def notify(http, cfg, alert):
    sent = False
    if cfg["ntfy_topic"]:
        http.post_json(cfg["ntfy_server"].rstrip("/") + "/", {
            "topic": cfg["ntfy_topic"],
            "title": alert.title,
            "message": alert.message,
            "priority": alert.priority,
            "tags": [alert.ntfy_tag],
            "click": alert.url,
        })
        sent = True
    if cfg["discord_webhook_url"]:
        http.post_json(cfg["discord_webhook_url"], {
            "content": f"{alert.emoji} **{alert.title}**\n{alert.message}\n{alert.url}"[:2000],
        })
        sent = True
    return sent


def print_alert(alert):
    print(f"\n{alert.emoji} {alert.title}\n{alert.message}\n{alert.url}")


# ---------------------------------------------------------------- run

def run_once(cfg, http, dry_run=False, now=None):
    now = now or time.time()
    tokens = {}
    posts = []
    cg_names = set()
    trends = []

    def attempt(label, fn):
        try:
            return fn()
        except Exception as exc:
            log(f"{label}: failed ({exc})")
            return None

    attempt("dexscreener boosts/profiles", lambda: fetch_dex_candidates(http, tokens))
    attempt("geckoterminal trending", lambda: fetch_gt_trending(http, tokens))
    cg_names = attempt("coingecko trending", lambda: fetch_cg_trending(http)) or set()
    trends = attempt("google trends", lambda: fetch_trends(http, cfg["trends_geo"])) or []
    posts += attempt("google news", lambda: fetch_news(http, cfg["news_query"])) or []
    posts += fetch_reddit(http, cfg["subreddits"])
    posts += fetch_rss(http, cfg["rss_feeds"])
    if cfg["discord_bot_token"] and cfg["discord_channel_ids"]:
        posts += fetch_discord(http, cfg["discord_bot_token"], cfg["discord_channel_ids"])
    if tokens:
        enrich_with_dexscreener(http, tokens)
    log(f"checked {len(tokens)} tokens, {len(posts)} posts, {len(trends)} trends")
    if not (tokens or posts or trends):
        log("every source failed. Check your internet connection.")

    state = load_state(cfg["state_file"])
    alerts = filter_new(build_alerts(cfg, tokens, posts, cg_names, trends, http), state, cfg, now)
    alerts.sort(key=lambda a: (a.priority, a.score), reverse=True)
    if len(alerts) > cfg["max_alerts_per_run"]:
        log(f"skipping {len(alerts) - cfg['max_alerts_per_run']} lower-priority alerts (max_alerts_per_run)")
        alerts = alerts[:cfg["max_alerts_per_run"]]

    has_notifier = bool(cfg["ntfy_topic"] or cfg["discord_webhook_url"])
    if not dry_run and not has_notifier:
        log("no ntfy_topic or discord_webhook_url set, printing alerts instead")
    for alert in alerts:
        if dry_run or not has_notifier:
            print_alert(alert)
        else:
            try:
                notify(http, cfg, alert)
            except Exception as exc:
                log(f"notify failed for {alert.key}: {exc}")
                continue
        if not dry_run:
            state["alerted"][alert.key] = {"ts": now, "score": alert.score}
    if not dry_run:
        save_state(cfg["state_file"], state, now)
    log(f"{len(alerts)} alert(s) {'previewed' if dry_run else 'sent'}")
    return alerts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Viral memecoin alerts")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="print alerts instead of sending them")
    parser.add_argument("--loop", action="store_true", help="keep running")
    parser.add_argument("--every", type=int, default=10, help="minutes between checks with --loop")
    parser.add_argument("--test-notify", action="store_true", help="send one test alert and exit")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    http = Http()
    if args.test_notify:
        test = Alert("test", "✅", "white_check_mark", "Viral alerts are connected",
                     "You'll get alerts like this when something starts heating up.",
                     "https://dexscreener.com", 3, 0)
        if notify(http, cfg, test):
            print("Test alert sent. Check your phone.")
            return 0
        print("Set ntfy_topic or discord_webhook_url first (see README.md).")
        return 1

    while True:
        run_once(cfg, http, dry_run=args.dry_run)
        if not args.loop:
            return 0
        time.sleep(args.every * 60)


if __name__ == "__main__":
    sys.exit(main())
