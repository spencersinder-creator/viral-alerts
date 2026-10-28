import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import viral_alerts as va  # noqa: E402

NOW = 1_800_000_000
SOL_MINT = "FrogCoin1111111111111111111111111111111111pump"
EVM_ADDR = "0xAbC0000000000000000000000000000000000001"

BOOSTS = [{"chainId": "solana", "tokenAddress": SOL_MINT, "amount": 100, "totalAmount": 500}]
PROFILES = [{"chainId": "base", "tokenAddress": EVM_ADDR, "description": "new"}]
GT_TRENDING = {"data": [
    {"id": "solana_PoolAddr1", "type": "pool", "attributes": {"name": "FROG / SOL"},
     "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}", "type": "token"}}}},
    {"id": "base_PoolAddr2", "type": "pool", "attributes": {"name": "ABC / WETH"},
     "relationships": {"base_token": {"data": {"id": f"base_{EVM_ADDR.lower()}", "type": "token"}}}},
    {"id": "unknownnet_x", "type": "pool",
     "relationships": {"base_token": {"data": {"id": "unknownnet_y", "type": "token"}}}},
]}
CG_TRENDING = {"coins": [{"item": {"id": "frog", "name": "Frog Moon", "symbol": "FROG", "score": 0}}],
               "nfts": [], "categories": []}


def pair(addr, symbol, name, liq, vol_h1, vol_h24, chg_h1, buys, sells, url, created_ms):
    return {
        "chainId": "x", "dexId": "raydium", "url": url, "pairAddress": "p" + symbol,
        "baseToken": {"address": addr, "name": name, "symbol": symbol},
        "quoteToken": {"address": "q", "name": "Wrapped SOL", "symbol": "SOL"},
        "priceUsd": "0.001",
        "txns": {"m5": {"buys": 1, "sells": 1}, "h1": {"buys": buys, "sells": sells},
                 "h6": {"buys": 1, "sells": 1}, "h24": {"buys": 1, "sells": 1}},
        "volume": {"m5": 1, "h1": vol_h1, "h6": 1, "h24": vol_h24},
        "priceChange": {"m5": 1, "h1": chg_h1, "h6": 1, "h24": 1},
        "liquidity": {"usd": liq, "base": 1, "quote": 1},
        "fdv": 2_500_000, "marketCap": 2_000_000, "pairCreatedAt": created_ms,
    }


SOL_PAIRS = [
    pair(SOL_MINT, "FROG", "Frog Moon", 150_000, 240_000, 480_000, 65, 900, 300,
         "https://dexscreener.com/solana/pfrog", (NOW - 5 * 3600) * 1000),
    # smaller pool for the same token should be ignored
    pair(SOL_MINT, "FROG", "Frog Moon", 1_000, 1, 1, 0, 0, 0, "https://dexscreener.com/solana/small", 0),
]
BASE_PAIRS = [
    pair("0xabc0000000000000000000000000000000000001", "ABC", "Abc Token", 5_000, 1, 1, 0, 1, 1,
         "https://dexscreener.com/base/pabc", 0),
]
RUGCHECK = {"score": 1, "risks": [{"name": "Low Liquidity", "level": "warn", "score": 100}]}

NEWS_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>news</title>
<item><title>Traders pile into $FROG as frog meme explodes</title><link>https://news.example/1</link>
<description>$FROG and $WIF lead memecoins</description></item>
<item><title>Bitcoin steady</title><link>https://news.example/2</link><description>$BTC flat</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Alpha: $ZORP is next</title><link href="https://atom.example/1"/><summary>$ZORP</summary></entry>
</feed>"""

TRENDS_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>frog moon</title><ht:approx_traffic>500K+</ht:approx_traffic></item>
<item><title>small thing</title><ht:approx_traffic>2,000+</ht:approx_traffic></item>
</channel></rss>"""

REDDIT = {"data": {"children": [
    {"data": {"title": "$ZORP about to send", "permalink": "/r/memecoins/1", "selftext": "", "score": 50, "num_comments": 10}},
    {"data": {"title": "why $ZORP", "permalink": "/r/memecoins/2", "selftext": "$FROG too", "score": 5, "num_comments": 1}},
    {"data": {"title": "price is $5k", "permalink": "/r/memecoins/3", "selftext": "", "score": 1, "num_comments": 0}},
]}}


class FakeNet:
    """Maps URL prefixes to canned responses and records POSTs."""

    def __init__(self, routes):
        self.routes = routes
        self.posts = []

    def __call__(self, url, data=None, headers=None):
        if data is not None:
            self.posts.append((url, json.loads(data), headers))
            return b"{}"
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise OSError(f"no route for {url}")


