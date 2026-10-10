#!/usr/bin/env python3
"""Opt-in synthetic Clef/oMLX HTTP checks; no tools, URL images or device actions.

Loads the selected model by inference. Uses local oMLX credentials privately.
Always disables truncation. No management/settings writes occur.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import pathlib
import statistics
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests/fixtures/clef"


def red_png(size=256):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    pixels = (b"\x00" + b"\xff\x00\x00" * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def validate_answers(response, model):
    assert response["model"] == model, "Unexpected model identity"
    answers = response["answers"]
    assert answers["department"]["choice"] in {"technical", "billing"}
    for name in ("department", "urgency"):
        p = answers[name]["probabilities"]
        assert all(
            isinstance(x, (int, float)) and math.isfinite(x) and 0 <= x <= 1
            for x in p.values()
        )
        assert abs(sum(p.values()) - 1) < 0.001
    assert (
        math.isfinite(answers["urgency"]["score"])
        and 0 <= answers["urgency"]["score"] <= 2
    )
    assert (
        math.isfinite(answers["outage"]["noul"]) and 0 <= answers["outage"]["noul"] <= 1
    )
    assert response["usage"]["input_tokens"] > 0
    assert response["usage"]["output_tokens"] == 0


def compare_baseline(answers, baseline):
    assert answers["department"]["choice"] == baseline["department"]["choice"]
    differences = [abs(answers["outage"]["noul"] - baseline["outage"]["noul"])]
    for name in ("department", "urgency"):
        assert set(answers[name]["probabilities"]) == set(
            baseline[name]["probabilities"]
        )
        differences.extend(
            abs(p - baseline[name]["probabilities"][k])
            for k, p in answers[name]["probabilities"].items()
        )
    assert max(differences) <= 0.01, "Probability drift exceeds declared tolerance"
    assert abs(answers["urgency"]["score"] - baseline["urgency"]["score"]) <= 0.025
    return max(differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="clef")
    parser.add_argument(
        "--settings",
        type=pathlib.Path,
        default=pathlib.Path.home() / ".omlx/settings.json",
    )
    parser.add_argument("--report", type=pathlib.Path, required=True)
    parser.add_argument(
        "--quick", action="store_true", help="Text/image verification only"
    )
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.url)
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.path
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        parser.error("Only a loopback HTTP base URL is accepted")
    settings = json.loads(args.settings.read_text())
    key = settings["auth"]["api_key"]
    report = {
        "model": args.model,
        "synthetic_only": True,
        "truncate": False,
        "checks": [],
        "limitations": [
            "Decision models do not support video; unknown extra JSON fields may be ignored by oMLX.",
            "Transport body cap is oMLX-wide and is not the former wrapper 16 MiB cap.",
            "Smoke test is not a full-context benchmark, security audit or calibration study.",
        ],
    }

    def request(path, body=None, raw=None, extra_headers=None):
        data = (
            raw
            if raw is not None
            else (json.dumps(body).encode() if body is not None else None)
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            **(extra_headers or {}),
        }
        req = urllib.request.Request(args.url + path, data=data, headers=headers)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        return (
            status,
            json.loads(payload),
            round((time.perf_counter() - started) * 1000, 2),
        )

    def record(name, **values):
        report["checks"].append({"name": name, **values})
        print(f"PASS {name}", flush=True)

    try:
        status, health, _ = request("/health")
        assert status == 200 and health["status"] == "healthy"
        record("health")
        status, models, _ = request("/v1/models")
        assert status == 200 and args.model in {m["id"] for m in models["data"]}
        record("model identity")
        example = json.loads((FIXTURES / "request.json").read_text())
        example.update(model=args.model, truncate=False)
        baseline = json.loads((FIXTURES / "baseline.json").read_text())["checks"][0][
            "answers"
        ]
        status, response, elapsed = request("/v1/systemone", example)
        assert status == 200, f"Warmup HTTP {status}"
        validate_answers(response, args.model)
        record("load and warmup", client_latency_ms=elapsed)
        latencies = []
        for index in range(1 if args.quick else 3):
            status, response, elapsed = request("/v1/systemone", example)
            assert status == 200, f"Text HTTP {status}"
            validate_answers(response, args.model)
            delta = compare_baseline(response["answers"], baseline)
            latencies.append(elapsed)
            record(
                f"typed decisions #{index + 1}",
                client_latency_ms=elapsed,
                max_probability_delta=delta,
                answers=response["answers"],
                usage=response["usage"],
            )
        report["text_latency_ms"] = {
            "median": statistics.median(latencies),
            "min": min(latencies),
            "max": max(latencies),
        }
        if not args.quick:
            bad_cases = [
                ("invalid JSON", None, b"{", {422}),
                (
                    "empty questions",
                    {
                        "model": args.model,
                        "state": "test",
                        "questions": {},
                        "truncate": False,
                    },
                    None,
                    {422},
                ),
                (
                    "invalid question type",
                    {
                        "model": args.model,
                        "state": "test",
                        "questions": {"q": {"type": "unknown"}},
                        "truncate": False,
                    },
                    None,
                    {422},
                ),
                (
                    "invalid choice criteria",
                    {
                        "model": args.model,
                        "state": "test",
                        "questions": {"q": {"type": "choice", "criteria": []}},
                        "truncate": False,
                    },
                    None,
                    {400},
                ),
                (
                    "video masquerading as image rejected",
                    {**example, "images": ["data:video/mp4;base64,dGVzdA=="]},
                    None,
                    {400, 422},
                ),
                (
                    "context overflow rejected",
                    {**example, "state": "outage " * 20000},
                    None,
                    {413},
                ),
            ]
            for name, body, raw, expected in bad_cases:
                status, _, _ = request("/v1/systemone", body, raw=raw)
                assert status in expected, f"{name}: HTTP {status}"
                record(name, http_status=status)
            # Declare an oversized body without allocating/sending it. The
            # middleware must reject Content-Length before attempting to read.
            status, _, _ = request(
                "/v1/systemone", raw=b"{}", extra_headers={"Content-Length": str(2**40)}
            )
            assert status == 413, f"Body cap: HTTP {status}"
            record("transport body cap", http_status=status)
            status, _, _ = request(
                "/v1/chat/completions",
                {
                    "model": args.model,
                    "messages": [{"role": "user", "content": "test"}],
                },
            )
            assert status == 400, f"Chat rejection: HTTP {status}"
            record("decision model rejects chat API", http_status=status)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(lambda _: request("/v1/systemone", example), range(2))
                )
            for status, response, _ in results:
                assert status == 200
                validate_answers(response, args.model)
            record("two concurrent requests", client_latency_ms=[r[2] for r in results])
        image_body = {
            "model": args.model,
            "truncate": False,
            "state": "Look at the supplied image and identify its dominant color.",
            "images": ["data:image/png;base64," + base64.b64encode(red_png()).decode()],
            "questions": {
                "color": {
                    "type": "choice",
                    "criteria": {
                        "red": "The image is red.",
                        "blue": "The image is blue.",
                    },
                }
            },
        }
        status, response, elapsed = request("/v1/systemone", image_body)
        assert status == 200, f"Image HTTP {status}"
        assert response["answers"]["color"]["choice"] == "red"
        record(
            "base64 image inference",
            client_latency_ms=elapsed,
            answers=response["answers"],
            usage=response["usage"],
        )
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        # Do not persist arbitrary network errors, URLs with credentials or
        # private server response bodies.
        report["failure_type"] = type(error).__name__
        if isinstance(error, AssertionError):
            report["failure"] = str(error)
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
