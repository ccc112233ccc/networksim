# 参考结果与结论

## 结果来源与可比性

- 全量历史矩阵日期：2026-08-14；公开上游复验日期：2026-08-17；
- 拓扑与工作负载：本仓库场景定义；
- CTP packet spray、CBFC、SP；固定上游提交不注入额外 ingress-contention penalty；
- 默认 sender inflight 512，OOO threshold 2048；
- 重传和端到端 congestion control 关闭；
- 完整原始 runlog 未提交，结构化结果保存在 [`results/reference`](../results/reference/)；
- 上游固定版本记录在 [`simulator.lock.json`](../simulator.lock.json)。

2026-08-14 的全量矩阵来自增强分支，traffic CSV 显式固定 `srcPortHint=0,dstPortHint=0`。公开上游固定提交只接受 11 列 traffic CSV，因此 2026-08-17 的复验使用公开版原生行为：source 在四条最短首跳 packet spray，destination 默认落到 port0。两组结果的核心机制一致，但精确数值不可视为同一次实验。公开复验只叠加 [`0001-networksim-observability.patch`](../patches/0001-networksim-observability.patch)，该补丁不改变协议行为。

## 128→1 加同目的背景流

| Background | Completed | FG first ms | FG median ms | FG P99 ms | FG last ms | FG payload Gbps | Nominal Gbps | FG/nominal | Receiver util. |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 128 | 79.892799 | 85.785403 | 86.655974 | 86.656056 | 396.507 | 400.000 | 99.127% | 99.998% |
| 43 | 171 | 108.595127 | 114.553429 | 115.665722 | 115.665805 | 297.060 | 299.415 | 99.214% | 99.999% |
| 128 | 256 | 165.066757 | 172.019839 | 173.209607 | 173.209690 | 198.371 | 200.000 | 99.185% | 99.999% |
| 383 | 511 | 330.351633 | 341.706617 | 345.797793 | 345.797958 | 99.364 | 100.196 | 99.170% | 100.000% |

结论：在这个纯正向接收瓶颈场景里没有额外显著欠吞吐。背景流越多，前景完成时间按公平份额增长，但测得前景带宽始终约为理论值的 99.2%。流间完成时间差主要表现为部分流提前完成，最慢流仍接近满口公平完成边界。

## 反向 TAACK 干扰

TAACK latency 定义为接收端完成一个 TA unit 到发送端处理对应 TAACK 的时间。

### 公开上游固定提交复验

| Case | FG last ms | FG payload Gbps | Receiver Rx Gbps | Max Rx gap us | TAACK median us | TAACK P99 us | TAACK max us |
|---|---:|---:|---:|---:|---:|---:|---:|
| `no-bg` | 2.709605 | 396.272 | 400.000 | 0.082640 | 0.705920 | 0.705920 | 0.706920 |
| `reverse-shared-fanin08` | 4.063631 | 264.232 | 282.110 | 58.287680 | 83.431800 | 267.905040 | 294.580480 |
| `reverse-shared-fanin08-window1024` | 3.225528 | 332.889 | 373.670 | 49.781000 | 87.689280 | 279.321520 | 327.420520 |
| `reverse-shared-fanin08-fgprio1` | 2.709824 | 396.240 | 400.000 | 0.082640 | 0.848720 | 1.068240 | 1.154040 |

这四个用例均从公开仓库提交 `9e6368f` 实际编译运行，RNG run 为 1。结构化原始值见 [`public-upstream-smoke.csv`](../results/reference/public-upstream-smoke.csv)。

### 历史全量扫描

