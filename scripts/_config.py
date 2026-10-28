"""Shared settings for the operational scripts: resource names come from Terraform outputs,
so there is one source of truth and nothing is hard-coded."""
from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def terraform_outputs() -> dict:
    """Read every output of the infra/ configuration as a plain dict ({name: value})."""
    result = subprocess.run(
        ["terraform", f"-chdir={REPO_ROOT / 'infra'}", "output", "-json"],
        capture_output=True, text=True, check=True,
    )
    return {name: item["value"] for name, item in json.loads(result.stdout).items()}


def setting(env_var: str, output_name: str) -> str:
    """An environment variable wins (handy for quick overrides); otherwise use the Terraform output."""
    return os.environ.get(env_var) or terraform_outputs()[output_name]
