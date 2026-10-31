# 评价边界全入口审计与干净基线计划（2026-10-31）

> **状态：** DONE
> **来源章节：** RMUC2027_UAV_V2_2.md §8.6、§10.4、§17、§20.2、§20.11；C 诊断交接
> **证据域：** 源码审计 + 单元测试 + 仿真（前台可视 GUI）
> **Gate：** 不提升任何 Gate

## 目标

1. 扫描全部 env.reset/step/_reset_idx/episode_length_buf/terminated/truncated 入口，建立清单。
2. 统一评价边界合同（EpisodeBoundary），修正 velocity/reach/compare（含调参/最终/故障），保留 layered 已修复路径；训练入口单独语义。
3. 审计历史 velocity/reach/compare/tuning/faults/layered 的污染，区分确认/未发现/数据不足。
4. 以前台可视 GUI 重建 velocity、reach、compare 60、faults 16 干净基线；layered 按隔离论证复用 final_run4。
5. 扩展独立核验、报告、交接、提交；不推送。

## 执行

- 新增 EpisodeBoundary 与测试；velocity/reach/compare 接入，终止分类改用步前状态，截断/未声明 reset 显式 INVALID。
- 修正 CSV 列表列引用（csv_io）与历史 legacy 解析；补充 manifest gui_mode/commit/hash。
- 历史审计脚本与结果；干净基线 GUI 运行（日志含窗口创建）。
- 独立核验：verify_baseline_runs / verify_guidance_runs（边界扩展） / verify_layered_runs。

## 验收

- 全入口清单与历史审计完成；正式入口边界处理有回归测试。
- 干净基线完成并核验；历史数值修订索引明确替代关系；旧文件保留。
- pytest/文档审计/diff 检查通过；中文提交；不推送。