| Case | FG last ms | FG payload Gbps | Receiver Rx Gbps | Max Rx gap us | TAACK median us | TAACK P99 us | TAACK max us | Representative queue |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `no-bg` | 2.709683 | 396.261 | 400.000 | 0.082640 | 0.744920 | 0.744920 | 0.754920 | 40 B |
| `reverse-disjoint` | 2.710834 | 396.093 | 400.000 | 0.082640 | 0.744920 | 1.812640 | 4.952960 | 72 B |
| `reverse-shared-fanin01` | 2.742662 | 391.496 | 400.000 | 0.082640 | 2.687160 | 41.399560 | 45.311080 | 0.426 MB |
| `reverse-shared-fanin04` | 3.051433 | 351.881 | 376.060 | 16.317360 | 45.072460 | 175.318440 | 181.315320 | 3.984 MB |
| `reverse-shared-fanin08` | 3.892146 | 275.874 | 299.410 | 26.660200 | 70.364960 | 268.399080 | 280.308440 | 5.075 MB |
| `reverse-shared` | 3.673723 | 292.276 | 321.430 | 61.843840 | 74.068240 | 241.559640 | 268.931480 | 4.331 MB |
| `reverse-shared-fanin08-window1024` | 3.005267 | 357.287 | 399.660 | 2.317200 | 75.527600 | 267.303800 | 299.559240 | 4.888 MB |
| `reverse-shared-fanin08-fgprio1` | 2.709869 | 396.234 | 400.000 | 0.082640 | 0.864080 | 1.063400 | 1.179240 | 4.665 MB |
| `reverse-shared-fanin08-bgprio6` | 7.836245 | 137.022 | 138.250 | 4991.206920 | 0.744920 | 5176.324320 | 5229.863520 | 4.024 MB |

## 因果链

```mermaid
flowchart LR
    A["Reverse bulk data targets source port 0"] --> B["Final L1 egress builds multiple VOQs"]
    B --> C["TAACK shares the same VL and RR service"]
    C --> D["TAACK return latency rises"]
    D --> E["512-segment window releases slowly"]
    E --> F["Replacement admission gaps"]
    F --> G["Forward receiver becomes idle"]
    G --> H["Wire throughput and FCT degrade"]
```

关键证据：

1. **不是一般反向负载。** `reverse-disjoint` 与无背景几乎相同；只有背景流和 TAACK 共享前景源最终回程口才出现问题。
2. **窗口是传导环节。** 历史固定端口扫描中，inflight 从 512 提到 1024 后接收口从 299.41 恢复到 399.66 Gbps；公开版四口喷洒复验从 282.11 恢复到 373.67 Gbps，方向一致但恢复不完全。按每源约 100 Gbps、4 KiB segment 估算，268 us 需要约 818 个在途 segment；512 明显覆盖不足，而单纯扩大窗口仍可能受到更长尾部和多路径调度影响。
3. **服务类共享是根本原因。** VL1/VL7 隔离后，最终出口仍有 4.665 MB 排队，但 TAACK P99 降至 1.063 us，接收口恢复 400 Gbps。不是“有队列就慢”，而是 TAACK 和 bulk data 共享该队列服务等级才慢。
4. **不是丢包。** 所有任务完成，重传关闭，也没有 OOO threshold 溢出。问题是 lossless queueing/HoL 和 sender-window starvation。

## 优化优先级

1. **推荐：独立 TAACK 控制 VL/保底带宽。** 真实实现最好允许 TAACK 单独映射 VL，并使用 SP、WRR reserved share 或 ACK-aware scheduling。只把全部前景流量提到高优先级是代理方案，可能饿死低优先级业务。
2. **按反馈 BDP 设置 inflight。** `window_segments >= fair_rate × TAACK_RTT / segment_bytes`。扩大窗口可以防止正向空洞，但不会消除最终 TAACK 尾延迟，并可能增加网络在途量和队列。
3. **分散回程最后一跳。** 如果协议和硬件允许，让 TAACK 使用多个目的端口/控制路径，而不是固定返回 port0。
4. **receiver-driven admission。** 限制面向同一源/目的端口的并发反向 bulk traffic，避免控制报文长期与多 VOQ 轮转。

CBFC/PFC 能避免丢包，但本身不会赋予 TAACK 更高调度优先级，因此不能单独解决本实验中的反馈路径干扰。
