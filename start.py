# Launcher: updates the bot from GitHub, then starts main.py.
# Set the panel's startup file to start.py to use it.
import os
import subprocess
import sys

REPO = "https://github.com/videosaftermath-source/LOJI"
BRANCH = "main"

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def head():
    return git("rev-parse", "HEAD").stdout.strip()


if not os.path.isdir(".git"):
    git("init", "-q")
    git("remote", "add", "origin", REPO)

before = head()
fetch = git("fetch", "-q", "--depth", "1", "origin", BRANCH)
if fetch.returncode == 0:
    # .env is ignored by git, so it is never touched.
    git("reset", "-q", "--hard", "FETCH_HEAD")
    after = head()
    if after != before:
        print(f"[🔄] Updated from GitHub to {after[:7]}", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
        )
    else:
        print(f"[✅] Already up to date ({after[:7]})", flush=True)
else:
    print(f"[⚠️] Could not update from GitHub: {fetch.stderr.strip()}", flush=True)

os.execv(sys.executable, [sys.executable, "main.py", *sys.argv[1:]])
