# -*- coding: utf-8 -*-
"""书写过程视频（可选功能，默认不调用）。

主流程 run.py 不挂这个分支：它需要额外约 44GB 的 MiniMax H3 权重、
单条要 110 秒以上、且约 1/4 概率需要重跑，不适合进常规出图链路。
只在显式运行本脚本时才用。

做法（三条硬规则，缺一条就会翻车）：
1. 首帧必须完全无字 —— 否则 H3 只会「对焦变清晰」，不写字；
2. 首尾帧必须同构图 —— 否则 H3 会演「切到纸面写黑墨」或「从黑场淡入」；
3. 提示词不提手/笔/纸 —— 一提就调到「纸面黑墨特写」先验（cfg=1 时否定词无效）。

所以先要一张「同场景无字底版」：用重绘那套元素清单、同一个种子、同一套 workflow，
把写字相关的句子全去掉再出一张（15 秒左右）。有现成底版就用 --plate 传进来。

用法：
    python src/write_video.py 雨夜独行 --poster 成片.png --base 照片.png
    python src/write_video.py 雨夜独行 --poster 成片.png --base 照片.png --hand
    python src/write_video.py 标题 --poster 成片.png --plate 底版.png --seed 731601
    python src/write_video.py 标题 --poster 成片.png --base 照片.png --dry   # 只出提示词

产出：<SAVE_DIR>/write_<片名>_<seed>.mp4（768×448，124 帧≈5.2 秒，带 H3 自生成的音轨）。
"""
import argparse
import glob
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C
import comfy_client as CC
import director as D
import single as S

# H3 的帧数必须落在 17k+5 网格上：124≈5.2s，训练区间约 124–362 帧
LENGTH_GRID = 17
LENGTH_OFFSET = 5

_ETH = ("烟", "雾", "蒸汽", "热气", "尘", "光晕", "光束")


# ---------------------------------------------------------------- 底版

def clean_prompt(spec, orient="横版"):
    """只用重绘规格里的背景那半段，一个字都不提。保持同一处地方、同一批人、同一个时刻。"""
    ES = spec.get("element_sheet") or {}
    parts = ["这是一张%s情绪海报，胶片质感、粗颗粒。" % orient]
    scene = D._clean(ES.get("scene") or "")
    if scene:
        parts.append("画面是" + scene + "。")
    anchors = [D._clean(x) for x in (ES.get("anchor_elements") or []) if D._clean(x)]
    if anchors:
        parts.append("必须原样保留的识别元素：" + "、".join(anchors[:5]) +
                     "；位置、朝向、体量基本不变，每一个都实际出现、肉眼可见，一个不能少。")
    eth = [a for a in anchors if any(k in a for k in _ETH)]
    if eth:
        parts.append("特别盯住" + "、".join(eth) +
                     "：要画在远处主体棱线或光源后方，被天光或逆光勾出细而连贯的边缘，"
                     "和背景有肉眼可辨的明暗差，不许用空留白代替。")
    key_el = [D._clean(x) for x in (ES.get("key_elements") or []) if D._clean(x)]
    people = [x for x in key_el if any(k in x for k in ("人", "队伍", "青年", "游客", "村民", "学生", "群像"))]
    if people:
        parts.append("照片里的" + "、".join(people[:2]) + "要出现在画面里，保持原有人数和朝向，不要重绘成空景。")
    pal = ES.get("palette") or {}
    if pal.get("tone"):
        p = "整体色调延续照片：" + D._clean(pal["tone"])
        if pal.get("brightness"):
            p += "，明度" + D._clean(pal["brightness"])
        parts.append(p + "。")
    if ES.get("light"):
        parts.append("光线延续照片：" + D._clean(ES["light"]) + "。")
    if ES.get("horizon"):
        parts.append("机位与构图不变，" + D._clean(ES["horizon"]) + "。")
    parts.append("保留底图真实空间结构，细节可概括、光影更电影化、可加雾与胶片颗粒，但地方不能换。")
    parts.append("画面干净：没有任何文字、字母、数字、印章、logo、水印、招牌字样；留白区保持干净空旷。")
    return re.sub(r"。+", "。", "。".join(parts))


