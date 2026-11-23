"""精简 ComfyUI 客户端：提交 workflow、轮询 history、返回产出文件名。

替代旧的 style2.py（single 只用到提交/轮询能力，不需要其模板与 design 依赖）。
端点与超时全部来自 config。
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C


class ComfyError(RuntimeError):
    pass


def _get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def is_alive():
    """ComfyUI 是否在线。"""
    try:
        _get_json(C.COMFY_URL + "/system_stats", timeout=8)
        return True
    except Exception:
        return False


def run(wf, poll_interval=1.5, max_wait=600, client_id="title-skill"):
    """提交 workflow 并阻塞到出图，返回 (filename, subfolder)；失败抛 ComfyError。"""
    body = json.dumps({"prompt": wf, "client_id": client_id}).encode()
    req = urllib.request.Request(
        C.COMFY_URL + "/prompt", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            queued = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:900]
        raise ComfyError("提交被拒: " + detail) from e

    pid = queued["prompt_id"]
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            hist = _get_json(f"{C.COMFY_URL}/history/{pid}", timeout=10)
        except Exception:
            continue
        if pid not in hist:
            continue
        status = hist[pid].get("status", {})
        if status.get("status_str") == "error":
            raise ComfyError("执行失败: " + json.dumps(status)[:600])
        images = [im for v in hist[pid].get("outputs", {}).values()
                  for im in v.get("images", [])]
        if images:
            im = images[0]
            return im.get("filename", ""), im.get("subfolder", "")
    raise ComfyError("轮询超时，未在 %ss 内出图" % max_wait)
