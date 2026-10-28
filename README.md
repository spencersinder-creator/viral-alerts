# Viral Alerts

Watches free sources for memecoins and news that are starting to go viral, scores them, and pushes the best ones to your phone.

**Alerts are signals, not financial advice.** By the time anything trends, someone was earlier. Always check the chart and [RugCheck](https://rugcheck.xyz) before buying, and only use money you can lose.

## What you get

| Alert | When it fires |
|---|---|
| 🦄 **Unicorn candidate** | A coin scores 8+ (lots of signals at once). Highest priority. |
| 🔥 **Heating up** | A coin scores 5+ |
| 📣 **Buzz** | The same `$TICKER` is posted 3+ times across Reddit, news, Discord or your RSS feeds |
| 📈 **Viral now** | Something has 100K+ Google searches right now. New coins often launch around these. |

A coin earns points for:
- volume jumping way above its normal pace
- price up big in the last hour
- buyers outnumbering sellers
- lots of trades
- being on the GeckoTerminal or CoinGecko trending lists
- `$TICKER` mentions across sources
- being named after a Google trend

It **loses** points for dumping or for RugCheck "danger" flags, such as the creator still being able to freeze wallets. Coins with less than $20K liquidity are ignored.

## Where it looks (all free)

- **DexScreener:** promoted (boosted) tokens, new token profiles, and live price, volume and trade data
- **GeckoTerminal** and **CoinGecko:** trending lists
- **RugCheck:** safety check for Solana coins
- **Google Trends:** what the US is searching right now
- **Google News:** memecoin headlines from the last hour
- **Reddit:** r/memecoins, r/CryptoMoonShots, r/SatoshiStreetBets, r/solana
- **Your Discord:** channels in a server you own (see below)
- **Any RSS feed** you add

### What it can't do for free
- **X/Twitter:** X no longer gives free read access. Workarounds:
  - Make an RSS feed of the accounts you care about with a service like rss.app and add it to `rss_feeds`.
  - Or pay for the X API.
- **Other people's Discord servers:** bots can only read servers they're invited to. Workaround:
  - Many crypto servers have announcement channels with a **Follow** button. Follow them into your own server, and the bot reads them there.
- **Predicting the future:** it finds things *as they heat up*, not before.

## Setup

### 1. Phone notifications (2 minutes)
1. Install the free **ntfy** app (iPhone or Android).
2. Tap **+**. Subscribe to a topic name that's hard to guess, like `my-alerts-8k2p9x`. Anyone who knows the name can see your alerts.
3. Use that same name as `ntfy_topic` below.

You can also get alerts in Discord: set `discord_webhook_url` to a webhook from one of your channels (Channel settings → Integrations → Webhooks).

### 2a. Run it on your laptop
Needs Python 3 (`python3 --version`).

```bash
cd viral-alerts
cp config.example.json config.json   # then put your ntfy topic in config.json
python3 viral_alerts.py --test-notify  # phone should buzz
python3 viral_alerts.py --dry-run      # preview alerts without sending
python3 viral_alerts.py --loop --every 10   # check every 10 minutes
```
It only runs while your laptop is on and awake.

### 2b. Or run it 24/7 for free on GitHub
This repo is public, so GitHub Actions minutes are free and unlimited. The workflow in `.github/workflows/viral-alerts.yml` checks **every 5 minutes**. GitHub runs schedules on a best-effort basis, so busy times can stretch that to 10–15 minutes.
1. In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**. Add `NTFY_TOPIC` with your topic name. Secrets stay hidden, even in a public repo.
2. Optional secrets: `DISCORD_WEBHOOK_URL`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_IDS`, `RSS_FEEDS`.
3. In the **Actions** tab, open **Viral alerts → Run workflow** to test it.

Reddit often blocks GitHub's servers, so Reddit may only work on your laptop. GitHub also pauses scheduled workflows in public repos after 60 days without commits. If that happens, it emails you; click **Enable workflow** to restart it.

### 3. Discord (optional)
1. Make your own Discord server. In crypto servers you're in, find announcement channels and click **Follow** to send them into your server.
2. Go to <https://discord.com/developers/applications>, then **New Application → Bot**. Turn on **Message Content Intent** and copy the bot token.
3. Under **OAuth2 → URL Generator**, tick `bot` and the **Read Message History** permission. Open the link and add the bot to *your* server.
4. Turn on Developer Mode in Discord (Settings → Advanced). Right-click each channel and choose **Copy Channel ID**.
5. Set `discord_bot_token` and `discord_channel_ids`.

Never share the bot token. If it leaks, reset it in the developer portal.

## Settings

Put these in `config.json`, or set them as environment variables in UPPER_CASE (lists are comma-separated).

| Setting | Default | What it does |
|---|---|---|
| `ntfy_topic` | — | Your ntfy topic for phone alerts |
| `discord_webhook_url` | — | Also send alerts to a Discord channel |
| `discord_bot_token`, `discord_channel_ids` | — | Read your own Discord channels |
| `rss_feeds` | `[]` | Extra RSS/Atom feeds to watch (X accounts via rss.app, blogs, etc.) |
| `subreddits` | 4 crypto subs | Subreddits to watch |
| `min_liquidity_usd` | `20000` | Ignore coins with less liquidity than this |
| `alert_score` / `unicorn_score` | `5` / `8` | Points needed for an alert / a unicorn alert |
| `buzz_min_mentions` | `3` | Mentions needed for a buzz alert |
| `trends_min_traffic` | `100000` | Google searches needed for a viral-now alert |
| `realert_hours` | `6` | Don't repeat a coin alert unless its score jumps by 2+ |
| `max_alerts_per_run` | `8` | Cap per check so your phone doesn't explode |

## Safety
- **This repo is public.** Put your ntfy topic and any tokens in GitHub secrets or your local `config.json`, never in committed files.
- **Never put a wallet seed phrase or private key anywhere in this project.** It doesn't need one. It only reads public data.
- `config.json` and `state.json` are git-ignored, so your tokens don't get committed.

## Tests
```bash
python3 -m unittest discover -s tests
```
