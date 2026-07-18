# 量化交易云服务器探针

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

一个无第三方 Python 依赖、可直接放到候选 Linux 云服务器运行的选型工具。它同时回答三类问题：

1. 这台服务器到 IBKR、Futu OpenAPI、数字资产交易所、Polymarket 和行情源的连接质量如何？
2. Binance/OKX 永续合约入口是否真实可达，是否能拿到合约目录和 WebSocket 行情？
3. CPU、内存、磁盘、fsync 与时钟状态是否适合事件驱动量化交易？

探针不会下单、不会要求 API Key、不会读取交易凭据。输出 JSON 原始结果和中文 Markdown 判断报告。

> **隐私与社区排名：完全自愿，默认关闭。** 普通 `probe` 命令只在本机生成报告，项目不会自动收集、上传或遥测任何数据。只有你另外执行 `public` 命令、检查生成的脱敏 JSON，并亲自向 GitHub 提交，才表示选择参加社区机房排名。请勿提交完整探针报告。详情见 [数据贡献与隐私说明](CONTRIBUTING_DATA.zh-CN.md)。

运行结束默认直接在终端显示完整彩色报告：主机硬件、CPU/内存/磁盘/fsync/NTP、分组与用途评分、衍生品能力、Polymarket 地域，以及每个端点的 TCP/HTTP/WS 中位、p95、抖动、成功率、HTTP状态、WS首包、对端IP和自动诊断。JSON/Markdown继续保留用于审计与多服务器比较。

默认 `--terminal-details all` 显示全部端点；用 `--terminal-details key` 仅显示关键与异常端点，`--terminal-details none` 隐藏端点明细，`--no-terminal-summary` 完全关闭屏显。

已有 JSON 无需重跑，可以直接重新显示终端仪表盘：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- show /path/to/probe-report.json
```

本项目以 [MIT License](LICENSE) 公开开源。

## 一句话运行

候选 Linux 云服务器只需 Python 3.10+，无需安装 Python 包：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

启动脚本会依次读取 `LC_ALL`、`LC_MESSAGES`、`LANG`。识别到英文、简体中文或繁体中文时直接使用相应语言；无法识别且有交互终端时会询问语言，没有交互终端时会提示并回退英文。也可以明确指定：

```bash
QUANT_PROBE_LANG=zh-CN curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

公开排名使用固定 JSON 字段、ISO 国家代码和数值指标；供应商、机房和套餐名称可以使用任意语言，不影响汇总。

带参数运行完整扩展扫描：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- --suite extended --profile balanced \
  --label "供应商-机房-套餐" --provider "供应商" --region "机房"
```

脚本仅下载 `quant_net_probe.py` 与 `endpoints.json` 到随机临时目录，结束时自动清理。报告优先保存到当前目录的 `probe-results/`；若当前目录不可写，则自动使用 `$HOME/quant-server-probe-results/`，最后才降级到 `/tmp`，终端会显示实际路径。审慎使用时可先下载并检查 `run.sh`，再执行。

## 快速使用

要求：Linux、Python 3.10+。建议额外安装 `mtr-tiny` 与 `iproute2`：

```bash
sudo apt-get update
sudo apt-get install -y python3 mtr-tiny iproute2
chmod +x quant_net_probe.py
```

在每台候选服务器执行完整测试：

```bash
./quant_net_probe.py probe \
  --label "provider-region-plan" \
  --provider "供应商" \
  --region "机房区域" \
  --profile balanced \
  --routes
```

针对你的主要用途可改配置档：`ibkr`、`futu`、`crypto`、`polymarket`、`research`、`balanced`。

默认 `--suite core` 只测最可能使用的核心场所。需要扫描更多候选券商、交易所、预测市场、数据源和区域锚点时：

```bash
./quant_net_probe.py probe --suite extended --profile balanced --label full-scan
```

只做两轮快速筛查：

```bash
./quant_net_probe.py probe --label test-a --quick --benchmark-level light
```

输出在 `probe-results/`，包括同名 `.json` 和 `.md`。把多个服务器生成的 JSON 放在一起比较：

```bash
./quant_net_probe.py compare server-a.json server-b.json server-c.json \
  --output server-comparison.md
```

## IBKR：正确的测法

核心扫描现在直接测试 IBKR 官方公布的六组 TWS 主后台：美东、美中、欧洲、香港、新加坡和中国大陆网关。测试 TCP 4001（登录/下单）、TCP 4000（行情）、4001 SSL 握手，并在系统安装 `ping` 时补充 ICMP；终端按区域显示中位、p95、抖动、成功率和最佳区域。`--suite extended` 还会检测所有官方备用主机。

中国大陆网关仅适用于账户分配到香港服务器、同时从中国大陆物理连接的客户，不能把它视为通用替代机房。

官方服务端口比官网/CDN 更有参考价值，但仍不能代表最终交易所撮合或完整 SmartRouting 延迟。最可靠的进一步验证是在候选服务器短时运行纸账户 IB Gateway/TWS：

只测试 IBKR 官方主机矩阵：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- --groups ibkr_official --profile ibkr --no-benchmark --no-bandwidth
```

