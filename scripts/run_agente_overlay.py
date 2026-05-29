from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from typing import Any

from common import (
    Scene1Cluster,
    build_output_dir,
    build_scene1_run_detail,
    ensure_scene1_synthetic_snapshot,
    fetch_json,
    infer_provider_from_model,
    load_env_file,
    make_ephemeral_runtime_dir,
    normalize_public_portal_mode,
    normalize_public_support_mode,
    remove_tree_strict,
    render_exact_url_block,
    render_scene_prompt,
    start_scene_cluster,
    write_json,
    write_run_summary,
    write_text,
)


def _configure_utf8_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


def _resolve_api_key(model: str) -> str:
    provider = infer_provider_from_model(model)
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    elif provider == "google":
        env = os.environ
        key = (env.get("GOOGLE_API_KEY") or env.get("GEMINI_API_KEY") or "").strip()
    else:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    raise RuntimeError(f"Missing API key for provider '{provider}'.")


def _build_llm_config(*, model: str, api_key: str) -> dict[str, object]:
    shared_model_config: dict[str, object] = {
        "model": model,
        "api_key": api_key,
    }
    provider = infer_provider_from_model(model)
    if provider == "google":
        shared_model_config["api_type"] = "google"
    elif provider == "anthropic":
        shared_model_config["api_type"] = "anthropic"

    lowered = model.strip().lower()
    if lowered.startswith("gpt"):
        shared_llm_config: dict[str, object] = {
            "temperature": 0.0,
            "top_p": 0.001,
            "seed": 12345,
            "cache_seed": None,
        }
    elif lowered.startswith("claude"):
        shared_llm_config = {
            "temperature": 0.1,
            "cache_seed": None,
        }
    else:
        shared_llm_config = {
            "temperature": 0.1,
            "top_p": 0.1,
            "cache_seed": None,
        }

    return {
        "planner_agent": {
            "model_config_params": dict(shared_model_config),
            "llm_config_params": dict(shared_llm_config),
            "other_settings": {"system_prompt": []},
        },
        "browser_nav_agent": {
            "model_config_params": dict(shared_model_config),
            "llm_config_params": dict(shared_llm_config),
            "other_settings": {"system_prompt": []},
        },
    }


def _build_overlay_bridge_state() -> dict[str, object]:
    return {
        "started": asyncio.Event(),
        "completed": asyncio.Event(),
        "command_task": None,
        "error": None,
        "result": None,
    }


async def _install_overlay_bridge(*, browser_manager, wrapper, notes: list[str], state: dict[str, object]) -> None:
    from ae.utils.ui_messagetype import MessageType

    context = await browser_manager.get_browser_context()

    async def receive_command(command: str) -> None:
        state["command_task"] = asyncio.current_task()
        started_event = state["started"]
        completed_event = state["completed"]
        assert isinstance(started_event, asyncio.Event)
        assert isinstance(completed_event, asyncio.Event)
        started_event.set()
        try:
            current_url = await browser_manager.get_current_url()
            browser_manager.ui_manager.clear_conversation_history()
            browser_manager.log_user_message(command)
            started_at = time.time()
            await browser_manager.update_processing_state("processing")
            result = await wrapper.process_command(command, current_url)
            elapsed = round(time.time() - started_at, 2)
            state["result"] = result
            if result is not None and getattr(result, "summary", None):
                notes.append(f"agent-e summary: {result.summary}")
            await browser_manager.update_processing_state("done")
            await browser_manager.notify_user(f"Task Completed ({elapsed}s).", MessageType.INFO)
            await browser_manager.command_completed(command, elapsed)
        except asyncio.CancelledError:
            notes.append("agent-e overlay command cancelled")
            raise
        except Exception as exc:
            state["error"] = str(exc)
            notes.append(f"agent-e overlay error: {exc}")
            with contextlib.suppress(Exception):
                await browser_manager.update_processing_state("done")
                await browser_manager.notify_user(f"Task failed: {exc}", MessageType.ERROR)
        finally:
            completed_event.set()

    await context.expose_function("process_task", receive_command)
    notes.append("agent-e interface bridge installed: process_task")


