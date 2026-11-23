"""片名海报 · 总导演

不是"选模板"，是从零产出一份完整制作规格：
  文字怎么排 / 笔法质感 / 怎么拟物 / 什么颜色 / 背景画什么（独立提示词）
"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

OLLAMA = C.OLLAMA_URL
MODEL = C.DIRECTOR_MODEL
FALLBACK = C.DIRECTOR_FALLBACK
HERE = C.HERE
CACHE = os.path.join(C.CACHE_DIR, "director_cache.json")
DOC = C.ISOMORPH_DOC

SYS = (
"你是电影片名海报的总导演，负责一次性定下全部制作规格。你不选现成模板，你是从零设计。\n"
"【核心书写哲学 · 整幅狂草】除下面的端庄例外，默认把整组字当作一整幅狂草来设计，而不是一个个独立端正的单字：\n"
"1 一气呵成、缠绕连笔：上一字收笔直接牵丝连到下一字起笔，字与字之间有看得见的细牵丝、整组像一条连绵气脉，有夸张的大弧线和游丝，允许连写、简化，但每个字的轮廓都在、整句读得出，一字不缺、不许缺字，也不合并成一团。\n"
"2 细劲为骨、飞白为肌（狂草的命门，也是和现代文艺体的分界）：这是毛笔在纸上快速挥写，不是马克笔或秀丽笔。整组字以细劲线条为绝对主调，绝大多数笔画都瘦、利、细，绝不能写成粗细均匀、实心光滑的一条。同一条线内部要有明显的提按宽窄变化：只在极少数重音字的关键处短暂铺开变宽，随即立刻收细成游丝，收笔放锋带出尖梢，宽窄落差要明显，但宽处也只是短暂铺开、不是实心块。大量枯笔飞白贯穿全字：快速行笔时笔画里露出丝丝背景、边缘毛涩断续，部分笔画甚至整字由一组平行细丝组成、中间大量露出背景，而不是实心填满。字与字之间牵丝缠绕、笔断意连，有迅疾的书写速度感。关键：宽窄只是同一支笔的提按、所有笔画颜色一样亮，绝不能把宽处写成灰色或黑色，不要用\"重墨、浓墨、藏锋、压住阵脚、墨色淋漓、铁石、淋漓\"这类会被理解成黑字的说法。\n"
"3 轻盈疏朗、敢空：整组字明显收小、缩成画面中部一小块，上下左右留出大片空白，画面以空为主，不要撑大、不要塞满。\n"
"4 字色统一锁死、且必须立得住：全组只用一种颜色，暗背景必须用明显亮于背景的字（亮白、青蓝、亮粉、荧光绿、红、紫这类亮色），亮背景才允许用暗字。优先柔和、低饱和的同色系，避免刺眼的荧光和发光感，字要像写在环境里、而不是发光贴上去。字色与背景之间必须有足够明度差，不许选铁灰、铅灰、深灰、暗褐这类和暗背景明度撞在一起的颜色。\"柔和、偏灰\"是指不要纯白刺眼、边缘可以柔、饱和可以低，不是让你真的用深灰色。画面里任何深色都只是飞白阴影、绝不是字色，不许出现第二种颜色的字、不许出现黑字。\n"
"5 散点排布、字势倾斜、大小欹侧、疏密肆意：承载情绪的重音字（关键名词、动词）放大、在关键处短暂铺开，虚词和连接字缩小、用细劲游丝轻带；放大的字仍以细劲为主、只在关键处短暂变宽，不要实心填满。判断重音字是你的工作，不要把所有字写成一样大。\n"
"【端庄例外】只有正剧、官方、纪念、纪录片这类必须端庄的场合，才把 dignified 设为 true：此时字独立端正、字号可以统一、不连笔缠绕。\n"
"【仍然是毛笔字】无论怎么写，必须是一笔一笔写出来的毛笔字，不能变成金属刻字、衬线印刷体、描边字、矢量图形或 3D 立体字。\"铁质、无毛刺、内嵌细纹\"这类材质化写法会做出刻字，禁止这样描述。允许为了字形美观在同一幅里让不同字分别用简体或繁体（书法里常见），但同一个字不要繁简混写、每个字都要规范可辨。\n"
"【拟物】你可以让至多两笔变成画面里已经存在的景物（一笔接山脊、末笔化成枝条之类），宁可险一点，但字必须还能读、这一笔仍然属于原来的字。\n"
"【装饰系统 · 第二层呼吸】你可以在主字组之外，克制地加一组装饰，让画面有设计层次：\n"
"1 手写花体副标：在主字下方或旁边加一行明显小的花体字，内容是片名的拼音（全小写连写，如 rimuhuoshaoyun、yanxing）或一句贴合意境的英文短句（如 a haughty fish in the mortal crowd）。必须是手写花体、和中文同一颜色或同色系、明显小、只作衬托，绝不能比中文醒目、不能喧宾夺主，也不许用印刷体。\n"
"2 几何点线：在副标或字组周围点缀极简的几何元素——由小到大的圆点、细横线、小矩形框，和字组对齐、留白，作为排版的呼吸点。几何元素要少而精、和字同色，不要花哨。\n"
"加不加、加拼音还是英文、几何怎么排，由你根据句子气质决定：字多、情绪满的可以不加或只加一点点；简洁的片名适合加一组。装饰是锦上添花、不是必须，整体仍以中文和留白为主。\n"
"【意境 · 最高要求】海报不是把字和景画清楚，是营造一种可感的情绪。意境靠五件事，缺一不可：\n"
"1 留白：画面要敢空，大区域是无细节的天空、雾、虚化，让观者有想象空间，绝不把字和景塞满。\n"
"2 虚实：景全部浅景深、失焦、朦胧，以剪影和轮廓为主，不要清晰锐利的细节；字相对实、但也带飞白。\n"
"3 情绪锚点：背景里放一个小而模糊的人物剪影（背影或侧影、看不清脸），位置靠边、不要居中、不要摆姿势，作为共情入口，而不是一个清晰的、摆拍的人。\n"
"4 强弱节奏（均匀用力是大忌）：像说话有重音、音乐有强弱拍。一两个主字要肯定、写到位、压得住；其余衬托字要放松、轻、可以连笔带过、部分压到极轻。要拉开的是用笔的强弱，不只是字号大小——每个字都写得一样完整、一样卖力，就是失败。\n"
"5 统一色调：整个画面笼罩在一种与句子情绪一致的色温里（孤独用冷灰、离别用黄昏紫、思念用朦胧蓝），景是情绪的外化、情景交融。\n"
"【先读文化，再定景 · 设计背景前必须先做的功课】不要一上来就写通用风景，先在心里把片名的文化语境想清楚，再让背景成为它的视觉化：\n"
"1 出处与典故：出自哪首诗词、哪篇古文、作者是谁、写于什么时节、当时的情境（如「但愿人长久」是苏轼中秋把酒望月思亲）。\n"
"2 节气物候：若片名是节气或带节气，要对应这个节气独有的物候与传统意象——惊蛰是春雷、草芽、泥土；白露是蒹葭、清晨草木上的白霜露水、归雁、一夜凉一夜，而不是泛泛的秋雾。\n"
"3 传统视觉符号：这个语境里本该出现的具体物件与场景（把酒、望月、桂影、钟声、渔火、归雁、旧窗），优先用这些，而不是放之四海皆准的风景。\n"
"先把这些写进 cultural_context，再据此写背景提示词。判断标准：这个景是不是只有这个片名才成立？换个片名还成立，就是失败的通用背景。\n"
"【背景独立设计】写一段能直接拿去出图的背景提示词，独立完整——景是什么、光线从哪来、什么时间、景深、留白在哪、材质颗粒、色调。必须是能拍到的具体场景（地点、时间、天气、光线、镜头焦段），且要承接上面 cultural_context 里的文化意象，优先失焦、剪影、浅景深、胶片颗粒这类有情绪的画面；不许写风格名或滤镜名（动态模糊、Motion Blur、赛博朋克、油画风、极简风），也不许拿风格词当场景——那样只会画出一张没有景的灰底。这一段里绝对不能出现任何文字。\n"
"【好图四标准 · 设计时逐条对照，也是一张图成不成立的验收纲】\n"
"1 文化特异性（最优先）：背景必须是只有这个片名才成立的景，由它的出处典故、节气物候、传统意象生长出来；禁用「黄昏+落日+电线杆+人物剪影」这类放之四海皆准的万能套路，换个片名还成立就是失败。\n"
"2 字景意象绑定：让一笔接上景里的线、字色呼应环境、拟物点题，字和景是一个整体，不是字浮在背景上的两张皮。\n"
"3 敢做的字：大小、粗细、缠绕、欹侧大胆拉开，主字写到位、衬托字轻带，拒绝每个字一样完整、一样卖力。\n"
"4 自然的光与色调、克制不堆砌：光要像真实环境里的自然天光，不要刻意的丁达尔光束、发光灯泡这种戏剧化光源；道具能少则少、人物剪影小而靠边，整张笼罩在统一色温里。高级感来自克制，不是堆道具加特效。\n"
"硬规则：不加描边、不加投影、不加外发光；拟物最多改两笔；再野也不许缺字。\n"
"只输出 JSON，不要解释。"
)

SCHEMA = """{
 "reading":"一句话理解片名的气质，20字内",
 "dignified":"true 或 false：这个片名是否属于必须端庄的场合（正剧/官方/纪念/纪录片）。为 false 时字号必须有大有小",
 "layout":{
   "lines":["第一行字","第二行字"],
   "block_width":"整组占画面宽度的比例，如 0.62",
   "position":"位置描述，如 上部三分之一、略偏右",
   "leading":"行距关系，如 第二行右移半个字、行距小于字高",
   "scale":"字号差：必须写清哪个字最大、哪个最小、相差多少；若 dignified 为 true 才可写统一",
   "tilt":"倾斜，如 整组右上倾 8 度",
   "occlusion":"被什么压住，如 末字下缘被雾带遮住",
   "emphasis":"强弱节奏：哪个是主字（肯定、写到位）、哪些衬托字放松带过、哪些压到极轻；只准用提按/粗细/轻重描述，不许出现墨、黑、铁等字"
 },
 "font_design":{
   "cursive_flow":"气脉怎么走、哪几个字牵丝相连，并写明哪个字重按成实块、哪个字用细游丝，35字内",
   "stroke":"笔法与质感，如 侧锋干笔、枯笔飞白、细劲游丝，25字内",
   "structure":"结构层面怎么变异，如 重心偏移、连写简化、部件省并，30字内",
   "bold_move":"一处最狠的动作，必须具体，如 末笔拉成一条横跨两字的大弧线，25字内"
 },
 "morph":{"technique":"用哪一招","stroke":"哪一笔变成什么、接到背景里的什么，40字内"},
 "color":{"name":"颜色名","hex":"#rrggbb","relation":"与背景明度关系，20字内"},
 "cultural_context":{
   "origin":"出处与典故：作者、篇目、时节、当时情境，40字内",
   "imagery":"对应的传统意象、节气物候、视觉符号，列出3-5个具体的",
   "why":"为什么这个景只有这个片名才成立，30字内"
 },
 "background":{
   "prompt":"可直接出图的背景提示词，120-200字，承接cultural_context，画面中不得有任何文字",
   "tone":"色调，10字内",
   "anchor":"情绪锚点，如 下方一个模糊的人物背影剪影",
   "negative":"要避免的东西，30字内"
 },
 "decoration":{
   "enabled":"true 或 false：这张是否加装饰（字多情绪满可 false，简洁片名适合 true）",
   "subtitle":"手写花体副标内容：拼音全小写连写，或一句贴合意境的英文短句；不加则空字符串",
   "geometry":"几何点缀，如 右侧三个由小到大的圆点、一条细横线、一个小矩形框；不加则空字符串",
   "placement":"装饰放在哪，如 主字组右下方、与末字对齐；不加则空字符串"
 },
 "reasoning":"为什么这样编排，40字内"
}"""


def _doc():
    try:
        with open(DOC, "r", encoding="utf-8") as f:
            return f.read()[:2600]
    except Exception:
        return ""


def _post(body, timeout=240):
    req = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _load():
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def direct(text, hint="", use_cache=True, temperature=1.0):
    key = f"{text}|{hint}|v1"
    cache = _load()
    if use_cache and key in cache:
        return _san(cache[key])

    user = (f"片名：{text}\n" + (f"补充倾向：{hint}\n" if hint else "")
            + "给这组字做一份完整规格。背景与文字分开描述，背景提示词必须独立成段。\n"
            + "输出 JSON 结构：\n" + SCHEMA)
    body = {
        "model": MODEL, "prompt": user,
        "system": SYS + "\n\n【可用的拟物招法】\n" + _doc(),
        "stream": False, "think": False, "format": "json",
        "keep_alive": "20s",
        "options": {"temperature": temperature, "top_p": 0.95, "num_predict": 1100},
    }
    try:
        try:
            r = _post(body)
        except Exception:
            body["model"] = FALLBACK
            r = _post(body)
        spec = json.loads(r.get("response", "").strip())
    except Exception as e:
        return dict(error=repr(e)[:150], text=text)

    # 补齐缺字段，防止下游 KeyError
    spec.setdefault("layout", {})
    spec.setdefault("morph", {})
    spec.setdefault("color", {})
    spec.setdefault("cultural_context", {})
    spec.setdefault("background", {})
    spec.setdefault("decoration", {})
    for k in ("lines",):
        if not spec["layout"].get("lines"):
            spec["layout"]["lines"] = [text]
    # 强兜底：导演漏填时给一个中性、不套路的自然场景（去掉黄昏/落日/电线杆/剪影万金油）
    if not spec["background"].get("prompt"):
        spec["background"]["prompt"] = (
            "清晨薄雾里的自然景物，浅景深、主体失焦，柔和的自然天光、低饱和，"
            "胶片颗粒、轻微色偏，大块面、没有锐利细节"
        )
    if not spec["color"].get("name"):
        spec["color"]["name"] = "亮白色"
    _san(spec)
    if use_cache:
        cache[key] = spec
        _save(cache)
    return spec


def _clean(s):
    import re
    return re.sub(r"[\[\]【】\'\"‘’“”]", "", str(s or "")).strip()


# 会让模型把字画成黑色/材质的词，做词级替换（不是整句丢弃，保住强弱设计意图）。
# 长词在前（按长度排序处理），避免被短词先替换。
INK_WORDS = {
    # 变黑/材质词：删除
    "墨色淋漓": "",
    "浓墨": "", "重墨": "", "焦墨": "", "泼墨": "", "黑墨": "",
    "墨色": "", "淋漓": "",
    "压住气口": "", "压住阵脚": "", "压住": "",
    # 触发黑色先验的「重按/实块」动作词 → 中性的形状/宽窄语言
    "重按成粗实块": "局部铺开变宽",
    "重按成实块": "局部铺开变宽",
    "重按成块": "局部铺开变宽",
    "重如铁石": "局部铺开变宽",
    "粗实块": "宽处",
    "重按": "铺开",
    "提笔": "收细",
    "墨团": "宽处", "墨块": "宽处",
    "实块": "宽处",
    "铁石": "宽处",
    "墨": "笔",
}


def _no_ink(s):
    """把会触发变黑/材质化的词替换成安全的形状语言或删除，并清理残留标点。"""
    import re
    s = _clean(s)
    for w in sorted(INK_WORDS, key=len, reverse=True):
        s = s.replace(w, INK_WORDS[w])
    s = re.sub(r"\s*[，。；、]{2,}\s*", "，", s)
    return s.strip("，。；、 ")


# ---------- 多方案：一次给 N 套互不相同的规格 ----------
COMBO_CACHE = os.path.join(C.CACHE_DIR, "combo_cache.json")

# 这些词一旦进到提示词，模型就会做刻字/玻璃字，或者把字拆到认不出。
# 导演很爱写它们（"无毛刺""结构崩塌""仅留外框""仅存骨架"），必须在进图前清掉。
BAD_WORDS = ("无毛刺", "铁质", "铁皮", "铁皮感", "内嵌", "刻字", "浮雕", "立体字", "3D", "金属",
             "崩塌", "仅留外框", "仅存骨架", "仅保留外轮廓", "仅剩外轮廓", "只剩轮廓",
             "严重残缺", "完全省略", "省略仅留", "省略仅", "字形残缺", "认不出", "抽象图形")


def _san_text(s):
    """先做变黑词替换，再按逗号/句号切句，丢掉含危险词的句子；全丢光则返回空串"""
    import re
    s = _no_ink(s)
    if not s:
        return ""
    parts = re.split(r"([，。；、])", s)
    out, buf = [], ""
    for seg in parts:
        if seg in "，。；、":
            if buf and not any(w in buf for w in BAD_WORDS):
                out.append(buf + seg)
            buf = ""
        else:
            buf += seg
    if buf and not any(w in buf for w in BAD_WORDS):
        out.append(buf)
    return "".join(out).strip("，。；、 ")


def _san(spec):
    """把一套规格里的危险描述清掉，保住设计意图，去掉会导致缺字/刻字/变黑的说法"""
    F, M, L = spec.setdefault("font_design", {}), spec.setdefault("morph", {}), spec.setdefault("layout", {})
    B, C = spec.setdefault("background", {}), spec.setdefault("color", {})
    for k in ("cursive_flow", "stroke", "structure", "bold_move"):
        if F.get(k):
            F[k] = _san_text(F[k]) or ("一笔一笔写出来的毛笔字" if k == "stroke" else "")
    for k in ("stroke", "technique"):
        if M.get(k):
            M[k] = _san_text(M[k])
    for k in ("scale", "tilt", "leading", "occlusion", "emphasis"):
        if L.get(k):
            L[k] = _san_text(L[k])
    if B.get("anchor"):
        B["anchor"] = _san_text(B["anchor"])
    if C.get("relation"):
        C["relation"] = _san_text(C["relation"])
    CCx = spec.setdefault("cultural_context", {})
    for k in ("origin", "imagery", "why"):
        if CCx.get(k):
            CCx[k] = _san_text(CCx[k])
    Dc = spec.setdefault("decoration", {})
    if Dc.get("subtitle"):
        Dc["subtitle"] = _clean(Dc["subtitle"])
    for k in ("geometry", "placement"):
        if Dc.get(k):
            Dc[k] = _san_text(Dc[k])
    return spec

COMBO_SYS = SYS + (
    "\n【这次要出多套】你要为同一个片名给出 {k} 套彼此明显不同的完整制作方案。\n"
    "它们必须覆盖不同气质：轻、重、险、静、繁、简里挑 {k} 种，不能四套都是同一个情绪。\n"
    "在【笔法】【拟物招法】【版式结构】【背景场景】【字色】这五项里，任意两套至少三项不同；\n"
    "换措辞不算不同——背景换一个完全不同的景、版式换一种完全不同的骨架、笔法换一路完全不同的笔。\n"
    "注意：再险的方案，每个字也必须完整可辨。禁止写「结构崩塌」「仅留外框」「仅存骨架」「笔画严重残缺」这类会让字认不出的做法。\n"
    "每套额外给两个字段：label（3-6 字的风格名，如「枯笔压雪」）、ref_style（从 heavy/dry/cursive 里挑最贴的一套笔法参考）。\n"
)


def _combo_schema(k):
    one = SCHEMA.rstrip().rstrip("}").rstrip()
    one += ',\n "label":"3-6 字的风格名",\n "ref_style":"heavy 或 dry 或 cursive"\n}'
    return ('{"specs":[ 这里共 %d 套，每套都按下面这个结构输出\n' % k) + one + "\n]}"


def combo(text, hint="", k=4, use_cache=True):
    """一次让导演给出 k 套互不相同的方案，避免多张图共用一份 spec 变成四胞胎"""
    key = f"{text}|{hint}|{k}|v1"
    cache = _load()
    cf = {}
    try:
        with open(COMBO_CACHE, "r", encoding="utf-8") as f:
            cf = json.load(f)
    except Exception:
        cf = {}
    if use_cache and key in cf:
        return cf[key]

    body = {
        "model": MODEL,
        "prompt": (f"片名：{text}\n" + (f"补充倾向：{hint}\n" if hint else "")
                   + f"请给出 {k} 套彼此明显不同的完整制作规格。\n"
                   + "输出 JSON：\n" + _combo_schema(k)),
        "system": COMBO_SYS.replace("{k}", str(k)),
        "stream": False, "think": False, "format": "json", "keep_alive": "20s",
        "options": {"temperature": 1.15, "top_p": 0.95, "num_predict": 4000},
    }
    specs = []
    try:
        try:
            r = _post(body, timeout=900)
        except Exception:
            body["model"] = FALLBACK
            r = _post(body, timeout=600)
        data = json.loads(r.get("response", "").strip())
        specs = data.get("specs") if isinstance(data, dict) else data
        if not isinstance(specs, list):
            specs = []
    except Exception as e:
        print("[combo fail]", repr(e)[:200])

    # 规整每套，补字段
    clean = []
    for i, s in enumerate(specs[:k]):
        if not isinstance(s, dict) or s.get("error"):
            continue
        s.setdefault("layout", {})
        s.setdefault("morph", {})
        s.setdefault("color", {})
        s.setdefault("cultural_context", {})
        s.setdefault("background", {})
        s.setdefault("decoration", {})
        if not s["layout"].get("lines"):
            s["layout"]["lines"] = [text]
        s.setdefault("label", f"方案{i + 1}")
        s.setdefault("ref_style", ["heavy", "dry", "cursive"][i % 3])
        _san(s)
        clean.append(s)

    # 不够 k 套就用独立调用补齐（高温，避免重复）
    while len(clean) < k:
        extra = direct(text, hint + " 换一种完全不同的做法", use_cache=False, temperature=1.25)
        if extra.get("error"):
            break
        extra["label"] = extra.get("label") or f"方案{len(clean) + 1}"
        extra.setdefault("ref_style", ["heavy", "dry", "cursive"][len(clean) % 3])
        _san(extra)
        clean.append(extra)

    for s in clean:
        print("[方案]", s.get("label"), "|", s.get("ref_style"), "|",
              (s.get("reading") or "")[:20], "|", (s.get("morph") or {}).get("technique", ""))
    if use_cache and clean:
        cf[key] = clean
        with open(COMBO_CACHE, "w", encoding="utf-8") as f:
            json.dump(cf, f, ensure_ascii=False, indent=1)
    return clean

def background_prompt(spec):
    """背景段：独立、无字"""
    bg = spec.get("background", {})
    p = _clean(bg.get("prompt", ""))
    if bg.get("tone"):
        p += f"整体色调：{_clean(bg['tone'])}。"
    p += "画面中没有任何文字、字母、数字、水印、边框。电影摄影感，真实的镜头缺陷。"
    return p


def type_prompt(spec, text):
    """文字段：版式 + 笔法 + 拟物 + 字色"""
    L, M, C = spec.get("layout", {}), spec.get("morph", {}), spec.get("color", {})
    p = f"在这张照片上写上片名「{text}」。"

    if L.get("block_width"):
        p += f"整组字占画面宽度约 {_clean(L['block_width'])}。"
    if L.get("position"):
        p += f"位置在{_clean(L['position'])}。"
    if L.get("lines") and len(L["lines"]) > 1:
        p += "分 {} 行，逐行为：{}。".format(len(L["lines"]), " / ".join(_clean(x) for x in L["lines"]))
    if L.get("leading"):
        p += f"{_clean(L['leading'])}。"
    if L.get("scale"):
        p += f"{_clean(L['scale'])}。"
    if L.get("tilt"):
        p += f"{_clean(L['tilt'])}。"
    if L.get("occlusion"):
        p += f"{_clean(L['occlusion'])}。"

    if spec.get("font_design"):
        F = spec["font_design"]
        p += "字体设计："
        if F.get("stroke"):
            p += f"{_clean(F['stroke'])}。"
        if F.get("structure"):
            p += f"结构上{_clean(F['structure'])}。"
        if F.get("bold_move"):
            p += f"必须做的一处动作：{_clean(F['bold_move'])}。"
    elif spec.get("glyph"):
        p += f"笔法：{_clean(spec['glyph'])}。"

    if C.get("name"):
        p += f"整组字只用一种颜色：{_clean(C['name'])}"
        p += f" {_clean(C['hex'])}" if C.get("hex") else ""
        p += "。"
    if C.get("relation"):
        p += f"{_clean(C['relation'])}。"

    if M.get("stroke"):
        p += f"拟物：{_clean(M['stroke'])}。这一笔必须和字的其余部分连写，不是贴上去的图案。"
        if any(w in _clean(M["stroke"]) for w in ("缺口", "残缺", "咬掉", "切掉", "撕")):
            p += "缺口只能占该字宽度的五分之一以内，主体结构必须完整可读。"

    p += "不描边、不加投影、不发光；字的笔画要压在背景的景物上，与枝条、山脊、雾气有前后遮挡。"
    Dc = spec.get("decoration") or {}
    sub = Dc.get("subtitle") or spec.get("subtitle")
    if Dc.get("enabled") and sub:
        if Dc.get("placement"):
            p += f"在{_clean(Dc['placement'])}，"
        p += f"加一行很小的手写花体副标 {_clean(sub)}，和中文同色、只作衬托。"
        if Dc.get("geometry"):
            p += f"旁边点缀极简几何：{_san_text(Dc['geometry'])}。"
    p += "画面中不要出现其他无关文字、字母、数字。"
    import re
    return re.sub(r"。+", "。", p)


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "后会友期"
    hint = "" if len(sys.argv) <= 2 else sys.argv[2]
    s = direct(t, hint, use_cache=("--fresh" not in sys.argv))
    print(json.dumps(s, ensure_ascii=False, indent=1))
    print("\n[背景提示词]\n" + background_prompt(s))
    print("\n[文字提示词]\n" + type_prompt(s, t))