然后继续验证已认证 Gateway 会话：

```bash
# API 默认常见端口：Gateway paper 4002；TWS paper 7497。
./quant_net_probe.py probe --profile ibkr --ib-host 127.0.0.1 --ib-port 4002

# 也可在主报告中直接纳入当前真实会话 RTT，并影响 IBKR/Futu 用途分。
sudo ./quant_net_probe.py probe --profile ibkr --live-sessions

# Gateway 登录并建立后台会话后，读取 Linux 内核对真实连接估计的 RTT。
sudo ./quant_net_probe.py discover --pattern 'ibgateway|tws|java' \
  --output ibkr-real-session.json
```

本机 API 端口延迟只说明“策略进程 → Gateway”；`discover` 的远端 RTT 才能补充“Gateway → IBKR 后台”。IBKR 后续还会路由到不同交易所，因此两者都不等于交易所撮合延迟。

## 富途：Futu OpenAPI / FutuOpenD

准确名称是 **Futu OpenAPI**，服务器网关叫 **FutuOpenD（OpenD）**；“富途牛牛”是客户端品牌。OpenD 默认监听 `127.0.0.1:11111`：

```bash
./quant_net_probe.py probe --profile futu --futu-host 127.0.0.1 --futu-port 11111
sudo ./quant_net_probe.py discover --pattern 'FutuOpenD|OpenD' \
  --output futu-real-session.json
```

公共 OpenAPI 页面仅能判断基础线路。OpenD 登录后，`discover` 会列出其已建立后台 TCP 会话、远端地址、内核 RTT 和 RTT 波动，不抓包也不读取账号密码。

富途官方 FAQ 公布的是云区域而不是固定后台 IP。因此探针加入了明确标注为“替代锚点”的区域端点：腾讯云广州、香港、弗吉尼亚、新加坡、东京，阿里云马来西亚，以及 AWS 加拿大中部和西部（富途只写明 AWS Canada，未给出具体区域）。选择所属券商后，对应的行情和交易锚点才进入 Futu 预筛评分：

```bash
./quant_net_probe.py probe --profile futu --futu-account futu-hk
./quant_net_probe.py probe --profile futu --futu-account moomoo-us
./quant_net_probe.py probe --profile futu --futu-account moomoo-sg
./quant_net_probe.py probe --profile futu --futu-account moomoo-au
./quant_net_probe.py probe --profile futu --futu-account moomoo-my
./quant_net_probe.py probe --profile futu --futu-account moomoo-ca
./quant_net_probe.py probe --profile futu --futu-account moomoo-jp
```

云区域端点与富途实际后台可能使用不同入口、对等互联、负载均衡和私网路由，只适合淘汰明显遥远的候选机房，不能宣称为真实下单延迟。

## Binance、OKX 永续合约

探针不是只访问官网：

- Binance：调用 USDⓈ-M Futures `exchangeInfo`，统计状态为 `TRADING` 的 `PERPETUAL` 合约，并连接期货 `bookTicker` WebSocket。
- OKX：调用 `instType=SWAP` 合约目录，统计 `state=live` 的永续合约，并订阅 `BTC-USDT-SWAP` ticker。

报告中的 `perpetual_market_reachable` / `swap_market_reachable` 表示公有衍生品市场和行情从该 IP 技术可达。它不代表你的账户主体、KYC 地区和账户权限一定允许衍生品下单。不要向探针填 API 密钥。

## Polymarket 地理检查

会调用 Polymarket 官方 `https://polymarket.com/api/geoblock`，记录请求 IP 对应国家/地区及 `blocked` 判断，并与 CLOB REST、Gamma/Data API、市场 WebSocket 可达性交叉检查。

- `fully_blocked`：前端与 API 完全封锁。
- `api_close_only_no_new_orders`：API 与前端只能平仓，不能开新仓。
- `frontend_close_only_api_available`：日本、荷兰（以及马耳他体育市场）的官方地区表称仅前端 close-only、API 可用；报告同时保留原始 `blocked` 值并提示官方页面的字段说明存在口径冲突。
- `geo_check_passed`：官方地区表未限制且原始检查通过，但仍不是账户、钱包和订单合规的最终保证。
- REST 可读而交易资格未知：只能作为行情/研究节点，不能直接认定可下单。

不得用服务器或代理规避适用的地区限制；应以平台条款、账户主体及当地法规为准。

## 主机性能测试

默认轻量测试使用短时、有界负载：最多 2 个短时 CPU 进程、32 MiB 内存块、64 MiB 临时磁盘文件。检测到测试前系统负载较高时会跳过多进程部分。所有磁盘测试都使用自动删除的临时文件上下文，正常完成或异常抛出时不会遗留测试文件。

- CPU：单进程 SHA-256 吞吐（事件循环/策略热路径参考）和最多 8 进程吞吐；
- 内存：大块复制吞吐；
- 磁盘：64 MiB 顺序读写、缓存条件下 4K 随机读、真实 `fsync` 延迟；
- 系统：CPU 型号、vCPU、内存、磁盘余量、虚拟化、负载、Linux clocksource、NTP 状态。

