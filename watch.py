#!/usr/bin/env python3
"""Publish Revit models dropped into a folder (a mounted Google Drive) and send the link.

Usage:
  watch.py             one pass: upload new files, finish pending ones, notify
  watch.py --dry-run   list what a pass would upload, change nothing

Settings (.env): WATCH_DIR (required), WATCH_MONTH_LIMIT (20), WATCH_NOTIFY_TOPIC (Модели),
WATCH_WAIT (600, seconds one pass waits for translations).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import aps
import cf

STATE = aps.ROOT / "watch.state.json"
VIEW = {"dir": [-1, 1, 1.3]}
SETTLE = 120          # a file younger than this may still be arriving
MAX_TRIES = 3         # upload attempts before giving up on a file
STALE = 3 * 3600      # a translation older than this is reported as failed
CLAUDE_TG = shutil.which("claude-tg") or str(Path.home() / ".local/bin/claude-tg")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"files": {}, "used": {}}


def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def notify(text, link=None):
    cmd = [CLAUDE_TG, "notify", "--topic", os.environ.get("WATCH_NOTIFY_TOPIC", "Модели")]
    if link:
        cmd += ["--button", f"Открыть модель={link}"]
    try:
        subprocess.run(cmd, input=text, text=True, timeout=60, stdout=subprocess.DEVNULL)
    except Exception as e:  # a failed send never stops the pass
        print(f"notify failed: {e}", file=sys.stderr)


def quota(state):
    month = time.strftime("%Y-%m")
    return month, state["used"].get(month, 0), int(os.environ.get("WATCH_MONTH_LIMIT", "20"))


def new_files(state, folder):
    now = time.time()
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.name.startswith((".", "~")):
            continue
        st = p.stat()
        key = f"{p.name}|{st.st_size}|{int(st.st_mtime)}"
        f = state["files"].get(key)
        month = time.strftime("%Y-%m")
        retry = f and (f["status"] == "retry" or (f["status"] == "limit" and f["month"] != month))
        if (f and not retry) or now - st.st_mtime < SETTLE:
            continue
        yield key, p


def take(state, key, path):
    """Upload one new file; returns False when the pass should report an error."""
    f = state["files"].setdefault(key, {"name": path.stem, "tries": 0})
    month, used, limit = quota(state)
    if path.suffix.lower() != ".rvt":
        f["status"] = "ignored"
        notify(f"Файл «{path.name}» в папке моделей пропущен: беру только файлы Revit (.rvt).\n"
               "Если это модель со связанными файлами, напишите мне, какой файл главный.")
        return True
    if used >= limit:
        f.update(status="limit", month=month)
        notify(f"Модель «{path.stem}» не выложена: в этом месяце уже использовано {used} из {limit} "
               "бесплатных преобразований. Выложу автоматически в начале следующего месяца.")
        return True
    f["tries"] += 1
    try:
        up = aps.upload(str(path))
    except (SystemExit, Exception) as e:
        print(f"upload {path.name}: {e}", file=sys.stderr)
        f["status"] = "retry" if f["tries"] < MAX_TRIES else "failed"
        if f["status"] == "failed":
            notify(f"Модель «{path.stem}» не удалось загрузить с трёх попыток. Напишите мне, разберусь.")
        return False
    state["used"][month] = used + 1
    f.update(status="pending", urn=up["urn"], started=time.time(), month=month)
    return True


def finish(state, f):
    """Check one pending translation; True when it is no longer pending."""
    m = aps.manifest(f["urn"])
    if m["status"] == "success":
        f["link"] = cf.add(f["urn"], f["name"], VIEW)
        f["status"] = "done"
        _, used, limit = quota(state)
        notify(f"Модель «{f['name']}» выложена.\nСсылка для просмотра: {f['link']}\n"
               f"В этом месяце использовано {used} из {limit} преобразований.", f["link"])
    elif m["status"] in ("failed", "timeout") or time.time() - f["started"] > STALE:
        f["status"] = "failed"
        print(f"translation {f['name']}: {m}", file=sys.stderr)
        notify(f"Модель «{f['name']}» загружена, но подготовить её к просмотру не удалось. "
               "Напишите мне, разберусь.")
    return f["status"] != "pending"


def run(dry=False):
    folder = Path(os.environ["WATCH_DIR"]).expanduser()
    if not folder.is_dir():
        raise SystemExit(f"WATCH_DIR is not a folder: {folder}")
    state = load_state()
    if dry:
        for key, p in new_files(state, folder):
            print("would take", p.name)
        return
    ok = True
    for key, p in list(new_files(state, folder)):
        ok = take(state, key, p) and ok
        save_state(state)
    deadline = time.time() + int(os.environ.get("WATCH_WAIT", "600"))
    while True:
        pending = [f for f in state["files"].values() if f["status"] == "pending"]
        for f in pending:
            finish(state, f)
            save_state(state)
        if all(f["status"] != "pending" for f in pending) or time.time() > deadline:
            break
        time.sleep(20)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    aps.load_env()
    a = sys.argv[1:]
    if a in ([], ["--dry-run"]):
        run(dry=bool(a))
    else:
        raise SystemExit(__doc__)
