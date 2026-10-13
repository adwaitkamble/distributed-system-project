"""Unit tests for Phase 7.2C ContainerTelemetrySampler, parsers, and TelemetryCollector."""

import json
import os
import subprocess
import time
import pytest

from experiments.core.telemetry_collector import (
    ContainerSample,
    ContainerTelemetrySampler,
    TelemetryCollector,
    parse_byte_size,
    parse_percentage,
)


def test_parse_byte_size_units():
    """Verify parse_byte_size accurately converts various unit scales."""
    assert parse_byte_size("500B") == 500
    assert parse_byte_size("12kB") == 12000
    assert parse_byte_size("12KiB") == 12 * 1024
    assert parse_byte_size("34.1MiB") == int(34.1 * 1024 * 1024)
    assert parse_byte_size("1.5GB") == int(1.5 * 1000 * 1000 * 1000)
    assert parse_byte_size("2GiB") == 2 * 1024 * 1024 * 1024
    assert parse_byte_size("0B") == 0
    assert parse_byte_size("--") is None
    assert parse_byte_size("N/A") is None
    assert parse_byte_size(None) is None
    assert parse_byte_size("invalid") is None


def test_parse_percentage():
    """Verify parse_percentage accurately parses percentage strings."""
    assert parse_percentage("0.45%") == 0.45
    assert parse_percentage("12.3%") == 12.3
    assert parse_percentage("0.0%") == 0.0
    assert parse_percentage("100%") == 100.0
    assert parse_percentage("--") is None
    assert parse_percentage("") is None
    assert parse_percentage(None) is None


def test_container_sample_serialization():
    """Verify ContainerSample serialization and explicit declaration of unavailable metrics."""
    sample = ContainerSample(
        timestamp=1728612345.678,
        run_id="run_test_01",
        node_id=1,
        container_name="voting-node1",
        cpu_percent=1.25,
        memory_bytes=35756441,
        memory_limit_bytes=8173420544,
        memory_percent=0.44,
        net_rx_bytes=12000,
        net_tx_bytes=45000,
        status="running",
        restart_count=0,
        health_status="healthy",
    )
    d = sample.to_dict()
    assert d["run_id"] == "run_test_01"
    assert d["node_id"] == 1
    assert d["cpu_percent"] == 1.25
    assert d["memory_bytes"] == 35756441
    assert "grpc_internal_queue_depth" in d["unavailable_metrics"]
    assert "lock_wait_nanoseconds" in d["unavailable_metrics"]


