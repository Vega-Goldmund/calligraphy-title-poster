"""单次出图（回到原思路）+ 重构过的提示词

反思结论：
1 分层合成的字是「贴上去的」——笔触与背景的材质交互全部丢失，遮挡是伪造的，字变半透明像水印
2 原来单次出图能出好图（8507/8401），说明模型有能力同时处理字和景
3 原思路真正的问题不是单 pass，而是提示词结构：
   · 二十多条并列约束互相打架，模型注意力分散 → 缺字、排版漂移
   · 字排在 prompt 靠后，权重低
   · 版式用抽象百分比（占宽0.55），模型不执行
   · 没写「字必须完整」，于是模型拿景物替代笔画（8507 的"友"被银杏叶顶替）
所以：把约束砍到 8 条以内，字放最前，版式改成画面里的具体锚点，加一条完整性硬约束。
"""
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import config as _CFG
from config import INK_RHYTHM_LINES
import comfy_client as CC
import director as D

OUT_DIR = C.OUTPUT_DIR
SAVE_DIR = C.SAVE_DIR


def _first_sentence(s):
    for sep in ("。", "；", "\n"):
        if sep in s:
            part = s.split(sep)[0].strip()
            if len(part) >= 12:
                return part
    return s.strip()


def brief(spec, text, orientation="横版", ink_rhythm=False, style=None):
    """把规格压成一段短提示词。默认按「整幅狂草」组织，端庄场合才走独立单字。

    style="neat" 为整齐版（默认），style="ink" 为浓淡版；
    ink_rhythm=True 是旧写法，等价于 style="ink"。"""
    ink_rhythm = _CFG.resolve_style(style, ink_rhythm)
    L = spec.get("layout") or {}
    F = spec.get("font_design") or {}
    M = spec.get("morph") or {}
    C = spec.get("color") or {}
    B = spec.get("background") or {}

    bg = _first_sentence(B.get("prompt", "") or "暗调的实拍风景")
    parts = [f"{orientation}情绪海报，胶片质感、粗颗粒。画面是{bg}"]
    parts.append("背景浅景深、失焦朦胧，以剪影和轮廓为主、没有锐利细节，大区域留白、画面要空，不要塞满")
    CC = spec.get("cultural_context") or {}
    if CC.get("imagery"):
        parts.append("文化意象，要自然出现在画面里：" + D._clean(CC["imagery"]))
    if B.get("anchor"):
        parts.append("情绪锚点：" + D._clean(B["anchor"]))

    if spec.get("dignified"):
        parts.append(f"画面上写着「{text}」，一字不少、每个字独立端正、完整可辨，不许缺字")
        parts.append("字号统一、不连笔缠绕、不倾斜")
        if F.get("stroke"):
            parts.append(D._clean(F["stroke"]))
    else:
        parts.append(f"画面上写「{text}」这一整句，一字不少、不要标点，整句读得出、不许缺字")
        if ink_rhythm:
            parts.append("毛笔在纸上快速挥写的整幅狂草，不是马克笔、秀丽笔或现代文艺体，"
                         "整组以细劲线条为主，但提按分明：重按处铺开成较宽的实笔，提起处收成细线，"
                         "不要整组一样细、不要粗细均匀的光滑笔画、不要圆润粗壮的设计字体")
        else:
            parts.append("毛笔在纸上快速挥写的整幅狂草，不是马克笔、秀丽笔或现代文艺体，"
                         "整组以细劲线条为绝对主调、笔画瘦而利，不要实心填充、不要粗细均匀的光滑笔画、不要圆润粗壮的设计字体")
        parts.append("字与字大胆缠绕连写：上字收笔直接牵出细丝连到下字起笔，多字可以一笔连写、牵丝不断，"
                     "看得见的细牵丝把整组连成一条连绵气脉，允许连写简化、字与字挨近呼应、互相穿插，"
                     "不要写成一个个分开的字，只要整句读得出即可")
        if ink_rhythm:
            parts.append("大量干笔飞白：笔毫散开干扫，部分笔画甚至整字由一组平行细丝组成、中间大量露出背景，"
                         "边缘毛涩断续；干丝比湿笔更浅、更透，是同一字色的淡墨，不是灰糊、不是黑块")
        else:
            parts.append("大量干笔飞白：笔毫散开干扫，部分笔画甚至整字由一组平行细丝组成、中间大量露出背景，"
                         "边缘毛涩断续；干丝依然是字的颜色、明亮，不发灰发黑")
        if ink_rhythm:
            parts.extend(INK_RHYTHM_LINES)
        if F.get("cursive_flow"):
            parts.append(D._clean(F["cursive_flow"]))
        if F.get("stroke"):
            parts.append(D._clean(F["stroke"]))
        parts.append("字势倾斜、大小欹侧、疏密肆意，主字放大、虚词小而细，整组不要一样大")
        if ink_rhythm:
            parts.append("字色铁律：字色必须和它所在那块背景有肉眼可辨的明度差——背景偏亮时用该字色的深色版本，背景偏暗时用该字色的浅色版本；"
                         "重按处是同一色相更浓、更厚实，提起处是同一色相更淡、更透，最浓处仍透出飞白；"
                         "不许糊成一整块，也不许出现灰糊墨团或第二种颜色")
        else:
            parts.append("字色铁律：字色必须和它所在那块背景有肉眼可辨的明度差——背景偏亮就把字压成深墨色"
                         "（干净的墨，不是发灰的墨团），背景偏暗就用亮白浅色；不论哪一种，最宽的一笔和细游丝同色同亮，"
                         "宽只是形状铺开，不许出现灰糊的墨团、灰字")
        if L.get("emphasis"):
            parts.append(D._clean(L["emphasis"]))
        if L.get("scale"):
            parts.append(D._clean(L["scale"]))
        if L.get("tilt"):
            parts.append(D._clean(L["tilt"]))

    pos = L.get("position") or "画面中部"
    parts.append(f"字压在{pos}，整组字明显收小、缩成画面中部一小块，上下左右都留出大片空白，画面以空为主、不要撑大")

    if C.get("name"):
        if ink_rhythm:
            parts.append(f"整组字统一为一个颜色（{C['name']}；如果这个颜色和所在背景明度太接近、字读不出来，"
                         "就自动压深或提亮到清晰可辨，仍然只有一个颜色），"
                         "浓淡只在这个颜色内部变化：重按处同色更浓、更厚实，提起处同色更淡、更透，最浓处仍透出飞白，"
                         "不许出现灰糊墨团或第二种颜色")
        else:
            parts.append(f"整组字统一为一个颜色（{C['name']}；如果这个颜色和所在背景明度太接近、字读不出来，"
                         "就自动压深或提亮到清晰可辨，仍然只有一个颜色），"
                         "深色只是飞白阴影、不是字色，不许出现灰糊的墨团或第二种颜色")
    if C.get("relation"):
        parts.append(D._clean(C["relation"]))

    bold = F.get("bold_move") or M.get("stroke")
    if bold:
        parts.append("其中只改一笔：" + D._clean(bold).rstrip("。") + "，这一笔仍属于原来的字、不许把整字变成线条")

    Dc = spec.get("decoration") or {}
    import subtitle as SUB
    # 副标文字一律程序生成：模型自己拼的拼音/英文实测会错（chaogi / a worth while existence）
    want = SUBTITLE_FORCE if SUBTITLE_FORCE is not None else bool(Dc.get("enabled"))
    sub = SUB.build(text, tones=SUBTITLE_TONES, english=SUBTITLE_EN) if want else ""
    if sub:
        place = D._clean(Dc.get("placement") or "主字组旁边")
        dline = (f"在{place}加一行很小的手写花体副标 {D._clean(sub)}，"
                 "和中文同色同色系、只作衬托、不喧宾夺主，不要印刷体")
        if Dc.get("geometry"):
            dline += "，旁边点缀极简几何：" + D._san_text(Dc["geometry"])
        dline += "，" + SUB.RULE
        parts.append(dline)
        tail = "除这行花体副标和几何点缀外，画面里不要出现其他文字、字母、数字、印章。"
    else:
        tail = "画面里不要出现其他文字、字母、数字、印章。"

    parts.append("不描边、不投影、不发光、不立体、不堆雪堆金属")
    parts.append("最后一个字必须写完整、给它留出位置，不许吞掉句末的字")
    return "。".join(parts) + "。" + tail


