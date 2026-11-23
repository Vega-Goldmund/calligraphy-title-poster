"""把 ComfyUI 以完全脱离控制台的方式拉起（DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP）。

之前用 Start-Process / cmd /c 起，进程都挂在调用它的控制台进程组里：
命令一结束控制台关闭，会向整组发 Ctrl+C，ComfyUI 就被打断（日志尾部是 ^C）。
路径、端口、输出目录全部来自 config，可用环境变量覆盖。
"""
import os
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

PY = C.COMFY_PY
WD = C.COMFY_PORTABLE
LOG = os.path.join(C.COMFY_ROOT, "comfy_run.log")

_parsed = urlparse(C.COMFY_URL)
HOST = _parsed.hostname or "127.0.0.1"
PORT = str(_parsed.port or 8188)

ARGS = [PY, "-u", "-s", "ComfyUI\\main.py", "--windows-standalone-build",
        "--listen", HOST, "--port", PORT,
        "--output-directory", C.OUTPUT_DIR,
        "--input-directory", C.INPUT_DIR,
        "--reserve-vram", "2.0", "--fast", "fp16_accumulation"]

DETACHED = 0x00000008
NEW_GROUP = 0x00000200


def launch():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", buffering=1, encoding="utf-8", errors="ignore")
    f.write("\n\n=== launch ===\n")
    p = subprocess.Popen(ARGS, cwd=WD, stdin=subprocess.DEVNULL,
                         stdout=f, stderr=subprocess.STDOUT,
                         creationflags=DETACHED | NEW_GROUP, close_fds=True)
    return p.pid


if __name__ == "__main__":
    print("comfy pid", launch())
