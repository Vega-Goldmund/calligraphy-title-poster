## Unreleased

### Added

- 两套正式版式接口：`--style neat`（整齐版，默认）与 `--style ink`（浓淡版），`single` / `redraw` / `alpha` / `run.py` / 工作台全部接通。
- Python 侧 `stable_render_neat` / `stable_render_ink`，以及 `redraw_neat` / `redraw_ink` 包装；核心函数统一接受 `style="neat" | "ink"`。
- 工作台新增「05 墨版」区块，选择写入任务参数并持久化到 `localStorage`。
- 5 组本地 A/B（2 / 4 / 7 / 10 / 18 字）；产物保留在 ComfyUI 输出目录，不入库。

### Changed

- `--ink-rhythm` 保留为旧写法，等价于 `--style ink`；与 `--style neat` 同时使用会直接报错。
- `config.resolve_style()` 统一解析：`style` 优先，`ink_rhythm=True` 兜底为 `ink`，默认取 `config.DEFAULT_STYLE`（当前 `neat`）。
- `config.DEFAULT_STYLE` 可一处切换全局默认版式，不必改各个 CLI。
- 工作台 ComfyUI 候选端口补入 `8191`，主实例 8188 卡死时可自动落到备用实例。

### Known issues

- 7 字金色底案例在浓淡版下仍可能首字过重、其余偏淡；建议先小批量试。
- `alpha` 的浓淡版只做过 2 字冒烟，笔画比整齐版更厚，未纳入 5 组 A/B。

# v0.1.0 · 2026-11-23

首个公开版本。把项目从个人 Skill 包整理成可独立运行的仓库。

## Added

- 三条产线：文生图 `single`、底图重绘 `redraw`、透明字层 `alpha`
- 导演 / 设计书 / 渲染两段式链路，导演出图前卸载释放显存
- 环境自检 `src/preflight.py`，缺什么直接给修复命令
- 可选本地工作台 `workbench/`：三条产线、批量队列、作品库
- 14 例 / 78 字批量验收数据 `benchmark/results.csv`
- 12 张示例成图、3 张笔法参考图、19 章研发记录 `docs/dev-log.md`
- Apache-2.0 代码许可与模型许可边界 `NOTICE`

## Known issues

- 亮底偶发黑白混用（`cfg=1` 先验，措辞压不住）
- 重绘不是像素级保真，细节会被概括
- 偶发重复字、个别虚锚点（烟/雾/光）不落地
- 长任务仍需人工盯 ComfyUI 进程

## Notes

- 不含任何模型权重；Qwen-Image 2.1 为 Qwen Research License，仅研究/评估用途
