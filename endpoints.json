{
  "schema_version": 1,
  "updated": "2026-07-18",
  "endpoints": [
    {"id":"ibkr-web","name":"IBKR Web / Client Portal","group":"ibkr","weight":2,"http_url":"https://www.interactivebrokers.com/","route":true,"notes":"Public edge only; not order-routing latency."},
    {"id":"ibkr-api","name":"IBKR Web API","group":"ibkr","weight":4,"http_url":"https://api.ibkr.com/v1/api/iserver/auth/status","route":true,"notes":"Unauthenticated status may return 401/4xx; reachability still useful."},

    {"id":"futu-openapi","name":"Futu OpenAPI / FutuOpenD 官方入口","group":"futu","weight":2,"http_url":"https://openapi.futunn.com/futu-api-doc/en/","route":true,"notes":"Public documentation edge only. Run FutuOpenD, then discover kernel RTT for real backend sessions."},

    {"id":"binance-spot-rest","name":"Binance Spot REST","group":"crypto","weight":2,"http_url":"https://api.binance.com/api/v3/time","route":true},
    {"id":"binance-spot-ws","name":"Binance Spot WS bookTicker","group":"crypto","weight":2,"ws_url":"wss://stream.binance.com:9443/ws/btcusdt@bookTicker"},
    {"id":"binance-usdm-rest","name":"Binance USD-M 永续合约目录","group":"crypto","weight":5,"http_url":"https://fapi.binance.com/fapi/v1/exchangeInfo","capability":"binance_usdm_perpetual","route":true},
    {"id":"binance-usdm-ws","name":"Binance USD-M 永续 WS","group":"crypto","weight":5,"ws_url":"wss://fstream.binance.com/ws/btcusdt@bookTicker"},

    {"id":"okx-rest","name":"OKX REST Time","group":"crypto","weight":2,"http_url":"https://www.okx.com/api/v5/public/time","route":true},
    {"id":"okx-swap-rest","name":"OKX SWAP 永续合约目录","group":"crypto","weight":5,"http_url":"https://www.okx.com/api/v5/public/instruments?instType=SWAP","capability":"okx_swap","route":true},
    {"id":"okx-swap-ws","name":"OKX SWAP 永续 WS","group":"crypto","weight":5,"ws_url":"wss://ws.okx.com:8443/ws/v5/public","ws_send":"{\"op\":\"subscribe\",\"args\":[{\"channel\":\"tickers\",\"instId\":\"BTC-USDT-SWAP\"}]}"},

    {"id":"bybit-linear-rest","name":"Bybit Linear Perpetual REST","group":"crypto","weight":4,"http_url":"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol=BTCUSDT","route":true},
    {"id":"bybit-linear-ws","name":"Bybit Linear Perpetual WS","group":"crypto","weight":4,"ws_url":"wss://stream.bybit.com/v5/public/linear","ws_send":"{\"op\":\"subscribe\",\"args\":[\"tickers.BTCUSDT\"]}"},
    {"id":"deribit-rest","name":"Deribit Options/Futures REST","group":"crypto","weight":3,"http_url":"https://www.deribit.com/api/v2/public/get_time","route":true},
    {"id":"deribit-ws","name":"Deribit Options/Futures WS","group":"crypto","weight":3,"ws_url":"wss://www.deribit.com/ws/api/v2","ws_send":"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"public/get_time\",\"params\":{}}"},
    {"id":"coinbase-rest","name":"Coinbase Exchange REST","group":"crypto","weight":2,"http_url":"https://api.exchange.coinbase.com/time","route":true},
    {"id":"coinbase-ws","name":"Coinbase Exchange WS","group":"crypto","weight":2,"ws_url":"wss://ws-feed.exchange.coinbase.com","ws_send":"{\"type\":\"subscribe\",\"product_ids\":[\"BTC-USD\"],\"channels\":[\"ticker\"]}"},
    {"id":"kraken-rest","name":"Kraken REST","group":"crypto","weight":2,"http_url":"https://api.kraken.com/0/public/Time","route":true},
    {"id":"kraken-ws","name":"Kraken WS v2","group":"crypto","weight":2,"ws_url":"wss://ws.kraken.com/v2","ws_send":"{\"method\":\"subscribe\",\"params\":{\"channel\":\"ticker\",\"symbol\":[\"BTC/USD\"]}}"},
    {"id":"hyperliquid-rest","name":"Hyperliquid Perps REST","group":"crypto","weight":3,"http_url":"https://api.hyperliquid.xyz/info","http_method":"POST","http_body":"{\"type\":\"meta\"}","route":true},
    {"id":"hyperliquid-ws","name":"Hyperliquid Perps WS","group":"crypto","weight":3,"ws_url":"wss://api.hyperliquid.xyz/ws","ws_send":"{\"method\":\"subscribe\",\"subscription\":{\"type\":\"allMids\"}}"},

    {"id":"bitget-rest","name":"Bitget Futures REST","group":"crypto","weight":2,"suite":"extended","http_url":"https://api.bitget.com/api/v2/public/time","route":true},
    {"id":"bitget-ws","name":"Bitget Futures WS","group":"crypto","weight":2,"suite":"extended","ws_url":"wss://ws.bitget.com/v2/ws/public","ws_send":"{\"op\":\"subscribe\",\"args\":[{\"instType\":\"USDT-FUTURES\",\"channel\":\"ticker\",\"instId\":\"BTCUSDT\"}]}"},
    {"id":"gate-rest","name":"Gate.io REST","group":"crypto","weight":1,"suite":"extended","http_url":"https://api.gateio.ws/api/v4/spot/time","route":true},
    {"id":"gate-ws","name":"Gate.io Futures WS","group":"crypto","weight":2,"suite":"extended","ws_url":"wss://fx-ws.gateio.ws/v4/ws/usdt","notes":"Handshake reachability; subscription schema changes should be kept in custom config."},
    {"id":"kucoin-futures","name":"KuCoin Futures REST","group":"crypto","weight":2,"suite":"extended","http_url":"https://api-futures.kucoin.com/api/v1/timestamp","route":true},
    {"id":"bitmex-rest","name":"BitMEX Perpetual REST","group":"crypto","weight":2,"suite":"extended","http_url":"https://www.bitmex.com/api/v1/instrument?symbol=XBTUSD&count=1&reverse=true","route":true},
    {"id":"bitmex-ws","name":"BitMEX Perpetual WS","group":"crypto","weight":2,"suite":"extended","ws_url":"wss://ws.bitmex.com/realtime?subscribe=instrument:XBTUSD"},
    {"id":"dydx-rest","name":"dYdX Indexer REST","group":"crypto","weight":2,"suite":"extended","http_url":"https://indexer.dydx.trade/v4/time","route":true},
    {"id":"dydx-ws","name":"dYdX Indexer WS","group":"crypto","weight":2,"suite":"extended","ws_url":"wss://indexer.dydx.trade/v4/ws","notes":"Handshake only; use authenticated/market-specific config for production feed tests."},

    {"id":"polymarket-geo","name":"Polymarket 官方地理资格检查","group":"polymarket","weight":8,"http_url":"https://polymarket.com/api/geoblock","capability":"polymarket_geoblock","route":true,"notes":"Official requesting-IP check; necessary but not sufficient for account/order eligibility."},
    {"id":"polymarket-clob","name":"Polymarket CLOB REST","group":"polymarket","weight":5,"http_url":"https://clob.polymarket.com/time","route":true},
    {"id":"polymarket-ws","name":"Polymarket CLOB Market WS","group":"polymarket","weight":6,"ws_url":"wss://ws-subscriptions-clob.polymarket.com/ws/market","route":true,"notes":"Handshake only unless a current asset ID is supplied in a custom config."},
    {"id":"polymarket-gamma","name":"Polymarket Gamma Markets","group":"polymarket","weight":2,"http_url":"https://gamma-api.polymarket.com/markets?limit=1"},
    {"id":"polymarket-data","name":"Polymarket Data API","group":"polymarket","weight":2,"http_url":"https://data-api.polymarket.com/"},

    {"id":"kalshi-status","name":"Kalshi Prediction Exchange","group":"prediction","weight":4,"suite":"extended","http_url":"https://external-api.kalshi.com/trade-api/v2/exchange/status","route":true},
    {"id":"kalshi-perps-status","name":"Kalshi Perps/Margin Exchange","group":"prediction","weight":2,"suite":"extended","http_url":"https://external-api.kalshi.com/trade-api/v2/margin/exchange/status","route":true},

    {"id":"alpaca-live","name":"Alpaca Trading API","group":"brokers","weight":1,"suite":"extended","host":"api.alpaca.markets","port":443,"tls":true,"notes":"TLS reachability only; trading endpoints require credentials."},
    {"id":"oanda-live","name":"OANDA v20 Trading API","group":"brokers","weight":1,"suite":"extended","host":"api-fxtrade.oanda.com","port":443,"tls":true,"notes":"TLS reachability only; account API requires token."},
    {"id":"tradier","name":"Tradier Brokerage API","group":"brokers","weight":1,"suite":"extended","host":"api.tradier.com","port":443,"tls":true},
    {"id":"schwab","name":"Schwab Trader API","group":"brokers","weight":1,"suite":"extended","host":"api.schwabapi.com","port":443,"tls":true},
    {"id":"saxo","name":"Saxo OpenAPI","group":"brokers","weight":1,"suite":"extended","host":"gateway.saxobank.com","port":443,"tls":true},

    {"id":"massive","name":"Massive/Polygon Market Data","group":"market_data","weight":3,"http_url":"https://api.polygon.io/v3/reference/tickers?limit=1","route":true,"notes":"401/403 without a key still measures edge reachability."},
    {"id":"databento","name":"Databento Market Data","group":"market_data","weight":3,"http_url":"https://hist.databento.com/v0/metadata.list_publishers","route":true,"notes":"Authentication response still measures edge reachability."},
    {"id":"twelvedata","name":"Twelve Data","group":"market_data","weight":1,"http_url":"https://api.twelvedata.com/time_series?symbol=AAPL&interval=1min&outputsize=1"},
    {"id":"finnhub","name":"Finnhub Market Data","group":"market_data","weight":1,"suite":"extended","http_url":"https://finnhub.io/api/v1/quote?symbol=AAPL"},
    {"id":"alphavantage","name":"Alpha Vantage","group":"market_data","weight":1,"suite":"extended","http_url":"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM"},
    {"id":"fred","name":"FRED Macro Data","group":"market_data","weight":1,"suite":"extended","http_url":"https://api.stlouisfed.org/fred/series?series_id=GDP"},

    {"id":"anchor-hk","name":"区域锚点 香港 (AWS ap-east-1)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.ap-east-1.amazonaws.com/","route":true},
    {"id":"anchor-tokyo","name":"区域锚点 东京 (AWS ap-northeast-1)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.ap-northeast-1.amazonaws.com/","route":true},
    {"id":"anchor-singapore","name":"区域锚点 新加坡 (AWS ap-southeast-1)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.ap-southeast-1.amazonaws.com/","route":true},
    {"id":"anchor-london","name":"区域锚点 伦敦 (AWS eu-west-2)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.eu-west-2.amazonaws.com/","route":true},
    {"id":"anchor-frankfurt","name":"区域锚点 法兰克福 (AWS eu-central-1)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.eu-central-1.amazonaws.com/","route":true},
    {"id":"anchor-useast","name":"区域锚点 美东弗吉尼亚 (AWS us-east-1)","group":"anchors","weight":1,"suite":"extended","http_url":"https://s3.us-east-1.amazonaws.com/","route":true},

    {"id":"github","name":"GitHub API","group":"infra","weight":2,"http_url":"https://api.github.com/rate_limit","route":true},
    {"id":"pypi","name":"PyPI","group":"infra","weight":1,"http_url":"https://pypi.org/pypi/nautilus_trader/json"},
    {"id":"cloudflare","name":"Cloudflare Edge","group":"infra","weight":1,"http_url":"https://www.cloudflare.com/cdn-cgi/trace"}
    ,{"id":"dockerhub","name":"Docker Hub Registry","group":"infra","weight":1,"suite":"extended","http_url":"https://registry-1.docker.io/v2/"}
    ,{"id":"npm","name":"npm Registry","group":"infra","weight":1,"suite":"extended","http_url":"https://registry.npmjs.org/"}
  ]
}