def make_plate(text, base, seed, size=(1536, 864), use_cache=True):
    """出同场景无字底版。复用 redraw 的读图规格，不额外调 Ollama。"""
    import redraw as R
    spec = R.design(text, base, use_cache=use_cache)
    if spec.get("error"):
        raise RuntimeError("底版规格失败: " + str(spec["error"])[:180])
    p = clean_prompt(spec, "竖版" if size[1] > size[0] else "横版")
    ref, _ = C.TPLS[C.FONT_KEY]
    R.unload(C.DIRECTOR_MODEL)
    time.sleep(4)
    t0 = time.time()
    fn, sub = CC.run(S._wf(p, seed, size[0], size[1], "plate_%d" % seed, ref), max_wait=3600)
    dst = os.path.join(C.SAVE_DIR, "baseplate_%s_%d.png" % (text, seed))
    shutil.copy(os.path.join(C.OUTPUT_DIR, sub, fn), dst)
    print("[底版] ->", dst, "(%.0fs)" % (time.time() - t0))
    return dst


# ---------------------------------------------------------------- 帧

def crop_resize(path, w, h):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    bw, bh = im.size
    t = w / h
    if bw / bh > t:
        nw = int(bh * t)
        im = im.crop(((bw - nw) // 2, 0, (bw - nw) // 2 + nw, bh))
    else:
        nh = int(bw / t)
        im = im.crop((0, (bh - nh) // 2, bw, (bh - nh) // 2 + nh))
    return im.resize((w, h), Image.LANCZOS)


def match_to(src, ref):
    """把 src 的逐通道均值/标准差对齐到 ref。两帧亮度差太大时，H3 容易演成黑场淡入。"""
    import numpy as np
    a = np.asarray(src, dtype=np.float32)
    b = np.asarray(ref, dtype=np.float32)
    out = np.empty_like(a)
    for c in range(3):
        sa, sb = a[..., c].std(), b[..., c].std()
        ma, mb = a[..., c].mean(), b[..., c].mean()
        k = (sb / sa) if sa > 1e-6 else 1.0
        out[..., c] = (a[..., c] - ma) * k + mb
    from PIL import Image
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- 提示词

def prompt_for(text, hand=False):
    """提示词必须短。H3 的文本编码器是 14.6GB，在 12GB 卡上长提示词会把激活内存撑爆。"""
    if hand:
        return (
            "镜头完全静止，这是同一场景同一个时刻的实景。"
            "一只握毛笔的手从画面右侧入画，笔尖落在画面上书写「%s」：从左向右一笔一笔推进，"
            "笔锋过处留下整幅狂草，细劲带飞白，暖白亚光浅色，全程不发黑。"
            "背景全程是原样的实景，不换景、不切纸面特写、不出现黑底，画面里没有纸张和桌面。"
            "写完手和笔撤出画面，这行字清晰留在画面上。"
        ) % text
    return (
        "镜头完全静止，从头到尾都是这一场景的实景：构图、光线、色调、主体原样不变，"
        "各帧都不是黑底、黑场、纯黑背景，也不是片头字幕卡。"
        "画面上空笔画一笔一笔逐笔浮现，先一笔再一笔，慢慢连成整幅狂草「%s」，"
        "细劲带飞白、暖白亚光浅色，全程不发黑。"
        "画面里不出现手、毛笔、纸张、桌面特写。写完这行字清晰留在画面上，然后静止。"
    ) % text


def grid_len(n):
    """把帧数吸附到 17k+5 网格。"""
    k = max(1, round((n - LENGTH_OFFSET) / LENGTH_GRID))
    return LENGTH_GRID * k + LENGTH_OFFSET


# ---------------------------------------------------------------- workflow

def h3_wf(f_first, f_last, text, seed, tag, w, h, length, steps, hand):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": C.H3_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": C.H3_CLIP, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": C.H3_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": C.H3_VAE_AUDIO}},
        "20": {"class_type": "LoadImage", "inputs": {"image": os.path.basename(f_first)}},
        "21": {"class_type": "LoadImage", "inputs": {"image": os.path.basename(f_last)}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt_for(text, hand),
            "width": w, "height": h, "length": length,
            "first_frame": ["20", 0], "last_frame": ["21", 0]}},
        "6": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "7": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "11": {"class_type": "CFGGuider", "inputs": {"model": ["6", 0], "positive": ["5", 0], "negative": ["10", 0], "cfg": 1}},
        "12": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["9", 0], "guider": ["11", 0], "sampler": ["8", 0], "sigmas": ["7", 0], "latent_image": ["5", 1]}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": 24.0, "audio": ["14", 0]}},
        "16": {"class_type": "SaveVideo", "inputs": {"video": ["15", 0], "filename_prefix": tag, "format": "mp4", "codec": "h264"}},
        "17": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": tag + "_f"}},
    }


