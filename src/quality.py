"""出图质检 · 封闭式核对（视觉大模型逐字确认）。

为什么不用开放式 OCR：狂草里写得轻、缠绕的字，无论小 OCR 还是大模型，
开放式"读出所有字"都会漏（实测「只」「道」「凡」都被漏过）。
改成把目标片名告诉模型、让它逐字确认"在不在"，只做有/无判断，
漏识别误报消失，真正缺字（如「后会友期」缺「会」）仍稳定抓到。
"""
import base64, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

OLLAMA = C.OLLAMA_URL
CHECK_MODEL = C.CHECK_MODEL


def verify(text, path, model=CHECK_MODEL, retries=2, wait=5):
    """封闭式核对，返回 (missing, reliable)。
    reliable=True：确实完成了核对，missing 可信；
    reliable=False：质检服务故障（如出图后立即调用撞上显存竞争、ollama 500），
    重试用尽也不硬等，软放行、交给人工验收。"""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    prompt = (
        f"这张书法图里应该写着「{text}」。请逐个核对这 {len(text)} 个字是否都出现在图中，"
        "允许连笔、简化、飞白、字与字缠绕。把每个字归入 present（在图里）或 missing（确实没有）。"
        "只输出 JSON：{\"present\":[...],\"missing\":[...]}"
    )
    body = {"model": model, "prompt": prompt, "images": [b64],
            "stream": False, "think": False, "format": "json", "keep_alive": "20s"}
    last = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(OLLAMA + "/api/generate",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=180).read()).get("response", "")
            data = json.loads(r)
            return [c for c in data.get("missing", []) if c], True
        except Exception as e:
            last = repr(e)
            if attempt < retries:
                print(f"[verify 第{attempt + 1}次失败，{wait}s 后重试] {last[:90]}")
                time.sleep(wait)
    # 重试用尽：软放行（reliable=False），不把主流程拖入死循环，交人工验收
    print("[verify 重试用尽，软放行待人工验收] ", last[:90])
    return [], False


def check(text, path, model=CHECK_MODEL):
    """返回 (ok, missing, reliable)。
    只有 reliable 且无缺字才算自动通过；服务故障时 reliable=False，提示人工验收。"""
    missing, reliable = verify(text, path, model)
    return (reliable and len(missing) == 0), missing, reliable


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        t, p = sys.argv[1], sys.argv[2]
        ok, missing, reliable = check(t, p)
        tag = "合格" if ok else "不合格 缺" + "".join(missing)
        if not reliable:
            tag += "（质检服务故障，软放行）"
        print("结论:", tag)
    else:
        print("用法: python quality.py <片名> <图片路径>")
