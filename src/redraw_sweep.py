# -*- coding: utf-8 -*-
"""重绘去噪档位对比：同一份设计规格，只换起始噪声，看哪一档既保住锚点又写得出字。

设计（35b 读图+出规格）只做一次并缓存成 json，后面各档复用，避免每档都吃一次 80s 冷启动。
用法:
  python redraw_sweep.py "片名" --base 底图 --denoise 0.6,0.75,0.9
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import redraw as R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--base", required=True)
    ap.add_argument("--denoise", default="0.6,0.75,0.9")
    ap.add_argument("--mode", default="keep", choices=["recompose", "keep"])
    ap.add_argument("--dignified", action="store_true", help="走端庄路线（默认整幅狂草）")
    ap.add_argument("--hint", default="")
    ap.add_argument("--size", default="1536x864")
    ap.add_argument("--spec", default="", help="复用已有规格 json；为空则重新设计并写回")
    a = ap.parse_args()

    w, h = (int(x) for x in a.size.lower().split("x"))
    spec_path = a.spec or os.path.join(C.CACHE_DIR, "redraw_spec_%s.json" % a.text)
    os.makedirs(C.CACHE_DIR, exist_ok=True)

    if os.path.exists(spec_path):
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        print("[复用规格]", spec_path)
    else:
        t0 = time.time()
        spec = R.design(a.text, a.base, a.hint)
        print("[设计完成] %.1fs" % (time.time() - t0))
        if spec.get("error"):
            print("[失败]", spec["error"])
            return
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        print("[规格已缓存]", spec_path)

    outs = []
    for d in [float(x) for x in a.denoise.split(",")]:
        print("\n===== denoise %.2f =====" % d)
        r = R.redraw(a.text, a.base, a.hint, size=(w, h), denoise=d,
                     reuse_spec=spec, mode=a.mode, cursive=not a.dignified)
        print("[结果]", r["status"], r["dst"] or "")
        outs.append((d, r.get("dst")))

    print("\n===== 汇总 =====")
    for d, p in outs:
        print("denoise %.2f -> %s" % (d, p or "失败"))


if __name__ == "__main__":
    main()
