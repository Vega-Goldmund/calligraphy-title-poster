"""集中配置：本机路径为默认值，全部可用环境变量覆盖，便于迁移到别的机器。

环境变量一览（均带 TG_ 前缀）：
  TG_COMFY_URL / TG_OLLAMA_URL      本地服务地址
  TG_COMFY_ROOT                     ComfyUI 根目录（其下有 input/output/ComfyUI_windows_portable）
  TG_INPUT_DIR / TG_OUTPUT_DIR / TG_SAVE_DIR   输入/输出/成片目录（可单独覆盖）
  TG_DIRECTOR_MODEL / TG_CHECK_MODEL           Ollama 模型名
  TG_CACHE_DIR                      导演缓存目录
"""
import os

# Skill 自身目录
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
REFERENCES_DIR = os.path.join(SKILL_DIR, "references")


def _env(name, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


# ---- 本地服务端点 ----
COMFY_URL = _env("TG_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OLLAMA_URL = _env("TG_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

# ---- ComfyUI 目录结构 ----
COMFY_ROOT = _env("TG_COMFY_ROOT", r"D:\ComfyUI")
COMFY_PORTABLE = os.path.join(COMFY_ROOT, "ComfyUI_windows_portable")
COMFY_PY = os.path.join(COMFY_PORTABLE, r"python_embeded\python.exe")

INPUT_DIR = _env("TG_INPUT_DIR", os.path.join(COMFY_ROOT, "input"))
OUTPUT_DIR = _env("TG_OUTPUT_DIR", os.path.join(COMFY_ROOT, "output"))
SAVE_DIR = _env("TG_SAVE_DIR", os.path.join(OUTPUT_DIR, "projects", "title_generator"))

CACHE_DIR = _env("TG_CACHE_DIR", os.path.join(SAVE_DIR, ".cache"))

# ---- Ollama 模型 ----
DIRECTOR_MODEL = _env("TG_DIRECTOR_MODEL", "qwen3.5:35b")
DIRECTOR_FALLBACK = _env("TG_DIRECTOR_FALLBACK", "qwen3.5:9b")
CHECK_MODEL = _env("TG_CHECK_MODEL", "qwen3.5:35b")

# ---- 底图重绘（可选功能，只在传 --base 时用到）----
# 读底图元素需要一个多模态模型。默认复用导演模型（qwen3.5:35b 自带 vision，实测准）。
# 想用更轻的视觉模型可覆盖，如 TG_REDRAW_VISION_MODEL=qwen2.5vl:7b；
# 但 7b 实测会漏掉风机、旗帜这类关键锚点，且同一张图两次识别结果不一致，不建议正式用。
REDRAW_VISION_MODEL = _env("TG_REDRAW_VISION_MODEL", "")

# ---- 绘图模型文件名（ComfyUI workflow 内引用）----
UNET_NAME = _env("TG_UNET_NAME", "qwen_image_2.1_turbo_int8_convrot.safetensors")
CLIP_NAME = _env("TG_CLIP_NAME", "qwen3vl_8b_int8_convrot.safetensors")
VAE_NAME = _env("TG_VAE_NAME", "qwen_image_2.1_vae_bf16.safetensors")

# ---- 笔法参考图（LoadImage 只认文件名；文件需位于 ComfyUI input 目录）----
# key -> (input 目录中的文件名, 说明)
TPLS = {
    "heavy": ("font_heavy_0.jpg", "重笔连写"),
    "dry": ("font_dry_0.jpg", "枯笔飞白"),
    "cursive": ("caoshu_ref3.png", "细瘦缠绕"),
}
FONT_KEY = "cursive"

# 参考图在 ComfyUI input 下的相对子目录（LoadImage 传不带路径文件名，0.45 可在子目录找到）
REF_SUBFOLDER = {
    "caoshu_ref3.png": "",
    "font_heavy_0.jpg": "title_refs",
    "font_dry_0.jpg": "title_refs",
}

# ---- 导演运行时读取的异构笔法谱 ----
ISOMORPH_DOC = os.path.join(REFERENCES_DIR, "isomorph.md")

# ---- 固定 8 步 sigmas（背景改动最小档）----
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"
NEGATIVE_PROMPT = "黑字、黑色笔画、暗字、笔画变黑、实心黑块、字发灰、墨团、墨块、脏污"


# ---- 书写视频（可选功能，只在显式运行 write_video.py 时用到，主流程不调用）----
# MiniMax H3 的 8 步蒸馏版及其配套 VAE/文本编码器；需要 ComfyUI 0.45+ 自带的
# comfy_extras/nodes_minimax_h3.py，不需要自定义节点。
H3_UNET = _env("TG_H3_UNET", "fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors")
H3_CLIP = _env("TG_H3_CLIP", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
H3_VAE = _env("TG_H3_VAE", "minimax_h3_video_vae_int8_convrot.safetensors")
H3_VAE_AUDIO = _env("TG_H3_VAE_AUDIO", "minimax_h3_audio_vae_fp32.safetensors")


def ensure_dirs():
    """确保输出/缓存目录存在。"""
    for d in (SAVE_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)
