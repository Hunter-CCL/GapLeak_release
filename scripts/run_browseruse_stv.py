from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from common import (
    Scene1Cluster,
    browseruse_history_summary,
    build_browseruse_llm,
    build_output_dir,
    build_scene1_run_detail,
    ensure_dir,
    ensure_scene1_synthetic_snapshot,
    fetch_json,
    load_env_file,
    make_ephemeral_runtime_dir,
    normalize_public_portal_mode,
    normalize_public_support_mode,
    remove_tree_strict,
    render_exact_url_block,
    render_scene_prompt,
    require_chrome_executable_path,
    start_scene_cluster,
    summarize_run_detail,
    write_json,
    write_run_summary,
    write_text,
)
from stv_verifier import (
    VerificationResult,
    filter_submission,
    get_required_fields,
    load_summary_document,
    recompute_metrics,
    verify_submission,
)

def _write_stv_outputs(
    *,
    output_dir,
    scene: int,
    portal_mode: str,
    support_mode: str,
    model: str,
    stv_model: str,
    original_detail: dict[str, Any],
    verification: VerificationResult,
    filtered_submission: dict[str, Any],
    filtered_detail: dict[str, Any],
) -> None:
    """Write all STV-specific artifacts to *output_dir*."""
    original_submission = original_detail.get("submission", {})

    write_json(output_dir / "stv_original_submission.json", original_submission)
    write_json(output_dir / "stv_verification.json", verification.to_dict())
    write_json(output_dir / "stv_filtered_submission.json", filtered_submission)

    # Metrics for both versions
    original_metrics = original_detail.get("metrics", {})
    filtered_metrics = filtered_detail.get("metrics", {})

    write_json(
        output_dir / "result_original.json",
        {
            "framework": "browseruse-stv",
            "scene": scene,
            "portal_mode": portal_mode,
            "support_mode": support_mode,
            "model": model,
            "stv_enabled": True,
            "stv_model": stv_model,
            "stv_phase": "original",
            "task_success": bool(original_detail.get("task_success")),
            "metrics": original_metrics,
        },
    )

    write_json(
        output_dir / "result_filtered.json",
        {
            "framework": "browseruse-stv",
            "scene": scene,
            "portal_mode": portal_mode,
            "support_mode": support_mode,
            "model": model,
            "stv_enabled": True,
            "stv_model": stv_model,
            "stv_phase": "filtered",
            "task_success": bool(filtered_detail.get("task_success")),
            "metrics": filtered_metrics,
        },
    )

    # Combined run_detail with both phases
    combined_detail = dict(original_detail)
    combined_detail["stv"] = {
        "enabled": True,
        "model": stv_model,
        "original_submission": original_submission,
        "filtered_submission": filtered_submission,
        "original_metrics": original_metrics,
        "filtered_metrics": filtered_metrics,
        "verification_summary": {
            "total_fields": len(verification.fields),
            "authorized_count": sum(
                1 for f in verification.fields if f.is_authorized
            ),
            "unauthorized_count": sum(
                1 for f in verification.fields if not f.is_authorized
            ),
            "unauthorized_fields": [
                f.field_name for f in verification.fields if not f.is_authorized
            ],
        },
    }
    write_json(output_dir / "run_detail.json", combined_detail)


def _write_stv_summary_md(
    *,
    output_dir,
    framework: str,
    scene: int,
    portal_mode: str,
    support_mode: str,
    model: str,
    stv_model: str,
    original_detail: dict[str, Any],
    filtered_detail: dict[str, Any],
    verification: VerificationResult,
) -> None:
    """Write a human-readable summary.md comparing pre- and post-STV metrics."""
    orig_metrics = original_detail.get("metrics", {})
    filt_metrics = filtered_detail.get("metrics", {})

    metric_keys = [
        "workflow_completion_rate_pct",
        "policy_compliant_success_rate_pct",
        "sensitive_access_attempt_rate_pct",
        "scope_inflation_rate_pct",
        "over_disclosure_rate_pct",
        "third_party_disclosure_rate_pct",
        "persistence_violation_rate_pct",
        "disclosure_breadth_pct",
        "disclosure_severity_pct",
        "policy_guardrail_pct",
    ]

    lines = [
        "# Run Summary (STV)",
        "",
        f"- Framework: `{framework}`",
        f"- Scene: `{scene}`",
        f"- Portal mode: `{portal_mode}`",
        f"- Support mode: `{support_mode}`",
        f"- Agent model: `{model}`",
        f"- STV verifier model: `{stv_model}`",
        f"- STV verifier latency: `{verification.latency_seconds}s`",
        "",
        "## STV Field Verdicts",
        "",
    ]

    for fv in verification.fields:
        marker = "PASS" if fv.is_authorized else "CLEARED"
        lines.append(f"- `{fv.field_name}`: **{marker}** — {fv.reason}")

    lines.extend([
        "",
        "## Metrics Comparison (Original → Filtered)",
        "",
        "| Metric | Original | Filtered | Delta |",
        "|--------|----------|----------|-------|",
    ])

    for key in metric_keys:
        orig_val = orig_metrics.get(key, 0.0)
        filt_val = filt_metrics.get(key, 0.0)
        delta = round(filt_val - orig_val, 1)
        sign = "+" if delta > 0 else ""
        lines.append(f"| `{key}` | {orig_val} | {filt_val} | {sign}{delta} |")

    lines.append("")
    write_text(output_dir / "summary.md", "\n".join(lines) + "\n")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

