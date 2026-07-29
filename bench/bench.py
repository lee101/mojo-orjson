from __future__ import annotations

import os
import platform
import statistics
import subprocess
import sys
import time

import orjson

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

import mojo_orjson  # noqa: E402


def elapsed(function, repeat=5):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def cpu_name():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def main():
    records = [
        {
            "id": index,
            "name": f"record-{index}",
            "enabled": index % 3 == 0,
            "value": index * 0.125,
            "tags": ["json", "mojo", "benchmark"],
        }
        for index in range(100_000)
    ]
    records_json = orjson.dumps(records)
    numbers_json = orjson.dumps([index * 0.125 for index in range(500_000)])
    ascii_value = "abcdefghijklmnopqrstuvwxyz0123456789" * 250_000

    cases = [
        ("dumps 100k records", lambda: mojo_orjson.dumps(records), lambda: orjson.dumps(records)),
        ("dumps 9 MB ASCII string", lambda: mojo_orjson.dumps(ascii_value), lambda: orjson.dumps(ascii_value)),
        ("loads 100k records", lambda: mojo_orjson.loads(records_json), lambda: orjson.loads(records_json)),
        ("loads 500k numbers", lambda: mojo_orjson.loads(numbers_json), lambda: orjson.loads(numbers_json)),
    ]

    mojo_version = subprocess.run(
        ["mojo", "--version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]
    print(
        f"Machine: {cpu_name()}; Python {platform.python_version()}; "
        f"{mojo_version}; orjson {orjson.__version__}"
    )
    print()
    print("| Case | mojo-orjson | orjson | Relative |")
    print("|---|---:|---:|---:|")
    for name, ours, upstream in cases:
        ours_value = ours()
        upstream_value = upstream()
        assert ours_value == upstream_value
        ours_time = elapsed(ours)
        upstream_time = elapsed(upstream)
        ratio = upstream_time / ours_time
        label = "faster" if ratio >= 1 else "slower"
        print(
            f"| {name} | {ours_time * 1000:.2f} ms | {upstream_time * 1000:.2f} ms "
            f"| {ratio:.2f}x ({label}) |"
        )


if __name__ == "__main__":
    main()
