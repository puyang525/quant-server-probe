# 量化交易伺服器探針

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

這是一個無第三方 Python 相依、唯讀且低負載的 Linux 探針，用於比較雲端供應商、機房與主機規格。它測試 IBKR、Futu OpenAPI/FutuOpenD、Binance/OKX 永續合約、其他數位資產交易所、Polymarket、行情源與基礎設施的 REST、WebSocket、延遲、成功率及主機效能。

> **社群排名完全自願，預設關閉。** 一般 `probe` 不收集、不遙測、不上傳資料。只有另外執行 `public`、人工檢查脫敏 JSON，並主動提交 GitHub Pull Request 才表示參與。切勿提交完整報告。詳見 [資料貢獻與隱私說明](CONTRIBUTING_DATA.md)。

## 一行執行

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

啟動器會偵測 `LC_ALL`、`LC_MESSAGES`、`LANG`。可明確指定：

```bash
QUANT_PROBE_LANG=zh-TW curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

終端會顯示網路、主機、用途評分，以及每個端點的 TCP/HTTP/WS 中位數、p95、抖動、成功率、狀態碼、首包延遲與自動診斷。完整參數、IB/Futu 真實會話測量、Polymarket 地區分級、衍生品限制與社群榜單方法請參閱 [英文完整說明](README.md) 或 [簡體中文完整說明](README.zh-CN.md)。

公開樣本的供應商、機房和方案名稱可使用任何語言；排名依固定 JSON 欄位、ISO 國家代碼和數值統計，不受顯示語言影響。
