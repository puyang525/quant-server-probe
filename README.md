# Quant Trading Server Probe

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

A dependency-free, read-only Linux probe for choosing cloud providers, regions, and instance types for quantitative trading. It tests real public REST/WebSocket paths for brokers, exchanges, prediction markets, and market-data vendors, then combines network quality with a deliberately light host benchmark.

It covers IBKR, Futu OpenAPI/FutuOpenD, Binance Spot and USDⓈ-M perpetuals, OKX SWAP, Bybit, Deribit, Coinbase, Kraken, Hyperliquid, Polymarket, Massive/Polygon, Databento, Twelve Data, and supporting infrastructure.

> **Privacy and community ranking are opt-in and disabled by default.** `probe`, `show`, and `compare` keep data on the server. There is no telemetry or automatic upload. Participation requires a separate `public` command, manual inspection of the sanitized JSON, and an intentional GitHub Pull Request. Never submit a complete probe report. See [Data contribution and privacy](CONTRIBUTING_DATA.md).

## One-line run

Python 3.10+ is the only required runtime:

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

The launcher reads `LC_ALL`, `LC_MESSAGES`, and `LANG`. A recognized language runs immediately. If no supported language can be detected and an interactive terminal is available, it asks for English, Simplified Chinese, or Traditional Chinese. Non-interactive runs print a notice and safely fall back to English.

Override language explicitly:

```bash
QUANT_PROBE_LANG=zh-CN curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

Supported runtime codes are `en`, `zh-CN`, and `zh-TW`. Contributor metadata may be written in any language; ranking uses language-neutral JSON keys and country codes.

Run an extended scan with labels:

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- --suite extended --profile balanced \
  --label "provider-region-plan" --provider "provider" --region "region"
```

Reports are saved under `probe-results/`. If the current directory is not writable, the launcher uses `$HOME/quant-server-probe-results/`, then `/tmp`. Temporary downloads and bounded benchmark files are removed automatically.

## What the result shows

The terminal report includes:

- overall network, host-performance, and selection scores;
- role scores for crypto execution, IBKR, Futu, Polymarket, market-data collection, and research/backtesting;
- CPU, RAM, disk, `fsync`, clock source, NTP, and a 1 MB bandwidth sanity check;
- per endpoint TCP/HTTP/WebSocket median, p95, jitter, success rate, HTTP status, first-message latency, peer address, and diagnostic notes;
- Binance/OKX public perpetual catalog evidence and Polymarket jurisdiction classification.

Use `--terminal-details all`, `key`, or `none`. Re-render an existing JSON without probing again:

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- show /path/to/probe-report.json --details all
```

Compare candidates:

```bash
./quant_net_probe.py compare server-a.json server-b.json server-c.json \
  --output server-comparison.md
```

## Safe, light host benchmark

The default `light` benchmark uses at most two short CPU workers, a 32 MiB memory block, and a 64 MiB temporary disk file. It skips multi-process CPU work when pre-test load is high. Temporary files use automatic cleanup, including on ordinary exceptions.

Measurements include single-worker and per-worker SHA-256 throughput, memory-copy throughput, bounded sequential I/O, cached 4K read sanity, real `fsync` latency, vCPU/RAM capacity, clock source, and NTP state. It is a comparative screen, not a substitute for a long noisy-neighbor, CPU-steal, or production replay test.

Disable host or bandwidth tests with `--no-benchmark` and `--no-bandwidth`.

## IBKR and Futu: measure the real gateway session

The core suite now measures IBKR's officially published TWS primary back-end hosts in six regions: US East, US Central, Europe, Hong Kong, Singapore, and the Mainland China gateway. It tests TCP 4001 for login/order submission, TCP 4000 for market data, the SSL handshake on 4001, and optional ICMP when `ping` is installed. The terminal ranks regions and shows median, p95, jitter, and success rate. `--suite extended` also checks every published backup host.

The Mainland China gateway is documented specifically for accounts assigned to the Hong Kong server while physically connecting from Mainland China. It must not be treated as a general-purpose alternative region.

These official service ports are much more informative than the website CDN, but still do not represent exchange matching or complete SmartRouting latency. After starting a paper/live IB Gateway/TWS or FutuOpenD session:

Run only the official IBKR host matrix when screening a region:

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- --groups ibkr_official --profile ibkr --no-benchmark --no-bandwidth
```

Then test the authenticated gateway session:

