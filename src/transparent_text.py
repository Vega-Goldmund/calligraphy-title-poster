# -*- coding: utf-8 -*-
"""透明背景文字（alpha text）

和重绘（redraw）的根本区别：重绘要让「保背景」和「写字」抢同一份去噪空间（T27 死结），
而这个功能直接生成一张只有字、没有背景的 RGBA 图——Qwen-Image 2.1 的 VAE 是四通道，
透明背景由模型直接生成在 alpha 通道里，不是事后抠图。

用法定位：
- 原图一个像素都不动，把这张透明字层叠上去即可，位置、颜色后期随便改，零随机、可复现。
- 字形（alpha）和字色分离：模型负责把笔画的浓淡飞白画进 alpha，最终 RGB 由程序统一着色，
  这样还能顺手消除 alpha 边缘的彩色污染（实测飞白细丝会混入蓝紫色杂边）。

工程隔离：不调用 Ollama 导演、不改 single/director/redraw，只被 run.py 的 --alpha 分支
和本文件命令行调用。
"""
import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import comfy_client as CC

DEFAULT_COLOR = "#EDE3D2"  # 暖米白，叠深底好看且亚光


def alpha_prompt(text):
    """透明背景专用提示词：只写字、其余区域 alpha=0。"""
    n = len(text)
    return (
        "一张背景完全透明的 PNG 毛笔书法字，画面里只有「" + text + "」，除此之外什么都没有："
        "没有场景、没有纸张、没有底色、没有边框、没有投影、没有光晕，所有非笔画区域都是完全透明的空 alpha 通道、alpha 等于 0。"
        "毛笔快速挥写的整幅狂草，恰好 " + str(n) + " 个字、一字不少也不多写、不重复任何字，"
        "细劲线条为绝对主调、笔画瘦而利、大量干笔飞白，字与字缠绕连写、牵丝不断，"
        "字势倾斜、大小欹侧、主次分明。"
        "字是亚光暖米白色，所有笔画包括最细的飞白细丝都是这同一个颜色，"
        "不发光、不描边、不立体、不出现第二种颜色。"
        "输出带 alpha 通道的 RGBA 透明 PNG，透明背景由 alpha 通道承载。"
    )


def _rgb(hexstr):
    h = (hexstr or "").lstrip("#").strip()
    if len(h) != 6:
        h = DEFAULT_COLOR.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tint_alpha(img, hex_color, floor=18):
    """统一字色、去掉 alpha 边缘的彩色污染，并清掉全画布的极淡底色。

    模型出的半透明飞白边缘 RGB 不稳定，会混入蓝紫杂色；这里保留 alpha（浓淡飞白全在里面），
    把 RGB 全部换成指定的一个字色。合成时浓淡仍由 alpha 自然呈现，颜色却干净统一。

    floor：alpha 低于这个值的像素一律归零。实测大画布（1920 宽）上模型会顺带给整张画布
    铺一层 alpha 1–64 的极淡「纸感」，叠到亮底上就是几条脏痕；飞白细丝的 alpha 实测都在
    40 以上，所以 18 的阈值只砍雾、不砍笔画。"""
    from PIL import Image
    im = img.convert("RGBA")
    a = im.getchannel("A")
    if floor:
        a = a.point(lambda v: 0 if v < floor else v)
    solid = Image.new("RGBA", im.size, _rgb(hex_color) + (255,))
    solid.putalpha(a)
    return solid


def _wf_alpha(prompt, seed, w, h, prefix, ref):
    """文生图同一条骨架，只是结果按 RGBA 保存（VAE 解码四通道）。"""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": C.UNET_NAME, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": C.CLIP_NAME, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": C.VAE_NAME}},
        "20": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": prompt, "negative_prompt": C.NEGATIVE_PROMPT,
            "resolution": 1024, "images": {"image_1": ["20", 0]}, "vae": ["3", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "7": {"class_type": "CFGGuider", "inputs": {"model": ["6", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "ManualSigmas", "inputs": {"sigmas": C.SIGMAS}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["9", 0], "guider": ["7", 0], "sampler": ["8", 0],
            "sigmas": ["10", 0], "latent_image": ["5", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    }


def generate(text, seed=0, size=(1536, 864), color=DEFAULT_COLOR, font="cursive", dry=False):
    """生成透明背景文字层。返回 dict(dst/seed/color/status)。"""
    seed = seed or int(time.time()) % 1000000
    p = alpha_prompt(text)
    if dry:
        return dict(dst=None, prompt=p, seed=seed, color=color, status="dry")

    ref, _ = C.TPLS.get(font, C.TPLS["cursive"])
    wf = _wf_alpha(p, seed, size[0], size[1], "alpha_%d" % seed, ref)
    fn, sub = CC.run(wf)

    from PIL import Image
    raw = Image.open(os.path.join(C.OUTPUT_DIR, sub, fn))
    final = tint_alpha(raw, color)
    # VAE 16 像素对齐：1080 会被补成 1088，按请求尺寸居中裁回
    tw, th = int(size[0]), int(size[1])
    if final.size != (tw, th) and final.size[0] >= tw and final.size[1] >= th:
        left = (final.size[0] - tw) // 2
        top = (final.size[1] - th) // 2
        final = final.crop((left, top, left + tw, top + th))
        print("[crop] %dx%d -> %dx%d" % (raw.size[0], raw.size[1], tw, th))
    C.ensure_dirs()
    dst = os.path.join(C.SAVE_DIR, "alpha_%s_%d.png" % (text, seed))
    final.save(dst)
    print("->", dst)
    return dict(dst=dst, prompt=p, seed=seed, color=color, status="rendered")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--size", default="1536x864")
    ap.add_argument("--color", default=DEFAULT_COLOR, help="字色 hex，默认暖米白")
    ap.add_argument("--font", default="cursive", choices=list(C.TPLS))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    r = generate(a.text, a.seed, (w, h), a.color, a.font, a.dry)
    print("\n[结果]", r["status"], r.get("dst") or "")
