# 端点依据与维护说明

维护日期：2026-07-18。端点随平台升级可能变化，运行前可根据官方文档更新 `endpoints.json`。

## 核心官方资料

- IBKR API / TWS：https://ibkrcampus.com/ibkr-api-page/twsapi-doc/
- IBKR Host and Ports Documentation（文档最后更新 2026-04-27）：TWS 4001 用于登录/下单且使用 SSL，4000 用于行情；主机区域包括 US East、US Central、Europe、Hong Kong、Singapore、Mainland China gateway，并列出各自备用主机。大陆网关仅用于分配到香港服务器且从中国大陆连接的客户。
- Futu OpenAPI / FutuOpenD：https://openapi.futunn.com/futu-api-doc/en/ ，默认本地 API 端口见 https://openapi.futunn.com/futu-api-doc/en/opend/opend-cmd.html
- Futu API 官方服务器区域 FAQ：https://openapi.futunn.com/futu-api-doc/en/qa/other.html
- 腾讯云 COS 区域与端点：https://www.tencentcloud.com/document/product/436/6224
- 阿里云 OSS 区域与端点：https://www.alibabacloud.com/help/en/oss/user-guide/regions-and-endpoints
- AWS S3 服务端点：https://docs.aws.amazon.com/general/latest/gr/s3.html
- Binance Spot / Futures：https://developers.binance.com/docs
- OKX API v5：https://www.okx.com/docs-v5/en/
- Bybit V5：https://bybit-exchange.github.io/docs/v5/intro
- Coinbase Exchange：https://docs.cdp.coinbase.com/exchange/introduction/welcome
- Kraken：https://docs.kraken.com/api/
- Deribit：https://docs.deribit.com/
- Hyperliquid：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Polymarket WebSocket：https://docs.polymarket.com/market-data/websocket/overview
- Polymarket 官方地理检查：https://docs.polymarket.com/api-reference/geoblock

## 扩展场所

- Bitget：https://www.bitget.com/api-doc/
- Gate.io：https://www.gate.com/docs/developers/apiv4/
- KuCoin Futures：https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-server-time
- BitMEX：https://www.bitmex.com/app/apiOverview
- dYdX Indexer：https://docs.dydx.xyz/indexer-client/http
- Kalshi：https://docs.kalshi.com/welcome
- Alpaca：https://docs.alpaca.markets/
- OANDA v20：https://developer.oanda.com/rest-live-v20/introduction/

## 解释边界

公开 REST/WS/TLS 端点只用于测公网入口、CDN/边缘和技术可达性。它们不能证明账户权限、KYC/账户主体资格、当地合规许可，也不能等同于最终撮合引擎延迟。IBKR、FutuOpenD、Rithmic、CQG、FIX 与专线应优先使用真实登录会话或签约后提供的专用端点复测。
