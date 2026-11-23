# -*- coding: utf-8 -*-
"""副标文本：只允许「能核对」的字进画面。

模型自己拼拼音/英文实测会出错（把「潮起潮落」拼成 chaogi、把「人间值得」译成
a worth while existence 这类）。所以副标文本一律由这里生成，模型只负责摆放和字形：

  - 拼音：pypinyin 逐字算，多音字走词组词典（银行行长 yín háng háng zhǎng 实测正确）
  - 英文：不接受模型自由发挥，只在调用方显式给出时使用
  - 拿不到 pypinyin 就返回空串——宁可不出副标，也不出错

上层在提示词里必须同时给出 RULE，把字数钉死，禁止模型自己加词改拼写。
"""
import re

try:
    from pypinyin import pinyin as _py, Style as _Style
    HAS_PINYIN = True
except Exception:
    _py = None
    _Style = None
    HAS_PINYIN = False

_CJK = re.compile(r"[\u4e00-\u9fff]")

RULE = ("副标文字必须逐字母照抄上面的字母串，不许多一个字母、不许少一个字母、"
        "不许改拼写、不许自己另拼一遍、不许再加任何单词或标点")


def pinyin(text, tones=True, spaced=True):
    """片名 → 无标点的拼音串。'雨夜独行' → 'yǔ yè dú xíng' / 'yu ye du xing'。"""
    if not HAS_PINYIN:
        return ""
    clean = "".join(_CJK.findall(text or ""))
    if not clean:
        return ""
    style = _Style.TONE if tones else _Style.NORMAL
    syl = [x[0] for x in _py(clean, style=style)]
    return (" " if spaced else "").join(syl)


def build(text, tones=True, spaced=True, english=""):
    """副标整串。英文只在显式给出时拼在后面。"""
    py = pinyin(text, tones=tones, spaced=spaced)
    en = (english or "").strip()
    if py and en:
        return py + "  ·  " + en
    return py or en


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["雨夜独行", "人间烟火气最抚凡人心", "银行行长"]):
        print(t, "->", build(t))
    print("HAS_PINYIN", HAS_PINYIN)