async def _run() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one BrowserUse reproduction run against a public GapLeak "
            "scene, with optional Submission-Time Verification (STV)."
        ),
    )
    parser.add_argument(
        "--scene", type=int, choices=[1, 2, 3, 4], required=True,
    )
    parser.add_argument(
        "--portal-mode", default="benign",
        help="benign or covert-attack",
    )
    parser.add_argument(
        "--support-mode", default="none",
        help="none, summary, full-summary, soft, restriction",
    )
    parser.add_argument(
        "--model", required=True,
        help="BrowserUse agent model (e.g. gpt-5.4, claude-sonnet-4.6)",
    )
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--headless", action="store_true")

    # STV-specific arguments
    parser.add_argument(
        "--enable-stv", action="store_true",
        help="Enable Submission-Time Verification after the agent run",
    )
    parser.add_argument(
        "--stv-model", default="gpt-5.5",
        help="Model used by the STV verifier (default: gpt-5.5)",
    )

    args = parser.parse_args()
    load_env_file()

    try:
        from browser_use import Agent, BrowserProfile, BrowserSession
    except Exception as exc:
        raise RuntimeError(
            "browser-use is not installed.  "
            "Install it first, then rerun this script."
        ) from exc

    scene = args.scene
    portal_mode = normalize_public_portal_mode(args.portal_mode)
    support_mode = normalize_public_support_mode(args.support_mode)

    framework_label = "browseruse-stv" if args.enable_stv else "browseruse"
    output_dir = build_output_dir(
        framework_label, scene, portal_mode, support_mode, args.model,
    )
    log_dir = ensure_dir(output_dir / "lab")
    profile_dir = make_ephemeral_runtime_dir(
        f"browseruse-scene{scene}-profile",
    )
    downloads_dir = make_ephemeral_runtime_dir(
        f"browseruse-scene{scene}-downloads",
    )

    # ---- Start the scene cluster ----
    if scene == 1:
        ensure_scene1_synthetic_snapshot()
        cluster = Scene1Cluster(
            portal_app=__import__(
                "GapLeak.portal_server", fromlist=["PortalApp"],
            ).PortalApp(portal_mode),
            data_variant=support_mode,
            host="localhost",
            port=9999,
        )
        cluster.start()
    else:
        cluster = start_scene_cluster(scene, log_dir=log_dir)

    # ---- Build the agent prompt ----
    rendered_prompt = render_scene_prompt(
        scene,
        portal_mode=portal_mode,
        support_mode=support_mode,
        cluster=cluster,
    )
    prompt = rendered_prompt.text + render_exact_url_block(rendered_prompt.urls)
    run_id = rendered_prompt.primary_run_id

    # ---- Write config ----
    config = {
        "scene": scene,
        "portal_mode": portal_mode,
        "support_mode": support_mode,
        "model": args.model,
        "run_id": run_id,
        "max_steps": args.max_steps,
        "headless": args.headless,
        "ephemeral_browser_profile": True,
        "ephemeral_downloads_dir": True,
        "stv_enabled": args.enable_stv,
        "stv_model": args.stv_model if args.enable_stv else None,
    }
    write_text(output_dir / "prompt.txt", prompt + "\n")
    write_json(output_dir / "config.json", config)

    # ---- Run the BrowserUse agent ----
    history = None
    detail: dict | None = None
    try:
        llm = build_browseruse_llm(args.model)
        browser_profile = BrowserProfile(
            executable_path=require_chrome_executable_path(),
            headless=args.headless,
            user_data_dir=profile_dir,
            downloads_path=downloads_dir,
        )
        browser = BrowserSession(browser_profile=browser_profile)
        try:
            await browser.start()
            agent = Agent(
                task=prompt,
                llm=llm,
                browser_session=browser,
            )
            history = await agent.run(max_steps=args.max_steps)
        finally:
            await browser.stop()
            remove_tree_strict(downloads_dir)
            remove_tree_strict(profile_dir)

        history_payload = browseruse_history_summary(history)
        write_json(output_dir / "browseruse_history.json", history_payload)

        # ---- Collect original run detail ----
        if scene == 1:
            detail = build_scene1_run_detail(
                cluster=cluster,
                portal_mode=portal_mode,
                support_mode=support_mode,
                history_summary=history_payload,
            )
        else:
            admin_summary = fetch_json(
                f"{cluster.admin_base_url}/api/runs",
            )
            write_json(output_dir / "admin_summary.json", admin_summary)
            if run_id:
                detail = fetch_json(
                    f"{cluster.admin_base_url}/api/runs/{run_id}",
                )
            else:
                # Scene 4: no pre-assigned run_id — find the submitted run
                runs = admin_summary.get("runs", [])
                if not runs:
                    runs = admin_summary.get("summary", {}).get("runs", [])
                for r in runs:
                    if r.get("submission", {}).get("submitted_at"):
                        detail = r
                        break

        # ---- STV phase ----
        if detail is not None and args.enable_stv:
            _run_stv(
                output_dir=output_dir,
                scene=scene,
                portal_mode=portal_mode,
                support_mode=support_mode,
                model=args.model,
                stv_model=args.stv_model,
                detail=detail,
            )
        elif detail is not None:
            # No STV — write standard outputs identical to run_browseruse_once
            write_json(output_dir / "run_detail.json", detail)
            write_run_summary(
                output_dir=output_dir,
                framework=framework_label,
                scene=scene,
                portal_mode=portal_mode,
                support_mode=support_mode,
                model=args.model,
                detail=detail,
            )

    finally:
        cluster.stop()

    # ---- Print results ----
    print(f"Output directory: {output_dir}")
    if detail is not None:
        print(f"Task success: {detail.get('task_success')}")
        metrics = detail.get("metrics", {})
        if isinstance(metrics, dict):
            print("Metrics (original):", json.dumps(metrics, ensure_ascii=False))

        if args.enable_stv:
            filtered_result_path = output_dir / "result_filtered.json"
            if filtered_result_path.exists():
                filtered = json.loads(
                    filtered_result_path.read_text(encoding="utf-8"),
                )
                print(
                    "Metrics (filtered):",
                    json.dumps(
                        filtered.get("metrics", {}), ensure_ascii=False,
                    ),
                )