TPLS = C.TPLS
FONT_KEY = C.FONT_KEY

# 副标开关（run.py 可覆盖）：
#   SUBTITLE_FORCE False（默认）=不出副标；True=加（文字由 subtitle.py 程序生成，可核对）
#                   None=完全听导演的（不推荐，等于让模型自己决定要不要加）
#   SUBTITLE_EN    显式英文副标；不填就不出英文，避免模型自己乱译
#   SUBTITLE_TONES 拼音是否带声调
SUBTITLE_FORCE = False
SUBTITLE_EN = ""
SUBTITLE_TONES = True


def _run(wf):
    """提交并轮询，返回 (filename, subfolder)；失败返回 (None, "")。"""
    try:
        return CC.run(wf)
    except Exception as e:
        print("[comfy]", e)
        return None, ""


def _save_out(fn, sub, kind, text, seed, size=None):
    """落盘。VAE 要求 16 像素对齐，1080 会被补成 1088，这里按请求尺寸居中裁回去。"""
    src = os.path.join(OUT_DIR, sub, fn)
    C.ensure_dirs()
    dst = os.path.join(SAVE_DIR, f"{kind}_{text}_{seed}.png")
    if size:
        from PIL import Image
        im = Image.open(src)
        tw, th = int(size[0]), int(size[1])
        if im.size != (tw, th) and im.size[0] >= tw and im.size[1] >= th:
            left = (im.size[0] - tw) // 2
            top = (im.size[1] - th) // 2
            im.crop((left, top, left + tw, top + th)).save(dst)
            print("[crop] %dx%d -> %dx%d" % (im.size[0], im.size[1], tw, th))
            return dst
    shutil.copy(src, dst)
    return dst


