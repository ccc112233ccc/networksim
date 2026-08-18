# networksim

`networksim` 是一个面向 ns-3-UB/CTP 的可复现实验仓库。它不复制外部仿真器源码，而是：

- 按固定提交从 [open-usim/ns-3-ub](https://gitcode.com/open-usim/ns-3-ub) 拉取源码和工具子模块；
- 自动配置并编译 `ub-quick-example`；
- 自动应用一个不改变协议行为的可观测性补丁，关闭无效逐包告警并记录 TA unit/TAACK 时间点；
- 生成 512 主机、32 台 L1、16 台 L2 的四端口 Clos 拓扑及完整路由表；
- 运行 128→1 背景干扰和反向 TAACK 干扰测试；
- 运行同步 incast/pacing 以及 mice–elephant/服务类隔离测试；
- 汇总任务完成时间、接收带宽、正向空洞、TAACK 延迟和队列占用；
- 保存已经得到的参考数据、结论和复现边界。

仿真器版本锁定在 [`simulator.lock.json`](simulator.lock.json) 中。当前固定提交为 `9e6368f`，避免上游更新导致结果漂移。可以通过环境变量 `SIM_REF` 显式覆盖，但覆盖后的结果不能再与仓库参考数据直接等同。

## 快速开始

环境要求：macOS 或 Linux、Git、CMake、Ninja 或 Make、支持 C++20 的编译器、Python 3.10+。上游文档推荐 Python 3.12，脚本会优先选择 `python3.12`，否则使用 `python3`；构建时优先 Ninja，缺失时自动回退到 Unix Makefiles。release 构建显式开启 ns-3 logging，因为 CTP window/detail 观测通过 `NS_LOG_INFO` 输出。

```bash
git clone https://github.com/ccc112233ccc/networksim.git
cd networksim

# 拉取固定版本的 ns-3-ub、初始化子模块并编译
make setup

# 生成默认 compact 场景
make generate

# 运行最能暴露反向 TAACK 干扰的 8-way fan-in 用例
make run CASE=reverse-shared-fanin08

# 运行默认反向 TAACK 测试组并汇总结果
make suite
make analyze
```

输出位于：

- `work/cases/<suite>/<profile>/<case>/runlog/`：原始 trace；
- `work/cases/<suite>/<profile>/<case>/output/`：上游解析器生成的任务和端口 CSV；
- `results/current/<suite>/<profile>/`：本仓库分析脚本生成的汇总。

这些目录默认被 Git 忽略。

## 常用命令

```bash
# 单独生成/运行无背景基线
make generate SUITE=reverse-taack PROFILE=compact
make run SUITE=reverse-taack PROFILE=compact CASE=no-bg

# 运行 128→1 加背景流测试组
make suite SUITE=same-destination-background PROFILE=compact
make analyze SUITE=same-destination-background PROFILE=compact

# 运行新增的队列级实验并重绘报告图表
make suite SUITE=synchronized-incast PROFILE=queue
make suite SUITE=mice-elephant PROFILE=queue
make plot

# 开启交换机队列和 CBFC 详细 trace；磁盘占用会显著增加
make run SUITE=reverse-taack PROFILE=diagnostic CASE=reverse-shared-fanin08

# 检查场景 JSON、脚本、拓扑结构和参考结果
make verify
```

也可以直接调用脚本：

```bash
./scripts/setup.sh
python3 scripts/generate_cases.py --suite reverse-taack --profile compact
./scripts/run_case.sh reverse-taack reverse-shared-fanin08 compact
python3 scripts/analyze_results.py --suite reverse-taack --profile compact
```

## Trace profile

| Profile | 默认用途 | 主要输出 | 典型磁盘开销 |
|---|---|---|---:|
| `compact` | 日常回归 | Task、Port、过滤后的 CTP window trace | 每个大流用例约数百 MB |
| `queue` | 队列/流控分析 | compact + Queue、CBFC，Packet trace 关闭 | 每个用例约数十至数百 MB |
| `diagnostic` | 根因定位 | queue + Packet、IngressQueue | 每个大流用例约 2–3 GB |

历史队列参考数据使用 `diagnostic` 等价配置获得；公开上游 smoke 数据使用 `compact`。完整默认 suite 包含多个用例，建议至少预留 20 GB。

## 仓库结构

```text
networksim/
├── simulator.lock.json                 # 外部仿真器固定版本
├── patches/                            # 仅增强日志可观测性的上游补丁
├── scripts/
│   ├── setup.sh                        # 拉取、初始化子模块、编译
│   ├── generate_cases.py               # 生成拓扑、路由和 traffic/config
│   ├── run_case.sh                     # 运行单个用例
│   ├── run_suite.sh                    # 运行一组默认用例
│   ├── analyze_results.py              # 汇总运行结果
│   └── verify_repository.py            # 自检
├── scenarios/
│   ├── reverse-taack/scenario.json
│   └── same-destination-background/scenario.json
├── docs/
│   ├── TOPOLOGY.md
│   ├── TEST_PLAN.md
│   ├── RESULTS.md
│   └── EXPERIMENT_REPORT.md             # 新增两类流量的图表化结果报告
└── results/reference/                   # 已有参考 CSV
```

## 当前主要结论

1. 既有 128→1 全量数据表明，0/43/128/383 条同目的背景流下，前景测得带宽分别达到理论公平份额的 99.13%/99.21%/99.19%/99.17%，没有额外显著欠吞吐。
2. 在本仓库从公开上游固定提交重新验证的反向用例中，8-way fan-in 使 TAACK P99 从 `0.706 us` 增至 `267.905 us`，前景聚合有效带宽从 `396.27` 降至 `264.23 Gbps`，并明确出现 `Inflight reach limit`。
3. sender inflight 从 512 提至 1024 后，前景带宽恢复到 `332.89 Gbps`，说明有限窗口是传导环节；但仍未完全恢复，说明扩大窗口只是缓解而非消除反馈排队。
4. 将前景及其 TAACK 放在高优先级 VL1、背景保留 VL7，可把 TAACK P99 降至 `1.068 us`，前景带宽恢复到 `396.24 Gbps`、接收口恢复 `400 Gbps`。
5. 所有上述任务均完成且重传关闭。这里复现的是 lossless feedback-path queueing/HoL 和窗口饥饿，不是丢包或 OOO bitmap 溢出。
6. 64→1 同步 incast 的峰值最终出口队列达到 `15.62 MiB`；将启动摊到 1.5 ms 后，P99 FCT 和峰值队列分别降低 `98.32%` 和 `95.18%`，但 job makespan 增加 `12.33%`。
7. 共享最终口/VL 的长流使 mice P99 增至 `4.528×`；VL1 隔离可把 P99 恢复至 `1.001×`，但峰值队列增至 `20.96 MiB`，说明 QoS 保护尾延迟但不消除拥塞。

详细表格和解释见 [docs/RESULTS.md](docs/RESULTS.md)。
同步 incast 和 mice–elephant 的完整报告见 [docs/EXPERIMENT_REPORT.md](docs/EXPERIMENT_REPORT.md)。

## Benchmark 设计工作簿

[outputs/networksim-benchmark-design/networksim-benchmark-design.xlsx](outputs/networksim-benchmark-design/networksim-benchmark-design.xlsx) 是可筛选的 Excel 版 benchmark 规范，包含：

- A–F 六大类、17 个场景族和 154 个原子 Case；
- 当前仓库 21 个可直接运行的 Case，以及尚需补配置、扩展生成器或仿真器能力的设计点；
- 每个原子 Case 的唯一变量、固定参数、业务映射、生成/运行/分析命令、输出路径和验收指标；
- CTP 反向 TAACK 专项扫描、参数字典、指标口径、从零运行手册和 Smoke/Core/Extended 推荐集合。

工作簿中的绿色 Case 可以直接复制命令运行；黄色、橙色和红色 Case 是目标接口，必须先完成对应实现，不能当作当前已支持能力。

## 解释边界

该实验属于包级网络与协议行为仿真，不是 RTL、周期精确或 NIC 微架构仿真。它能够表达拓扑、路由、包序列化、交换机 VOQ/仲裁、CBFC/PFC、CTP TAACK、发送窗口和端到端任务完成；不能自动代表真实硬件中的 doorbell/WQE 调度、PCIe/DMA、片上缓存争用、firmware 时序或 PHY 误码。

上游 ns-3-UB 使用 GPL-2.0。本仓库不 vendoring 上游源码；拉取后的源码仍受其原始许可证约束。

## 上游补丁边界

[`patches/0001-networksim-observability.patch`](patches/0001-networksim-observability.patch) 只做两件事：关闭 `ub-case-runner` 强制启用的 `UbHeader` 逐包告警，以及调用 CTP 中已有的过滤式 detail logger 记录 `ta-unit-complete`/`taack-received`。它不改变包格式、路由、仲裁、流控、发送窗口或完成逻辑。`setup.sh` 每次都会先恢复固定提交、重新应用补丁并验证补丁状态。