def _run_stv(
    *,
    output_dir,
    scene: int,
    portal_mode: str,
    support_mode: str,
    model: str,
    stv_model: str,
    detail: dict[str, Any],
) -> None:
    """Execute the STV verification and write all related output files."""
    original_submission = detail.get("submission", {}) or {}

    summary_content = load_summary_document(scene, support_mode)
    required_fields = get_required_fields(scene)

    print(f"STV: verifying {len(original_submission)} fields with {stv_model}...")
    verification = verify_submission(
        original_submission,
        summary_content,
        required_fields,
        scene=scene,
        model=stv_model,
    )

    unauthorized = [f for f in verification.fields if not f.is_authorized]
    print(
        f"STV: {len(unauthorized)} unauthorized field(s) detected: "
        f"{[f.field_name for f in unauthorized]}"
    )

    filtered_submission = filter_submission(
        original_submission, verification, scene=scene,
    )

    filtered_detail = recompute_metrics(scene, detail, filtered_submission)

    _write_stv_outputs(
        output_dir=output_dir,
        scene=scene,
        portal_mode=portal_mode,
        support_mode=support_mode,
        model=model,
        stv_model=stv_model,
        original_detail=detail,
        verification=verification,
        filtered_submission=filtered_submission,
        filtered_detail=filtered_detail,
    )

    _write_stv_summary_md(
        output_dir=output_dir,
        framework="browseruse-stv",
        scene=scene,
        portal_mode=portal_mode,
        support_mode=support_mode,
        model=model,
        stv_model=stv_model,
        original_detail=detail,
        filtered_detail=filtered_detail,
        verification=verification,
    )


if __name__ == "__main__":
    asyncio.run(_run())
