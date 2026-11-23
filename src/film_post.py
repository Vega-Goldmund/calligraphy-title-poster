"""胶片后处理：去 AI 光滑感 —— 压灰、胶片颗粒、高光 halation、暗角、色偏"""
import sys, os
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

src = sys.argv[1]
strength = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(np.float32) / 255.0

# 1) 压对比度、提灰、高光收住（让纯白不刺眼）
gray = 0.5 + (a - 0.5) * 0.82
a = gray
a = a * 0.96 + 0.05  # 整体提灰，黑不死

# 2) 胶片颗粒：亮度颗粒（主）+ 彩色颗粒（辅）
rng = np.random.default_rng(20240607)
h, w, _ = a.shape
lum_noise = rng.normal(0, 1, (h, w)).astype(np.float32)
# 颗粒在暗部/中间调更明显
lum = a.mean(axis=2)
mask = (1.0 - lum) ** 1.5 * 0.5 + 0.5
for c in range(3):
    a[:, :, c] += lum_noise * 0.055 * strength * mask
col = rng.normal(0, 1, (h, w, 3)).astype(np.float32)
a += col * 0.022 * strength

# 3) 高光 halation：亮部轻微扩散、带暖红
x = np.clip(a, 0, 1)
hi = np.clip((x.max(axis=2) - 0.72) / 0.28, 0, 1)[:, :, None]
glow = Image.fromarray((x * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(14))
g = np.asarray(glow).astype(np.float32) / 255.0
g[:, :, 0] *= 1.06; g[:, :, 2] *= 0.96
a = a * (1 - hi * 0.35) + g * (hi * 0.35)

# 4) 轻微暖色偏 + 暗角
a[:, :, 0] *= 1.015; a[:, :, 2] *= 0.985
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
dx = (xx - w / 2) / (w / 2); dy = (yy - h / 2) / (h / 2)
vig = 1 - np.clip(dx * dx + dy * dy, 0, 2) * 0.16
a *= vig[:, :, None]

out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
dst = src.replace(".png", "_film.png")
out.save(dst)
print("->", dst)
