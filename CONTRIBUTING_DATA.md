# Community Data Contribution and Privacy

[English](CONTRIBUTING_DATA.md) | [简体中文](CONTRIBUTING_DATA.zh-CN.md)

Community ranking uses voluntarily published samples to compare countries, cloud providers, regions, and datacenters for quantitative-trading infrastructure. Participation is optional and has no effect on any probe, scoring, display, or comparison feature.

## The short version

- **No collection by default:** `probe`, `show`, and `compare` keep reports on your server.
- **No automatic upload:** the project contains no telemetry or silent reporting service.
- **Explicit opt-in:** participation requires running `public`, inspecting the sanitized file, and intentionally submitting a GitHub Pull Request.
- **Never submit full reports:** `probe-*.json` and `probe-*.md` may contain source IP, hostname, routes, peer addresses, and precise timestamps.
- **Withdrawal:** submit a deletion Pull Request or open an Issue identifying the `sample_id`. Removal from this repository cannot erase copies already made by third parties.

## Create an optional public sample

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- public /path/to/probe-report.json \
  --provider "provider" --region "region/datacenter" --plan "instance type" \
  --output public-sample.json
```

`public` creates a local file and does not upload it. Inspect it in a text editor. If you agree to publish the included country/region, provider, datacenter, plan bucket, and measurements, place it under `public-samples/` in a Pull Request. Doing nothing is the default opt-out; no special opt-out flag is required.

Provider, datacenter, and plan labels may be written in any language. Aggregation uses language-neutral JSON field names, ISO country codes, numerical values, and sample IDs.

## Removed and retained data

| Removed automatically | Retained for aggregation |
|---|---|
| Source public IP and hostname | Country and region code |
| Exact CPU model | Architecture, vCPU count, RAM bucket |
| Route hops, DNS answers, peer IPs | Contributor-supplied provider/datacenter/plan labels |
| Raw error strings | TCP/HTTP/WS percentiles and success rates |
| Timestamps finer than one day | Calendar date |
| Local paths, credentials, account data | Network, performance, and role scores |

The probe does not read API keys, wallet private keys, or trading credentials. Such data must never be added to a report or repository.

## Ranking rules and limitations

- A country/provider/datacenter combination is shown only after at least three different sample IDs are available.
- Rankings use medians; a single low-latency run cannot create a rank.
- Sample count, date coverage, plan, and probe version should accompany results.
- Repeated measurements from one host may support stability analysis but must not be represented as independent users.
- Network reachability and ranking do not prove legal, KYC, account, or product eligibility at any broker or exchange.
- Maintainers may reject malformed, duplicate, manipulated, implausible, or privacy-sensitive samples.

By submitting, a contributor confirms that they may publish the measurement, have inspected it for sensitive information, have labeled the provider/region honestly, have not modified values to manipulate ranking, and understand that public data may be copied elsewhere.
