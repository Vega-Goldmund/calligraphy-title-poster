# 模型与依赖

本仓库**不包含任何模型权重**。以下文件需自行下载，并按目录放好；文件名不同时可用 `TG_*` 环境变量覆盖（见 `src/config.py`）。

## ComfyUI

- 版本：0.45.0+，需含 `comfy_extras.nodes_qwen`，提供 `TextEncodeQwenImage21` 与 `QwenImage21Cache`。
- 不需要安装任何自定义节点。

| 文件 | 放置目录 | 大小 |
|---|---|---|
| `qwen_image_2.1_turbo_int8_convrot.safetensors` | `models/diffusion_models/` | 6.8 GB |
| `qwen3vl_8b_int8_convrot.safetensors` | `models/text_encoders/` | 8.7 GB |
| `qwen_image_2.1_vae_bf16.safetensors` | `models/vae/` | 0.6 GB |

模型放在别处时，用 ComfyUI 的 `extra_model_paths.yaml` 配外部路径。文件名不同则覆盖：

```bash
TG_UNET_NAME=... TG_CLIP_NAME=... TG_VAE_NAME=...
```

## Ollama

| 模型 | 用途 | 大小 |
|---|---|---|
| `qwen3.5:35b` | 导演设计 + 逐字质检 + 重绘读图 | 约 22 GB |
| `qwen3.5:9b` | 导演兜底（可选） | 约 6.6 GB |

```bash
ollama pull qwen3.5:35b
ollama pull qwen3.5:9b
```

`qwen3.5:35b` 自带 vision，底图重绘不需要额外装视觉模型。轻量替代 `qwen2.5vl:7b` 会漏风机、旗帜等关键锚点，且同一张图两次识别结果不一致，不建议正式使用。

## 可选：书写视频（MiniMax H3）

默认不调用，只影响 `src/write_video.py`。需要额外约 44 GB 权重，12 GB 卡上长提示词容易把文本编码器激活内存撑爆。

| 文件 | 目录 | 大小 |
|---|---|---|
| `fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors` | `models/diffusion_models/` | 20.6 GB |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` | 14.6 GB |
| `minimax_h3_video_vae_int8_convrot.safetensors` | `models/vae/` | 2.6 GB |
| `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` | 0.6 GB |

## Python

```bash
python -m pip install -r requirements.txt
```

- `Pillow`、`requests`：出图必需。
- `pypinyin`：仅 `--subtitle` 需要；缺失时 `HAS_PINYIN=False`，副标一律不出，不影响其它功能。

## 硬件

实测环境：RTX 5070 Ti Laptop / 12 GB 显存，文生图单张 48–226 s（含 35B 冷启动；设计书命中缓存约 22 s）。显存更小会变慢，甚至无法同时容纳导演与绘图模型。
