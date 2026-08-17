#!/usr/bin/env python3
"""Generate reproducible ns-3-UB cases without external Python dependencies."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from collections import Counter, defaultdict, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_COUNT = 512
L1_BASE = 512
L1_COUNT = 32
L2_BASE = 544
L2_COUNT = 16
TOTAL_NODE_COUNT = 560
EXPECTED_LINKS = 2560
EXPECTED_ROUTE_ROWS = 1_144_832
TRAFFIC_COLUMNS = (
    "taskId",
    "sourceNodeId",
    "destNodeId",
    "dataSize(Byte)",
    "opType",
    "priority",
    "delay",
    "phaseId",
    "dependOnPhases",
    "srcEntityId",
    "dstEntityId",
)


def scenario_path(suite: str) -> Path:
    return ROOT / "scenarios" / suite / "scenario.json"


def load_scenario(suite: str) -> dict:
    path = scenario_path(suite)
    if not path.is_file():
        raise SystemExit(f"Unknown suite or missing scenario: {suite} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def build_links() -> list[tuple[int, int, int, int, str, str]]:
    links = []
    for host_id in range(HOST_COUNT):
        group_id = host_id // 64
        l1_down_port = host_id % 64
        for host_port in range(4):
            l1_id = L1_BASE + group_id * 4 + host_port
            links.append((host_id, host_port, l1_id, l1_down_port, "400Gbps", "100ns"))
    for l1_index in range(L1_COUNT):
        l1_id = L1_BASE + l1_index
        for l2_index in range(L2_COUNT):
            l2_id = L2_BASE + l2_index
            links.append((l1_id, 64 + l2_index, l2_id, l1_index, "400Gbps", "250ns"))
    return links


def validate_links(links: list[tuple[int, int, int, int, str, str]]) -> None:
    endpoint_uses = Counter()
    degree = Counter()
    for node1, port1, node2, port2, _bandwidth, _delay in links:
        endpoint_uses[(node1, port1)] += 1
        endpoint_uses[(node2, port2)] += 1
        degree[node1] += 1
        degree[node2] += 1
    duplicates = {endpoint: count for endpoint, count in endpoint_uses.items() if count != 1}
    if duplicates:
        raise RuntimeError(f"Topology contains reused endpoint ports: {duplicates}")
    if len(links) != EXPECTED_LINKS:
        raise RuntimeError(f"Expected {EXPECTED_LINKS} links, got {len(links)}")
    if any(degree[node] != 4 for node in range(HOST_COUNT)):
        raise RuntimeError("Every host must have degree 4")
    if any(degree[node] != 80 for node in range(L1_BASE, L1_BASE + L1_COUNT)):
        raise RuntimeError("Every L1 switch must have degree 80")
    if any(degree[node] != 32 for node in range(L2_BASE, L2_BASE + L2_COUNT)):
        raise RuntimeError("Every L2 switch must have degree 32")


def effective_outgoing_links(links):
    outgoing = {}
    for row_index, (node1, port1, node2, port2, _bandwidth, _delay) in enumerate(links):
        outgoing[(node1, port1)] = (node2, port2, row_index)
        outgoing[(node2, port2)] = (node1, port1, row_index)
    return outgoing


def distances_to_destination_port(destination: int, destination_port: int, outgoing: dict):
    reverse = defaultdict(list)
    for (node, local_port), (peer, peer_port, _row_index) in outgoing.items():
        reverse[peer].append((node, local_port, peer_port))
    distance = {}
    pending = deque()
    for predecessor, _local_port, peer_port in reverse[destination]:
        if peer_port == destination_port and predecessor != destination:
            distance[predecessor] = 1
            pending.append(predecessor)
    while pending:
        node = pending.popleft()
        for predecessor, _local_port, _peer_port in reverse[node]:
            if predecessor == destination or predecessor in distance:
                continue
            distance[predecessor] = distance[node] + 1
            pending.append(predecessor)
    return distance


def write_topology_assets(topology_dir: Path) -> int:
    topology_dir.mkdir(parents=True, exist_ok=True)
    links = build_links()
    validate_links(links)

    node_path = topology_dir / "node.csv"
    topology_path = topology_dir / "topology.csv"
    routing_path = topology_dir / "routing_table.csv"

    with node_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("nodeId", "nodeType", "portNum", "forwardDelay"))
        writer.writerow(("0..511", "DEVICE", 4, "1ns"))
        writer.writerow(("512..543", "SWITCH", 80, "1ns"))
        writer.writerow(("544..559", "SWITCH", 32, "1ns"))

    with topology_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("nodeId1", "portId1", "nodeId2", "portId2", "bandwidth", "delay"))
        writer.writerows(links)

    outgoing = effective_outgoing_links(links)
    by_node = defaultdict(list)
    destination_ports = defaultdict(set)
    for (node, local_port), (peer, peer_port, row_index) in outgoing.items():
        by_node[node].append((local_port, peer, peer_port, row_index))
        if node < HOST_COUNT:
            destination_ports[node].add(local_port)

    row_count = 0
    with routing_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("nodeId", "dstNodeId", "dstPortId", "outPorts", "metrics"))
        for destination in range(HOST_COUNT):
            for destination_port in sorted(destination_ports[destination]):
                distance = distances_to_destination_port(destination, destination_port, outgoing)
                for node in sorted(distance):
                    metric = distance[node]
                    candidates = []
                    for local_port, peer, peer_port, _row_index in by_node[node]:
                        if metric == 1:
                            usable = peer == destination and peer_port == destination_port
                        else:
                            usable = distance.get(peer) == metric - 1
                        if usable:
                            candidates.append(local_port)
                    candidates = sorted(set(candidates))
                    if not candidates:
                        raise RuntimeError(
                            f"No next hop from node {node} to {destination}:{destination_port}"
                        )
                    writer.writerow(
                        (
                            node,
                            destination,
                            destination_port,
                            " ".join(map(str, candidates)),
                            " ".join([str(metric)] * len(candidates)),
                        )
                    )
                    row_count += 1

    if row_count != EXPECTED_ROUTE_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROUTE_ROWS} route rows, got {row_count}")

    (topology_dir / "generation-summary.json").write_text(
        json.dumps(
            {
                "topology": "clos512-4x400g",
                "nodes": TOTAL_NODE_COUNT,
                "hosts": HOST_COUNT,
                "l1_switches": L1_COUNT,
                "l2_switches": L2_COUNT,
                "links": len(links),
                "route_rows": row_count,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return row_count


def ensure_topology(output_root: Path) -> Path:
    topology_dir = output_root / "_topologies" / "clos512-4x400g"
    summary_path = topology_dir / "generation-summary.json"
    required = (topology_dir / "node.csv", topology_dir / "topology.csv", topology_dir / "routing_table.csv")
    if summary_path.is_file() and all(path.is_file() for path in required):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("links") == EXPECTED_LINKS and summary.get("route_rows") == EXPECTED_ROUTE_ROWS:
            return topology_dir
    write_topology_assets(topology_dir)
    return topology_dir


def hardlink_or_copy(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def write_network_attributes(case_dir: Path, inflight_max: int, profile: str, window_trace: bool) -> None:
    diagnostic = profile == "diagnostic"
    queue_observability = profile in ("queue", "diagnostic")
    attributes = [
        ('default ns3::TpConnectionManager::RemoveUselessTp', 'false'),
        ('default ns3::UbApp::CtpUseUnboundSourceJetty', 'false'),
        ('default ns3::UbApp::TransportMode', 'CTP'),
        ('default ns3::UbApp::UsePacketSpray', 'true'),
        ('default ns3::UbApp::UseShortestPaths', 'true'),
        ('default ns3::UbCtpTransportService::BoundOutPortCount', '4'),
        ('default ns3::UbCtpTransportService::DelayTaAckTime', '+0ns'),
        ('default ns3::UbCtpTransportService::ExperimentTaAckPacketBytes', '0'),
        ('default ns3::UbCtpTransportService::WindowTraceDstNode', '128'),
        ('default ns3::UbCtpTransportService::WindowTraceEnabled', str(window_trace).lower()),
        ('default ns3::UbCtpTransportService::WindowTraceSrcNode', '0'),
        ('default ns3::UbJetty::JettyOooAckThreshold', '2048'),
        ('default ns3::UbJetty::UbJettyInflightMax', str(inflight_max)),
        ('default ns3::UbRoutingProcess::RoutingAlgorithm', 'HASH'),
        ('default ns3::UbSwitch::FlowControl', 'CBFC'),
        ('default ns3::UbSwitch::VlScheduler', 'SP'),
        ('default ns3::UbSwitchAllocator::AllocationTime', '+10ns'),
        ('default ns3::UbTransportChannel::EnableRetrans', 'false'),
        ('global UB_CC_ENABLED', 'false'),
        ('global UB_CONGESTION_CONTROL_TRACE_ENABLE', 'false'),
        ('global UB_FLOW_CONTROL_TRACE_ENABLE', str(queue_observability).lower()),
        ('global UB_PACKET_TRACE_ENABLE', str(diagnostic).lower()),
        ('global UB_PARSE_TRACE_ENABLE', 'true'),
        ('global UB_PORT_TRACE_ENABLE', 'true'),
        ('global UB_PYTHON_SCRIPT_PATH', 'scratch/ns-3-ub-tools/trace_analysis/parse_trace.py'),
        ('global UB_QUEUE_TRACE_ENABLE', str(queue_observability).lower()),
        ('global UB_RECORD_PKT_TRACE', 'false'),
        ('global UB_TASK_TRACE_ENABLE', 'true'),
        ('global UB_TRACE_ENABLE', 'true'),
    ]
    text = "\n".join(f'{key} "{value}"' for key, value in attributes) + "\n"
    (case_dir / "network_attribute.txt").write_text(text, encoding="utf-8")


def traffic_row(task_id: int, source: int, destination: int, size: int, operation: str,
                priority: int, start: str) -> tuple:
    return (
        task_id,
        source,
        destination,
        size,
        operation,
        priority,
        start,
        0,
        "",
        "",
        "",
    )


def build_reverse_traffic(scenario: dict, case: dict) -> list[tuple]:
    foreground = scenario["foreground"]
    foreground_priority = case.get("foreground_priority", foreground["priority"])
    rows = []
    for task_id, source in enumerate(foreground["sources"]):
        rows.append(
            traffic_row(
                task_id,
                source,
                foreground["destination"],
                foreground["bytes_per_flow"],
                foreground["operation"],
                foreground_priority,
                foreground["start"],
            )
        )
    background = case.get("background")
    if background is None:
        return rows
    for offset in range(background["source_count"]):
        source = background["source_start"] + offset
        target = background["targets"][offset % len(background["targets"])]
        rows.append(
            traffic_row(
                len(foreground["sources"]) + offset,
                source,
                target,
                background["bytes_per_flow"],
                "URMA_WRITE",
                background["priority"],
                background["start"],
            )
        )
    return rows


def build_same_destination_traffic(scenario: dict, case: dict) -> list[tuple]:
    foreground = scenario["foreground"]
    background = scenario["background"]
    rows = []
    for offset in range(foreground["source_count"]):
        source = foreground["source_start"] + offset
        rows.append(
            traffic_row(
                offset,
                source,
                foreground["destination"],
                foreground["bytes_per_flow"],
                foreground["operation"],
                foreground["priority"],
                foreground["start"],
            )
        )
    for offset in range(case["background_count"]):
        source = background["source_start"] + offset
        rows.append(
            traffic_row(
                foreground["source_count"] + offset,
                source,
                background["destination"],
                background["bytes_per_flow"],
                background["operation"],
                background["priority"],
                background["start"],
            )
        )
    return rows


def build_synchronized_incast_traffic(scenario: dict, case: dict) -> list[tuple]:
    foreground = scenario["foreground"]
    count = int(foreground["source_count"])
    spread_us = float(case["start_spread_us"])
    rows = []
    for offset in range(count):
        fraction = offset / (count - 1) if count > 1 else 0
        start_us = float(foreground["base_start_us"]) + spread_us * fraction
        rows.append(
            traffic_row(
                offset,
                foreground["source_start"] + offset,
                foreground["destination"],
                foreground["bytes_per_flow"],
                foreground["operation"],
                foreground["priority"],
                f"{start_us:.6f}us",
            )
        )
    return rows


def build_mice_elephant_traffic(scenario: dict, case: dict) -> list[tuple]:
    mice = scenario["mice"]
    elephants = scenario["elephants"]
    mice_priority = int(case.get("mice_priority", mice["priority"]))
    rows = []
    for offset in range(mice["source_count"]):
        rows.append(
            traffic_row(
                offset,
                mice["source_start"] + offset,
                mice["destination"],
                mice["bytes_per_flow"],
                mice["operation"],
                mice_priority,
                mice["start"],
            )
        )
    destination = case.get("elephant_destination")
    if destination is None:
        return rows
    for offset in range(elephants["source_count"]):
        rows.append(
            traffic_row(
                mice["source_count"] + offset,
                elephants["source_start"] + offset,
                destination,
                elephants["bytes_per_flow"],
                elephants["operation"],
                elephants["priority"],
                elephants["start"],
            )
        )
    return rows


def validate_traffic(rows: list[tuple]) -> None:
    task_ids = [int(row[0]) for row in rows]
    if len(task_ids) != len(set(task_ids)):
        raise RuntimeError("traffic.csv contains duplicate task IDs")
    for row in rows:
        source = int(row[1])
        destination = int(row[2])
        priority = int(row[5])
        if not 0 <= source < HOST_COUNT or not 0 <= destination < HOST_COUNT:
            raise RuntimeError(f"Invalid host in traffic row: {row}")
        if source == destination:
            raise RuntimeError(f"Self-traffic is not allowed: {row}")
        if not 1 <= priority <= 15:
            raise RuntimeError(f"Data priority must be 1..15: {row}")


def write_case(output_root: Path, suite: str, profile: str, scenario: dict, case: dict,
               topology_dir: Path) -> Path:
    case_dir = output_root / suite / profile / case["name"]
    case_dir.mkdir(parents=True, exist_ok=True)
    for name in ("node.csv", "topology.csv", "routing_table.csv"):
        hardlink_or_copy(topology_dir / name, case_dir / name)

    if suite == "reverse-taack":
        rows = build_reverse_traffic(scenario, case)
        window_trace = True
    elif suite == "same-destination-background":
        rows = build_same_destination_traffic(scenario, case)
        window_trace = False
    elif suite == "synchronized-incast":
        rows = build_synchronized_incast_traffic(scenario, case)
        window_trace = False
    elif suite == "mice-elephant":
        rows = build_mice_elephant_traffic(scenario, case)
        window_trace = False
    else:
        raise RuntimeError(f"Unsupported suite: {suite}")
    validate_traffic(rows)

    with (case_dir / "traffic.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(TRAFFIC_COLUMNS)
        writer.writerows(rows)

    inflight_max = int(case.get("inflight_max", 512))
    write_network_attributes(case_dir, inflight_max, profile, window_trace)
    (case_dir / "generation-summary.json").write_text(
        json.dumps(
            {
                "suite": suite,
                "case": case["name"],
                "profile": profile,
                "tasks": len(rows),
                "inflight_max": inflight_max,
                "topology": scenario["topology"],
                "topology_links": EXPECTED_LINKS,
                "routing_rows": EXPECTED_ROUTE_ROWS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return case_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=(
            "reverse-taack",
            "same-destination-background",
            "synchronized-incast",
            "mice-elephant",
        ),
        default="reverse-taack",
    )
    parser.add_argument(
        "--profile", choices=("compact", "queue", "diagnostic"), default="compact"
    )
    parser.add_argument("--case", help="Generate only one named case")
    parser.add_argument("--output", type=Path, default=ROOT / "work" / "cases")
    parser.add_argument("--list", action="store_true", help="List case names and exit")
    parser.add_argument("--default-only", action="store_true", help="With --list, omit optional cases")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = load_scenario(args.suite)
    cases = scenario["cases"]
    if args.list:
        for case in cases:
            if args.default_only and not case.get("default", True):
                continue
            print(case["name"])
        return

    if args.case:
        cases = [case for case in cases if case["name"] == args.case]
        if not cases:
            raise SystemExit(f"Unknown case {args.case!r} in suite {args.suite!r}")

    output_root = args.output.resolve()
    topology_dir = ensure_topology(output_root)
    for case in cases:
        case_dir = write_case(output_root, args.suite, args.profile, scenario, case, topology_dir)
        print(f"generated {case_dir}")


if __name__ == "__main__":
    main()
