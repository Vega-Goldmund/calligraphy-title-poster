"""统一入口：环境自检 → 导演设计 → 出图 →（可选）质检/胶片后处理。

常用：
  python run.py 惊蛰                      # 横版单张，默认细瘦缠绕狂草
  python run.py 末班地铁 --vertical       # 竖版
  python run.py 裸辞 --fresh              # 不用导演缓存，重新设计
  python run.py 凡尘 --verify             # 出图后用 35b 逐字核对
  python run.py 惊蛰 --film               # 追加胶片后处理（去 AI 光滑感）
  python run.py 山河 --combo 4            # 一次出 4 套不同方案
  python run.py 惊蛰 --size 1920x1080     # 自定义尺寸
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import single


def _parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def _preflight_ok(force):
    import preflight
    checks = preflight.run(autofix=True)
    bad = [c for c in checks if not c["ok"] and c["critical"]]
    for c in checks:
        if not c["ok"]:
            print(("[!!] " if c["critical"] else "[--] ") + c["item"]
                  + (" — " + c["detail"] if c["detail"] else ""))
    if bad and not force:
        print("\n关键环境未就绪，已中止。可先按上面提示修复，或加 --force 强制继续。")
        return False
    return True


def _maybe_film(path):
    out = subprocess.run([sys.executable, os.path.join(C.HERE, "film_post.py"), path],
                         capture_output=True, text=True)
    print(out.stdout.strip())
    if out.returncode != 0:
        print("胶片后处理失败:", out.stderr[:300])
        return path
    return path.replace(".png", "_film.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--hint", default="")
    ap.add_argument("--vertical", action="store_true")
    ap.add_argument("--size", type=_parse_size, default=None)
    ap.add_argument("--font", default=C.FONT_KEY, choices=list(C.TPLS))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--film", action="store_true")
    ap.add_argument("--combo", type=int, default=0)
    ap.add_argument("--base", default="",
                    help="底图路径：给了就走「读图→元素驱动重绘」，不给就是原来的文生图")
    ap.add_argument("--mode", default="recompose", choices=["recompose", "keep"],
                    help="重绘方式：recompose 元素驱动重画（默认，字最稳）；keep 保底图重绘")
    ap.add_argument("--denoise", type=float, default=0.90,
                    help="仅 --mode keep 有效：起始噪声，越小越贴底图（字也越弱）")
    ap.add_argument("--dignified", action="store_true",
                    help="重绘时走端庄路线（默认整幅狂草）")
    ap.add_argument("--no-subtitle", action="store_true",
                    help="强制不加副标（默认就是不加）")
    ap.add_argument("--subtitle", action="store_true",
                    help="加一行拼音副标：文字由 subtitle.py 用 pypinyin 程序生成，可核对")
    ap.add_argument("--subtitle-en", default="",
                    help="副标里追加的英文；只有显式给出才出现，不接受模型自己翻译")
    ap.add_argument("--no-tones", action="store_true",
                    help="拼音不带声调（默认带声调）")
    ap.add_argument("--alpha", action="store_true",
                    help="生成透明背景文字层（RGBA），不画背景、原图不动")
    ap.add_argument("--color", default="#EDE3D2",
                    help="透明文字颜色 hex（仅 --alpha 有效），默认暖米白")
    ap.add_argument("--seed", type=int, default=0,
                    help="透明文字随机种子（仅 --alpha 有效），默认按时间")
    ap.add_argument("--skip-check", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    size = a.size or ((864, 1536) if a.vertical else (1536, 864))

    if not a.skip_check and not _preflight_ok(a.force):
        return 1

    # 副标：默认不出；出了也必须是程序生成、可核对的文字
    single.SUBTITLE_FORCE = True if a.subtitle else False
    single.SUBTITLE_EN = a.subtitle_en
    single.SUBTITLE_TONES = not a.no_tones
    import redraw as _R
    _R.SUBTITLE_EN = a.subtitle_en
    _R.SUBTITLE_TONES = not a.no_tones
    sub_flag = True if a.subtitle else False

    # 透明背景文字：独立功能，不画背景、不调导演
    if a.alpha:
        import transparent_text as TT
        r = TT.generate(a.text, seed=a.seed, size=size, color=a.color, font=a.font)
        print("\n===== 透明文字结果 =====")
        print("状态:", r["status"], " 颜色:", r["color"], " 文件:", r.get("dst") or "")
        return 0 if r.get("dst") else 1

    # 传了底图才走重绘；不传完全走原来的文生图路径
    if a.base:
        import redraw
        r = redraw.redraw(a.text, a.base, a.hint, size=size, denoise=a.denoise,
                          font=a.font, mode=a.mode,
                          subtitle=sub_flag, cursive=not a.dignified,
                          use_cache=not a.fresh)
        dst = r.get("dst")
        print("\n===== 重绘结果 =====")
        print("模式:", r.get("mode", a.mode), " 状态:", r["status"], " 文件:", dst or "")
        if not dst:
            return 1
        if a.film:
            dst = _maybe_film(dst)
            print("最终文件:", dst)
        return 0

    if a.combo:
        results = single.render_set(a.text, a.hint, k=a.combo, size=size,
                                    use_cache=not a.fresh, font=a.font)
        paths = [r.get("dst") for r in results if r.get("dst")]
        print("\n===== 多方案出图 =====\n" + "\n".join(p for p in paths if p))
        return 0 if paths else 1

    r = single.stable_render(a.text, a.hint, size=size,
                             use_cache=not a.fresh, font=a.font)
    dst = r["dst"]
    print("\n===== 出图结果 =====")
    print("状态:", r["status"], " 文件:", dst)
    if not dst:
        return 1

    if a.verify:
        import quality
        ok, missing, reliable = quality.check(a.text, dst)
        print("质检:", "合格" if ok else "缺字 " + "".join(missing),
              "" if reliable else "（服务故障软放行）")
    if a.film:
        dst = _maybe_film(dst)
        print("最终文件:", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