async def _refresh_overlay(browser_manager, page) -> None:
    with contextlib.suppress(Exception):
        await browser_manager.ui_manager.handle_navigation(page)
    await page.wait_for_load_state("domcontentloaded")


async def _dispatch_command_through_overlay(browser_manager, portal_page, task: str) -> None:
    await portal_page.wait_for_load_state("domcontentloaded")
    last_error: Exception | None = None
    for _ in range(3):
        await _refresh_overlay(browser_manager, portal_page)
        with contextlib.suppress(Exception):
            await portal_page.evaluate(
                """() => {
                    if (typeof showExpandedOverlay === 'function') {
                        showExpandedOverlay('init', true);
                    }
                }"""
            )
        input_box = portal_page.locator("#agente-user-input")
        send_button = portal_page.locator("#agente-send-btn")
        try:
            await input_box.wait_for(state="visible", timeout=10000)
            await send_button.wait_for(state="visible", timeout=10000)
            await input_box.click()
            await input_box.evaluate(
                """(element, value) => {
                    element.value = value;
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                }""",
                task,
            )
            await portal_page.wait_for_timeout(1200)
            await send_button.click()
            with contextlib.suppress(Exception):
                await portal_page.evaluate(
                    """() => {
                        const input = document.querySelector('#agente-user-input');
                        let panel = input;
                        while (panel && panel !== document.body) {
                            const style = window.getComputedStyle(panel);
                            const rect = panel.getBoundingClientRect();
                            if ((style.position === 'fixed' || style.position === 'absolute') && rect.width >= 320 && rect.height >= 120) {
                                break;
                            }
                            panel = panel.parentElement;
                        }
                        if (panel && panel !== document.body) {
                            panel.style.maxWidth = '520px';
                            panel.style.width = 'min(520px, calc(100vw - 24px))';
                            panel.style.maxHeight = '70vh';
                            panel.style.right = '12px';
                            panel.style.bottom = '12px';
                        }
                    }"""
                )
            return
        except Exception as exc:
            last_error = exc
            await portal_page.wait_for_timeout(1000)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Agent-E overlay input did not become ready.")


