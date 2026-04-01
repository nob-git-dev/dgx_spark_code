"""Git operations for the docs repository."""

import logging

from .config import DOCS_DIR
from .subprocess_utils import run

logger = logging.getLogger("gx10-mcp")


async def ensure_clean() -> str | None:
    """If working tree has modified tracked files, auto-commit them.

    Only commits already-tracked files that have been modified.
    Untracked files are left alone (they'll be committed by commit_file).
    Returns None on success, error message on failure.
    """
    # Check for modified tracked files only (exclude untracked '??')
    stdout, _, rc = await run(
        ["git", "status", "--porcelain"], cwd=str(DOCS_DIR)
    )
    if rc != 0:
        return "Failed to check git status"

    modified = [
        line for line in stdout.strip().split("\n")
        if line and not line.startswith("??")
    ]
    if not modified:
        return None  # No tracked changes

    logger.info("Working tree has modified tracked files, auto-committing")
    _, stderr, rc = await run(
        ["git", "add", "-u"], cwd=str(DOCS_DIR)  # -u: only tracked files
    )
    if rc != 0:
        return f"git add failed: {stderr}"

    _, stderr, rc = await run(
        ["git", "commit", "-m", "chore: auto-commit pending changes"],
        cwd=str(DOCS_DIR),
    )
    if rc != 0:
        return f"git commit failed: {stderr}"

    return None


async def commit_file(path: str, message: str) -> str | None:
    """Stage a specific file and commit. Returns None on success, error on failure."""
    err = await ensure_clean()
    if err:
        return err

    _, stderr, rc = await run(
        ["git", "add", path], cwd=str(DOCS_DIR)
    )
    if rc != 0:
        return f"git add failed: {stderr}"

    _, stderr, rc = await run(
        ["git", "commit", "-m", message], cwd=str(DOCS_DIR)
    )
    if rc != 0:
        # "nothing to commit" is not a real error (file unchanged)
        if "nothing to commit" in stderr:
            logger.info("No changes to commit for: %s", path)
            return None
        return f"git commit failed: {stderr}"

    logger.info("Committed: %s", message)
    return None
