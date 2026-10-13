"""High-precision concurrent benchmark client for submitting votes and recording latency percentiles."""

from concurrent import futures
from dataclasses import asdict, dataclass, field
import hashlib
import inspect
import json
import logging
import math
import os
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from experiments.config.benchmark_config import (
    DEFAULT_CANDIDATES,
    DEFAULT_CONCURRENCY,
    DEFAULT_REQUEST_TIMEOUT_SEC,
    DEFAULT_WARMUP_REQUESTS,
)

logger = logging.getLogger("experiments.workload_client")


@dataclass
class RequestResult:
    """Represents the observation and outcome of a single vote submission request."""

    client_id: str
    choice: str
    status_code: int
    latency_ms: float
    success: bool
    vote_id: Optional[str] = None
    error: Optional[str] = None
    lamport_ts: Optional[int] = None
    req_id: int = 0
    run_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    is_warmup: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert request record to dictionary conforming to the raw NDJSON schema."""
        return {
            "run_id": self.run_id,
            "req_id": self.req_id,
            "client_id": self.client_id,
            "choice": self.choice,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "latency_ms": self.latency_ms,
            "status_code": self.status_code,
            "success": self.success,
            "vote_id": self.vote_id,
            "lamport_ts": self.lamport_ts,
            "error": self.error,
            "is_warmup": self.is_warmup,
        }

    def to_ndjson(self) -> str:
        """Serialize record to single-line JSON string."""
        return json.dumps(self.to_dict())


# Type alias for clarity and semantic consistency
RequestRecord = RequestResult


class ThreadSafeNDJSONWriter:
    """Thread-safe, streaming NDJSON file writer for raw benchmark trace records.

    Persists raw request results to disk immediately as each request completes,
    avoiding holding all records in memory before writing and ensuring partial-run
    traces are preserved on disk.

    Concurrency & Atomicity:
    - Thread-safe serialization and file output guarded by an internal threading.Lock.
    - Serializes complete line with trailing newline prior to writing to prevent partial lines.
    - Flushes to operating system page cache immediately upon each record write.

    Crash Safety Guarantees & Limits:
    - User-space vs OS Kernel: Calling `file.flush()` pushes user-space buffered data
      to the operating system kernel page cache. If the Python process crashes, aborts,
      encounters an unhandled exception, or exits abruptly, the OS kernel retains the data
      and persists it to disk. Partial runs preserve all completed requests.
    - Hardware / Power-Loss Limits: This writer deliberately does NOT invoke `os.fsync()`
      or Windows `FlushFileBuffers()` on every request. Hardware disk flushes introduce
      1-15ms of storage I/O latency per record, which would bottleneck the thread pool
      and severely distort network latency benchmark measurements. Therefore, in the event
      of sudden operating system kernel panic, hardware crash, or host power failure, dirty
      pages in the OS page cache not yet flushed to non-volatile storage media may be lost.
    """

    def __init__(self, filepath: str, overwrite: bool = False):
        self.filepath = os.path.abspath(filepath)
        if os.path.exists(self.filepath) and not overwrite:
            raise FileExistsError(
                f"Output trace file already exists at '{self.filepath}'. "
                f"Specify overwrite=True or choose a unique path."
            )
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self._file = open(self.filepath, "w", encoding="utf-8")
        self._lock = threading.Lock()
        self._closed = False

    def write_record(self, record: Any) -> None:
        """Atomically serialize and write a single record as NDJSON, flushing to OS buffer."""
        if hasattr(record, "to_ndjson"):
            line = record.to_ndjson() + "\n"
        elif isinstance(record, dict):
            line = json.dumps(record) + "\n"
        else:
            line = str(record).rstrip("\n") + "\n"

        with self._lock:
            if not self._closed:
                self._file.write(line)
                self._file.flush()

    def close(self) -> None:
        """Flush and close the underlying file."""
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._file.flush()
                finally:
                    self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


@dataclass
class BenchmarkRunSummary:
    """Aggregated machine-readable summary of a workload benchmark execution.

    Semantic definitions:
    - attempted_requests: Total measured requests submitted (excludes warm-up).
    - successful_requests: Measured requests returning HTTP 201 with non-null vote_id.
    - rejected_requests: Measured requests receiving domain rejection (HTTP 400, 404, 409, 503).
    - failed_requests: Measured requests failing due to transport, timeouts, or unexpected errors.
    - throughput_ops_sec: Successful-completion throughput (successful_requests / duration_sec).
    - overall_throughput_ops_sec: Gross attempted request throughput (attempted_requests / duration_sec).
    - latency percentiles (p50, p90, p95, p99): Computed strictly over successful measured requests.
    """

    run_id: str = ""
    target_endpoint: str = ""
    concurrency: int = 1
    warmup_requests: int = 0
    measured_requests: int = 0
    total_requests: int = 0
    attempted_requests: int = 0
    successful_requests: int = 0
    rejected_requests: int = 0
    failed_requests: int = 0
    duration_sec: float = 0.0
    throughput_ops_sec: float = 0.0
    overall_throughput_ops_sec: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    mean_ms: float = 0.0
    stddev_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    raw_trace_path: Optional[str] = None
    results: List[RequestResult] = field(default_factory=list)
    warmup_results: List[RequestResult] = field(default_factory=list)

    def to_dict(self, include_records: bool = False) -> Dict[str, Any]:
        """Generate machine-readable summary dictionary."""
        summary = {
            "run_id": self.run_id,
            "target_endpoint": self.target_endpoint,
            "concurrency": self.concurrency,
            "warmup_requests": self.warmup_requests,
            "measured_requests": self.measured_requests,
            "total_requests": self.total_requests,
            "attempted_requests": self.attempted_requests,
            "successful_requests": self.successful_requests,
            "rejected_requests": self.rejected_requests,
            "failed_requests": self.failed_requests,
            "duration_sec": self.duration_sec,
            "successful_throughput_ops_sec": self.throughput_ops_sec,
            "overall_throughput_ops_sec": self.overall_throughput_ops_sec,
            "throughput_ops_sec": self.throughput_ops_sec,  # alias for backwards compatibility
            "latency_stats_ms": {
                "p50": self.p50_ms,
                "p90": self.p90_ms,
                "p95": self.p95_ms,
                "p99": self.p99_ms,
                "mean": self.mean_ms,
                "stddev": self.stddev_ms,
                "min": self.min_ms,
                "max": self.max_ms,
            },
            "raw_trace_path": self.raw_trace_path,
        }
        if include_records:
            summary["measured_records"] = [r.to_dict() for r in self.results]
            summary["warmup_records"] = [r.to_dict() for r in self.warmup_results]
        return summary

    def save_summary_json(self, path: str, overwrite: bool = False) -> None:
        """Write machine-readable summary to a JSON file."""
        target_path = os.path.abspath(path)
        if os.path.exists(target_path) and not overwrite:
            raise FileExistsError(
                f"Summary file already exists at '{target_path}'. Specify overwrite=True to replace."
            )
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(include_records=False), f, indent=2)


# Type alias for clarity
BenchmarkSummary = BenchmarkRunSummary


class WorkloadClient:
    """Submits client votes to a coordinator node and measures latency and throughput."""

    def __init__(
        self,
        base_url: str,
        timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
        candidates: Optional[List[str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.candidates = candidates or DEFAULT_CANDIDATES

    @staticmethod
    def make_run_id() -> str:
        """Generate a collision-safe run identifier incorporating timestamp and random hex."""
        return f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def generate_client_id(prefix: str, run_id: str, seq_idx: int, is_warmup: bool = False) -> str:
        """Generate a valid, colon-free, globally unique client identity.

        Application duplicate-vote rules mandate:
        - Non-empty stripped string.
        - Must NOT contain ':' (colons are reserved delimiters for vote_id receipts).
        - Must be unique per voter to avoid HTTP 409 duplicate_client rejection.
        - Must not exceed 64 characters to strictly adhere to the MySQL VARCHAR(64) schema constraint.
        """
        clean_prefix = prefix.replace(":", "_").strip() or "client"
        phase_tag = "warmup_" if is_warmup else ""
        candidate = f"{phase_tag}{clean_prefix}_{run_id}_{seq_idx:06d}"
        if len(candidate) <= 64:
            return candidate

        # If candidate exceeds MySQL column constraint VARCHAR(64), compact deterministically:
        # Preserve phase differentiation, compact prefix, truncated run_id with hash digest, and exact seq_idx.
        short_phase = "w_" if is_warmup else ""
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8]
        seq_str = f"_{seq_idx:06d}"
        pfx_clean = clean_prefix[:10].rstrip("_")
        avail_for_run = 64 - len(short_phase) - len(pfx_clean) - 1 - len(digest) - 1 - len(seq_str)
        short_run = run_id[:max(avail_for_run, 8)]
        compacted = f"{short_phase}{pfx_clean}_{short_run}_{digest}{seq_str}"
        if len(compacted) > 64:
            compacted = f"{short_phase}{pfx_clean[:6]}_{digest}{seq_str}"
        return compacted[:64]

    @staticmethod
    def _inspect_signature_supports_rich_args(func: Any) -> bool:
        """Inspect whether func accepts extended arguments (req_id, is_warmup, run_id).

        Performs static signature inspection upfront instead of catching TypeError at runtime,
        preventing internal method TypeErrors from triggering accidental retry duplications.
        """
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
                return True
            param_names = {p.name for p in params}
            if "req_id" in param_names:
                return True
            positional_count = sum(
                1
                for p in params
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            )
            return positional_count >= 5
        except (ValueError, TypeError):
            return True

    def submit_single_vote(
        self,
        client_id: str,
        choice: str,
        req_id: int = 0,
        is_warmup: bool = False,
        run_id: str = "",
    ) -> RequestResult:
        """Submit a single vote synchronously and measure exact latency with sub-millisecond precision.

        Uses time.perf_counter() for relative elapsed time measurement and
        time.time() for wall-clock start/end timestamps.
        """
        url = f"{self.base_url}/api/votes"
        payload = json.dumps({"client_id": client_id, "choice": choice}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        t_start_perf = time.perf_counter()
        t_start_wall = time.time()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                t_end_perf = time.perf_counter()
                t_end_wall = time.time()
                latency_ms = (t_end_perf - t_start_perf) * 1000.0

                raw_body = resp.read().decode("utf-8")
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    return RequestResult(
                        req_id=req_id,
                        run_id=run_id,
                        client_id=client_id,
                        choice=choice,
                        status_code=resp.status,
                        start_time=round(t_start_wall, 4),
                        end_time=round(t_end_wall, 4),
                        latency_ms=round(latency_ms, 3),
                        success=False,
                        error=f"Malformed JSON response: {exc}",
                        is_warmup=is_warmup,
                    )

                vote_id = body.get("vote_id") if isinstance(body, dict) else None
                lamport_ts = body.get("lamport_ts") if isinstance(body, dict) else None
                is_success = (resp.status == 201 and bool(vote_id))
                err_msg = None if is_success else "Missing vote_id in 201 response"

                return RequestResult(
                    req_id=req_id,
                    run_id=run_id,
                    client_id=client_id,
                    choice=choice,
                    status_code=resp.status,
                    start_time=round(t_start_wall, 4),
                    end_time=round(t_end_wall, 4),
                    latency_ms=round(latency_ms, 3),
                    success=is_success,
                    vote_id=vote_id,
                    lamport_ts=lamport_ts,
                    error=err_msg,
                    is_warmup=is_warmup,
                )

        except urllib.error.HTTPError as exc:
            t_end_perf = time.perf_counter()
            t_end_wall = time.time()
            latency_ms = (t_end_perf - t_start_perf) * 1000.0
            err_body = None
            try:
                raw_err = exc.read().decode("utf-8")
                err_body = json.loads(raw_err)
            except Exception:
                err_body = None

            if isinstance(err_body, dict):
                err_msg = err_body.get("message") or err_body.get("error") or str(err_body)
            else:
                err_msg = str(exc.reason)

            return RequestResult(
                req_id=req_id,
                run_id=run_id,
                client_id=client_id,
                choice=choice,
                status_code=exc.code,
                start_time=round(t_start_wall, 4),
                end_time=round(t_end_wall, 4),
                latency_ms=round(latency_ms, 3),
                success=False,
                error=f"HTTP {exc.code}: {err_msg}",
                is_warmup=is_warmup,
            )

        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            t_end_perf = time.perf_counter()
            t_end_wall = time.time()
            latency_ms = (t_end_perf - t_start_perf) * 1000.0
            is_timeout = (
                isinstance(exc, (TimeoutError, socket.timeout))
                or "timed out" in str(exc).lower()
                or (hasattr(exc, "reason") and isinstance(exc.reason, socket.timeout))
            )
            err_desc = f"Timeout after {self.timeout_sec}s: {exc}" if is_timeout else f"Network error: {exc}"

            return RequestResult(
                req_id=req_id,
                run_id=run_id,
                client_id=client_id,
                choice=choice,
                status_code=0,
                start_time=round(t_start_wall, 4),
                end_time=round(t_end_wall, 4),
                latency_ms=round(latency_ms, 3),
                success=False,
                error=err_desc,
                is_warmup=is_warmup,
            )

        except Exception as exc:
            t_end_perf = time.perf_counter()
            t_end_wall = time.time()
            latency_ms = (t_end_perf - t_start_perf) * 1000.0
            return RequestResult(
                req_id=req_id,
                run_id=run_id,
                client_id=client_id,
                choice=choice,
                status_code=0,
                start_time=round(t_start_wall, 4),
                end_time=round(t_end_wall, 4),
                latency_ms=round(latency_ms, 3),
                success=False,
                error=f"Unexpected error: {exc}",
                is_warmup=is_warmup,
            )

    def run_workload(
        self,
        request_count: int,
        concurrency: int = DEFAULT_CONCURRENCY,
        warmup_count: int = 0,
        client_prefix: str = "bench",
        raw_ndjson_path: Optional[str] = None,
        run_id: Optional[str] = None,
        include_warmup_in_ndjson: bool = True,
        overwrite: bool = False,
    ) -> BenchmarkRunSummary:
        """Execute warm-up phase followed by concurrent measurement phase.

        Streaming Persistence & Traceability:
        - Writes records incrementally as each request completes via ThreadSafeNDJSONWriter.
        - Flushes immediately so partial-run observations are preserved on disk.
        - Run identifier is assigned to every request record for cross-run traceability.
        - If raw_ndjson_path exists and overwrite=False, raises FileExistsError upfront.
        """
        assigned_run_id = run_id or self.make_run_id()

        # Initialize streaming NDJSON writer if requested (performs collision check upfront)
        writer: Optional[ThreadSafeNDJSONWriter] = None
        if raw_ndjson_path:
            writer = ThreadSafeNDJSONWriter(raw_ndjson_path, overwrite=overwrite)

        accepts_rich_args = self._inspect_signature_supports_rich_args(self.submit_single_vote)

        def _invoke_submit(cid: str, choice: str, req_idx: int, is_warm: bool) -> RequestResult:
            if accepts_rich_args:
                res = self.submit_single_vote(
                    cid, choice, req_id=req_idx, is_warmup=is_warm, run_id=assigned_run_id
                )
            else:
                res = self.submit_single_vote(cid, choice)

            if isinstance(res, RequestResult):
                res.req_id = req_idx
                res.run_id = assigned_run_id
                res.is_warmup = is_warm

            return res

        warmup_results: List[RequestResult] = []
        measured_results: List[RequestResult] = []

        try:
            # ── 1. Warm-up Phase ──────────────────────────────────────────
            if warmup_count > 0:
                logger.info("Executing %d warm-up requests (discarded from metrics)...", warmup_count)
                warmup_tasks = []
                for i in range(warmup_count):
                    cid = self.generate_client_id(client_prefix, assigned_run_id, i, is_warmup=True)
                    choice = self.candidates[i % len(self.candidates)]
                    warmup_tasks.append((i, cid, choice))

                for req_idx, cid, choice in warmup_tasks:
                    try:
                        res = _invoke_submit(cid, choice, req_idx, True)
                    except Exception as exc:
                        t_now = time.time()
                        res = RequestResult(
                            req_id=req_idx,
                            run_id=assigned_run_id,
                            client_id=cid,
                            choice=choice,
                            status_code=0,
                            start_time=round(t_now, 4),
                            end_time=round(t_now, 4),
                            latency_ms=0.0,
                            success=False,
                            error=f"Warmup exception: {exc}",
                            is_warmup=True,
                        )
                    warmup_results.append(res)
                    if writer is not None and include_warmup_in_ndjson:
                        writer.write_record(res)

            # ── 2. Measured Benchmark Phase ───────────────────────────────
            logger.info(
                "Executing measurement benchmark: %d requests (concurrency=%d, endpoint=%s)...",
                request_count,
                concurrency,
                self.base_url,
            )
            measured_tasks = []
            for i in range(request_count):
                cid = self.generate_client_id(client_prefix, assigned_run_id, i, is_warmup=False)
                choice = self.candidates[i % len(self.candidates)]
                measured_tasks.append((i, cid, choice))

            bench_start = time.perf_counter()

            def _worker(idx: int, cid: str, choice: str) -> RequestResult:
                try:
                    res = _invoke_submit(cid, choice, idx, False)
                except Exception as exc:
                    t_now = time.time()
                    res = RequestResult(
                        req_id=idx,
                        run_id=assigned_run_id,
                        client_id=cid,
                        choice=choice,
                        status_code=0,
                        start_time=round(t_now, 4),
                        end_time=round(t_now, 4),
                        latency_ms=0.0,
                        success=False,
                        error=f"Worker exception: {exc}",
                        is_warmup=False,
                    )

                # Persist raw trace record immediately upon request completion
                if writer is not None:
                    writer.write_record(res)

                return res

            with futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
                fut_map = {
                    executor.submit(_worker, idx, cid, choice): (idx, cid, choice)
                    for idx, cid, choice in measured_tasks
                }
                for fut in futures.as_completed(fut_map):
                    try:
                        res = fut.result()
                        measured_results.append(res)
                    except Exception as exc:
                        idx, cid, choice = fut_map[fut]
                        t_now = time.time()
                        res = RequestResult(
                            req_id=idx,
                            run_id=assigned_run_id,
                            client_id=cid,
                            choice=choice,
                            status_code=0,
                            start_time=round(t_now, 4),
                            end_time=round(t_now, 4),
                            latency_ms=0.0,
                            success=False,
                            error=f"Worker future exception: {exc}",
                            is_warmup=False,
                        )
                        measured_results.append(res)
                        if writer is not None:
                            writer.write_record(res)

            bench_end = time.perf_counter()
            total_duration = bench_end - bench_start

        finally:
            if writer is not None:
                writer.close()

        # Sort in-memory measured results sequentially by request index for deterministic reporting
        measured_results.sort(key=lambda r: r.req_id)

        if raw_ndjson_path:
            logger.info("Preserved raw per-request NDJSON trace in %s", os.path.abspath(raw_ndjson_path))

        # ── 4. Aggregate Measured Statistics ──────────────────────────
        attempted_count = len(measured_results)
        latencies = [r.latency_ms for r in measured_results if r.success]
        successful_count = len(latencies)
        rejected_count = sum(1 for r in measured_results if r.status_code in (400, 404, 409, 503))
        failed_count = sum(
            1 for r in measured_results if not r.success and r.status_code not in (400, 404, 409, 503)
        )

        summary = BenchmarkRunSummary(
            run_id=assigned_run_id,
            target_endpoint=self.base_url,
            concurrency=concurrency,
            warmup_requests=len(warmup_results),
            measured_requests=attempted_count,
            total_requests=len(warmup_results) + attempted_count,
            attempted_requests=attempted_count,
            successful_requests=successful_count,
            rejected_requests=rejected_count,
            failed_requests=failed_count,
            duration_sec=round(total_duration, 4),
            raw_trace_path=raw_ndjson_path,
            results=measured_results,
            warmup_results=warmup_results,
        )

        if total_duration > 0:
            summary.throughput_ops_sec = round(successful_count / total_duration, 2)
            summary.overall_throughput_ops_sec = round(attempted_count / total_duration, 2)

        summary.latencies_ms = latencies
        if latencies:
            latencies.sort()
            summary.min_ms = round(latencies[0], 2)
            summary.max_ms = round(latencies[-1], 2)
            summary.mean_ms = round(statistics.mean(latencies), 2)
            summary.stddev_ms = round(statistics.stdev(latencies) if len(latencies) > 1 else 0.0, 2)
            summary.p50_ms = round(self._percentile(latencies, 50), 2)
            summary.p90_ms = round(self._percentile(latencies, 90), 2)
            summary.p95_ms = round(self._percentile(latencies, 95), 2)
            summary.p99_ms = round(self._percentile(latencies, 99), 2)

        logger.info(
            "Workload completed: %d/%d committed, throughput=%.2f ops/sec, p50=%.2fms, p95=%.2fms, p99=%.2fms",
            summary.successful_requests,
            summary.attempted_requests,
            summary.throughput_ops_sec,
            summary.p50_ms,
            summary.p95_ms,
            summary.p99_ms,
        )
        return summary

    def run_benchmark(
        self,
        request_count: int,
        concurrency: int = DEFAULT_CONCURRENCY,
        warmup_count: int = 0,
        client_prefix: str = "bench",
        raw_trace_path: Optional[str] = None,
        run_id: Optional[str] = None,
        overwrite: bool = True,  # Backwards-compatible default for runners
    ) -> BenchmarkRunSummary:
        """Backwards-compatible alias for run_workload."""
        return self.run_workload(
            request_count=request_count,
            concurrency=concurrency,
            warmup_count=warmup_count,
            client_prefix=client_prefix,
            raw_ndjson_path=raw_trace_path,
            run_id=run_id,
            overwrite=overwrite,
        )

    @staticmethod
    def _percentile(sorted_data: List[float], percent: float) -> float:
        """Calculate percentile using linear interpolation."""
        if not sorted_data:
            return 0.0
        if len(sorted_data) == 1:
            return sorted_data[0]
        k = (len(sorted_data) - 1) * (percent / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Submit benchmark voting workload and capture raw NDJSON metrics")
    parser.add_argument("--target", type=str, default="http://localhost:5001", help="Coordinator REST endpoint URL")
    parser.add_argument("--requests", type=int, default=10, help="Number of measured requests to submit")
    parser.add_argument("--concurrency", type=int, default=2, help="Number of concurrent worker threads")
    parser.add_argument("--warmup", type=int, default=2, help="Number of warmup requests (discarded from metrics)")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP request timeout in seconds")
    parser.add_argument("--prefix", type=str, default="bench", help="Client ID prefix")
    parser.add_argument(
        "--output",
        type=str,
        default="experiments/results/raw/workload_test.ndjson",
        help="Path to write per-request raw NDJSON observations",
    )
    parser.add_argument(
        "--summary-output",
        type=str,
        default="",
        help="Path to write machine-readable summary JSON",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files if they exist",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

    client = WorkloadClient(base_url=args.target, timeout_sec=args.timeout)
    summary = client.run_workload(
        request_count=args.requests,
        concurrency=args.concurrency,
        warmup_count=args.warmup,
        client_prefix=args.prefix,
        raw_ndjson_path=args.output,
        overwrite=args.overwrite,
    )

    if args.summary_output:
        summary.save_summary_json(args.summary_output, overwrite=args.overwrite)
        print(f"Summary JSON saved to: {args.summary_output}")

    print("\n" + "=" * 60)
    print("WORKLOAD BENCHMARK EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Run ID:             {summary.run_id}")
    print(f"Target Endpoint:    {summary.target_endpoint}")
    print(f"Concurrency:        {summary.concurrency}")
    print(f"Warm-up Requests:   {summary.warmup_requests}")
    print(f"Measured Requests:  {summary.attempted_requests}")
    print(f"Successful Commits: {summary.successful_requests}")
    print(f"Rejected Requests:  {summary.rejected_requests}")
    print(f"Failed / Network:   {summary.failed_requests}")
    print(f"Duration:           {summary.duration_sec:.3f} s")
    print(f"Success Throughput: {summary.throughput_ops_sec:.2f} votes/s")
    print(f"Overall Throughput: {summary.overall_throughput_ops_sec:.2f} req/s")
    print(f"Latency p50:        {summary.p50_ms:.2f} ms")
    print(f"Latency p90:        {summary.p90_ms:.2f} ms")
    print(f"Latency p95:        {summary.p95_ms:.2f} ms")
    print(f"Latency p99:        {summary.p99_ms:.2f} ms")
    print(f"Mean (Stddev):      {summary.mean_ms:.2f} ms (+/- {summary.stddev_ms:.2f} ms)")
    print(f"Min / Max:          {summary.min_ms:.2f} ms / {summary.max_ms:.2f} ms")
    print(f"Raw NDJSON Output:  {summary.raw_trace_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