def routes():
    return {
        "https://api.dexscreener.com/token-boosts/top/v1": BOOSTS,
        "https://api.dexscreener.com/token-profiles/latest/v1": PROFILES,
        "https://api.geckoterminal.com/api/v2/networks/trending_pools": GT_TRENDING,
        "https://api.coingecko.com/api/v3/search/trending": CG_TRENDING,
        "https://api.dexscreener.com/tokens/v1/solana/": SOL_PAIRS,
        "https://api.dexscreener.com/tokens/v1/base/": BASE_PAIRS,
        "https://api.rugcheck.xyz/": RUGCHECK,
        "https://trends.google.com/trending/rss": TRENDS_RSS,
        "https://news.google.com/rss/search": NEWS_RSS,
        "https://www.reddit.com/r/memecoins/": REDDIT,
        "https://www.reddit.com/r/": OSError("HTTP Error 403: Blocked"),
        "https://atom.example/feed": ATOM,
    }


def config(tmp, **overrides):
    cfg = va.load_config(os.path.join(tmp, "missing.json"), env={})
    cfg.update(state_file=os.path.join(tmp, "state.json"), subreddits=["memecoins", "blocked"],
               rss_feeds=["https://atom.example/feed"], ntfy_topic="", discord_webhook_url="")
    cfg.update(overrides)
    return cfg


class ParsingTests(unittest.TestCase):
    def test_parse_traffic(self):
        self.assertEqual(va.parse_traffic("200K+"), 200_000)
        self.assertEqual(va.parse_traffic("1M+"), 1_000_000)
        self.assertEqual(va.parse_traffic("2,000+"), 2_000)
        self.assertEqual(va.parse_traffic(""), 0)

    def test_parse_rss_and_atom(self):
        rss = va.parse_feed(NEWS_RSS, "news")
        self.assertEqual([p.url for p in rss], ["https://news.example/1", "https://news.example/2"])
        atom = va.parse_feed(ATOM, "rss")
        self.assertEqual(atom[0].url, "https://atom.example/1")
        self.assertIn("$ZORP", atom[0].text)

    def test_trends(self):
        http = va.Http(FakeNet(routes()))
        self.assertEqual(va.fetch_trends(http, "US"), [("frog moon", 500_000), ("small thing", 2_000)])

    def test_buzz_ignores_majors_prices_and_double_counting(self):
        posts = [va.Post("reddit", "$zorp $ZORP", "u1"), va.Post("news", "$BTC and $5k", "u2"),
                 va.Post("rss", "x", "u3", text="$Zorp")]
        buzz = va.count_buzz(posts)
        self.assertEqual(set(buzz), {"ZORP"})
        self.assertEqual(buzz["ZORP"]["count"], 2)
        self.assertEqual(buzz["ZORP"]["sources"], {"reddit", "rss"})

    def test_candidates_merge_evm_case_and_skip_unknown_networks(self):
        http = va.Http(FakeNet(routes()))
        tokens = {}
        va.fetch_dex_candidates(http, tokens)
        va.fetch_gt_trending(http, tokens)
        self.assertEqual(set(tokens), {("solana", SOL_MINT), ("base", EVM_ADDR.lower())})
        self.assertEqual(tokens[("solana", SOL_MINT)].tags, {"paid_boost", "gt_trending"})
        self.assertEqual(tokens[("base", EVM_ADDR.lower())].tags, {"new_profile", "gt_trending"})

    def test_enrich_picks_most_liquid_pair(self):
        http = va.Http(FakeNet(routes()))
        tokens = {}
        va.fetch_dex_candidates(http, tokens)
        va.enrich_with_dexscreener(http, tokens)
        frog = tokens[("solana", SOL_MINT)]
        self.assertEqual((frog.symbol, frog.liquidity, frog.buys_h1), ("FROG", 150_000, 900))
        self.assertEqual(frog.url, "https://dexscreener.com/solana/pfrog")
        self.assertEqual(tokens[("base", EVM_ADDR.lower())].symbol, "ABC")


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.cfg = va.load_config("/nonexistent.json", env={})

    def token(self, **kw):
        base = dict(chain="solana", address="m", symbol="FROG", name="Frog Moon", liquidity=100_000,
                    volume_h1=0, volume_h24=0, change_h1=0, buys_h1=0, sells_h1=0)
        base.update(kw)
        return va.Token(**base)

    def test_illiquid_tokens_are_skipped(self):
        self.assertIsNone(va.score_token(self.token(liquidity=500), self.cfg, {}, set(), []))

    def test_hot_token_scores_high(self):
        tok = self.token(volume_h1=240_000, volume_h24=480_000, change_h1=65, buys_h1=900, sells_h1=300,
                         tags={"gt_trending"})
        buzz = {"FROG": {"count": 5, "sources": {"reddit", "news"}, "posts": []}}
        score, reasons = va.score_token(tok, self.cfg, buzz, {"frog"}, [("frog moon", 500_000)])
        # 3 volume + 2 price + 1 buyers + 1 trades + 1 GT + 2 CG + 3 mentions + 2 trend
        self.assertEqual(score, 15)
        self.assertTrue(any("Google trend" in r for r in reasons))

    def test_dumping_token_loses_points(self):
        score, reasons = va.score_token(self.token(change_h1=-45), self.cfg, {}, set(), [])
        self.assertEqual(score, -2)
        self.assertIn("dumping", reasons[0])

    def test_trend_match_rules(self):
        self.assertEqual(va.match_trend(self.token(name="Taylor Swift Coin", symbol="TSWIFT"),
                                        [("Taylor Swift", 1)]), "Taylor Swift")
        self.assertIsNone(va.match_trend(self.token(name="Frog", symbol="FRG"), [("fr", 1), ("dog", 1)]))


