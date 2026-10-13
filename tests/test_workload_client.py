"""Comprehensive unit tests for Phase 7.2A WorkloadClient, request recording, percentiles, error handling, run traceability, collision protection, and NDJSON outputs."""

import json
import socket
import urllib.error
import pytest

from experiments.core.workload_client import (
    BenchmarkRunSummary,
    RequestResult,
    WorkloadClient,
)


def test_request_result_schema_and_ndjson():
    """Verify RequestResult converts to dictionary and NDJSON conforming to the raw-data schema including run_id."""
    result = RequestResult(
        run_id="run_test_01",
        req_id=42,
        client_id="client_run1_000042",
        choice="Alice",
        status_code=201,
        latency_ms=18.452,
        success=True,
        vote_id="client_run1_000042:1:100",
        lamport_ts=100,
        start_time=1700000000.1234,
        end_time=1700000000.1418,
        error=None,
        is_warmup=False,
    )

    d = result.to_dict()
    assert d["run_id"] == "run_test_01"
    assert d["req_id"] == 42
    assert d["client_id"] == "client_run1_000042"
    assert d["choice"] == "Alice"
    assert d["status_code"] == 201
    assert d["latency_ms"] == 18.452
    assert d["success"] is True
    assert d["vote_id"] == "client_run1_000042:1:100"
    assert d["lamport_ts"] == 100
    assert d["start_time"] == 1700000000.1234
    assert d["end_time"] == 1700000000.1418
    assert d["error"] is None
    assert d["is_warmup"] is False

    ndjson_line = result.to_ndjson()
    parsed = json.loads(ndjson_line)
    assert parsed == d


def test_client_id_generation_rules():
    """Ensure generated client IDs have no colons, are distinct, and adhere to duplicate-vote rules."""
    cid_measured = WorkloadClient.generate_client_id(
        prefix="bench:voter",  # Should sanitize colons
        run_id="run99",
        seq_idx=5,
        is_warmup=False,
    )
    assert ":" not in cid_measured
    assert cid_measured == "bench_voter_run99_000005"

    cid_warmup = WorkloadClient.generate_client_id(
        prefix="bench",
        run_id="run99",
        seq_idx=5,
        is_warmup=True,
    )
    assert ":" not in cid_warmup
    assert cid_warmup == "warmup_bench_run99_000005"
    assert cid_measured != cid_warmup

    # Long run_id and prefix must never exceed MySQL VARCHAR(64) column limit
    long_run = "preflight_02_3n_bully_majority_t1_20261011_060813_de883b"
    cid_long = WorkloadClient.generate_client_id("post_crash", long_run, 1, is_warmup=False)
    assert len(cid_long) <= 64
    assert ":" not in cid_long
    assert "post_crash" in cid_long

    cid_long_warmup = WorkloadClient.generate_client_id("post_crash", long_run, 1, is_warmup=True)
    assert len(cid_long_warmup) <= 64
    assert ":" not in cid_long_warmup
    assert cid_long != cid_long_warmup


def test_percentile_math_linear_interpolation():
    """Verify linear-interpolation percentile math for edge cases and distributions."""
    assert WorkloadClient._percentile([], 50) == 0.0
    assert WorkloadClient._percentile([42.0], 50) == 42.0
    assert WorkloadClient._percentile([42.0], 99) == 42.0

    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert WorkloadClient._percentile(data, 0) == 10.0
    assert WorkloadClient._percentile(data, 50) == 55.0
    assert WorkloadClient._percentile(data, 90) == 91.0
    assert WorkloadClient._percentile(data, 95) == 95.5
    assert WorkloadClient._percentile(data, 99) == 99.1
    assert WorkloadClient._percentile(data, 100) == 100.0


def test_submit_single_vote_success(monkeypatch):
    """Mock successful HTTP 201 response and verify latency and vote ID capture."""
    client = WorkloadClient(base_url="http://localhost:5001")

    class MockResponse:
        status = 201
        def read(self):
            return json.dumps({
                "success": True,
                "vote_id": "voter_01:1:15",
                "client_id": "voter_01",
                "choice": "Alice",
                "lamport_ts": 15,
                "node_id": 1,
            }).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: MockResponse())

    res = client.submit_single_vote(
        client_id="voter_01", choice="Alice", req_id=1, is_warmup=False, run_id="r1"
    )

    assert res.run_id == "r1"
    assert res.success is True
    assert res.status_code == 201
    assert res.vote_id == "voter_01:1:15"
    assert res.lamport_ts == 15
    assert res.error is None
    assert res.latency_ms >= 0.0
    assert res.start_time > 0
    assert res.end_time >= res.start_time
    assert res.is_warmup is False


