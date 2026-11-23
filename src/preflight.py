"""环境自检：核对本地 ComfyUI / Ollama / 模型 / 参考图 / 目录 / GPU 是否就绪。

用法：
  python preflight.py            人类可读报告，缺失项给出修复建议
  python preflight.py --json     输出结构化结果
  python preflight.py --fix      自动修复可修复项（建目录、从 assets 同步参考图）

退出码：全部关键项通过为 0，否则为 1（GPU/胶片依赖等仅警告，不致命）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

CHECKS = []


def _record(item, ok, detail="", fix="", critical=True):
    CHECKS.append(dict(item=item, ok=ok, detail=detail, fix=fix, critical=critical))


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def check_dirs(autofix):
    for name, d in (("ComfyUI 根目录", C.COMFY_ROOT),
                    ("input 目录", C.INPUT_DIR),
                    ("output 目录", C.OUTPUT_DIR)):
        _record(name, os.path.isdir(d), d,
                "检查 TG_COMFY_ROOT / TG_INPUT_DIR / TG_OUTPUT_DIR 配置")
    try:
        os.makedirs(C.SAVE_DIR, exist_ok=True)
        os.makedirs(C.CACHE_DIR, exist_ok=True)
        _record("成片/缓存目录可写", True, C.SAVE_DIR)
    except Exception as e:
        _record("成片/缓存目录可写", False, repr(e)[:120])


def check_ollama():
    try:
        tags = {m.get("name"): m for m in _get(C.OLLAMA_URL + "/api/tags").get("models", [])}
        _record("Ollama 服务在线", True, C.OLLAMA_URL)
    except Exception as e:
        _record("Ollama 服务在线", False, repr(e)[:120],
                "启动 Ollama 后重试（命令行 ollama serve）")
        return
    for role, model in (("导演模型", C.DIRECTOR_MODEL),
                        ("质检模型", C.CHECK_MODEL),
                        ("导演兜底模型", C.DIRECTOR_FALLBACK)):
        _record(f"{role} {model}", model in tags,
                "已安装" if model in tags else "未在 ollama list 中",
                f"ollama pull {model}")


def check_comfy():
    try:
        stats = _get(C.COMFY_URL + "/system_stats")
        _record("ComfyUI 服务在线", True,
                C.COMFY_URL + "  " + stats.get("system", {}).get("comfyui_version", ""))
    except Exception as e:
        _record("ComfyUI 服务在线", False, repr(e)[:120],
                "运行 python launch_comfy.py 拉起本地 ComfyUI")
        return
    # Qwen-Image 节点由 ComfyUI 官方 comfy_extras.nodes_qwen 提供，版本过老会缺失
    for node in ("TextEncodeQwenImage21", "QwenImage21Cache"):
        try:
            info = _get(f"{C.COMFY_URL}/object_info/{node}")
            mod = (info.get(node) or {}).get("python_module", "")
            _record(f"节点 {node}", bool(info.get(node)), mod or "缺失",
                    "升级 ComfyUI 到含 comfy_extras.nodes_qwen 的版本（0.45.0 实测可用）")
        except Exception as e:
            _record(f"节点 {node}", False, "无法读取: " + repr(e)[:80],
                    "升级 ComfyUI 版本")

    # 通过 object_info 拿各 loader 实际可用文件名，避免硬猜目录结构
    targets = [("UNETLoader", C.UNET_NAME, "绘图 UNET"),
               ("CLIPLoader", C.CLIP_NAME, "CLIP"),
               ("VAELoader", C.VAE_NAME, "VAE")]
    for node, want, label in targets:
        try:
            info = _get(f"{C.COMFY_URL}/object_info/{node}")
            opts = info[node]["input"]["required"]
            names = []
            for v in opts.values():
                if isinstance(v, list) and v and isinstance(v[0], list):
                    names = v[0]
                    break
            _record(f"{label} {want}", want in names,
                    "可用" if want in names else "该节点可选列表中没有",
                    "把模型放到 ComfyUI models 对应目录，或用 TG_* 环境变量改名")
        except Exception as e:
            _record(f"{label} {want}", False, "无法读取 object_info: " + repr(e)[:80])


def check_refs(autofix):
    for key, (fname, desc) in C.TPLS.items():
        sub = C.REF_SUBFOLDER.get(fname, "")
        dst_dir = os.path.join(C.INPUT_DIR, sub) if sub else C.INPUT_DIR
        dst = os.path.join(dst_dir, fname)
        ok = os.path.exists(dst)
        if not ok and autofix:
            src = os.path.join(C.ASSETS_DIR, fname)
            if os.path.exists(src):
                os.makedirs(dst_dir, exist_ok=True)
                import shutil
                shutil.copy(src, dst)
                ok = True
        _record(f"笔法参考图 {fname}（{desc}）", ok,
                dst_dir if ok else "input 目录缺失",
                "用 --fix 从 assets 同步，或手动放入 ComfyUI input 对应子目录")


def check_vision():
    """底图重绘（可选功能）需要多模态模型；默认复用导演模型，没有也不影响文生图。"""
    model = C.REDRAW_VISION_MODEL or C.DIRECTOR_MODEL
    label = "重绘视觉模型（可选）" + model
    try:
        tags = {m.get("name") for m in _get(C.OLLAMA_URL + "/api/tags").get("models", [])}
    except Exception:
        _record(label, False, "Ollama 不可用，仅 --base 重绘受影响", critical=False)
        return
    if model not in tags:
        _record(label, False, "未安装；只有 --base 重绘才需要",
                fix=f"ollama pull {model}", critical=False)
        return
    try:
        req = urllib.request.Request(
            C.OLLAMA_URL + "/api/show",
            data=json.dumps({"name": model}).encode(),
            headers={"Content-Type": "application/json"})
        info = json.loads(urllib.request.urlopen(req, timeout=15).read())
        has = "vision" in (info.get("capabilities") or [])
        _record(label, has,
                "带 vision，可读底图" if has else "没有 vision 能力，读不了底图",
                fix="换多模态模型，或用 TG_REDRAW_VISION_MODEL 指定", critical=False)
    except Exception as e:
        _record(label, False, "无法查询能力: " + repr(e)[:80],
                fix="确认 ollama 版本支持 /api/show", critical=False)


def check_python_extras():
    for mod, label in (("PIL", "Pillow（出图/后处理）"), ("numpy", "numpy（胶片后处理）")):
        _record(f"依赖 {label}", importlib.util.find_spec(mod) is not None,
                critical=False,
                fix="当前 python 安装 " + mod + "（胶片后处理才需要，不影响主出图）")


def check_gpu():
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    for cand in (exe, "nvidia-smi"):
        try:
            out = subprocess.run([cand, "--query-gpu=name,memory.total",
                                  "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=15)
            if out.returncode == 0:
                _record("GPU 可见", True, out.stdout.strip(), critical=False)
                return
        except Exception:
            continue
    _record("GPU 可见", False, "未找到 nvidia-smi", critical=False,
            fix="确认 NVIDIA 驱动正常；驱动级卡死需重启机器")


def run(autofix=False):
    check_dirs(autofix)
    check_ollama()
    check_comfy()
    check_refs(autofix)
    check_vision()
    check_python_extras()
    check_gpu()
    return CHECKS


def _print_report():
    critical_fail = [c for c in CHECKS if not c["ok"] and c["critical"]]
    warn = [c for c in CHECKS if not c["ok"] and not c["critical"]]
    for c in CHECKS:
        mark = "[OK] " if c["ok"] else ("[!!] " if c["critical"] else "[--] ")
        line = mark + c["item"]
        if c["detail"]:
            line += " — " + c["detail"]
        print(line)
        if not c["ok"] and c["fix"]:
            print("       修复: " + c["fix"])
    print("\n关键项: " +
          ("全部通过" if not critical_fail else f"{len(critical_fail)} 项未通过") +
          (f"；{len(warn)} 个可选项警告" if warn else ""))
    return 0 if not critical_fail else 1


if __name__ == "__main__":
    autofix = "--fix" in sys.argv
    as_json = "--json" in sys.argv
    run(autofix=autofix)
    if as_json:
        print(json.dumps(CHECKS, ensure_ascii=False, indent=1))
        sys.exit(0 if all(c["ok"] for c in CHECKS if c["critical"]) else 1)
    sys.exit(_print_report())
