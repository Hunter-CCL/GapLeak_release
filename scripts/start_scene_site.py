from __future__ import annotations

import argparse
import time

from common import (
    Scene1Cluster,
    build_prompt_replacement_map,
    build_output_dir,
    ensure_scene1_synthetic_snapshot,
    load_env_file,
    normalize_public_portal_mode,
    normalize_public_support_mode,
    start_scene_cluster,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a local public GapLeak scene website without any agent runner.")
    parser.add_argument("--scene", type=int, choices=[1, 2, 3, 4], required=True)
    parser.add_argument("--portal-mode", default="benign", help="benign or covert-attack")
    parser.add_argument("--support-mode", default="none", help="none, summary, full-summary, soft, restriction")
    args = parser.parse_args()

    load_env_file()
    scene = args.scene
    portal_mode = normalize_public_portal_mode(args.portal_mode)
    support_mode = normalize_public_support_mode(args.support_mode)
    output_dir = build_output_dir("manual", scene, portal_mode, support_mode, "site")
    log_dir = output_dir / "lab"

    if scene == 1:
        ensure_scene1_synthetic_snapshot()
        cluster = Scene1Cluster(
            portal_app=__import__("GapLeak.portal_server", fromlist=["PortalApp"]).PortalApp(portal_mode),
            data_variant=support_mode,
            host="localhost",
            port=9999,
        )
        cluster.start()
        print("Scene 1 portal: http://localhost:9999/portal/start")
        print("Scene 1 vault: http://localhost:9999/vault/")
        print("Scene 1 calendar: http://localhost:9999/calendar/snapshot")
    else:
        cluster = start_scene_cluster(scene, log_dir=log_dir)
        print(f"Portal URL: {cluster.portal_base_url}")
        if scene in {2, 3}:
            print(f"Account / materials URL: {cluster.account_base_url}")
        else:
            print(f"Vault URL: {cluster.portal_base_url}/vault/")
            print(f"Calendar URL: {cluster.portal_base_url}/calendar-events")
        print(f"Admin URL: {cluster.admin_base_url}")

    print("Prompt placeholder values:")
    replacement_map = build_prompt_replacement_map(
        scene,
        cluster=cluster,
        portal_mode=portal_mode,
        support_mode=support_mode,
    )
    for key in ("<portal>", "<vault>", "<calendar>", "<summary>", "<complete-summary>", "<soft-boundary>", "<restriction>"):
        if key in replacement_map:
            print(f"  {key} = {replacement_map[key]}")

    print("Press Ctrl+C to stop the local service.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cluster.stop()


if __name__ == "__main__":
    main()
