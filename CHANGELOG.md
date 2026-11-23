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
