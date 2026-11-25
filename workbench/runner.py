# -*- coding: utf-8 -*-
"""片名工作台 · 任务执行器

由 server.py 以子进程方式拉起：python runner.py <params.json>
只 import 已封包 skill 里的模块并调用它们的公开函数，不修改 skill 任何文件。
"""
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.environ.get("TG_SKILL_ROOT") or os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_ROOT, "src")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import config as C  # noqa: E402
import single  # noqa: E402
import redraw as R  # noqa: E402
import transparent_text as TT  # noqa: E402

RESULT = {"dst": None, "seed": None, "seconds": None, "artifacts": []}


def emit(**kw):
    RESULT.update(kw)


def out_path(p):
    if not p:
        return
    # skill 自己已经打印 "-> 路径"，这里不再重复
    if p not in RESULT["artifacts"]:
        RESULT["artifacts"].append(p)
    if not RESULT["dst"]:
        RESULT["dst"] = p


def film(p):
    try:
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "film_post.py"), p],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((r.stdout or "").strip(), flush=True)
        fp = p.replace(".png", "_film.png")
        if os.path.exists(fp):
            out_path(fp)
    except Exception as e:
        print("[film] 失败: %r" % (e,), flush=True)


def unload():
    """把 Ollama 的导演模型踢出显存/内存，再让 ComfyUI 加载大模型。"""
    try:
        R.unload(C.DIRECTOR_MODEL)
    except Exception:
        pass
    try:
        R.unload(C.DIRECTOR_FALLBACK)
    except Exception:
        pass
    time.sleep(5)


def verify(text, p):
    try:
        import quality
        ok, missing, reliable = quality.check(text, p)
        print("[质检] %s%s" % ("合格" if ok else "缺字 " + "".join(missing),
                              "" if reliable else "（服务故障软放行）"), flush=True)
        emit(missing=list(missing), reliable=bool(reliable))
    except Exception as e:
        print("[质检] 失败: %r" % (e,), flush=True)


def main():
    pf = sys.argv[1]
    a = json.load(open(pf, encoding="utf-8"))
    route = a.get("route", "single")
    text = (a.get("text") or "").strip()
    size = tuple(int(x) for x in (a.get("size") or [1536, 864]))
    font = a.get("font") or "cursive"
    seed = int(a.get("seed") or 0)
    hint = a.get("hint") or ""
    style = a.get("style") or (C.STYLE_INK if a.get("inkRhythm") else C.DEFAULT_STYLE)
    if style not in C.STYLES:
        raise SystemExit("未知版式: %s" % style)
    t0 = time.time()

    print("== 工作台任务 ==", flush=True)
    print("路由: %s | 文字: %s | 尺寸: %dx%d | 风格: %s | 版式: %s | 种子: %s"
          % (route, text, size[0], size[1], font, C.STYLE_LABELS.get(style, style),
             seed or "随机"), flush=True)

    # 副标口径：默认关；开了就由 subtitle.py 程序生成
    single.SUBTITLE_FORCE = bool(a.get("sub"))
    single.SUBTITLE_EN = a.get("subEn") or ""
    single.SUBTITLE_TONES = not a.get("noTones")
    R.SUBTITLE_EN = a.get("subEn") or ""
    R.SUBTITLE_TONES = not a.get("noTones")

    if route == "single":
        import director as D
        combo = int(a.get("combo") or 1)
        fresh = not a.get("cache", True)
        if combo > 1:
            print("[多方案] %d 套" % combo, flush=True)
            unload()
            outs = single.render_set(text, hint, k=combo, size=size,
                                     use_cache=not fresh, font=font, style=style)
            for i, o in enumerate(outs):
                if o.get("dst"):
                    print("[方案%d] %s" % (i + 1, o.get("label") or ""), flush=True)
                    out_path(o["dst"])
                    if not RESULT.get("seed") and o.get("seed"):
                        emit(seed=o["seed"])
        else:
            # 导演设计 → 把 35b 踢出显存 → 再出图。
            # 不做这一步时，35b 还在显存/内存里，ComfyUI 加载 8.9G 文本编码器会直接 abort。
            spec = D.direct(text, hint, use_cache=not fresh)
            if spec.get("error"):
                print("[导演失败] %s" % spec["error"], flush=True)
            else:
                unload()
                sd = seed or int(time.time() * 1000) % 1000000
                print("[出图 · seed %d]" % sd, flush=True)
                dst, p = single._render_with_spec(spec, text, sd, size, font, style=style)
                if dst:
                    out_path(dst)
                emit(seed=sd)

    elif route == "redraw":
        base = a.get("base")
        if not base or not os.path.exists(base):
            raise SystemExit("没有可用的底图：%s" % base)
        r = R.redraw(text, base, hint, seed, size, float(a.get("denoise") or 0.90),
                     font=font, mode=(a.get("mode") or "recompose"),
                     subtitle=bool(a.get("sub")),
                     cursive=not a.get("dignified"),
                     use_cache=bool(a.get("cache", True)), style=style)
        if r.get("dst"):
            out_path(r["dst"])
        emit(seed=r.get("seed"))

    elif route == "alpha":
        r = TT.generate(text, seed=seed, size=size,
                        color=a.get("color") or TT.DEFAULT_COLOR, font=font, style=style)
        if r.get("dst"):
            out_path(r["dst"])
        emit(seed=r.get("seed"))

    elif route == "video":
        import write_video as WV
        r = WV.write_video(text, a.get("poster"), base=a.get("base") or None,
                           plate=a.get("plate") or None, seed=seed,
                           size=(768, 448), length=int(a.get("length") or 124),
                           hand=bool(a.get("hand")))
        if r.get("dst"):
            out_path(r["dst"])
        emit(seed=r.get("seed"), seconds=r.get("seconds"))
    else:
        raise SystemExit("未知路由: %s" % route)

    if a.get("film") and RESULT.get("dst") and route != "video":
        film(RESULT["dst"])
    if a.get("verify") and RESULT.get("dst") and route != "video":
        verify(text, RESULT["dst"])

    emit(seconds=round(time.time() - t0))
    print("##RESULT##" + json.dumps(RESULT, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print("[中止] %s" % (e,), flush=True)
        print("##RESULT##" + json.dumps(RESULT, ensure_ascii=False), flush=True)
        raise
    except Exception:
        traceback.print_exc()
        print("##RESULT##" + json.dumps(RESULT, ensure_ascii=False), flush=True)
        raise SystemExit(1)
