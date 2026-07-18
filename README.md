# 量化交易云服务器探针

一个无第三方 Python 依赖、可直接放到候选 Linux 云服务器运行的选型工具。它同时回答三类问题：

1. 这台服务器到 IBKR、Futu OpenAPI、数字资产交易所、Polymarket 和行情源的连接质量如何？
2. Binance/OKX 永续合约入口是否真实可达，是否能拿到合约目录和 WebSocket 行情？
3. CPU、内存、磁盘、fsync 与时钟状态是否适合事件驱动量化交易？

探针不会下单、不会要求 API Key、不会读取交易凭据。输出 JSON 原始结果和中文 Markdown 判断报告。

本项目以 [MIT License](LICENSE) 公开开源。

## 一句话运行

候选 Linux 云服务器只需 Python 3.10+，无需安装 Python 包：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

带参数运行完整扩展扫描：

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | \
  bash -s -- --suite extended --profile balanced \
  --label "供应商-机房-套餐" --provider "供应商" --region "机房"
```

脚本仅下载 `quant_net_probe.py` 与 `endpoints.json` 到随机临时目录，结束时自动清理；探针报告仍保存在当前目录的 `probe-results/`。审慎使用时可先下载并检查 `run.sh`，再执行。

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

IBKR 公网/API 端点主要用于购买前淘汰明显较差的线路，不能代表最终订单路由。最可靠的做法是在候选服务器短时运行纸账户 IB Gateway/TWS：

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

## Binance、OKX 永续合约

探针不是只访问官网：

- Binance：调用 USDⓈ-M Futures `exchangeInfo`，统计状态为 `TRADING` 的 `PERPETUAL` 合约，并连接期货 `bookTicker` WebSocket。
- OKX：调用 `instType=SWAP` 合约目录，统计 `state=live` 的永续合约，并订阅 `BTC-USDT-SWAP` ticker。

报告中的 `perpetual_market_reachable` / `swap_market_reachable` 表示公有衍生品市场和行情从该 IP 技术可达。它不代表你的账户主体、KYC 地区和账户权限一定允许衍生品下单。不要向探针填 API 密钥。

## Polymarket 地理检查

会调用 Polymarket 官方 `https://polymarket.com/api/geoblock`，记录请求 IP 对应国家/地区及 `blocked` 判断，并与 CLOB REST、Gamma/Data API、市场 WebSocket 可达性交叉检查。

- `geo_blocked`：不应购买此节点用于 Polymarket 交易。
- `geo_check_passed`：必要条件通过，但仍不是账户、钱包和订单合规的最终保证。
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

地理规则优先于纯延迟：Polymarket 官方地理检查若为 blocked，其执行用途分封顶 20；Binance/OKX 均未确认任何永续/SWAP 目录时，数字资产执行分封顶 55。

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
