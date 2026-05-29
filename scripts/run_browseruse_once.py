from __future__ import annotations

import argparse
import asyncio
import json

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
    write_run_summary,
    write_json,
    write_text,
)

async def _run() -> None:
    parser = argparse.ArgumentParser(description="Run one BrowserUse reproduction run against a public GapLeak scene.")
    parser.add_argument("--scene", type=int, choices=[1, 2, 3, 4], required=True)
    parser.add_argument("--portal-mode", default="benign", help="benign or covert-attack")
    parser.add_argument("--support-mode", default="none", help="none, summary, full-summary, soft, restriction")
    parser.add_argument("--model", required=True, help="BrowserUse model label, e.g. gpt-5.4 / claude-sonnet-4.6 / gemini-2.5-pro")
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    load_env_file()

    try:
        from browser_use import Agent, BrowserProfile, BrowserSession
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "browser-use is not installed. Install it first, then rerun this script."
        ) from exc

    scene = args.scene
    portal_mode = normalize_public_portal_mode(args.portal_mode)
    support_mode = normalize_public_support_mode(args.support_mode)
    output_dir = build_output_dir("browseruse", scene, portal_mode, support_mode, args.model)
    log_dir = ensure_dir(output_dir / "lab")
    profile_dir = make_ephemeral_runtime_dir(f"browseruse-scene{scene}-profile")
    downloads_dir = make_ephemeral_runtime_dir(f"browseruse-scene{scene}-downloads")
    if scene == 1:
        ensure_scene1_synthetic_snapshot()
        cluster = Scene1Cluster(
            portal_app=__import__("GapLeak.portal_server", fromlist=["PortalApp"]).PortalApp(portal_mode),
            data_variant=support_mode,
            host="localhost",
            port=9999,
        )
        cluster.start()
    else:
        cluster = start_scene_cluster(scene, log_dir=log_dir)

    rendered_prompt = render_scene_prompt(
        scene,
        portal_mode=portal_mode,
        support_mode=support_mode,
        cluster=cluster,
    )
    prompt = rendered_prompt.text + render_exact_url_block(rendered_prompt.urls)
    run_id = rendered_prompt.primary_run_id
    write_text(output_dir / "prompt.txt", prompt + "\n")
    write_json(
        output_dir / "config.json",
        {
            "scene": scene,
            "portal_mode": portal_mode,
            "support_mode": support_mode,
            "model": args.model,
            "run_id": run_id,
            "max_steps": args.max_steps,
            "headless": args.headless,
            "ephemeral_browser_profile": True,
            "ephemeral_downloads_dir": True,
        },
    )

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

        if scene == 1:
            detail = build_scene1_run_detail(
                cluster=cluster,
                portal_mode=portal_mode,
                support_mode=support_mode,
                history_summary=history_payload,
            )
            write_json(output_dir / "run_detail.json", detail)
        else:
            admin_summary = fetch_json(f"{cluster.admin_base_url}/api/runs")
            write_json(output_dir / "admin_summary.json", admin_summary)
            if run_id:
                detail = fetch_json(f"{cluster.admin_base_url}/api/runs/{run_id}")
                write_json(output_dir / "run_detail.json", detail)
        if detail is not None:
            write_run_summary(
                output_dir=output_dir,
                framework="browseruse",
                scene=scene,
                portal_mode=portal_mode,
                support_mode=support_mode,
                model=args.model,
                detail=detail,
            )
    finally:
        cluster.stop()

    print(f"Output directory: {output_dir}")
    if detail is not None:
        print(f"Task success: {detail.get('task_success')}")
        metrics = detail.get("metrics", {})
        if isinstance(metrics, dict):
            print("Metrics:", json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_run())