# ---------------------------------------------------------------- 主流程

def write_video(text, poster, base=None, plate=None, seed=0, size=(768, 448),
                length=124, steps=8, hand=False, align=True, dry=False, tag=None):
    """出书写视频。返回 dict(dst/plate/prompt/seed/status)。"""
    C.ensure_dirs()
    length = grid_len(length)
    if length != 124 and length < 39:
        print("[warn] 帧数偏少（%d），字可能还没写完就到末帧了" % length)
    seed = seed or int(time.time()) % 1000000
    tag = tag or ("h3w_%d" % seed)

    if dry:
        print("[prompt]", prompt_for(text, hand))
        return dict(dst=None, plate=plate, prompt=prompt_for(text, hand), seed=seed, status="dry")

    if not plate:
        if not base:
            raise ValueError("没给 --plate 就必须给 --base（用来出同场景无字底版）")
        plate = make_plate(text, base, seed, use_cache=True)

    last = crop_resize(poster, size[0], size[1])
    first = crop_resize(plate, size[0], size[1])
    if align:
        first = match_to(first, last)

    f1 = os.path.join(C.INPUT_DIR, "%s_first.png" % tag)
    f2 = os.path.join(C.INPUT_DIR, "%s_last.png" % tag)
    first.save(f1)
    last.save(f2)
    print("[帧] 首帧=无字底版(已对齐) 末帧=成片  %dx%d / %d帧" % (size[0], size[1], length))

    t0 = time.time()
    CC.run(h3_wf(f1, f2, text, seed, tag, size[0], size[1], length, steps, hand), max_wait=7200)
    mp4s = sorted(glob.glob(os.path.join(C.OUTPUT_DIR, tag + "*.mp4")), key=os.path.getmtime)
    if not mp4s:
        return dict(dst=None, plate=plate, prompt=prompt_for(text, hand), seed=seed, status="failed")
    dst = os.path.join(C.SAVE_DIR, "write_%s_%d.mp4" % (text, seed))
    shutil.copy(mp4s[-1], dst)
    print("->", dst, "(%.0fs)" % (time.time() - t0))
    return dict(dst=dst, plate=plate, prompt=prompt_for(text, hand), seed=seed,
                status="rendered", seconds=round(time.time() - t0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="书写过程视频（可选，默认不调用）")
    ap.add_argument("text")
    ap.add_argument("--poster", required=True, help="已经出好的成片（末帧）")
    ap.add_argument("--base", help="原始底图；没给 --plate 时用它出无字底版")
    ap.add_argument("--plate", help="现成的同场景无字底版（比现算快 15 秒）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--size", default="768x448", help="短边 768 是模型基准；1344x768 约 3 倍耗时")
    ap.add_argument("--length", type=int, default=124, help="帧数，自动吸附到 17k+5 网格")
    ap.add_argument("--steps", type=int, default=8, help="8 步蒸馏版默认 8")
    ap.add_argument("--hand", action="store_true", help="让 H3 自己加一只握笔的手（更『书写』，也更容易切纸面特写）")
    ap.add_argument("--no-align", dest="align", action="store_false", help="不做首帧亮度对齐")
    ap.add_argument("--dry", action="store_true", help="只打印提示词，不出图")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    r = write_video(a.text, a.poster, a.base, a.plate, a.seed, (w, h),
                    a.length, a.steps, a.hand, a.align, a.dry)
    print("\n[结果]", r["status"], r["dst"] or "")
