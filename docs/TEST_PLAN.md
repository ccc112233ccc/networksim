# 测试计划

## 1. 目标

测试分成两个问题：

1. 当更多数据流直接竞争同一个 400 Gbps 接收口时，前景流是否按理论剩余带宽公平分享，还是出现额外欠吞吐？
2. 当反向 bulk data 与 CTP TAACK 共享源节点最终回程口时，TAACK 是否会因 VOQ/仲裁排队而延迟，进而耗尽 sender inflight window 并让正向链路空闲？

## 2. 固定网络和协议参数

- 拓扑：[TOPOLOGY.md](TOPOLOGY.md) 中的 512-host Clos；
- CTP、shortest path、packet spray；
- 每个 CTP entity 最多绑定 4 个 source outport；
- 路由算法：`HASH`；
- Flow control：`CBFC`；
- VL scheduler：`SP`；
- 默认 sender inflight：512 个 4 KiB TA segment；
- OOO ACK bitmap：2048；
- congestion control：关闭；
- retransmission：关闭；
- 所有实验性 TAACK/端口附加延迟：关闭。

公开版 `ub-quick-example` 的 traffic CSV 接口是 11 列，不接受本地增强分支曾使用的 `srcPortHint/dstPortHint`。本仓库严格使用公开接口：source 按四条最短首跳做 packet spray；destination CNA 默认解析到 port 0。因而历史固定 port0 参考数据与公开版复验数据应比较机制和数量级，不应要求逐位一致。

关闭重传是有意选择：只要发生实际数据丢包，任务通常无法完整结束，因此“所有任务完成”可作为 lossless 路径的附加验证。

## 3. Suite A：128→1 同目的背景干扰

场景定义：[scenario.json](../scenarios/same-destination-background/scenario.json)

### 前景流

- source：node `0..127`；
- destination：node `128`, port `0`；
- 每条 `32 MiB URMA_WRITE`；
- priority/VL `7`；
- source 从 4 个端口 packet spray，destination 使用 port `0`；
- `100 us` 同步启动。

### 背景流

- source 从 node `129` 起；
- destination 同为 node `128`, port `0`；
- 每条 `32 MiB URMA_WRITE`；
- 在 `0 us` 启动，比前景早 100 us；
- 测试 `0/43/128/383` 条背景流。

### 假设与判据

如果只有接收瓶颈而没有协议额外损失，则：

```text
前景理论带宽 = 400 Gbps × 128 / (128 + background_count)
```

主要判据：测得前景 payload bandwidth / 理论前景带宽。参考验收范围为 98%–102%。

## 4. Suite B：反向 TAACK 干扰

场景定义：[scenario.json](../scenarios/reverse-taack/scenario.json)

### 前景流

- source：node `0..3`；
- destination：node `128`, port `0`；
- 每条 `32 MiB URMA_WRITE`；
- priority/VL `7`；
- source 从 4 个端口 packet spray，destination 使用 port `0`；
- `100 us` 启动。

使用 4 条而不是 128 条前景流，是为了把每条前景流的 TAACK 精确对应到 4 个可控回程目标口，从而构造最小因果实验。

### 对照和干预

| Case | 背景目标 | 每目标 fan-in | 每目标背景总量 | 目的 |
|---|---|---:|---:|---|
| `no-bg` | 无 | 0 | 0 | 基线 |
| `reverse-disjoint` | node 4..7 | 16 | 256 MiB | 共享反向 fabric，但不共享 TAACK 最后一跳 |
| `reverse-shared-fanin01` | node 0..3 | 1 | 256 MiB | 低 fan-in |
| `reverse-shared-fanin04` | node 0..3 | 4 | 256 MiB | 中等 fan-in |
| `reverse-shared-fanin08` | node 0..3 | 8 | 256 MiB | 强干扰点 |
| `reverse-shared` | node 0..3 | 16 | 256 MiB | 更高 fan-in |
| `reverse-shared-fanin08-window1024` | node 0..3 | 8 | 256 MiB | 仅扩大 sender window |
| `reverse-shared-fanin08-fgprio1` | node 0..3 | 8 | 256 MiB | 前景/TAACK VL1，背景 VL7 |
| `reverse-shared-fanin08-bgprio6` | node 0..3 | 8 | 256 MiB | 可选反向优先级负对照 |

