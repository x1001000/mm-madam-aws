"""
Test provisioned concurrency effectiveness on AWS Lambda.

Sends concurrent /health requests at various levels to verify:
  1. Up to N (provisioned) concurrent requests → zero cold starts
  2. Beyond N concurrent requests → cold starts appear

Usage:
  python provisioned_concurrency_test.py --base-url URL --provisioned 10
  python provisioned_concurrency_test.py --base-url URL --provisioned 10 --beyond 15
"""
import argparse
import asyncio
import time
import statistics
import httpx


COLD_START_THRESHOLD_MS = 500


async def fire_simultaneous(client: httpx.AsyncClient, url: str, n: int, timeout: float):
    """Fire exactly N requests at the same instant."""
    barrier = asyncio.Barrier(n)

    async def one_request(req_id):
        await barrier.wait()
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


def print_results(n: int, label: str, results: list):
    latencies = sorted([lat for _, _, lat in results])
    warm = sum(1 for lat in latencies if lat <= COLD_START_THRESHOLD_MS)
    cold = sum(1 for lat in latencies if lat > COLD_START_THRESHOLD_MS)
    mn = min(latencies)
    mx = max(latencies)
    avg = statistics.mean(latencies)

    status = "✅ 全部暖機" if cold == 0 else f"🧊 冷啟動 x{cold}"
    print(f"  [{label}] N={n:2d}  Min={mn:7.1f}ms  Max={mx:7.1f}ms  Mean={avg:7.1f}ms  暖={warm} 冷={cold}  {status}")
    return warm, cold


async def run_test(base_url: str, provisioned: int, beyond: int, rounds: int, pause: float, timeout: float):
    health_url = base_url.rstrip("/") + "/health"

    print(f"\n{'='*70}")
    print(f"Provisioned Concurrency 測試")
    print(f"端點        : {health_url}")
    print(f"預置併發數  : {provisioned}")
    print(f"測試輪數    : {rounds}")
    print(f"冷啟動閾值  : >{COLD_START_THRESHOLD_MS}ms")
    print(f"{'='*70}")

    async with httpx.AsyncClient() as client:
        # Phase 1: 驗證預置併發範圍內無冷啟動
        print(f"\n📋 階段一：驗證 N=1..{provisioned} 無冷啟動")
        print("-" * 70)

        phase1_cold_total = 0
        for n in [1, provisioned // 2, provisioned]:
            if n < 1:
                continue
            for r in range(rounds):
                results = await fire_simultaneous(client, health_url, n, timeout)
                _, cold = print_results(n, f"第{r+1}輪", results)
                phase1_cold_total += cold
                await asyncio.sleep(pause)

        if phase1_cold_total == 0:
            print(f"\n  ✅ 階段一通過：預置併發 {provisioned} 以內，全部零冷啟動")
        else:
            print(f"\n  ⚠️  階段一異常：預置併發範圍內出現 {phase1_cold_total} 次冷啟動")
            print(f"      可能原因：預置併發尚未完全分配（需等待 1-2 分鐘）")

        # Phase 2: 測試超出預置併發的行為
        print(f"\n📋 階段二：測試超出預置併發 N={provisioned+1}..{beyond}")
        print("-" * 70)

        phase2_cold_total = 0
        for n in range(provisioned + 1, beyond + 1):
            for r in range(rounds):
                results = await fire_simultaneous(client, health_url, n, timeout)
                _, cold = print_results(n, f"第{r+1}輪", results)
                phase2_cold_total += cold
                await asyncio.sleep(pause)

        if phase2_cold_total > 0:
            print(f"\n  🧊 階段二結果：超出預置併發後出現 {phase2_cold_total} 次冷啟動（預期行為）")
        else:
            print(f"\n  ℹ️  階段二結果：尚未觀測到冷啟動（可能先前實例仍暖機中）")

        # Phase 3: 持續監測（等待暖機實例回收後再測）
        print(f"\n📋 階段三：持續監測（每 60 秒發送 {provisioned} 個並行請求）")
        print(f"    目的：確認預置併發的實例不會被回收")
        print(f"    按 Ctrl+C 停止")
        print("-" * 70)

        cycle = 0
        try:
            while True:
                await asyncio.sleep(60)
                cycle += 1
                results = await fire_simultaneous(client, health_url, provisioned, timeout)
                print_results(provisioned, f"#{cycle:3d} ({cycle}分鐘)", results)
        except KeyboardInterrupt:
            print(f"\n\n已停止監測（共 {cycle} 個週期）")

    print(f"\n{'='*70}")
    print("結論")
    print(f"{'='*70}")
    if phase1_cold_total == 0:
        print(f"  ✅ Provisioned Concurrency = {provisioned} 有效消除冷啟動")
        if phase2_cold_total > 0:
            print(f"  🧊 超出 {provisioned} 併發時仍會冷啟動（需增加預置數或搭配 reserved）")
    else:
        print(f"  ⚠️  預置併發可能尚未就緒，請確認 Lambda 控制台狀態為 Ready")
    print()


def main():
    parser = argparse.ArgumentParser(description="測試 Lambda Provisioned Concurrency 效果")
    parser.add_argument("--base-url", required=True, help="Base URL")
    parser.add_argument("--provisioned", "-n", type=int, default=10, help="預置併發數（default: 10）")
    parser.add_argument("--beyond", "-b", type=int, default=15, help="測試超出預置併發的上限（default: 15）")
    parser.add_argument("--rounds", "-r", type=int, default=2, help="每個等級的測試輪數（default: 2）")
    parser.add_argument("--pause", "-p", type=float, default=3, help="輪次之間暫停秒數（default: 3）")
    parser.add_argument("--timeout", "-t", type=float, default=60, help="請求逾時秒數（default: 60）")
    args = parser.parse_args()

    asyncio.run(run_test(args.base_url, args.provisioned, args.beyond, args.rounds, args.pause, args.timeout))


if __name__ == "__main__":
    main()