它用于同批实例横向比较，不替代 `fio`、长时 CPU steal/noisy-neighbor 和生产行情回放压测。突发型 vCPU 必须在不同时间重复测，不能只看一次高分。

如候选机完全空闲、希望稍厚一些的短测，可显式使用 `--benchmark-level standard`；它仍将临时文件限制在 128 MiB。生产机建议保持默认 `light`，或用 `--no-benchmark` 完全关闭性能测试。轻量带宽测试只下载 1 MB，可用 `--no-bandwidth` 关闭。

## 评分结构

- 端点分：TCP、HTTP/API、WebSocket/首包延迟，叠加成功率、协议失败和 403/451 地域阻断惩罚；
- 分组分：IBKR、Futu、其他券商、Crypto、Polymarket、其他预测市场、行情源和基础设施；
- 性能分：单核/多进程 CPU、内存、磁盘随机读与 `fsync`；
- 用途分：数字资产执行、IBKR 执行、Futu 执行、Polymarket 执行、行情节点、研究回测；
- 最终选择分：按所选 profile 合成网络和性能，并给出 S/A/B/C/D/E 等级。

地理规则优先于纯延迟：Polymarket 地区表若明确禁止 API 新开仓，其执行用途分封顶 20；日本/荷兰不会仅因原始 `blocked=true` 被错误封顶。Binance/OKX 均未确认任何永续/SWAP 目录时，数字资产执行分封顶 55。

IBKR/Futu 没有检测到真实后台会话时，其执行用途分属于购买前预筛，封顶 65。运行 Gateway/OpenD 后加 `--live-sessions`，真实内核 RTT 才会进入用途评分。

## 连续 24 小时测试

单次测试用于淘汰，不用于最终购买。建议在候选机上每 5 分钟快速测一次：

```bash
mkdir -p soak
for i in $(seq 1 288); do
  ./quant_net_probe.py probe --label "candidate-a-$i" --quick \
    --no-benchmark --output soak
  sleep 300
done
```

至少覆盖亚洲、欧洲和美国交易活跃时段。最终应关注 p95、抖动、失败率、断流、路由变化，而不只是最低延迟。

## 找不到 IP 或网关时

工具按以下顺序降级：DNS → TCP → TLS → HTTP/API → WebSocket。目标禁 ICMP 不会被误判为完全不可用。若供应商或券商不公开地址：

1. 先运行其官方 Gateway/OpenD；
2. 用 `discover` 读取已建立真实连接；
3. 已知专用地址时可追加任意 TCP 目标：

```bash
./quant_net_probe.py probe \
  --target 'VendorFIX=fix.example.com:443' \
  --target 'PrivateFeed=10.0.0.8:9000'
```

也可以复制编辑 `endpoints.json`，加入专用 REST/WS/FIX/行情端点。不要把凭据、签名或私有 API Key 写进配置文件。

## 如何选用途

- 数字资产超短线/做市：优先 WS 首包、TCP/WS p95、抖动、失败率，再看单核 CPU、fsync；带宽通常不是首要矛盾。
- IBKR/Futu 中低频执行：真实 Gateway/OpenD 会话 RTT 和稳定性比官网延迟重要。
- 期权/多市场数据节点：内存、CPU、持续带宽和磁盘写入更重要，应另做生产数据回放。
- 研究/回测/控制面：CPU 多核、内存、磁盘吞吐和 GitHub/PyPI/行情源可达性权重更高。
- 不要让一个“综合分”替代职责拆分；最佳实践常是执行节点、数据/研究节点和控制面分别选址。

端点会变化，购买前应核对各平台最新官方文档；`endpoints.json` 的 `updated` 字段记录了维护日期。

## 自愿提交脱敏样本与社区榜单

程序绝不会自动上传报告。是否参与由用户自行选择，不参与不会影响探针、评分或比较功能。愿意参与集体评估时，先从完整 JSON 生成公开样本：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- public /path/to/probe-report.json \
  --provider "AWS" --region "ap-northeast-1" --plan "c7i.large" \
  --output public-sample.json
```

公开样本自动移除源 IP、主机名、CPU 精确型号、路由跳点、对端/DNS IP、原始错误和精确时间；仅保留到“天”的日期、国家/地区、用户填写的供应商/机房/套餐、性能档位和各端点统计。生成后**不会上传**，请先人工查看，再通过 Pull Request 放入仓库的 `public-samples/` 目录。

维护者可以从公开样本生成榜单：

```bash
./quant_net_probe.py aggregate 'public-samples/*.json' \
  --min-samples 3 --output COMMUNITY_LEADERBOARD.md
```

默认至少 3 个不同样本 ID 才显示一个“国家 + 供应商 + 机房”组合，并使用中位数，不按单台机器或单次最低延迟排名。更可靠的结论应继续要求不同日期、不同网络出口和足够的 p95/失败率样本；公开榜单不能证明交易账户在当地具有法律或产品资格。