```bash
sudo ./quant_net_probe.py probe --profile ibkr --live-sessions
sudo ./quant_net_probe.py discover --pattern 'ibgateway|tws|java'

sudo ./quant_net_probe.py probe --profile futu --live-sessions
sudo ./quant_net_probe.py discover --pattern 'FutuOpenD|OpenD'
```

Futu's API product is **Futu OpenAPI** and its local gateway is **FutuOpenD (OpenD)**. Local API-port latency measures strategy-to-gateway only. Established-session kernel RTT is more useful, but still is not exchange matching latency.

Futu's official FAQ publishes cloud locations rather than fixed backend IPs. The probe therefore uses clearly labeled regional substitutes: Tencent Cloud COS in Guangzhou, Hong Kong, Virginia, Singapore, and Tokyo; Alibaba Cloud OSS in Malaysia; and both AWS Canada regions because Futu names only “AWS Canada.” Select your brokerage profile so the applicable quote and trade anchors affect the Futu pre-screen score:

```bash
./quant_net_probe.py probe --profile futu --futu-account futu-hk
./quant_net_probe.py probe --profile futu --futu-account moomoo-us
./quant_net_probe.py probe --profile futu --futu-account moomoo-sg
./quant_net_probe.py probe --profile futu --futu-account moomoo-au
./quant_net_probe.py probe --profile futu --futu-account moomoo-my
./quant_net_probe.py probe --profile futu --futu-account moomoo-ca
./quant_net_probe.py probe --profile futu --futu-account moomoo-jp
```

Cloud endpoints may use different front doors, peering, load balancers, and private routing from Futu. They are useful for eliminating clearly distant regions, not for claiming actual order latency.

## Binance and OKX derivatives

The probe reads Binance USDⓈ-M `exchangeInfo`, counts live `PERPETUAL` contracts, and connects to a futures WebSocket. It reads OKX `instType=SWAP`, counts live swaps, and subscribes to a swap ticker.

`perpetual_market_reachable` or `swap_market_reachable` proves only that the public product catalog and market-data path are technically reachable from that IP. It does not prove that a particular account, legal entity, KYC jurisdiction, or user is allowed to trade derivatives. The probe never asks for API keys.

## Polymarket geography

The probe calls the official `https://polymarket.com/api/geoblock` endpoint and applies the published three-tier jurisdiction table:

- `fully_blocked`: frontend and API are fully blocked;
- `api_close_only_no_new_orders`: frontend and API may close but may not open positions;
- `frontend_close_only_api_available`: the published table says the frontend is close-only while the API is available, currently including Japan and the Netherlands, with Malta limited to sports scope;
- `geo_check_passed`: not restricted by the table and the raw check passed.

The official page currently describes the raw `blocked` field generically as order-blocked while separately saying the API is unrestricted for the frontend-only tier. The report preserves both values and flags any conflict instead of silently choosing one. An authenticated account/order-eligibility check and current platform policy remain authoritative. Do not use a server or proxy to evade restrictions.

## Optional sanitized community samples

Generate a local, sanitized sample:

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- public /path/to/probe-report.json \
  --provider "AWS" --region "ap-northeast-1" --plan "c7i.large" \
  --output public-sample.json
```

This command does **not** upload. It removes source IP, hostname, exact CPU model, route hops, DNS/peer IPs, raw errors, precise timestamps, and local paths. Inspect the file, then optionally submit it under `public-samples/` by Pull Request.

Community ranking accepts provider/region/plan labels in any language. Aggregation uses stable JSON keys, ISO country codes, numerical measurements, and sample IDs:

```bash
./quant_net_probe.py aggregate 'public-samples/*.json' \
  --min-samples 3 --output COMMUNITY_LEADERBOARD.md
```

At least three different sample IDs are required before a country/provider/datacenter combination is ranked. Medians are used; a single lowest-latency run cannot create a ranking. A network ranking does not prove legal or account-level trading eligibility.

## Recommended selection process

1. Run a quick probe on several providers and regions.
2. Eliminate jurisdiction failures, unstable endpoints, weak single-core CPU, insufficient RAM, poor `fsync`, and bad p95/jitter.
3. Repeat at different hours for at least 24 hours.
4. Start IB Gateway/TWS and FutuOpenD where applicable and measure real established sessions.
5. Validate authenticated account product eligibility without placing unintended orders.
6. Prefer separate execution, data/research, and control nodes when one region cannot serve every venue well.

Endpoints and geographic policies change. Verify current official documentation before purchase and before production deployment.

## License

[MIT](LICENSE)