def test_container_telemetry_sampler_sample_once_mocked(tmp_path, monkeypatch):
    """Verify sample_once queries docker stats and correctly parses multi-container output."""
    output_ndjson = tmp_path / "telemetry.ndjson"
    sampler = ContainerTelemetrySampler(
        node_count=2,
        run_id="run_mock_sample",
        output_path=str(output_ndjson),
        sampling_interval_sec=0.5,
    )

    mock_stats_stdout = (
        json.dumps({
            "Name": "voting-node1",
            "CPUPerc": "1.50%",
            "MemUsage": "34.1MiB / 8.00GiB",
            "MemPerc": "0.42%",
            "NetIO": "12kB / 45kB",
        })
        + "\n"
        + json.dumps({
            "Name": "voting-node2",
            "CPUPerc": "2.10%",
            "MemUsage": "36.2MiB / 8.00GiB",
            "MemPerc": "0.45%",
            "NetIO": "15kB / 50kB",
        })
    )

    def mock_run(cmd, **kwargs):
        class MockRes:
            returncode = 0
            stderr = ""
            stdout = ""

        if "stats" in cmd:
            MockRes.stdout = mock_stats_stdout
            return MockRes()
        if "inspect" in cmd:
            MockRes.stdout = '{"Status": "running", "Health": {"Status": "healthy"}}|||0'
            return MockRes()
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    samples = sampler.sample_once()
    assert len(samples) == 2
    s1, s2 = samples[0], samples[1]
    assert s1.node_id == 1
    assert s1.container_name == "voting-node1"
    assert s1.cpu_percent == 1.50
    assert s1.memory_percent == 0.42
    assert s1.status == "running"

    assert s2.node_id == 2
    assert s2.container_name == "voting-node2"
    assert s2.cpu_percent == 2.10

    # Verify streamed to NDJSON file
    sampler.stop()
    assert output_ndjson.exists()
    with open(output_ndjson, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2
    assert lines[0]["cpu_percent"] == 1.50


def test_container_telemetry_sampler_stopped_container_handling(tmp_path, monkeypatch):
    """Verify sampler gracefully queries docker inspect when a container is paused or stopped during fault injection."""
    output_ndjson = tmp_path / "telemetry_stopped.ndjson"
    sampler = ContainerTelemetrySampler(
        node_count=2,
        run_id="run_stopped_test",
        output_path=str(output_ndjson),
    )

    # docker stats returns only node 1; node 2 is paused/stopped so not in stats output
    mock_stats_stdout = json.dumps({
        "Name": "voting-node1",
        "CPUPerc": "0.80%",
        "MemUsage": "30.0MiB / 8.00GiB",
        "MemPerc": "0.37%",
        "NetIO": "10kB / 20kB",
    })

    def mock_run(cmd, **kwargs):
        class MockRes:
            returncode = 0
            stderr = ""
            stdout = ""

        if "stats" in cmd:
            MockRes.stdout = mock_stats_stdout
            return MockRes()
        if "inspect" in cmd:
            if "voting-node2" in cmd:
                MockRes.stdout = '{"Status": "paused", "Health": null}|||1'
            else:
                MockRes.stdout = '{"Status": "running", "Health": {"Status": "healthy"}}|||0'
            return MockRes()
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    samples = sampler.sample_once()
    sampler.stop()

    assert len(samples) == 2
    s1 = next(s for s in samples if s.node_id == 1)
    s2 = next(s for s in samples if s.node_id == 2)

    assert s1.status == "running"
    assert s1.cpu_percent == 0.80

    # Node 2 was omitted from docker stats, but inspect recorded it as paused
    assert s2.status == "paused"
    assert s2.cpu_percent is None
    assert s2.restart_count == 1


def test_container_telemetry_sampler_aggregate_summary(tmp_path, monkeypatch):
    """Verify get_summary computes accurate container aggregates across collected samples."""
    sampler = ContainerTelemetrySampler(node_count=1, run_id="run_agg")

    s1 = ContainerSample(
        timestamp=100.0,
        run_id="run_agg",
        node_id=1,
        container_name="voting-node1",
        cpu_percent=2.0,
        memory_bytes=40000000,
        memory_limit_bytes=80000000,
        memory_percent=0.5,
        net_rx_bytes=1000,
        net_tx_bytes=2000,
        status="running",
        restart_count=0,
    )
    s2 = ContainerSample(
        timestamp=101.0,
        run_id="run_agg",
        node_id=1,
        container_name="voting-node1",
        cpu_percent=4.0,
        memory_bytes=60000000,
        memory_limit_bytes=80000000,
        memory_percent=0.75,
        net_rx_bytes=2500,
        net_tx_bytes=4000,
        status="running",
        restart_count=1,
    )

    sampler._samples = [s1, s2]
    summary = sampler.get_summary()

    assert summary["total_samples"] == 2
    c1 = summary["containers"]["1"]
    assert c1["sample_count"] == 2
    assert c1["cpu_mean_pct"] == 3.0
    assert c1["cpu_max_pct"] == 4.0
    assert c1["mem_mean_bytes"] == 50000000
    assert c1["mem_max_bytes"] == 60000000
    assert c1["net_rx_peak_bytes"] == 2500
    assert c1["net_tx_peak_bytes"] == 4000
    assert c1["total_restarts"] == 1
    assert "grpc_internal_queue_depth" in summary["unavailable_metrics"]


def test_telemetry_collector_background_sampling_lifecycle(tmp_path, monkeypatch):
    """Verify TelemetryCollector starts and stops background sampler cleanly."""
    collector = TelemetryCollector(1)
    output_file = tmp_path / "collector_bg.ndjson"

    def mock_sample_once():
        return []

    sampler = collector.start_background_sampling(
        run_id="bg_run_01",
        output_path=str(output_file),
        interval_sec=0.2,
    )
    assert sampler is not None
    assert sampler._thread.is_alive()

    time.sleep(0.3)
    summary = collector.stop_background_sampling()
    assert summary is not None
    assert "containers" in summary
    assert not sampler._thread.is_alive()
