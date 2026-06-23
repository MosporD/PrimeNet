"""Subprocess helpers for pipeline pull/load scripts."""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_script(
    *path_parts: str,
    extra_env: dict[str, str] | None = None,
    args: list[str] | None = None,
) -> int:
    script = os.path.join(PROJECT_ROOT, *path_parts)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, script] + (args or [])
    print(f"[pipeline] run: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    return int(proc.returncode or 0)


def run_hourly_pull_load(*, disable_time_filter: bool = False) -> int:
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    if disable_time_filter:
        env["RAW_LOADER_TIME_FILTER"] = "0"
    rc = run_script("pipeline", "pull", "hourly", "pull_all.py", extra_env=env)
    if rc != 0:
        return rc
    return run_script("pipeline", "load", "hourly", "load_all.py", extra_env=env)


def run_daily_pull_load(*, disable_time_filter: bool = False) -> int:
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    if disable_time_filter:
        env["RAW_LOADER_TIME_FILTER"] = "0"
    rc = run_script("pipeline", "pull", "daily", "pull_all.py", extra_env=env)
    if rc != 0:
        return rc
    return run_script("pipeline", "load", "daily", "load_all.py", extra_env=env)


def run_pm_target_pull_load(
    *,
    scope: str,
    vendor: str,
    category: str,
    disable_time_filter: bool = False,
) -> int:
    """Pull and load one PM target, e.g. hourly/huawei/cells."""
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    if disable_time_filter:
        env["RAW_LOADER_TIME_FILTER"] = "0"

    pull_script = {
        ("hourly", "huawei"): ("scripts", "pipeline", "pull_huawei_raw.py"),
        ("hourly", "nokia"): ("scripts", "pipeline", "pull_nokia_raw.py"),
        ("daily", "huawei"): ("scripts", "pipeline", "pull_huawei_raw_daily.py"),
        ("daily", "nokia"): ("scripts", "pipeline", "pull_nokia_raw_daily.py"),
    }.get((scope, vendor))
    if not pull_script:
        print(f"[pipeline] unsupported PM target: scope={scope} vendor={vendor} category={category}")
        return 1

    rc = run_script(*pull_script, extra_env=env, args=["--category", category])
    if rc != 0:
        return rc

    return run_pm_target_load_only(
        scope=scope,
        vendor=vendor,
        category=category,
        disable_time_filter=disable_time_filter,
    )


def run_pm_target_load_only(
    *,
    scope: str,
    vendor: str,
    category: str,
    disable_time_filter: bool = False,
) -> int:
    """Load one already-staged PM target."""
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    if disable_time_filter:
        env["RAW_LOADER_TIME_FILTER"] = "0"

    load_args = ["--scope", scope, "--vendor", vendor, "--category", category]
    if scope == "daily":
        load_args.append("--skip-kpi-db")
    return run_script(
        "scripts",
        "pipeline",
        "load_raw_csv_to_databases.py",
        extra_env=env,
        args=load_args,
    )


def run_metadata_pull_load() -> int:
    """Pull and load the metadata snapshot only."""
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    rc = run_script("scripts", "pipeline", "pull_metadata_raw.py", extra_env=env)
    if rc != 0:
        return rc
    return run_metadata_load_only()


def run_metadata_load_only() -> int:
    """Load an already-staged metadata snapshot only."""
    env = {"RAW_PULL_AUTO_LOAD": "0"}
    return run_script(
        "scripts",
        "pipeline",
        "load_raw_csv_to_databases.py",
        extra_env=env,
        args=["--scope", "hourly", "--category", "metadata", "--skip-kpi-db"],
    )