async def _run() -> None:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run one public GapLeak reproduction through an Agent-E overlay workflow.")
    parser.add_argument("--scene", type=int, choices=[1, 2, 3, 4], required=True)
    parser.add_argument("--portal-mode", default="benign", help="benign or covert-attack")
    parser.add_argument("--support-mode", default="none", help="none, summary, full-summary, soft, restriction")
    parser.add_argument("--model", required=True, help="Agent-E model label configured in your local Agent-E environment.")
    parser.add_argument("--planner-max-chat-round", type=int, default=50)
    parser.add_argument("--browser-nav-max-chat-round", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    load_env_file()

    try:
        from ae.core.autogen_wrapper import AutogenWrapper
        from ae.core.playwright_manager import PlaywrightManager
    except Exception as exc:
        raise RuntimeError(
            "Agent-E is not bundled in this repository. Activate your own Agent-E environment, then rerun this script."
        ) from exc

    scene = args.scene
    portal_mode = normalize_public_portal_mode(args.portal_mode)
    support_mode = normalize_public_support_mode(args.support_mode)
    output_dir = build_output_dir("agente", scene, portal_mode, support_mode, f"{args.model}-overlay")
    log_dir = output_dir / "lab"
    profile_dir = make_ephemeral_runtime_dir(f"agente-overlay-scene{scene}-profile")

    if scene == 1:
        ensure_scene1_synthetic_snapshot()
        cluster = Scene1Cluster(
            portal_app=__import__("GapLeak.portal_server", fromlist=["PortalApp"]).PortalApp(portal_mode),
            data_variant=support_mode,
            host="localhost",
            port=9999,
        )
        cluster.start()
        portal_url = f"{cluster.base_url}/portal/start"
    else:
        cluster = start_scene_cluster(scene, log_dir=log_dir)
        portal_url = cluster.portal_base_url

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
            "planner_max_chat_round": args.planner_max_chat_round,
            "browser_nav_max_chat_round": args.browser_nav_max_chat_round,
            "timeout_seconds": args.timeout_seconds,
            "headless": args.headless,
            "interface_mode": "overlay",
            "ephemeral_browser_profile": True,
        },
    )

    notes: list[str] = [f"portal_url: {portal_url}", f"interface_mode: overlay"]
    runtime_payload: dict[str, Any] = {}
    detail: dict[str, Any] | None = None
    previous_browser_storage_dir = os.environ.get("BROWSER_STORAGE_DIR")
    os.environ["BROWSER_STORAGE_DIR"] = str(profile_dir)
    browser_manager = PlaywrightManager(browser_type="chromium", headless=args.headless, gui_input_mode=True)
    try:
        llm_config = _build_llm_config(model=args.model, api_key=_resolve_api_key(args.model))
        await browser_manager.async_initialize()
        current_page = await browser_manager.get_current_page()
        await current_page.goto(portal_url, wait_until="domcontentloaded")
        await _refresh_overlay(browser_manager, current_page)
        wrapper = await AutogenWrapper.create(
            llm_config["planner_agent"],
            llm_config["browser_nav_agent"],
            save_chat_logs_to_files=True,
            planner_max_chat_round=args.planner_max_chat_round,
            browser_nav_max_chat_round=args.browser_nav_max_chat_round,
        )
        overlay_state = _build_overlay_bridge_state()
        await _install_overlay_bridge(
            browser_manager=browser_manager,
            wrapper=wrapper,
            notes=notes,
            state=overlay_state,
        )
        timed_out = False
        started_monotonic = time.monotonic()
        try:
            await _dispatch_command_through_overlay(browser_manager, current_page, prompt)
            started_event = overlay_state["started"]
            completed_event = overlay_state["completed"]
            assert isinstance(started_event, asyncio.Event)
            assert isinstance(completed_event, asyncio.Event)
            await asyncio.wait_for(started_event.wait(), timeout=15)
            await asyncio.wait_for(completed_event.wait(), timeout=args.timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            notes.append(f"agent-e run timed out after {args.timeout_seconds} seconds")
            command_task = overlay_state.get("command_task")
            if isinstance(command_task, asyncio.Task) and not command_task.done():
                command_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await command_task
        elapsed = round(time.monotonic() - started_monotonic, 2)
        result = overlay_state.get("result")
        overlay_error = overlay_state.get("error")
        if isinstance(overlay_error, str) and overlay_error:
            notes.append(f"agent-e overlay execution finished with error: {overlay_error}")
        runtime_payload = {
            "timed_out": timed_out,
            "elapsed_seconds": elapsed,
            "overlay_error": overlay_error,
            "result_summary": getattr(result, "summary", None) if result is not None else None,
            "notes": notes,
        }
        write_json(output_dir / "overlay_runtime.json", runtime_payload)
        if scene == 1:
            detail = build_scene1_run_detail(
                cluster=cluster,
                portal_mode=portal_mode,
                support_mode=support_mode,
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
                framework="agente-overlay",
                scene=scene,
                portal_mode=portal_mode,
                support_mode=support_mode,
                model=args.model,
                detail=detail,
            )
    finally:
        with contextlib.suppress(Exception):
            await browser_manager.stop_playwright()
        if previous_browser_storage_dir is None:
            os.environ.pop("BROWSER_STORAGE_DIR", None)
        else:
            os.environ["BROWSER_STORAGE_DIR"] = previous_browser_storage_dir
        remove_tree_strict(profile_dir)
        cluster.stop()

    print(f"Output directory: {output_dir}")
    if detail is not None:
        print(f"Task success: {detail.get('task_success')}")
        metrics = detail.get("metrics", {})
        if isinstance(metrics, dict):
            print("Metrics:", json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_run())
