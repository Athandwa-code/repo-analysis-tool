"""Repository ingestion: zip archives (containing .git) and full clones."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


def clone(url: str, dest: Path, timeout: int = 3600) -> Path:
    """Full (non-shallow) clone; history is required for metrics."""
    if dest.exists():
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git clone failed: " + proc.stderr.decode("utf-8", "replace").strip()
        )
    return dest


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract an uploaded zip and return the directory that contains .git."""
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest_res)):
                raise ValueError(f"unsafe path in zip: {info.filename!r}")
        zf.extractall(dest)
    candidates = [d for d in dest.rglob(".git") if d.is_dir()]
    if not candidates:
        # some tools produce a bare repo or .git as a plain file
        raise ValueError("zip does not contain a .git directory")
    repo_dir = min(candidates, key=lambda d: len(d.parts)).parent
    return repo_dir
