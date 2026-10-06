#!/usr/bin/env python3
"""Build the synthetic 'alpha' repository with hand-computed metrics.

History (1 step = 1 commit; all committer dates fixed at 2023-01-k 12:00 UTC):

  c1  Alice <alice@x>   + src/a.txt (3 lines)  + README.md (2)  + .mailmap (2)
  c2  Bob <b@x>         ~ src/a.txt  (adds l2b,l4; removes l2)     -> +2/-1
  c3  A2 <a2@x>         rename src/a.txt -> src/b.txt, append l5   -> +1/-0 on new path
  c4  Alice <alice@x>   pure rename src/b.txt -> src/c.txt         -> no metric change
  c5  B2 <b2@x>         delete src/c.txt                           -> -5 on path
  c6  Alice <alice@x>   + bin/data.bin (binary)                    -> not measured
  c7  Bob <b@x>         + src/deep/d.txt (1)                       -> +1
  c8  A2 <a2@x>         empty commit                               -> no change
  c9  Alice <alice@x>   + 'space name.txt' (2)                     -> +2
  c10 Bob <b@x>         + 'ünïcode.txt' (1)                        -> +1

.mailmap maps <a2@x> -> Canonical A <a@x> and <b2@x> -> Canonical B <b@x>.
"""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "_scratch" / "fixtures" / "alpha"


def run(*args):
    subprocess.run(args, cwd=FIX, check=True, capture_output=True)


def write(rel, content):
    p = FIX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


def commit(k, name, email, msg):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_COMMITTER_NAME=name,
        GIT_COMMITTER_EMAIL=email,
        GIT_AUTHOR_DATE=f"2023-01-{k:02d}T12:00:00Z",
        GIT_COMMITTER_DATE=f"2023-01-{k:02d}T12:00:00Z",
    )
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=FIX, env=env, check=True
    )


def main():
    if FIX.exists():
        shutil.rmtree(FIX)
    FIX.mkdir(parents=True)
    run("git", "init", "-q", "-b", "main")

    write("src/a.txt", "l1\nl2\nl3\n")
    write("README.md", "# Alpha\nHello\n")
    write(".mailmap", "Canonical A <a@x> <a2@x>\nCanonical B <b@x> <b2@x>\n")
    run("git", "add", "-A")
    commit(1, "Alice", "alice@x", "c1")

    write("src/a.txt", "l1\nl2b\nl3\nl4\n")
    run("git", "add", "-A")
    commit(2, "Bob", "b@x", "c2")

    run("git", "mv", "src/a.txt", "src/b.txt")
    write("src/b.txt", "l1\nl2b\nl3\nl4\nl5\n")
    run("git", "add", "-A")
    commit(3, "A2", "a2@x", "c3")

    run("git", "mv", "src/b.txt", "src/c.txt")
    commit(4, "Alice", "alice@x", "c4")

    os.remove(FIX / "src/c.txt")
    run("git", "add", "-A")
    commit(5, "B2", "b2@x", "c5")

    write("bin/data.bin", b"abc\x00def")
    run("git", "add", "-A")
    commit(6, "Alice", "alice@x", "c6")

    write("src/deep/d.txt", "d1\n")
    run("git", "add", "-A")
    commit(7, "Bob", "b@x", "c7")

    commit(8, "A2", "a2@x", "c8")

    write("space name.txt", "s1\ns2\n")
    run("git", "add", "-A")
    commit(9, "Alice", "alice@x", "c9")

    write("ünïcode.txt", "u\n")
    run("git", "add", "-A")
    commit(10, "Bob", "b@x", "c10")

    print(f"fixture built at {FIX}")


if __name__ == "__main__":
    main()
