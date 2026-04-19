#!/usr/bin/env python3
"""Claude Code Stop hook — remind to write_journal before session ends.

直近のプロジェクトへのコミットと docs への記録状況を照合し、
未記録の作業があれば write_journal() を促す。

Usage in Claude Code settings.json:
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python3 ~/projects/gx10-mcp/hooks/stop_guard.py",
        "timeout": 5
      }]
    }]
  }
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

AGENT = "gx10-claude"
ACTIVITY_URL = "http://localhost:9100/activity"
EXPIRY_SECONDS = 30 * 60  # 30 minutes

_HOME = Path.home()

# 監視対象プロジェクト（作業が発生しやすいもの）
PROJECTS = [
    str(_HOME / "projects/sglang"),
    str(_HOME / "projects/nob-san-tools"),
    str(_HOME / "projects/gx10-mcp"),
    str(_HOME / "projects/nanoclaw"),
    str(_HOME / "projects/whisper-transcriber"),
]
DOCS_DIR = str(_HOME / "projects/docs")

# snapshot: コミットはノイズなので除外
SNAPSHOT_PREFIX = "snapshot:"


def read_activities() -> list:
    """REST API GET /activity からアクティビティ一覧を取得する."""
    try:
        with urllib.request.urlopen(ACTIVITY_URL, timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("agents", [])
    except Exception:
        return []


def get_recent_commits(repo_path: str, since_hours: int = 3) -> list[str]:
    """直近 N 時間のコミットを取得（snapshot コミットは除外）。"""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_hours} hours ago"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = [
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip() and SNAPSHOT_PREFIX not in line
        ]
        return lines
    except Exception:
        return []


def get_recent_journals(since_hours: int = 3) -> list[str]:
    """直近 N 時間の docs コミットを取得。"""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_hours} hours ago"],
            cwd=DOCS_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return [
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip()
        ]
    except Exception:
        return []


def main() -> None:
    agents = read_activities()
    entry = next((a for a in agents if a.get("agent") == AGENT), None)
    now = time.time()
    activity_active = entry and (now - entry.get("timestamp", 0)) < EXPIRY_SECONDS

    # 直近のプロジェクトコミットを収集
    recent_commits: list[str] = []
    for proj in PROJECTS:
        commits = get_recent_commits(proj)
        if commits:
            proj_name = os.path.basename(proj)
            for c in commits[:3]:
                recent_commits.append(f"  [{proj_name}] {c}")

    # 何もなければ何も出力しない
    if not activity_active and not recent_commits:
        return

    # docs の記録状況
    recent_journals = get_recent_journals()

    lines: list[str] = []
    lines.append("[GX10 MCP] セッション終了 — write_journal() は済みましたか？")

    if activity_active:
        desc = entry.get("description", "不明")
        lines.append(f"  宣言済み作業: 「{desc}」")

    if recent_commits:
        lines.append("  直近のコミット（未記録の可能性あり）:")
        lines.extend(recent_commits[:6])

    if recent_journals:
        lines.append("  docs に記録済み:")
        for j in recent_journals[:3]:
            lines.append(f"    {j}")
    else:
        lines.append("  docs への記録: なし ← write_journal() を推奨")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
