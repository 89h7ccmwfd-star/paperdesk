"""Hochladen des Dashboards zu Cloudflare Pages (nur mit Freigabe)."""
import os
import shutil
import subprocess

from . import config
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


def publish() -> Tuple[bool, str]:
    """Laeuft nur mit Cloudflare-Token (GitHub-Secret) oder lokaler Freigabe (Datei .publish-enabled)."""
    if not (os.environ.get("CLOUDFLARE_API_TOKEN") or os.path.exists(os.path.join(config.HOME, ".publish-enabled"))):
        return False, "Hochladen nicht freigegeben"
    npx = shutil.which("npx") or "/usr/local/bin/npx"
    res = subprocess.run([npx, "--yes", "wrangler@3", "pages", "deploy", os.path.join(config.HOME, "site"),
                          "--project-name", "paperdesk-sim", "--branch", "main", "--commit-dirty=true"],
                         cwd=config.HOME, capture_output=True, text=True, timeout=240)
    return res.returncode == 0, (res.stdout + res.stderr)[-400:]