def _orient(size):
    return "竖版" if size[1] > size[0] else "横版"


def _wf(prompt, seed, w, h, prefix, ref):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": C.UNET_NAME, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": C.CLIP_NAME, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": C.VAE_NAME}},
        "20": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": prompt,
            "negative_prompt": C.NEGATIVE_PROMPT,
            "resolution": 1024, "images": {"image_1": ["20", 0]}, "vae": ["3", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "7": {"class_type": "CFGGuider", "inputs": {"model": ["6", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "ManualSigmas", "inputs": {"sigmas": C.SIGMAS}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["9", 0], "guider": ["7", 0], "sampler": ["8", 0], "sigmas": ["10", 0], "latent_image": ["5", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    }


def render(text, hint="", seed=0, size=(1536, 864), use_cache=True, font="cursive", ink_rhythm=False, style=None):
    spec = D.direct(text, hint, use_cache=use_cache)
    if spec.get("error"):
        print("[director fail]", spec["error"])
        return None, spec, ""
    seed = seed or int(time.time()) % 1000000
    ref, _ = TPLS.get(font, TPLS["cursive"])
    p = brief(spec, text, _orient(size), ink_rhythm=ink_rhythm, style=style)
    print("[prompt]", p)
    fn, sub = _run(_wf(p, seed, size[0], size[1], f"single_{seed}", ref))
    if not fn:
        print("失败")
        return None, spec, p
    dst = _save_out(fn, sub, "single", text, seed, size)
    print("->", dst)
    return dst, spec, p


def _render_with_spec(spec, text, seed, size, font="cursive", ink_rhythm=False, style=None):
    """用同一份规格、指定 seed 出一张图，返回 (dst, prompt)。"""
    ref, _ = TPLS.get(spec.get("ref_style", font), TPLS["cursive"])
    p = brief(spec, text, _orient(size), ink_rhythm=ink_rhythm, style=style)
    fn, sub = _run(_wf(p, seed, size[0], size[1], f"single_{seed}", ref))
    if not fn:
        return None, p
    dst = _save_out(fn, sub, "single", text, seed, size)
    print("->", dst)
    return dst, p


def stable_render(text, hint="", max_tries=1, size=(1536, 864), use_cache=True, font="cursive", ink_rhythm=False, style=None):
    """直接出图（出图已稳定，默认不再做 Ollama 自检）。
    经过多轮压力测试，单次出图本身已稳定、字完整；而出图后立即调用 35b 自检，
    每次都撞显存竞争 500、要等待重试，反而增加耗时和模型换入换出，故默认关闭。
    quality.py 保留为手动旁路：需要逐字核对时，可单独调用 quality.check(text, path)。
    max_tries 仅为兼容旧调用保留，当前一次出图即返回。
    返回结果 dict：dst/spec/prompt/attempts/status/missing/reliable。"""
    spec = D.direct(text, hint, use_cache=use_cache)
    if spec.get("error"):
        print("[director fail]", spec["error"])
        return dict(dst=None, spec=spec, prompt="", attempts=0,
                    status="failed", missing=[], reliable=False)
    seed = int(time.time()) % 1000000
    print(f"[直接出图 · seed {seed}，不做 Ollama 自检]")
    dst, p = _render_with_spec(spec, text, seed, size, font, ink_rhythm=ink_rhythm, style=style)
    if not dst:
        print("出图失败")
        return dict(dst=None, spec=spec, prompt="", attempts=0,
                    status="failed", missing=[], reliable=False)
    return dict(dst=dst, spec=spec, prompt=p, attempts=1,
                status="rendered", missing=[], reliable=False)


def stable_render_neat(text, hint="", **kwargs):
    """整齐版接口：等价于 style="neat"。"""
    kwargs["style"] = C.STYLE_NEAT
    return stable_render(text, hint, **kwargs)


def stable_render_ink(text, hint="", **kwargs):
    """浓淡版接口：等价于 style="ink"。"""
    kwargs["style"] = C.STYLE_INK
    return stable_render(text, hint, **kwargs)


def render_set(text, hint="", k=4, seed_base=0, size=(1536, 864),
               use_cache=True, font="cursive", ink_rhythm=False, style=None):
    """一次出 k 套不同方案：导演先给 k 份互不相同的规格，再一套套出图。
    这是「四张几乎一样」的解药——差异来自规格本身，不是同一份规格换种子。"""
    specs = D.combo(text, hint, k=k, use_cache=use_cache)
    if not specs:
        print("[combo] 导演没给出方案")
        return []
    seed_base = seed_base or int(time.time()) % 100000
    outs = []
    for i, spec in enumerate(specs):
        seed = seed_base + i * 419
        ref, _ = TPLS.get(spec.get("ref_style", "cursive"), TPLS["cursive"])
        p = brief(spec, text, _orient(size), ink_rhythm=ink_rhythm, style=style)
        print(f"\n[方案{i + 1} · {spec.get('label')} · seed {seed}]\n{p}")
        fn, sub = _run(_wf(p, seed, size[0], size[1], f"set_{seed}", ref))
        if not fn:
            outs.append(dict(dst=None, spec=spec, prompt=p, label=spec.get("label"), seed=seed))
            continue
        dst = _save_out(fn, sub, "set", text, seed, size)
        outs.append(dict(dst=dst, spec=spec, prompt=p, label=spec.get("label"), seed=seed))
    return outs


def render_one(text, spec, seed, size=(1536, 864), ink_rhythm=False, style=None):
    """用指定的一份规格再出一张（挑中方案后换种子细化，规格不变）"""
    ref, _ = TPLS.get(spec.get("ref_style", "heavy"), TPLS["heavy"])
    p = brief(spec, text, _orient(size), ink_rhythm=ink_rhythm, style=style)
    fn, sub = _run(_wf(p, seed, size[0], size[1], f"ref_{seed}", ref))
    if not fn:
        return None
    dst = _save_out(fn, sub, "ref", text, seed, size)
    print("->", dst)
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--hint", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--font", default="cursive", choices=list(TPLS))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--stable", action="store_true", help="直接出图（默认不做 Ollama 自检）")
    ap.add_argument("--style", choices=list(C.STYLES), default=None,
                    help="版式：neat 整齐版（默认）/ ink 浓淡版")
    ap.add_argument("--ink-rhythm", action="store_true",
                    help="旧写法，等价于 --style ink")
    ap.add_argument("--tries", type=int, default=1)
    a = ap.parse_args()
    if a.ink_rhythm and a.style == C.STYLE_NEAT:
        ap.error("--ink-rhythm 等价于 --style ink，不能同时指定 --style neat")
    style = a.style or (C.STYLE_INK if a.ink_rhythm else C.DEFAULT_STYLE)
    if a.stable:
        r = stable_render(a.text, a.hint, max_tries=a.tries,
                          size=(1536, 864), use_cache=not a.fresh, font=a.font,
                          style=style)
        print("\n===== 出图结果 =====")
        print("文件:", r["dst"])
        print("状态:", {"rendered": "直接出图（未自检）", "passed": "质检通过",
                        "needs_review": "待人工验收", "failed": "出图失败"}[r["status"]])
        if r["missing"]:
            print("疑似缺字:", "".join(r["missing"]))
    else:
        render(a.text, a.hint, a.seed, (1536, 864), use_cache=not a.fresh, font=a.font,
               style=style)
