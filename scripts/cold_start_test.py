"""
Cold start detection for AWS Lambda.
Finds how many simultaneous requests trigger new instance provisioning.

Strategy:
  1. Warm up with a single /health request
  2. Fire N simultaneous /health requests
  3. Warm instances respond in ~X ms, cold starts take significantly longer
  4. Ramp N from 1..max to find the threshold

Usage:
  python cold_start_test.py --base-url URL [--max-concurrency N] [--rounds R] [--pause P]
"""
import argparse
import asyncio
import time
import statistics
import httpx


COLD_START_THRESHOLD_MS = 500  # responses slower than this are likely cold starts


async def fire_simultaneous(client: httpx.AsyncClient, url: str, n: int, timeout: float):
    """Fire exactly N requests at the same instant. Returns list of (req_id, status, latency_ms)."""
    barrier = asyncio.Barrier(n)

    async def one_request(req_id):
        await barrier.wait()  # all coroutines release at the same instant
        start = time.perf_counter()
        try:
            resp = await client.get(url, timeout=timeout)
            latency = (time.perf_counter() - start) * 1000
            return (req_id, resp.status_code, latency)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return (req_id, 0, latency)

    tasks = [one_request(i) for i in range(n)]
    return await asyncio.gather(*tasks)


async def run_cold_start_test(base_url: str, max_concurrency: int, rounds: int, pause: float, timeout: float):
    health_url = base_url.rstrip("/") + "/health"

    print(f"\n{'='*70}")
    print(f"Cold Start Detection Test")
    print(f"Endpoint : {health_url}")
    print(f"Ramp     : 1 → {max_concurrency} simultaneous requests")
    print(f"Rounds   : {rounds} per level  |  Pause: {pause}s between levels")
    print(f"Cold start threshold: >{COLD_START_THRESHOLD_MS}ms")
    print(f"{'='*70}\n")

    async with httpx.AsyncClient() as client:
        # Step 1: warm up
        print("Warming up (1 request)...")
        resp = await client.get(health_url, timeout=timeout)
        print(f"  Warm-up: HTTP {resp.status_code}\n")
        await asyncio.sleep(1)

        # Step 2: ramp up concurrency
        print(f"{'N':>4s}  {'Round':>5s}  {'Min':>8s}  {'Max':>8s}  {'Mean':>8s}  {'Median':>8s}  {'Warm':>5s}  {'Cold':>5s}  {'Latencies'}")
        print("-" * 100)

        for n in range(1, max_concurrency + 1):
            for r in range(rounds):
                results = await fire_simultaneous(client, health_url, n, timeout)
                latencies = sorted([lat for _, _, lat in results])
                warm = sum(1 for lat in latencies if lat <= COLD_START_THRESHOLD_MS)
                cold = sum(1 for lat in latencies if lat > COLD_START_THRESHOLD_MS)

                lat_str = "  ".join(f"{lat:7.1f}" for lat in latencies)
                mn = min(latencies)
                mx = max(latencies)
                avg = statistics.mean(latencies)
                med = statistics.median(latencies)

                cold_marker = "  <<<" if cold > 0 else ""
                print(f"{n:4d}  {r+1:5d}  {mn:7.1f}  {mx:7.1f}  {avg:7.1f}  {med:7.1f}  {warm:5d}  {cold:5d}  [{lat_str}]{cold_marker}")

            if n < max_concurrency:
                await asyncio.sleep(pause)

    print(f"\n{'='*70}")
    print("How to read results:")
    print(f"  - 'Warm' = responses <= {COLD_START_THRESHOLD_MS}ms (reused instance)")
    print(f"  - 'Cold' = responses > {COLD_START_THRESHOLD_MS}ms (new instance / cold start)")
    print("  - When 'Cold' first appears, that N exceeds your warm instance count")
    print("  - The number of 'Warm' responses at that level = your warm instance count")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Cold start detection for Lambda")
    parser.add_argument("--base-url", required=True, help="Base URL (e.g. https://xxx.lambda-url.region.on.aws)")
    parser.add_argument("--max-concurrency", "-m", type=int, default=15, help="Max simultaneous requests to ramp to (default: 15)")
    parser.add_argument("--rounds", "-r", type=int, default=2, help="Rounds per concurrency level (default: 2)")
    parser.add_argument("--pause", "-p", type=float, default=3, help="Pause between concurrency levels in seconds (default: 3)")
    parser.add_argument("--timeout", "-t", type=float, default=30, help="Request timeout in seconds (default: 30)")
    args = parser.parse_args()

    asyncio.run(run_cold_start_test(args.base_url, args.max_concurrency, args.rounds, args.pause, args.timeout))


if __name__ == "__main__":
    main()
