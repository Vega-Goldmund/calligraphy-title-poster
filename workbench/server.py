# -*- coding: utf-8 -*-
"""片名工作台 · 本地服务

只调用已封包的 calligraphy-title-poster skill，不修改它的任何文件。
启动后浏览器打开 http://127.0.0.1:8790
"""
import glob
import json
import mimetypes
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库根目录；也可用 TG_SKILL_ROOT 指向已安装的 skill 目录
SKILL_ROOT = os.environ.get("TG_SKILL_ROOT") or os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_ROOT, "src")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import config as C  # noqa: E402  只读引用 skill 的路径配置

SAVE_DIR = C.SAVE_DIR
UPLOAD_DIR = os.path.join(HERE, "uploads")
LOG_DIR = os.path.join(HERE, "logs")
JOBS_FILE = os.path.join(HERE, "jobs.json")
RUNNER = os.path.join(HERE, "runner.py")
PY = sys.executable

for d in (UPLOAD_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)


def _crash(exc_type, exc, tb):
    """未捕获异常写 logs/server.err，免得后台静默死掉查不到原因。"""
    try:
        with open(os.path.join(LOG_DIR, "server.err"), "a", encoding="utf-8") as f:
            f.write("\n[%s] %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), exc))
            traceback.print_exception(exc_type, exc, tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _crash

ALLOW_ROOTS = [SAVE_DIR, UPLOAD_DIR, os.path.join(HERE, "outputs"),
               os.path.join(SKILL_ROOT, "assets"), C.INPUT_DIR]
for d in ALLOW_ROOTS:
    os.makedirs(d, exist_ok=True)

ROUTE_PREFIX = {"single": "single_", "set": "set_", "ref": "ref_", "redraw": "redraw_",
                "alpha": "alpha_", "video": "write_", "comp": "comp_"}

LOCK = threading.Lock()
JOBS = {}
ORDER = []
QUEUE = deque()
STATE = {"worker": None, "current": None}


# ------------------------------------------------------------------ 工具
def http_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


COMFY_CANDIDATES = ["http://127.0.0.1:8188", "http://127.0.0.1:8191",
                    "http://127.0.0.1:8189", "http://127.0.0.1:8187",
                    "http://127.0.0.1:8190"]
_SYNC = {"url": "", "t": 0.0}
_ENV = {"t": 0.0, "v": None}


def sync_comfy(force=False):
    """ComfyUI 可能不在 8188（自己另开了个端口、或重启后换了端口）。
    这里在候选端口里挑一个活着的接上，并把 TG_COMFY_URL 传给子进程。
    探活结果缓存 10 秒，别让界面每 3 秒轮询都去扫一遍端口（会把接口拖到十秒级）。"""
    now = time.time()
    if not force and now - _SYNC["t"] < 10:
        return _SYNC["url"]
    if http_json(C.COMFY_URL + "/system_stats", timeout=1.2):
        _SYNC.update(url=C.COMFY_URL, t=now)
        return C.COMFY_URL
    found = ""
    for u in COMFY_CANDIDATES:
        if u == C.COMFY_URL:
            continue
        if http_json(u + "/system_stats", timeout=1.2):
            C.COMFY_URL = u
            os.environ["TG_COMFY_URL"] = u
            found = u
            break
    _SYNC.update(url=found, t=now)
    return found


def png_size(path):
    """读 PNG 头拿宽高，避免为 400 张图开 PIL。"""
    try:
        if os.path.getsize(path) < 33:
            return None
        with open(path, "rb") as f:
            head = f.read(33)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return [w, h]
    except Exception:
        return None


def safe_path(p):
    try:
        rp = os.path.realpath(p)
        for root in ALLOW_ROOTS:
            rr = os.path.realpath(root)
            if rp == rr or rp.startswith(rr + os.sep):
                return rp
    except Exception:
        pass
    return None


def job_log(jid):
    return os.path.join(LOG_DIR, jid + ".log")


def save_jobs():
    with LOCK:
        data = [JOBS[i] for i in ORDER if i in JOBS][:300]
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return
    try:
        data = json.load(open(JOBS_FILE, encoding="utf-8"))
    except Exception:
        return
    for j in data:
        if j.get("status") == "running":
            j["status"] = "failed"
            j["error"] = "上次退出时中断"
        JOBS[j["id"]] = j
        ORDER.append(j["id"])


# ------------------------------------------------------------------ 任务
def new_job(route, text, params):
    jid = time.strftime("%m%d%H%M%S") + "-" + str(random.randint(0, 999)).zfill(3)
    j = dict(id=jid, route=route, text=text, params=params, status="queued",
             created=int(time.time()), started=None, finished=None,
             seed=params.get("seed") or None, dst=None, artifacts=[], error=None, seconds=None)
    with LOCK:
        JOBS[jid] = j
        ORDER.insert(0, jid)
    QUEUE.append(jid)
    save_jobs()
    return jid


def worker():
    while True:
        try:
            jid = QUEUE.popleft()
        except IndexError:
            time.sleep(0.4)
            continue
        if jid not in JOBS:
            continue
        j = JOBS[jid]
        if j["status"] == "cancelled":
            continue
        j["status"] = "running"
        j["started"] = int(time.time())
        STATE["current"] = jid
        save_jobs()

        def bail(msg):
            """开跑前的硬拦：不满足条件就别把 ComfyUI 推崩，直接把原因写给用户。"""
            j["status"] = "failed"
            j["error"] = msg
            j["finished"] = int(time.time())
            STATE["current"] = None
            save_jobs()

        # ComfyUI 不在（换了端口或根本没开）：直接说清楚，别让 runner 去等 600 秒
        if not sync_comfy() and not http_json(C.COMFY_URL + "/system_stats", timeout=2):
            bail("ComfyUI 没在跑（8188 / 8189 都没响应）。点左上角那盏灯启动，或先把 ComfyUI 开起来。")
            continue

        pf = os.path.join(LOG_DIR, jid + ".params.json")
        payload = dict(route=j["route"], text=j["text"], **j["params"])
        with open(pf, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        # 端口有可能被换过（用户自己另起了一个 ComfyUI），出图前重新认一次
        sync_comfy()
        env["TG_COMFY_URL"] = C.COMFY_URL
        # 任务前先让 Comfy 交还上一张占的显存，跨任务连跑才稳
        comfy_free()
        time.sleep(2)
        timeout = 7200 if j["route"] == "video" else (3600 if (j["params"] or {}).get("combo", 1) > 1 else 1800)
        try:
            with open(job_log(jid), "w", encoding="utf-8") as lf:
                p = subprocess.Popen([PY, "-u", RUNNER, pf], cwd=HERE, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     bufsize=1, universal_newlines=True,
                                     encoding="utf-8", errors="replace")
                j["_proc"] = p.pid
                t0 = time.time()
                for line in p.stdout:
                    lf.write(line)
                    lf.flush()
                    if line.startswith("##RESULT##"):
                        try:
                            r = json.loads(line[len("##RESULT##"):])
                            if r.get("dst"):
                                j["dst"] = r["dst"]
                                if r["dst"] not in j["artifacts"]:
                                    j["artifacts"].append(r["dst"])
                            for k in ("seed", "seconds", "missing", "reliable", "status"):
                                if r.get(k) not in (None, "", []):
                                    j[k] = r[k]
                        except Exception:
                            pass
                        continue
                    m = re.match(r"^-> (.+)$", line.strip())
                    if m:
                        pth = m.group(1).strip()
                        if pth and pth not in j["artifacts"]:
                            j["artifacts"].append(pth)
                            if not j["dst"]:
                                j["dst"] = pth
                    m2 = re.search(r"seed (\d+)", line)
                    if m2 and not j.get("seed"):
                        j["seed"] = int(m2.group(1))
                    if time.time() - t0 > timeout:
                        p.kill()
                        j["error"] = "超时终止"
                        break
                rc = p.wait()
            j["seconds"] = round(time.time() - j["started"])
            if j["status"] != "cancelled":
                if j["dst"]:
                    j["status"] = "done"
                else:
                    j["status"] = "failed"
                    j["error"] = j.get("error") or "没有产出文件，看日志末尾的报错"
            if rc not in (0, None) and not j["dst"] and not j["error"]:
                j["error"] = "退出码 %s" % rc
        except Exception as e:
            j["status"] = "failed"
            j["error"] = repr(e)[:300]
        finally:
            j["finished"] = int(time.time())
            j.pop("_proc", None)
            STATE["current"] = None
            save_jobs()


def comfy_free():
    """让 ComfyUI 交还上一张图占着的显存/模型缓存。跨任务连跑时不做这一步，
    下一次加载文本编码器会和上一张的 UNet 抢显存，实测会直接把进程 abort 掉。"""
    try:
        req = urllib.request.Request(
            C.COMFY_URL + "/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=12).read()
        return True
    except Exception:
        return False


def kill_comfy():
    """只杀当前端口上的 ComfyUI main.py 进程（崩溃后卡住的那种僵尸态）。"""
    killed = []
    port = str(urllib.parse.urlparse(C.COMFY_URL).port or 8188)
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cl = " ".join(p.info.get("cmdline") or [])
                if ("main.py" in cl and "ComfyUI" in cl
                        and re.search(r"--port\s+" + re.escape(port), cl)):
                    p.kill()
                    killed.append(p.info["pid"])
            except Exception:
                continue
    except Exception:
        pass
    return killed


def start_worker():
    if STATE["worker"] and STATE["worker"].is_alive():
        return
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    STATE["worker"] = t


def watchdog():
    """ComfyUI 中途崩掉时，runner 会卡在轮询里等 600 秒。这里直接判死，别让用户干等。"""
    bad = 0
    while True:
        time.sleep(10)
        jid = STATE.get("current")
        if not jid:
            bad = 0
            continue
        j = JOBS.get(jid)
        if not j or j.get("status") != "running":
            bad = 0
            continue
        if http_json(C.COMFY_URL + "/system_stats", timeout=4):
            bad = 0
            continue
        bad += 1
        if bad >= 2 and j.get("_proc"):
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(j["_proc"])],
                               capture_output=True, timeout=20)
            except Exception:
                pass
            j["error"] = "ComfyUI 中途退出（Fatal / CUDA 崩溃），任务已终止。重启 ComfyUI 后再试。"
            j["status"] = "failed"
            j["finished"] = int(time.time())
            save_jobs()
            bad = 0


def kill_job(jid):
    j = JOBS.get(jid)
    if not j:
        return False
    with LOCK:
        if jid in QUEUE:
            QUEUE.remove(jid)
    j["status"] = "cancelled"
    pid = j.get("_proc")
    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        except Exception:
            pass
    save_jobs()
    return True


# ------------------------------------------------------------------ 环境状态
def env_status():
    now = time.time()
    if _ENV["v"] is not None and now - _ENV["t"] < 2.5:
        return _ENV["v"]
    stats = http_json(C.COMFY_URL + "/system_stats", timeout=1.2)
    if not stats:
        if sync_comfy(force=True):
            stats = http_json(C.COMFY_URL + "/system_stats", timeout=1.2)
    comfy = {"up": bool(stats), "url": C.COMFY_URL,
             "port": urllib.parse.urlparse(C.COMFY_URL).port or 8188}
    if stats:
        try:
            devs = stats.get("devices") or stats.get("system", {}).get("devices") or []
            d0 = devs[0] if devs else {}
            free = d0.get("vram_free") or d0.get("torch_vram_free") or 0
            total = d0.get("vram_total") or d0.get("torch_vram_total") or 0
            if total:
                comfy["vram_free"] = round(free / (1024 ** 3), 1)
                comfy["vram_total"] = round(total / (1024 ** 3), 1)
        except Exception:
            pass
    tags = http_json(C.OLLAMA_URL + "/api/tags")
    ollama = {"up": bool(tags), "models": []}
    if tags:
        ollama["models"] = [m.get("name") for m in tags.get("models", [])][:12]
    return {"comfy": comfy, "ollama": ollama,
            "running": STATE["current"], "queued": len(QUEUE),
            "save_dir": SAVE_DIR, "python": PY}


def gallery(route="", q="", limit=300):
    items = []
    pats = ["*.png", "*.mp4"]
    files = []
    for p in pats:
        files.extend(glob.glob(os.path.join(SAVE_DIR, p)))
    files.sort(key=os.path.getmtime, reverse=True)
    for f in files[: max(limit * 2, 400)]:
        name = os.path.basename(f)
        r = ""
        for k, pre in ROUTE_PREFIX.items():
            if name.startswith(pre):
                r = k
                break
        if r == "set":
            r = "single"
        if route and r != route:
            continue
        if q and q.lower() not in name.lower():
            continue
        item = {"path": f, "name": name, "route": r,
                "mtime": int(os.path.getmtime(f)), "bytes": os.path.getsize(f)}
        if name.lower().endswith(".png"):
            sz = png_size(f)
            if sz:
                item["w"], item["h"] = sz
        items.append(item)
        if len(items) >= limit:
            break
    return items


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self):
        try:
            return json.loads(self._body().decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        path = u.path

        if path in ("/", "/index.html"):
            p = os.path.join(HERE, "ui.html")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(404, "ui.html 缺失")

        if path == "/api/state":
            with LOCK:
                jobs = [JOBS[i] for i in ORDER if i in JOBS][:80]
            return self._send(200, {"env": env_status(), "jobs": jobs})

        if path == "/api/log":
            jid = (qs.get("id") or [""])[0]
            tail = int((qs.get("tail") or ["200"])[0])
            j = JOBS.get(jid)
            lines = []
            f = job_log(jid)
            if os.path.exists(f):
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        lines = fh.read().splitlines()[-tail:]
                except Exception:
                    pass
            return self._send(200, {"lines": lines,
                                    "status": (j or {}).get("status"),
                                    "dst": (j or {}).get("dst"),
                                    "seconds": (j or {}).get("seconds"),
                                    "error": (j or {}).get("error"),
                                    "artifacts": (j or {}).get("artifacts", [])})

        if path == "/api/gallery":
            return self._send(200, {"items": gallery(
                (qs.get("route") or [""])[0],
                (qs.get("q") or [""])[0],
                int((qs.get("limit") or ["300"])[0]))})

        if path == "/api/pinyin":
            text = (qs.get("text") or [""])[0]
            try:
                import subtitle
                r = subtitle.build(text, tones=(qs.get("tones") or ["1"])[0] != "0",
                                   english=(qs.get("en") or [""])[0])
                return self._send(200, {"ok": True, "text": r, "has": bool(getattr(subtitle, "HAS_PINYIN", False))})
            except Exception as e:
                return self._send(200, {"ok": False, "text": "", "err": repr(e)[:120]})

        if path == "/api/quality":
            fp = safe_path((qs.get("path") or [""])[0])
            if not fp:
                return self._send(400, {"error": "路径不允许"})
            try:
                import quality
                ok, missing, reliable = quality.check((qs.get("text") or [""])[0], fp)
                return self._send(200, {"ok": ok, "missing": missing, "reliable": reliable})
            except Exception as e:
                return self._send(200, {"ok": False, "err": repr(e)[:200]})

        if path == "/file":
            fp = safe_path((qs.get("path") or [""])[0])
            if not fp or not os.path.isfile(fp):
                return self._send(404, {"error": "no file"})
            ctype = "image/png"
            if fp.lower().endswith(".mp4"):
                ctype = "video/mp4"
            elif fp.lower().endswith(".jpg"):
                ctype = "image/jpeg"
            try:
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), ctype)
            except Exception as e:
                return self._send(500, {"error": repr(e)})

        if path == "/asset":
            name = os.path.basename((qs.get("name") or [""])[0])
            fp = safe_path(os.path.join(SKILL_ROOT, "assets", name))
            if not fp or not os.path.isfile(fp):
                return self._send(404, {"error": "no asset"})
            with open(fp, "rb") as f:
                return self._send(200, f.read(), mimetypes.guess_type(fp)[0] or "image/png")

        if path == "/api/thumb":
            fp = safe_path((qs.get("path") or [""])[0])
            if not fp or not os.path.isfile(fp):
                return self._send(404, {"error": "no file"})
            try:
                from PIL import Image
                im = Image.open(fp)
                im.thumbnail((520, 520))
                import io
                buf = io.BytesIO()
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGBA", im.size, (34, 32, 28, 255))
                    bg.alpha_composite(im)
                    bg.convert("RGB").save(buf, "JPEG", quality=82)
                else:
                    im.convert("RGB").save(buf, "JPEG", quality=82)
                return self._send(200, buf.getvalue(), "image/jpeg")
            except Exception as e:
                return self._send(500, {"error": repr(e)})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path

        if path == "/api/job":
            d = self._json()
            route = d.get("route", "single")
            text = (d.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "没有文字"})
            ids = []
            for one in [t.strip() for t in text.splitlines() if t.strip()]:
                ids.append(new_job(route, one, d.get("params", {})))
            return self._send(200, {"ids": ids})

        if path == "/api/cancel":
            d = self._json()
            return self._send(200, {"ok": kill_job(d.get("id"))})

        if path == "/api/upload":
            name = urllib.parse.unquote(self.headers.get("X-Filename", "upload.png"))
            name = re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "_", name)[-60:]
            dest = os.path.join(UPLOAD_DIR, time.strftime("%H%M%S_") + name)
            with open(dest, "wb") as f:
                f.write(self._body())
            return self._send(200, {"path": dest, "name": os.path.basename(dest)})

        if path == "/api/composite":
            d = self._json()
            alpha = safe_path(d.get("alpha") or "")
            base = safe_path(d.get("base") or "")
            if not alpha or not base:
                return self._send(400, {"error": "缺少图片"})
            try:
                from PIL import Image
                a = Image.open(alpha).convert("RGBA")
                b = Image.open(base).convert("RGBA")
                scale = float(d.get("scale") or 0.72)
                scale = max(0.2, min(1.0, scale))
                fit = min(b.size[0] / a.size[0], b.size[1] / a.size[1]) * scale
                a = a.resize((max(1, int(a.size[0] * fit)), max(1, int(a.size[1] * fit)),), Image.LANCZOS)
                pos = (d.get("pos") or "mc")
                mx = int(b.size[0] * 0.04)
                my = int(b.size[1] * 0.04)
                ax = {"l": mx, "c": (b.size[0] - a.size[0]) // 2, "r": b.size[0] - a.size[0] - mx}[pos[1:2] or "c"]
                ay = {"t": my, "m": (b.size[1] - a.size[1]) // 2, "b": b.size[1] - a.size[1] - my}[pos[:1] or "m"]
                out = os.path.join(HERE, "outputs", "comp_%s_%d.png" % (
                    os.path.splitext(os.path.basename(base))[0][:20], int(time.time())))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                b.alpha_composite(a, (max(0, ax), max(0, ay)))
                b.convert("RGB").save(out)
                return self._send(200, {"path": out})
            except Exception as e:
                return self._send(500, {"error": repr(e)[:200]})

        if path == "/api/openfolder":
            d = self._json()
            fp = safe_path(d.get("path") or "")
            if not fp:
                return self._send(400, {"error": "路径不允许"})
            try:
                if os.path.isfile(fp):
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(fp)])
                else:
                    os.startfile(fp)
                return self._send(200, {"ok": True})
            except Exception as e:
                return self._send(500, {"error": repr(e)[:120]})

        if path == "/api/launch_comfy":
            try:
                subprocess.Popen([PY, os.path.join(SCRIPTS, "launch_comfy.py")], cwd=SCRIPTS,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=0x00000008 | 0x00000200)
                return self._send(200, {"ok": True, "msg": "已发出启动命令，约 80–90 秒后灯会变绿"})
            except Exception as e:
                return self._send(500, {"error": repr(e)[:160]})

        if path == "/api/restart_comfy":
            try:
                killed = kill_comfy()
                time.sleep(3)
                subprocess.Popen([PY, os.path.join(SCRIPTS, "launch_comfy.py")], cwd=SCRIPTS,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=0x00000008 | 0x00000200)
                return self._send(200, {"ok": True, "killed": killed,
                                        "msg": ("已清掉卡死的进程并重启，" if killed else "已发出启动命令，")
                                               + "约 30–90 秒后灯会变绿"})
            except Exception as e:
                return self._send(500, {"error": repr(e)[:160]})

        return self._send(404, {"error": "not found"})