fan-in 扫描始终保持每个目标 256 MiB，分别使用 256/64/32/16 MiB 的单流大小，避免把“流数”与“总背景字节数”混在一起。

### 主要指标

1. 前景最晚完成时间；
2. node128:port0 接收带宽；
3. 连续 4132-byte data packet 之间的最大接收空洞；
4. TAACK latency：receiver `ta-unit-complete` 到 source `taack-received`；
5. source0 outstanding、窗口满持续时间和最大重新准入间隙；
6. diagnostic profile 下 node512:port0 聚合队列峰值。

### 因果验收

- `reverse-disjoint` 应接近 `no-bg`，否则只能说明一般反向 fabric 负载有影响；
- shared case 应同时出现 TAACK 延迟、sender admission gap 和正向接收空洞；
- 只增大窗口后，如果 TAACK 仍慢但 wire rate 恢复，可确认有限窗口是传导环节；
- 只改变 VL 隔离后，如果大队列仍存在但 TAACK/wire rate 恢复，可确认共享服务类而非队列存在本身是根因。

## 5. Suite C：同步 incast 与 admission/pacing

场景定义：[scenario.json](../scenarios/synchronized-incast/scenario.json)

- node0..63 向 node128 同步发送 1 MiB URMA_WRITE；
- 总流量固定为 64 MiB；
- 将 64 条流的启动时间均匀摊在 `0/100/500/1500 us`；
- 使用 `queue` profile，重点测量 FCT P50/P95/P99、job makespan、node520:port0 峰值队列、队列≥1 MiB 时长和接收空洞。

因果判据：如果小幅错峰只改变单流等待起点而没有消除过载，FCT 会改善但峰值队列和 job makespan 基本不变；只有启动间隔接近单流 wire serialization 时间后，持续队列才应显著下降。

## 6. Suite D：mice–elephant 与服务类隔离

场景定义：[scenario.json](../scenarios/mice-elephant/scenario.json)

- 32 条 256 KiB mice：node0..31 → node128，100 us 启动；
- 8 条 16 MiB elephants：node256..263，0 us 启动；
- 对比无背景、elephant 去 node192、共享 node128/VL7、共享 node128 但 mice 使用 VL1；
- 主要测量 mice FCT 分位数、P99 slowdown、mice 聚合带宽和最终出口队列。

因果判据：disjoint case 应与 mice-only 接近；共享最终口和 VL 后短流尾延迟应上升；只隔离 VL 后若短流恢复但总队列仍高，说明 QoS 改变了服务顺序而非消除了拥塞。

## 7. 运行矩阵

```bash
make setup

# 快速回归
make suite SUITE=reverse-taack PROFILE=compact
make suite SUITE=same-destination-background PROFILE=compact

# 新增队列级矩阵和报告图表
make suite SUITE=synchronized-incast PROFILE=queue
make suite SUITE=mice-elephant PROFILE=queue
make plot

# 详细根因 trace；建议只跑选定用例
make run SUITE=reverse-taack PROFILE=diagnostic CASE=reverse-shared-fanin08
make run SUITE=reverse-taack PROFILE=diagnostic CASE=reverse-shared-fanin08-fgprio1
```

可选负对照不在默认 suite 中：

```bash
make run SUITE=reverse-taack PROFILE=compact CASE=reverse-shared-fanin08-bgprio6
```

## 8. 结果解释限制

- 单个固定 RNG/hash 映射可证明“该机制能够发生”，不能直接给出生产分布概率；生产结论应再扫描 RNG run、流启动抖动和端口映射。
- 8-way 比 16-way 略差并不违反因果关系；多 VOQ 的哈希落点和 RR phase 会造成非单调变化。
- `taskCompletesTime` 包含最终 TAACK 尾延迟；判断正向 wire utilization 时应同时看接收口吞吐和 packet gap。
- QoS 用例让前景 data 与其继承的 TAACK 一起使用 VL1，是“独立 TAACK VL”的代理实验；当前配置接口不能只改变 TAACK 的 VL。