def test_submit_single_vote_http_409_duplicate(monkeypatch):
    """Mock HTTP 409 conflict and verify failure and structured error capture."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_urlopen(req, timeout):
        fp = type("MockFp", (), {
            "read": lambda self: json.dumps({
                "success": False,
                "error": "duplicate_client",
                "message": "client 'voter_01' has already voted",
            }).encode("utf-8")
        })()
        raise urllib.error.HTTPError(
            url="http://localhost:5001/api/votes",
            code=409,
            msg="Conflict",
            hdrs={},
            fp=fp,
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.submit_single_vote(client_id="voter_01", choice="Alice", req_id=2, run_id="r2")

    assert res.run_id == "r2"
    assert res.success is False
    assert res.status_code == 409
    assert "HTTP 409" in res.error
    assert "already voted" in res.error
    assert res.vote_id is None


def test_submit_single_vote_http_503_replication_failed(monkeypatch):
    """Mock HTTP 503 replication failure and verify failure status."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_urlopen(req, timeout):
        fp = type("MockFp", (), {
            "read": lambda self: json.dumps({
                "success": False,
                "error": "replication_failed",
                "message": "replication failed (quorum not reached)",
                "vote_id": "voter_02:2:20",
            }).encode("utf-8")
        })()
        raise urllib.error.HTTPError(
            url="http://localhost:5001/api/votes",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=fp,
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.submit_single_vote(client_id="voter_02", choice="Bob", req_id=3)

    assert res.success is False
    assert res.status_code == 503
    assert "HTTP 503" in res.error
    assert "quorum not reached" in res.error


def test_submit_single_vote_malformed_json_response(monkeypatch):
    """Verify handling when backend returns non-JSON or HTML error page on 201."""
    client = WorkloadClient(base_url="http://localhost:5001")

    class MockBadResponse:
        status = 201
        def read(self):
            return b"<html><body>Internal Gateway HTML</body></html>"
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: MockBadResponse())

    res = client.submit_single_vote(client_id="voter_03", choice="Charlie", req_id=4)

    assert res.success is False
    assert res.status_code == 201
    assert "Malformed JSON" in res.error


