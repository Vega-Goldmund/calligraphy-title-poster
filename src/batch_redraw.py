# -*- coding: utf-8 -*-
"""重绘功能批量稳定性测试驱动。

严格一次出图：每个用例只提交一次 workflow，不重试、不挑图，这样统计出的
「一次成功率」才是真实的。断点续跑：结果落 batch_result.json，已 rendered
的用例跳过，服务崩溃重启后可接着跑。

用法：
    python batch_redraw.py            # 跑全部（跳过已完成）
    python batch_redraw.py --only 3   # 只跑第 3 个用例（1 起）
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import comfy_client as CC
import single as S
import redraw as R

REF_WEB = os.path.join(C.INPUT_DIR, "ref_web")
RESULT = os.path.join(C.CACHE_DIR, "batch_result.json")
SIZE = (1536, 864)

# (片名, 底图文件名, 期望字数)，按字数从少到多，长句放最后
CASES = [
    ("归途", "web_road.png", 2),
    ("惊蛰", "web_forest.png", 2),
    ("晚风", "web_reed.png", 2),
    ("潮起潮落", "web_sea.png", 4),
    ("万家灯火", "web_city.png", 4),
    ("山河故人", "web_town.png", 4),
    ("雨夜独行", "web_rain.png", 4),
    ("孤灯照海", "web_beacon.png", 4),
    ("高处不胜寒", "web_snow.png", 5),
    ("大漠孤烟直", "web_desert.png", 5),
    ("稻花香里说丰年", "web_rice.png", 7),
    ("当时只道是寻常", "web_alley.png", 7),
    ("人间烟火气最抚凡人心", "web_market.png", 10),
    ("从流行文化与青年消费看新时代伟大变革", "web_youth.png", 18),
]


def _load_result():
    try:
        with open(RESULT, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_result(d):
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def run_one(i, text, base_name, expected):
    base = os.path.join(REF_WEB, base_name)
    t0 = time.time()
    rec = dict(case_id=i, text=text, expected_chars=expected, base=base_name,
               luma=round(R._base_luma(base), 3), seed=0, elapsed_sec=0,
               dst="", status="", anchors=[], color_name="", color_hex="", error="")

    spec = R.design(text, base)
    if spec.get("error"):
        rec.update(status="failed", error=spec["error"], elapsed_sec=round(time.time() - t0, 1))
        return rec

    es = spec.get("element_sheet", {})
    rec["anchors"] = es.get("anchor_elements", [])
    co = spec.get("color", {})
    rec["color_name"] = co.get("name", "")
    rec["color_hex"] = co.get("hex", "")

    # 与 redraw() 一致的默认：关拼音、压端庄走狂草
    spec.setdefault("decoration", {})["subtitle"] = ""
    spec["dignified"] = False

    seed = 700000 + i * 101
    rec["seed"] = seed
    prompt = R.redraw_brief(spec, text, "横版", luma=rec["luma"])

    # 出图前把 35b 踢出显存
    R.unload(C.DIRECTOR_MODEL)
    time.sleep(4)

    ref, _ = C.TPLS.get(spec.get("ref_style", "cursive"), C.TPLS["cursive"])
    try:
        wf = S._wf(prompt, seed, SIZE[0], SIZE[1], "redraw_batch_%d" % seed, ref)
        fn, sub = CC.run(wf)  # 严格一次，失败直接抛，不重试
    except Exception as e:
        rec.update(status="failed", error=repr(e)[:200],
                   elapsed_sec=round(time.time() - t0, 1))
        return rec

    C.ensure_dirs()
    dst = os.path.join(C.SAVE_DIR, "redraw_batch_%s_%d.png" % (text, seed))
    shutil.copy(os.path.join(C.OUTPUT_DIR, sub, fn), dst)
    rec.update(dst=dst, status="rendered", elapsed_sec=round(time.time() - t0, 1))
    print("->", dst, "  %.1fs" % rec["elapsed_sec"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=0)
    a = ap.parse_args()

    result = _load_result()
    for i, (text, base_name, expected) in enumerate(CASES, start=1):
        cid = str(i)
        if a.only and a.only != i:
            continue
        if not a.only and result.get(cid, {}).get("status") == "rendered":
            print("[skip] %d %s" % (i, text))
            continue
        print("\n=== [%d/%d] %s（%d字）on %s ===" % (i, len(CASES), text, expected, base_name))
        try:
            result[cid] = run_one(i, text, base_name, expected)
        except Exception as e:
            result[cid] = dict(case_id=i, text=text, status="failed", error=repr(e)[:200])
        _save_result(result)

    _save_result(result)
    done = sum(1 for v in result.values() if v.get("status") == "rendered")
    print("\nrendered %d / %d" % (done, len(CASES)))


if __name__ == "__main__":
    main()
