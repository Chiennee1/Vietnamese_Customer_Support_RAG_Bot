"""Run a small authenticated chat latency smoke test against a live deployment."""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import httpx


@dataclass(frozen=True, slots=True)
class LoadReport:
    requests: int
    concurrency: int
    successful: int
    failed: int
    success_rate: float
    p50_ms: int
    p95_ms: int
    maximum_ms: int


def percentile(values: list[int], level: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, round(level * len(ordered) + 0.499) - 1))
    return ordered[index]


async def run(
    *,
    base_url: str,
    email: str,
    password: str,
    requests: int,
    concurrency: int,
) -> LoadReport:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        login.raise_for_status()
        token = str(login.json()["access_token"])
        headers = {"Authorization": f"Bearer {token}"}
        semaphore = asyncio.Semaphore(concurrency)
        conversation_ids: list[str] = []

        async def one(index: int) -> tuple[int, int]:
            async with semaphore:
                started = perf_counter()
                response = await client.post(
                    "/api/v1/chat",
                    headers={
                        **headers,
                        "X-Request-ID": f"load-smoke-{index:04d}",
                    },
                    json={"message": "Xin chào"},
                )
                latency_ms = max(0, round((perf_counter() - started) * 1000))
                if response.status_code == 200:
                    conversation_ids.append(str(response.json()["conversation_id"]))
                return response.status_code, latency_ms

        results = await asyncio.gather(*(one(index) for index in range(requests)))
        for conversation_id in conversation_ids:
            await client.delete(
                f"/api/v1/conversations/{conversation_id}",
                headers=headers,
            )

    successful_latencies = [
        latency for status, latency in results if 200 <= status < 300
    ]
    successful = len(successful_latencies)
    return LoadReport(
        requests=requests,
        concurrency=concurrency,
        successful=successful,
        failed=requests - successful,
        success_rate=successful / requests if requests else 0.0,
        p50_ms=percentile(successful_latencies, 0.50),
        p95_ms=percentile(successful_latencies, 0.95),
        maximum_ms=max(successful_latencies, default=0),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="customer0006@example.test")
    parser.add_argument("--password", default="Demo-customer-2026")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.requests < 1 or arguments.concurrency < 1:
        raise SystemExit("requests and concurrency must be positive")
    report = asyncio.run(
        run(
            base_url=arguments.base_url,
            email=arguments.email,
            password=arguments.password,
            requests=arguments.requests,
            concurrency=arguments.concurrency,
        )
    )
    rendered = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    print(rendered)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    if report.success_rate < 1.0 or report.p95_ms >= 6000:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