def test_submit_single_vote_timeout_detection(monkeypatch):
    """Verify socket timeout exception is handled as status 0 with clean timeout error message."""
    client = WorkloadClient(base_url="http://localhost:5001", timeout_sec=2.5)

    def mock_urlopen(req, timeout):
        raise socket.timeout("Operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.submit_single_vote(client_id="voter_04", choice="Alice", req_id=5)

    assert res.success is False
    assert res.status_code == 0
    assert "Timeout after 2.5s" in res.error


def test_submit_single_vote_network_error(monkeypatch):
    """Verify connection refused is caught as status 0 with network error message."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_urlopen(req, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.submit_single_vote(client_id="voter_05", choice="Bob", req_id=6)

    assert res.success is False
    assert res.status_code == 0
    assert "Network error" in res.error


def test_warmup_separated_from_measured(tmp_path, monkeypatch):
    """Verify warmup requests are kept completely separate from measured benchmark metrics."""
    client = WorkloadClient(base_url="http://localhost:5001")

    call_history = []

    def mock_submit(client_id, choice, *args, **kwargs):
        call_history.append((client_id, choice))
        latency = 10.0 if "warmup" in client_id else 25.0
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=latency,
            success=True,
            vote_id=f"vote_{client_id}",
            lamport_ts=10,
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    trace_file = tmp_path / "results" / "warmup_test.ndjson"
    summary = client.run_workload(
        request_count=5,
        concurrency=2,
        warmup_count=3,
        client_prefix="test_run",
        raw_ndjson_path=str(trace_file),
        include_warmup_in_ndjson=True,
    )

    # 3 warmup + 5 measured = 8 total requests executed
    assert len(call_history) == 8
    assert summary.warmup_requests == 3
    assert summary.measured_requests == 5
    assert summary.attempted_requests == 5
    assert summary.successful_requests == 5
    assert summary.total_requests == 8

    # Verify warmup and measured lists
    assert len(summary.warmup_results) == 3
    assert len(summary.results) == 5
    assert all(r.is_warmup for r in summary.warmup_results)
    assert all(not r.is_warmup for r in summary.results)

    # Metric stats should only include measured (latency = 25.0, NOT 10.0)
    assert summary.p50_ms == 25.0
    assert summary.min_ms == 25.0
    assert summary.max_ms == 25.0
    assert summary.mean_ms == 25.0

    # Verify NDJSON output written with run_id
    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 8
    warmup_lines = [l for l in lines if l["is_warmup"]]
    measured_lines = [l for l in lines if not l["is_warmup"]]
    assert len(warmup_lines) == 3
    assert len(measured_lines) == 5
    assert all(l["run_id"] == summary.run_id for l in lines)


def test_run_traceability_across_repeated_runs(tmp_path, monkeypatch):
    """Verify that multiple consecutive runs generate distinct run_ids and client identities."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_submit(client_id, choice, *args, **kwargs):
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=12.0,
            success=True,
            vote_id=f"vote_{client_id}",
            lamport_ts=1,
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    file1 = tmp_path / "run1.ndjson"
    file2 = tmp_path / "run2.ndjson"

    summary1 = client.run_workload(request_count=3, raw_ndjson_path=str(file1))
    summary2 = client.run_workload(request_count=3, raw_ndjson_path=str(file2))

    assert summary1.run_id != summary2.run_id
    assert summary1.results[0].client_id != summary2.results[0].client_id

    # Check run_id in traces
    with open(file1, "r", encoding="utf-8") as f:
        records1 = [json.loads(line) for line in f]
    with open(file2, "r", encoding="utf-8") as f:
        records2 = [json.loads(line) for line in f]

    assert all(r["run_id"] == summary1.run_id for r in records1)
    assert all(r["run_id"] == summary2.run_id for r in records2)


def test_output_file_collision_protection(tmp_path, monkeypatch):
    """Verify FileExistsError is raised when output file already exists unless overwrite=True."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_submit(client_id, choice, *args, **kwargs):
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=10.0,
            success=True,
            vote_id="v1",
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    existing_file = tmp_path / "protected_run.ndjson"
    existing_file.write_text("existing content\n", encoding="utf-8")

    # Attempting to run with overwrite=False (default) should raise FileExistsError
    with pytest.raises(FileExistsError, match="already exists"):
        client.run_workload(request_count=2, raw_ndjson_path=str(existing_file), overwrite=False)

    # With overwrite=True, it succeeds
    summary = client.run_workload(request_count=2, raw_ndjson_path=str(existing_file), overwrite=True)
    assert summary.attempted_requests == 2


def test_concurrent_output_integrity_and_accounting(tmp_path, monkeypatch):
    """Verify concurrent workers produce exact accounting and ordered NDJSON without corruption."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_submit(client_id, choice, req_id=0, *args, **kwargs):
        # Emulate varied statuses: 201, 409, 503, timeout (0)
        idx = int(client_id.split("_")[-1])
        if idx % 4 == 0:
            return RequestResult(client_id=client_id, choice=choice, status_code=201, latency_ms=15.0, success=True, vote_id=f"v_{idx}")
        elif idx % 4 == 1:
            return RequestResult(client_id=client_id, choice=choice, status_code=409, latency_ms=10.0, success=False, error="duplicate")
        elif idx % 4 == 2:
            return RequestResult(client_id=client_id, choice=choice, status_code=503, latency_ms=30.0, success=False, error="quorum failed")
        else:
            return RequestResult(client_id=client_id, choice=choice, status_code=0, latency_ms=50.0, success=False, error="timeout")

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    ndjson_path = tmp_path / "concurrent_trace.ndjson"
    summary = client.run_workload(
        request_count=20,
        concurrency=4,
        warmup_count=0,
        raw_ndjson_path=str(ndjson_path),
    )

    # Total attempted = 20
    assert summary.attempted_requests == 20
    # Modulo counts: 5 of each type
    assert summary.successful_requests == 5
    assert summary.rejected_requests == 10  # 409 + 503
    assert summary.failed_requests == 5     # status 0
    assert summary.attempted_requests == (summary.successful_requests + summary.rejected_requests + summary.failed_requests)

    # Throughput checks
    assert summary.duration_sec > 0
    assert summary.overall_throughput_ops_sec >= summary.throughput_ops_sec

    # NDJSON line integrity: exactly 20 lines, streamed incrementally upon request completion
    with open(ndjson_path, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 20
    seen_req_ids = {rec["req_id"] for rec in lines}
    assert seen_req_ids == set(range(20))
    for rec in lines:
        assert rec["run_id"] == summary.run_id
        assert "client_id" in rec
        assert "status_code" in rec

    # In-memory summary results are sorted deterministically by req_id
    assert [r.req_id for r in summary.results] == list(range(20))


def test_summary_to_dict_and_save_json(tmp_path, monkeypatch):
    """Verify machine-readable summary schema, throughput calculations, and save_summary_json."""
    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_submit(client_id, choice, *args, **kwargs):
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=20.0,
            success=True,
            vote_id=f"vote_{client_id}",
            lamport_ts=10,
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    summary_file = tmp_path / "summary.json"
    summary = client.run_workload(request_count=4, concurrency=1, warmup_count=0)
    summary.save_summary_json(str(summary_file))

    with open(summary_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["run_id"] == summary.run_id
    assert data["target_endpoint"] == "http://localhost:5001"
    assert data["concurrency"] == 1
    assert data["attempted_requests"] == 4
    assert data["successful_requests"] == 4
    assert data["rejected_requests"] == 0
    assert data["failed_requests"] == 0
    assert "successful_throughput_ops_sec" in data
    assert "overall_throughput_ops_sec" in data
    assert data["latency_stats_ms"]["p50"] == 20.0
    assert data["latency_stats_ms"]["p99"] == 20.0
    assert data["latency_stats_ms"]["stddev"] == 0.0  # All identical latencies -> stddev 0.0

    # Overwrite protection on summary JSON
    with pytest.raises(FileExistsError):
        summary.save_summary_json(str(summary_file), overwrite=False)


def test_internal_type_error_does_not_trigger_retry(monkeypatch):
    """Regression test: verify internal TypeError inside submit_single_vote is not caught as argument mismatch and does not trigger duplicate submission retry."""
    client = WorkloadClient(base_url="http://localhost:5001")
    submission_count = 0

    def buggy_submit(*args, **kwargs):
        nonlocal submission_count
        submission_count += 1
        raise TypeError("simulated internal TypeError inside vote submission handler")

    monkeypatch.setattr(client, "submit_single_vote", buggy_submit)

    summary = client.run_workload(request_count=1, concurrency=1, warmup_count=0)

    # Must have attempted exactly 1 submission, never retried
    assert submission_count == 1
    assert summary.attempted_requests == 1
    assert summary.failed_requests == 1
    assert summary.successful_requests == 0
    assert "simulated internal TypeError" in summary.results[0].error


def test_thread_safe_writer_concurrent_integrity(tmp_path):
    """Verify ThreadSafeNDJSONWriter handles concurrent multi-threaded writes without corrupting lines or interleaving."""
    from concurrent.futures import ThreadPoolExecutor
    from experiments.core.workload_client import ThreadSafeNDJSONWriter

    trace_file = tmp_path / "concurrent_writer_test.ndjson"
    writer = ThreadSafeNDJSONWriter(str(trace_file), overwrite=True)

    threads_count = 10
    records_per_thread = 50

    def worker_write(thread_id: int):
        for seq in range(records_per_thread):
            rec = RequestResult(
                run_id="stress_run",
                req_id=thread_id * 1000 + seq,
                client_id=f"thread_{thread_id}_client_{seq}",
                choice="Alice",
                status_code=201,
                latency_ms=5.0,
                success=True,
                vote_id=f"vote_{thread_id}_{seq}",
            )
            writer.write_record(rec)

    with ThreadPoolExecutor(max_workers=threads_count) as executor:
        futs = [executor.submit(worker_write, tid) for tid in range(threads_count)]
        for f in futs:
            f.result()

    writer.close()

    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Must have exactly 500 lines
    assert len(raw_lines) == threads_count * records_per_thread

    # Every line must be valid, uncorrupted JSON
    parsed_records = [json.loads(line) for line in raw_lines]
    assert len(parsed_records) == 500

    # Ensure all distinct request IDs are accounted for
    seen_req_ids = {r["req_id"] for r in parsed_records}
    assert len(seen_req_ids) == 500


def test_streaming_ndjson_partial_run_behavior(tmp_path, monkeypatch):
    """Verify results are flushed to disk as requests complete, preserving partial-run traces if run aborts."""
    client = WorkloadClient(base_url="http://localhost:5001")
    trace_file = tmp_path / "partial_run.ndjson"

    completed_requests = 0

    def mock_submit_abort_on_third(client_id, choice, req_id=0, *args, **kwargs):
        nonlocal completed_requests
        if req_id >= 2:
            raise KeyboardInterrupt("Simulated user abort / SIGINT midway through benchmark")
        completed_requests += 1
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=10.0,
            success=True,
            vote_id=f"v_{req_id}",
            req_id=req_id,
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit_abort_on_third)

    # Execution should abort with KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        client.run_workload(
            request_count=5,
            concurrency=1,
            warmup_count=0,
            raw_ndjson_path=str(trace_file),
            overwrite=True,
        )

    # Even though execution aborted, the 2 requests that completed must be intact and flushed on disk
    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 2
    assert lines[0]["req_id"] == 0
    assert lines[0]["success"] is True
    assert lines[1]["req_id"] == 1
    assert lines[1]["success"] is True