def main():
    # --detach：把自己再起一份真正脱离控制台的进程，然后本进程立刻退出。
    # 这样双击 bat 也好、控制台被关掉也好，服务都不会跟着死。
    if "--detach" in sys.argv:
        logf = open(os.path.join(LOG_DIR, "server.out"), "a", buffering=1,
                    encoding="utf-8", errors="ignore")
        logf.write("\n\n=== %s start ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        p = subprocess.Popen([PY, "-u", os.path.abspath(__file__)], cwd=HERE,
                             stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                             creationflags=0x00000008 | 0x00000200, close_fds=True)
        print("工作台已在后台启动 pid=%d" % p.pid)
        return

    # 已经有一个工作台在跑：直接开页面，不再起第二个实例
    try:
        with urllib.request.urlopen("http://127.0.0.1:8790/api/state", timeout=2) as r:
            r.read()
        print("工作台已在运行 -> http://127.0.0.1:8790")
        webbrowser.open("http://127.0.0.1:8790")
        return
    except Exception:
        pass

    sync_comfy(force=True)
    load_jobs()
    start_worker()
    threading.Thread(target=watchdog, daemon=True).start()
    port = 8790
    srv = None
    for p in range(8790, 8800):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if not srv:
        print("8790-8799 都被占用")
        return
    url = "http://127.0.0.1:%d" % port
    print("片名工作台 ->", url)
    print("输出目录:", SAVE_DIR)
    if not os.environ.get("WB_NO_OPEN"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
