# クオンツ取引サーバープローブ

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

クラウド事業者、リージョン、インスタンスタイプを比較するための、依存パッケージ不要・読み取り専用・低負荷の Linux プローブです。IBKR、Futu OpenAPI/FutuOpenD、Binance/OKX の無期限先物、暗号資産取引所、Polymarket、マーケットデータ配信元への REST/WebSocket 接続と、CPU・メモリ・ディスク・`fsync`・NTP を測定します。

> **コミュニティランキングへのデータ提供は完全なオプトインで、既定では無効です。** 通常の `probe` は収集、テレメトリー、アップロードを行いません。`public` を別途実行し、匿名化 JSON を確認したうえで、自分で GitHub Pull Request を送った場合だけ参加となります。完全なプローブレポートは投稿しないでください。

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

実行言語は `LC_ALL`、`LC_MESSAGES`、`LANG` から自動判定されます。未対応ロケールでは対話端末なら言語を確認し、非対話実行では英語にフォールバックします。詳細なコマンド、評価方法、地域制限、匿名化データの仕様は [英語版](README.md) を参照してください。

公開サンプルの事業者名、リージョン名、プラン名は任意の言語で記述できます。集計は固定 JSON キー、ISO 国コード、数値メトリクスを利用するため、表示言語には依存しません。
