# -*- coding: utf-8 -*-
"""基于底图重绘（redraw）

和文生图的区别：不用空 latent 从零画，而是把底图 VAEEncode 成 latent，
用中等强度去噪（不是 1.0 全重画、也不是 0.895 那种只敢保背景的极低强度），
让模型在保住底图「识别锚点」的前提下重绘并写上狂草字。

为什么做成一次 Ollama 调用：35b 冷启动要 80 秒左右，识别一次、设计一次就是两次冷启动。
所以让它同一次输出两样东西：
  1 element_sheet  底图元素清单（识别锚点、留白区、色调光线）
  2 完整制作规格     layout / font_design / morph / color / background / decoration
加载一次，两件事都拿到。

工程隔离：本文件只被 run.py 的 --base 分支和命令行调用，不改 single.py / director.py。
不传底图时完全走原来的文生图路径，两边互不影响。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from config import INK_RHYTHM_LINES
import comfy_client as CC
import director as D
import single as S
import subtitle as SUB

OUT_DIR = C.OUTPUT_DIR
SAVE_DIR = C.SAVE_DIR

# 副标（默认不出；要出必须是程序生成可核对的文字，run.py 可覆盖）
SUBTITLE_EN = ""
SUBTITLE_TONES = True


# ---------------------------------------------------------------- 提示词

REDRAW_SYS = (
    "\n【本次是「基于底图重绘」，不是从零画一张】\n"
    "用户会给你一张照片和一句话。你要一次做完两件事：\n"
    "第一件 读图：把照片拆成结构化元素清单——场景是什么、有哪些关键元素（带位置）、"
    "哪几个是识别锚点（换了就不是这个地方的元素）、构图（地平线/主体在哪/哪里有干净留白）、"
    "色调（明度/色温）、光线（时间/方向/天气）、整体气质。只写你真实看到的，不要臆测、不要补不存在的细节。\n"
    "第二件 设计：在保留这些识别锚点的前提下，设计这句话怎么写在照片上。\n"
    "【重绘铁律】\n"
    "1 识别锚点必须保留：重绘结果里这些元素仍在、位置和形态基本不变，它们是这张照片的身份证。\n"
    "2 底图的构图与色调是地基：机位、地平线、主结构位置、整体色温都延续底图，这是同一个地方的重绘，不是另画一个场景。\n"
    "3 字优先压在底图本来就空的地方（天空、水面、雾、墙面、路面），不要盖住锚点元素。\n"
    "4 字色从底图的色调里长出来，并且和它所在的那块区域有足够明度差。\n"
    "5 允许的变化：光影更电影化、细节更概括、可以加雾加颗粒，但地方不能换。\n"
    "6 人物与活动必须留住：照片里有人、有队伍、有活动，就要把人写进 key_elements——人数、穿着、动作、朝向，"
    "并且必须把人列为识别锚点。有人物活动才是活的场景，不许重绘成一张空景；只有照片里本来没有人，才可以画空景。\n"
    "7 光色指纹不许抹掉：照片如果有明显的色温特征——夕阳的暖橙、清晨的冷青、灯火的暖黄、雪原的冷蓝——"
    "那是这个时刻的指纹，必须保留在背景提示词里，并让字色与它呼应。"
    "「统一色调」指的是整体协调，不是把特征色改写成中性灰蓝；不要在背景提示词里出现与照片真实色温相反的描述"
    "（照片是暖调就不要写紫灰冷调），也不要写「避免暖色」这类否定。\n"
    "8 断行按语义断：分行时不许把一个词从中间切开，「青年消费」「伟大变革」这类词必须完整待在同一行。\n"
    "9 不许添加底图里没有的元素：闪电、飞鸟、额外的船或建筑、多余的光斑，底图没有就是没有。\n"
    "10 留白和比例也是构图的一部分：底图若是极简剪影（主体只是天地间小小一个黑影、四周大片空茫），"
    "重绘必须保持主体仍然小、空茫仍然大，不许把主体放大成特写、不许给它补细节——那种图的意境就靠这个比例。\n"
    "判断标准：重绘结果和原照片并排看，要一眼认得出是同一个地方、同一批人、同一个时刻的光。\n"
)

REDRAW_SCHEMA_ES = """ "element_sheet":{
   "scene":"场景类型，一句话",
   "key_elements":["关键元素，带位置，如 前景水塘、左侧草地"],
   "anchor_elements":["识别锚点，3-5个，最有辨识度；照片里有人物活动时必须有人的活动"],
   "blank_areas":["底图上适合压字的干净留白区，带位置"],
   "horizon":"地平线/主结构位置",
   "palette":{"tone":"整体色调","brightness":"明度","temperature":"色温"},
   "light":"时间与光线方向",
   "mood":"整体气质，一句话"
 }"""


def redraw_schema():
    """在原导演 SCHEMA 上追加 element_sheet，其余字段原样保留。"""
    body = D.SCHEMA.strip()
    inner = body[1:-1].rstrip() if body.startswith("{") and body.endswith("}") else body
    return "{" + inner + ",\n" + REDRAW_SCHEMA_ES + "\n}"


def _post_chat(body, timeout=900):
    req = urllib.request.Request(
        C.OLLAMA_URL + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _b64(path):
    with open(path, "rb") as f:
        return __import__("base64").b64encode(f.read()).decode("ascii")


def unload(model):
    """出图前把 Ollama 的模型踢出显存：ComfyUI 出图要 12G，和 22G 的 35b 抢不下。
    先查 /api/ps，确认真的在显存里才发卸载请求，避免对未加载模型做无谓的加载再卸载。"""
    try:
        with urllib.request.urlopen(C.OLLAMA_URL + "/api/ps", timeout=10) as r:
            ps = json.loads(r.read().decode("utf-8"))
        loaded = [m.get("name", "") for m in ps.get("models", [])]
        if not any(model == n or model.replace(":latest", "") == n for n in loaded):
            return False
        req = urllib.request.Request(
            C.OLLAMA_URL + "/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=60).read()
        return True
    except Exception:
        return False


def _base_hash(path):
    """底图指纹：同一个片名配不同底图，规格不能混用。"""
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:12]
    except Exception:
        return "nobase"


REDRAW_CACHE = os.path.join(C.CACHE_DIR, "redraw_cache.json")


def _cache_load():
    try:
        with open(REDRAW_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cache_save(d):
    try:
        os.makedirs(C.CACHE_DIR, exist_ok=True)
        with open(REDRAW_CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def design(text, base_image, hint="", temperature=0.85, use_cache=True):
    """一次调用：读图 + 设计。返回 spec（含 element_sheet）；失败返回带 error 的 dict。"""
    key = "%s|%s|%s|v1" % (text, hint, _base_hash(base_image))
    cache = _cache_load()
    if use_cache and key in cache:
        print("[复用重绘规格]")
        return cache[key]

    user = (
        "这是底图。片名：" + text + "\n"
        + (("补充倾向：" + hint + "\n") if hint else "")
        + "先读这张图，再给这组字做一份完整制作规格。背景描述要基于这张照片的真实内容。\n"
        + "输出 JSON 结构：\n" + redraw_schema()
    )
    body = {
        "model": C.REDRAW_VISION_MODEL or C.DIRECTOR_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "30s",
        "options": {"temperature": temperature, "top_p": 0.95, "num_predict": 2000},
        "messages": [
            {"role": "system", "content": D.SYS + "\n\n【可用的拟物招法】\n" + D._doc() + REDRAW_SYS},
            {"role": "user", "content": user, "images": [_b64(base_image)]},
        ],
    }
    try:
        try:
            r = _post_chat(body)
        except Exception:
            body["model"] = C.DIRECTOR_FALLBACK
            r = _post_chat(body, timeout=600)
        spec = json.loads(r.get("message", {}).get("content", "").strip())
    except Exception as e:
        return dict(error=repr(e)[:200], text=text)

    spec.setdefault("element_sheet", {})
    spec.setdefault("layout", {})
    spec.setdefault("morph", {})
    spec.setdefault("color", {})
    spec.setdefault("cultural_context", {})
    spec.setdefault("background", {})
    spec.setdefault("decoration", {})
    # 导演偶发漏给锚点（实测惊蛰那张 anchor_elements 为空）：用关键元素兜底，
    # 否则重绘时没有“身份证”可守，模型容易自由发挥
    _es = spec["element_sheet"]
    if not _es.get("anchor_elements"):
        _es["anchor_elements"] = (_es.get("key_elements") or [])[:5]
    if not spec["layout"].get("lines"):
        spec["layout"]["lines"] = [text]
    if not spec["color"].get("name"):
        spec["color"]["name"] = "亮白色"
    D._san(spec)
    if use_cache:
        cache[key] = spec
        _cache_save(cache)
    return spec


# ---------------------------------------------------------------- 提示词组装

def _soften(hexstr, sat_cap=0.52):
    """把高饱和字色降饱和，避免刺眼的荧光/发光感——这是 AI 味最主要的来源之一。

    只降饱和度、不动明度，所以字与背景的明度差不被破坏（不会因降饱和而撞进背景）。
    本来就低饱和的色（墨青、灰蓝）原样返回，避免把好看的沉稳色洗成灰。
    返回 (颜色, 是否改过)。"""
    import colorsys
    import re
    h = (hexstr or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", h)
    if not m:
        return hexstr, False
    v = int(m.group(1), 16)
    r, g, b = [(v >> s) & 0xFF for s in (16, 8, 0)]
    hh, ll, ss = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    if ss <= sat_cap:
        return hexstr, False
    r2, g2, b2 = colorsys.hls_to_rgb(hh, ll, sat_cap)
    out = "#%02x%02x%02x" % (int(r2 * 255), int(g2 * 255), int(b2 * 255))
    return out, True


_COLOR_WORDS = (
    "淡青", "浅青", "深青", "青绿", "青蓝", "青色", "蓝色", "绿色", "红色", "黄色",
    "金色", "紫色", "粉色", "橙色", "白色", "黑色", "灰色", "朱红", "赭红", "黛青",
    "翠绿", "碧绿", "琥珀", "珊瑚", "绛红", "米白", "墨色", "银灰", "淡金", "浅金",
)


def _strip_color(txt):
    """几何装饰的文案里若写死颜色（实测「右侧三个淡青色圆点」就真画成青绿，
    与白字打架），把颜色词摘掉，让装饰跟字同色。"""
    import re
    s = txt or ""
    for w in _COLOR_WORDS:
        s = s.replace(w, "")
    s = re.sub(r"(淡|浅|深|亮|暗|灰)(青|蓝|绿|红|黄|金|紫|粉|橙|白|黑|灰|赭|黛|翠|碧)", "", s)
    # 删完颜色字会留下孤零零的「色」和形容亮度的「冷/暖」，它们照样会把模型带偏
    s = s.replace("色圆点", "圆点").replace("色线条", "细线").replace("的色", "的")
    s = re.sub(r"(冷|暖|艳|鲜)(圆|点|线|块|条|圈|方)", r"\2", s)
    s = re.sub(r"的的|，，|、、|的，", lambda m: m.group(0)[1:], s)
    s = s.strip(" ，、的")
    return s if len(s) >= 4 else "极简点线"


def _base_luma(path):
    """底图平均明度（0-1）。暗背景上彩色字必然显成荧光，需要据此改字色。"""
    try:
        from PIL import Image
        im = Image.open(path).convert("L").resize((64, 64))
        px = list(im.getdata())
        return sum(px) / len(px) / 255.0
    except Exception:
        return 0.5


def _adapt_dark(hexstr, l=0.86, s=0.18):
    """暗背景专用：把彩色转成偏白的浅色，保留一点色相。
    实测提示词里写 hex 数值对模型几乎没有控制力（写 #7EC8E3 仍出亮青蓝），
    真正的杠杆是「接近白」这个形态——白字在暗背景上亮而不荧光。"""
    import colorsys
    import re
    h = (hexstr or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", h)
    if not m:
        return "#e8eef2", "浅米白"
    v = int(m.group(1), 16)
    r, g, b = [(v >> s_) & 0xFF for s_ in (16, 8, 0)]
    hh, _ll, _ss = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    r2, g2, b2 = colorsys.hls_to_rgb(hh, l, s)
    out = "#%02x%02x%02x" % (int(r2 * 255), int(g2 * 255), int(b2 * 255))
    # 不按色相给名字：说成「浅绿」模型就真去画绿字。这个颜色视觉上几乎无彩，就该这么描述
    return out, "接近白的浅色"


def redraw_brief(spec, text, orient="横版", luma=None, ink_rhythm=False, style=None):
    """重绘专用提示词：字的部分与原管线同源，背景部分换成「保留锚点」。"""
    ink_rhythm = C.resolve_style(style, ink_rhythm)
    L = spec.get("layout") or {}
    F = spec.get("font_design") or {}
    M = spec.get("morph") or {}
    Co = spec.get("color") or {}
    ES = spec.get("element_sheet") or {}
    n = len(text)
    parts = []

    scene = D._clean(ES.get("scene") or "")
    anchors = [D._clean(x) for x in (ES.get("anchor_elements") or []) if D._clean(x)]
    head = f"这是一张{orient}情绪海报，在给定照片的基础上重绘，不是另画一个新场景。"
    if scene:
        head += f"照片里是{scene}。"
    if anchors:
        head += "必须原样保留下来的识别元素：" + "、".join(anchors[:5]) + "；它们的位置、朝向、体量基本不变，"
        head += "而且这每一个元素都要在成片里实际出现、肉眼清楚可见，一个都不能少、不能漏掉；再小再虚的（一缕烟、一束光、一个远剪影）也要如实画出来。"
    parts.append(head)

    # 烟/雾/光/尘这类无实体的虚锚点最容易在重画时被省略（实测大漠的“一缕烟”两次都没画），
    # 单独给一条带位置和形态的具体指令，比泛泛说“要可见”更有效
    _eth = ("烟", "雾", "蒸汽", "热气", "尘", "光晕", "光束")
    _eth_hits = [a for a in anchors if any(k in a for k in _eth)]
    if _eth_hits:
        parts.append(
            "特别盯住" + "、".join(_eth_hits) + "：它们没有实体、靠空气透视，最容易被当成可省略的细节，"
            "要画在远处主体棱线或光源的后方，被天光或逆光勾出一条细而连贯的边缘，"
            "和周围背景有虽然微弱但肉眼可辨的明暗差，成片里一定找得到，不许用一片空留白代替")

    # 人物是活的场景，不能被重绘成空景
    key_el = [D._clean(x) for x in (ES.get("key_elements") or []) if D._clean(x)]
    people = [x for x in key_el if any(k in x for k in ("人", "队伍", "青年", "游客", "村民", "学生", "群像"))]
    if people:
        parts.append("照片里的" + "、".join(people[:2]) + "要出现在画面里，保持原有的人数和行走方向，不要重绘成空景")

    pal = ES.get("palette") or {}
    if pal.get("tone"):
        p = f"整体色调延续照片：{D._clean(pal['tone'])}"
        if pal.get("brightness"):
            p += f"，明度{D._clean(pal['brightness'])}"
        parts.append(p + "。")
    if ES.get("light"):
        parts.append(f"光线延续照片：{D._clean(ES['light'])}。")
    if ES.get("horizon"):
        parts.append(f"机位与构图不变，{D._clean(ES['horizon'])}。")

    parts.append("保留底图的真实空间结构，细节可以概括、光影可以更电影化、可以加雾与胶片颗粒，"
                 "但地方不能换，不能把建筑、水面、山脊换成别的东西")

    # ---- 字（与 single.brief 同源的硬约束）----
    if spec.get("dignified"):
        parts.append(f"在这一小块留白里写上「{text}」，恰好 {n} 个字、一字不少也不多写，每个字独立端正、完整可辨，不许缺字、不许重复任何字")
        parts.append("字号统一、不连笔缠绕、不倾斜")
        if F.get("stroke"):
            parts.append(D._clean(F["stroke"]))
    else:
        parts.append(f"在照片的留白处写上「{text}」这一整句，恰好 {n} 个字、一字不少也不多写、不要标点，整句读得出、不许缺字、不许重复或额外加字，写完这 {n} 个字立即停笔")
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
            parts.append("字色铁律：整组仍是一个字色系，但必须有浓淡——重按处是同一色相更浓、更厚实，提起处是同一色相更淡、更透，"
                         "深与浅之间连续过渡，不是两种颜色；最浓处仍透出飞白与纸纹，不许糊成一整块，也不是灰糊墨团")
        else:
            parts.append("字色铁律：哪怕最宽最显眼的一笔，也和细游丝同色同亮，宽只是形状铺开、绝不是黑或灰，全图没有黑字")
        if L.get("emphasis"):
            parts.append(D._clean(L["emphasis"]))
        if L.get("scale"):
            parts.append(D._clean(L["scale"]))
        if L.get("tilt"):
            parts.append(D._clean(L["tilt"]))

    blanks = [D._clean(x) for x in (ES.get("blank_areas") or []) if D._clean(x)]
    where = (L.get("position") or "").strip() or (blanks[0] if blanks else "照片里最空的区域")
    parts.append(f"字压在{where}，整组字收小成一块，不要盖住上面说的识别元素，四周留出空白")

    if Co.get("name"):
        # 导演爱把字色命名成「青蓝荧光」「高亮青」之类，这些词一进提示词就会诱导模型加光晕，
        # 先把名字里的发光词摘掉
        cname = D._clean(Co["name"])
        glow_words = ("荧光", "霓虹", "发光", "高亮", "炫光", "光感", "亮彩")
        had_glow = any(w in cname for w in glow_words)
        for w in glow_words:
            cname = cname.replace(w, "")
        cname = cname.strip() or "低饱和色"

        # 暗背景（luma < 0.45）上彩色字怎么降饱和都还是荧光——实测写 #7EC8E3 仍出亮青蓝，
        # 真正的杠杆是「接近白」这个形态，所以暗底直接换成偏白浅色。
        # 亮背景反过来：金黄压稻田、赭红压雪原都成立，这里乱降饱和会把好图洗成土色，不动。
        dark = luma is not None and luma < 0.45
        soft_hex, changed = _soften(Co.get("hex"))
        if dark and changed:
            # 只有本来就高饱和的才需要换；低饱和浅色（如 #dcebf2 浅冷蓝）本来就安全，别动它
            soft_hex, cname = _adapt_dark(Co.get("hex"))
        elif not dark:
            soft_hex = Co.get("hex")  # 亮背景不降饱和：金黄压稻田、赭红压雪原都成立
        line = f"整组字统一为{cname}"
        if soft_hex:
            line += f" {soft_hex}"
        if ink_rhythm:
            line += f"，所有笔画仍属于这个颜色、偏灰不刺眼，只有同色浓淡：重按处是{cname}的浓色版本（同色相加深，不是另一色），" \
                    "提起处更浅更透；最浓处仍透出飞白，不许糊成一整块或灰糊墨团"
        else:
            line += "，所有笔画都是这个颜色、偏灰不刺眼，深色只是飞白阴影、不是字色，不许出现黑字或第二种颜色"
        parts.append(line)
        if dark or had_glow:
            parts.append("这个颜色要压掉荧光感：它是亚光颜料混进环境里的颜色，不是屏幕发光色，不要霓虹、不要光晕辉光、不要外发光")
    if Co.get("relation"):
        parts.append(D._clean(Co["relation"]))

    bold = F.get("bold_move") or M.get("stroke")
    if bold:
        parts.append("其中只改一笔：" + D._clean(bold).rstrip("。") + "，这一笔仍属于原来的字、不许把整字变成线条")

    Dc = spec.get("decoration") or {}
    sub = Dc.get("subtitle")
    place = D._clean(Dc.get("placement") or "主字组旁边")
    geo = _strip_color(Dc.get("geometry") or "")
    # 副标与几何分开判断：长句拼音不可靠，关掉副标时几何装饰仍可保留
    if Dc.get("enabled") and sub:
        dl = (f"在{place}加一行很小的手写花体副标 {D._clean(sub)}，"
              "和中文同色同色系、只作衬托、不喧宾夺主，不要印刷体")
        dl += "，" + SUB.RULE
        if Dc.get("geometry"):
            dl += f"，旁边点缀极简几何：{geo}，跟字用同一个颜色、不另配色"
        parts.append(dl)
    elif Dc.get("enabled") and Dc.get("geometry"):
        parts.append(f"在{place}点缀极简几何：{geo}，"
                     "和字是同一个颜色、不另配任何颜色，少而精，只作排版的呼吸点")

    parts.append("不描边、不投影、不发光、不立体")
    parts.append("最后一个字必须写完整、给它留出位置，不许吞掉句末的字")
    parts.append(f"交图前自己核对一遍：画面里恰好只有「{text}」这 {n} 个字、没有重复字和多余字，上面列的识别元素全部实际可见、一个不缺")
    import re
    return re.sub(r"。+", "。", "。".join(parts) + "。照片上不要出现其他文字、字母、数字、印章。")


# ---------------------------------------------------------------- workflow

def sigmas_from(d):
    """把完整 schedule 按比例压到起点 d：保留原有形状，只降低起始噪声。
    d=1.0 等于全重画（和文生图一样），d 越小越贴近底图。"""
    base = [float(x) for x in C.SIGMAS.split(",")]
    out = []
    for x in base:
        v = d * x
        out.append("0" if v <= 0 else ("%.4f" % v).rstrip("0").rstrip("."))
    return ",".join(out)


def stage_base(path):
    """底图复制进 ComfyUI input 目录（LoadImage 只认那里），返回文件名。"""
    os.makedirs(C.INPUT_DIR, exist_ok=True)
    ext = os.path.splitext(path)[1].lower() or ".png"
    with open(path, "rb") as f:
        h = hashlib.md5(f.read()).hexdigest()[:10]
    name = "base_%s%s" % (h, ext)
    dst = os.path.join(C.INPUT_DIR, name)
    if not os.path.exists(dst):
        shutil.copy(path, dst)
    return name


def _wf_redraw(prompt, seed, w, h, prefix, ref, base_img, sigmas):
    """底图 VAEEncode 成 latent，中等强度去噪；其余节点与文生图一致。"""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": C.UNET_NAME, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": C.CLIP_NAME, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": C.VAE_NAME}},
        "20": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "21": {"class_type": "LoadImage", "inputs": {"image": base_img}},
        "22": {"class_type": "ImageScale", "inputs": {
            "image": ["21", 0], "upscale_method": "lanczos",
            "width": w, "height": h, "crop": "center"}},
        "23": {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["3", 0]}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": prompt,
            "negative_prompt": C.NEGATIVE_PROMPT,
            "resolution": 1024, "images": {"image_1": ["20", 0]}, "vae": ["3", 0]}},
        "6": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "7": {"class_type": "CFGGuider", "inputs": {"model": ["6", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "ManualSigmas", "inputs": {"sigmas": sigmas}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["9", 0], "guider": ["7", 0], "sampler": ["8", 0],
            "sigmas": ["10", 0], "latent_image": ["23", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    }


# ---------------------------------------------------------------- 主流程

def redraw(text, base, hint="", seed=0, size=(1536, 864), denoise=0.90,
           font="cursive", dry=False, reuse_spec=None, subtitle=None, mode="recompose",
           cursive=True, use_cache=True, ink_rhythm=False, style=None):
    """识别 + 设计 + 出图。返回 dict(dst/spec/prompt/seed/status)。

    cursive=True（默认）强制走整幅狂草；导演有时会把「新时代伟大变革」这类宏大命题
        判成官方端庄场合（dignified=true），那样字会变成独立端正、字号统一，狂草就没了。
        本器的主风格是狂草，所以默认压住这条判断，要端庄才显式 cursive=False。

    mode="recompose"（默认）元素驱动重绘：读图拿到元素清单，然后和文生图完全同一条
        工作流（空 latent 全流程去噪）重画一张新图，元素清单写进提示词约束。
        为什么这是主路线：保真叠字那套要让「保背景」和「写字」抢同一份去噪空间，
        低噪段字写不进去（实测 0.60/0.75 一个字的笔画都没有），高了又丢底图。
        重画则字走满流程，质量与原有管线一致，元素靠提示词落地。
    mode="keep" 保底图重绘：VAEEncode 底图 + 起始噪声 denoise，背景更像原图，但字会变弱。

    subtitle: None=默认关掉拼音副标（拼音实测不可靠，如「潮起」拼成 chaogi）；
              True=加；False=关。"""
    spec = reuse_spec or design(text, base, hint, use_cache=use_cache)
    if spec.get("error"):
        print("[redraw] 导演失败:", spec["error"])
        return dict(dst=None, spec=spec, prompt="", seed=0, status="failed")

    # 副标开关：拼音不可靠（实测 4 字的「潮起潮落」就拼成 chaogi，q 写成 g），
    # 按用户偏好默认一律不加，需要时才 --subtitle 显式打开；几何装饰不受影响
    # 副标：默认一律不出。要加时文字由 subtitle.py 程序生成（pypinyin），
    # 不让导演自己拼——模型拼过 chaogi、译过 a worth while existence。
    want_sub = bool(subtitle) if subtitle is not None else False
    Dc = spec.setdefault("decoration", {})
    Dc["subtitle"] = SUB.build(text, tones=SUBTITLE_TONES, english=SUBTITLE_EN) if want_sub else ""

    # 主风格是狂草：压住导演「官方场合要端庄」的判断
    if cursive:
        spec["dignified"] = False

    seed = seed or int(time.time()) % 1000000
    p = redraw_brief(spec, text, "竖版" if size[1] > size[0] else "横版",
                     luma=_base_luma(base), ink_rhythm=ink_rhythm, style=style)
    print("[prompt]", p)
    if dry:
        return dict(dst=None, spec=spec, prompt=p, seed=seed, status="dry")

    base_img = stage_base(base) if mode == "keep" else None
    ref, _ = C.TPLS.get(spec.get("ref_style", font), C.TPLS["cursive"])
    sg = sigmas_from(denoise)

    # 先把 35b 踢出显存，再让 ComfyUI 出图（12G 卡吃不住 22G 模型常驻）
    unload(C.DIRECTOR_MODEL)
    time.sleep(4)

    for attempt in range(3):
        sd = seed + attempt * 137
        try:
            if mode == "keep":
                wf = _wf_redraw(p, sd, size[0], size[1], "redraw_%d" % sd, ref, base_img, sg)
            else:
                # 元素驱动重绘走的就是文生图同一条 workflow（空 latent 全流程），
                # 字的质量与原有管线一致，不新增风险
                wf = S._wf(p, sd, size[0], size[1], "redraw_%d" % sd, ref)
            fn, sub = CC.run(wf)
        except Exception as e:
            print("[redraw] 出图失败:", repr(e)[:200])
            return dict(dst=None, spec=spec, prompt=p, seed=seed, status="failed")
        if not fn:
            continue
        dst = S._save_out(fn, sub, "redraw", text, sd, size)
        print("->", dst)
        return dict(dst=dst, spec=spec, prompt=p, seed=sd, status="rendered", mode=mode)

    return dict(dst=None, spec=spec, prompt=p, seed=seed, status="failed")


def redraw_neat(text, base, hint="", **kwargs):
    """整齐版接口：等价于 style="neat"。"""
    kwargs["style"] = C.STYLE_NEAT
    return redraw(text, base, hint, **kwargs)


def redraw_ink(text, base, hint="", **kwargs):
    """浓淡版接口：等价于 style="ink"。"""
    kwargs["style"] = C.STYLE_INK
    return redraw(text, base, hint, **kwargs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--base", required=True, help="底图路径")
    ap.add_argument("--hint", default="")
    ap.add_argument("--mode", default="recompose", choices=["recompose", "keep"],
                    help="recompose=元素驱动重绘（默认，字最稳）；keep=保底图重绘")
    ap.add_argument("--denoise", type=float, default=0.90,
                    help="仅 keep 模式有效：起始噪声，1.0 全重画，越小越贴底图")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--size", default="1536x864")
    ap.add_argument("--font", default="cursive", choices=list(C.TPLS))
    ap.add_argument("--dry", action="store_true", help="只识别和设计，不出图")
    ap.add_argument("--style", choices=list(C.STYLES), default=None,
                    help="版式：neat 整齐版（默认）/ ink 浓淡版")
    ap.add_argument("--ink-rhythm", action="store_true",
                    help="旧写法，等价于 --style ink")
    ap.add_argument("--subtitle", dest="subtitle", action="store_true", default=None,
                    help="强制加拼音副标（默认 8 字以上自动关闭）")
    ap.add_argument("--no-subtitle", dest="subtitle", action="store_false",
                    help="强制不加副标，只留几何装饰")
    a = ap.parse_args()
    if a.ink_rhythm and a.style == C.STYLE_NEAT:
        ap.error("--ink-rhythm 等价于 --style ink，不能同时指定 --style neat")
    style = a.style or (C.STYLE_INK if a.ink_rhythm else C.DEFAULT_STYLE)
    w, h = (int(x) for x in a.size.lower().split("x"))
    r = redraw(a.text, a.base, a.hint, a.seed, (w, h), a.denoise,
               font=a.font, dry=a.dry, subtitle=a.subtitle, mode=a.mode,
               style=style)
    if a.dry:
        print("\n[元素清单]")
        print(json.dumps(r["spec"].get("element_sheet", {}), ensure_ascii=False, indent=2))
    print("\n[结果]", r["status"], r["dst"] or "")
