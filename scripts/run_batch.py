"""
Batch runner for STV experiments.

Runs multiple trials per scene×model combination, saving results into
a structured batch folder.

Usage:
    # Run one scene (27 runs: 3 models × 9 remaining)
    python scripts/run_batch.py --scene 1

    # Run specific model only
    python scripts/run_batch.py --scene 2 --model gpt-5.4

    # Custom run range
    python scripts/run_batch.py --scene 3 --start-run 2 --end-run 10

Each scene uses different ports, so multiple scenes CAN run in parallel.
Within a scene, runs are sequential (shared ports).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

MODELS = [
    ("claude-sonnet-4-6", "sonnet"),
    ("gpt-5.4", "gpt54"),
    ("gemini-2.5-pro", "gemini"),
]

SCENE_RANGE = range(1, 5)


def run_one(
    *,
    scene: int,
    model_id: str,
    model_short: str,
    run_num: int,
    batch_dir: Path,
    headless: bool,
) -> dict | None:
    dest = batch_dir / f"{model_short}-run{run_num:02d}"
    if dest.exists():
        print(f"  SKIP {dest.name} (already exists)")
        return None

    print(f"  START {dest.name} ...")
    t0 = time.time()

    cmd = [
        str(PYTHON),
        str(ROOT / "scripts" / "run_browseruse_stv.py"),
        "--scene", str(scene),
        "--portal-mode", "covert-attack",
        "--support-mode", "summary",
        "--model", model_id,
        "--enable-stv",
    ]
    if headless:
        cmd.append("--headless")

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=1200,
    )

    elapsed = time.time() - t0

    output_dir = None
    for line in result.stdout.splitlines():
        if line.startswith("Output directory:"):
            output_dir = Path(line.split(":", 1)[1].strip())
            break

    if output_dir and output_dir.exists():
        shutil.copytree(output_dir, dest)
        print(f"  DONE {dest.name}  ({elapsed:.0f}s)")
        return {"run": run_num, "model": model_id, "dir": str(dest), "elapsed": elapsed}
    else:
        print(f"  FAIL {dest.name}  ({elapsed:.0f}s)")
        if result.stderr:
            last_lines = result.stderr.strip().splitlines()[-5:]
            for line in last_lines:
                print(f"    stderr: {line}")
        return {"run": run_num, "model": model_id, "dir": None, "elapsed": elapsed, "error": True}


def main():
    parser = argparse.ArgumentParser(description="Batch STV runner")
    parser.add_argument("--scene", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--model", type=str, default=None, help="Run only this model")
    parser.add_argument("--start-run", type=int, default=2)
    parser.add_argument("--end-run", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    batch_dir = ROOT / "outputs" / "browseruse-stv" / f"batch-scene{args.scene}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    models = MODELS
    if args.model:
        models = [(mid, mshort) for mid, mshort in MODELS if mid == args.model or mshort == args.model]
        if not models:
            print(f"Unknown model: {args.model}")
            sys.exit(1)

    total = len(models) * (args.end_run - args.start_run + 1)
    done = 0

    print(f"=== Batch: Scene {args.scene}, {len(models)} model(s), runs {args.start_run}-{args.end_run} ({total} total) ===")
    print(f"    Output: {batch_dir}")
    print()

    for model_id, model_short in models:
        print(f"[Scene {args.scene} / {model_short}]")
        for run_num in range(args.start_run, args.end_run + 1):
            run_one(
                scene=args.scene,
                model_id=model_id,
                model_short=model_short,
                run_num=run_num,
                batch_dir=batch_dir,
                headless=args.headless,
            )
            done += 1
            remaining = total - done
            print(f"    Progress: {done}/{total} done, {remaining} remaining")
        print()

    print(f"=== Batch complete: Scene {args.scene} ===")


if __name__ == "__main__":
    main()