class RunTests(unittest.TestCase):
    def test_full_run_alerts_then_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = FakeNet(routes())
            cfg = config(tmp, ntfy_topic="my-secret-topic")
            http = va.Http(net)

            alerts = va.run_once(cfg, http, now=NOW)
            keys = [a.key for a in alerts]
            self.assertEqual(keys[0], f"token:solana:{SOL_MINT}")  # unicorn sorts first
            self.assertIn("buzz:ZORP", keys)       # 3 mentions across reddit + rss
            self.assertIn("trend:frogmoon", keys)  # 500K+ searches
            self.assertNotIn("trend:smallthing", keys)
            self.assertNotIn(f"token:base:{EVM_ADDR.lower()}", keys)  # $5K liquidity, skipped
            self.assertNotIn("buzz:FROG", keys)    # already covered by the token alert

            frog = alerts[0]
            self.assertTrue(frog.title.startswith("Unicorn candidate: $FROG"))
            self.assertIn("RugCheck: no danger-level risks found", frog.message)
            self.assertIn("paid DexScreener boost", frog.message)

            sent = [payload for url, payload, _ in net.posts if url == "https://ntfy.sh/"]
            self.assertEqual(len(sent), len(alerts))
            self.assertEqual(sent[0]["topic"], "my-secret-topic")
            self.assertEqual(sent[0]["tags"], ["unicorn"])
            self.assertEqual(sent[0]["click"], "https://dexscreener.com/solana/pfrog")

            # Same data an hour later: nothing new to say.
            self.assertEqual(va.run_once(cfg, http, now=NOW + 3600), [])
            # After the re-alert window, token alerts come back; trends wait 24h.
            later = [a.key for a in va.run_once(cfg, http, now=NOW + 7 * 3600)]
            self.assertIn(f"token:solana:{SOL_MINT}", later)
            self.assertNotIn("trend:frogmoon", later)

    def test_rugcheck_danger_can_drop_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = routes()
            r["https://api.rugcheck.xyz/"] = {"risks": [
                {"name": "Freeze Authority still enabled", "level": "danger"}]}
            alerts = va.run_once(config(tmp, unicorn_score=99), va.Http(FakeNet(r)), dry_run=True, now=NOW)
            frog = [a for a in alerts if a.key.startswith("token:")][0]
            self.assertIn("RugCheck danger: Freeze Authority still enabled", frog.message)
            self.assertEqual(frog.score, 12)

    def test_every_source_down_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            dead = FakeNet({})
            self.assertEqual(va.run_once(config(tmp), va.Http(dead), now=NOW), [])

    def test_dry_run_does_not_send_or_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = FakeNet(routes())
            cfg = config(tmp, ntfy_topic="t")
            self.assertTrue(va.run_once(cfg, va.Http(net), dry_run=True, now=NOW))
            self.assertEqual(net.posts, [])
            self.assertFalse(os.path.exists(cfg["state_file"]))

    def test_discord_webhook_and_discord_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = routes()
            r["https://discord.com/api/v10/channels/42/messages"] = [
                {"id": "1", "content": "$ZORP listing soon", "embeds": []},
                {"id": "2", "content": "", "embeds": [{"title": "Announcement", "description": "$ZORP"}]},
            ]
            r["https://discord.com/api/v10/channels/42"] = {"id": "42", "guild_id": "7"}
            net = FakeNet(r)
            cfg = config(tmp, discord_webhook_url="https://discord.com/api/webhooks/1/abc",
                         discord_bot_token="tok", discord_channel_ids=["42"])
            alerts = va.run_once(cfg, va.Http(net), now=NOW)
            zorp = [a for a in alerts if a.key == "buzz:ZORP"][0]
            self.assertIn("discord", zorp.message)
            hooks = [p for url, p, _ in net.posts if url.startswith("https://discord.com/api/webhooks/")]
            self.assertEqual(len(hooks), len(alerts))
            self.assertLessEqual(max(len(h["content"]) for h in hooks), 2000)


class ConfigTests(unittest.TestCase):
    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as f:
                json.dump({"ntfy_topic": "from-file", "alert_score": 7}, f)
            cfg = va.load_config(path, env={"NTFY_TOPIC": "from-env", "SUBREDDITS": "a, b",
                                            "MIN_LIQUIDITY_USD": "5000"})
            self.assertEqual(cfg["ntfy_topic"], "from-env")
            self.assertEqual(cfg["alert_score"], 7)
            self.assertEqual(cfg["subreddits"], ["a", "b"])
            self.assertEqual(cfg["min_liquidity_usd"], 5000)


if __name__ == "__main__":
    unittest.main()
