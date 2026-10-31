# 历史结论修订索引（评价边界，2026-10-31）

| 旧结论/数值 | 状态 | 新证据/替代 |
| --- | --- | --- |
| 速度执行链方向/组合/停止/过期/reset/KINEMATIC 检查 PASS | 仍可用 | 干净 GUI velocity_clean3 逐项一致，新增边界字段核验 |
| 6 episode reach 6/6 SUCCESS（smoke） | 仍可用 | 干净 GUI reach_clean/run2 6/6，INCOMPLETE smoke |
| compare 比例/制动均 30/30；比例更快 | 方向仍可用，数值被替代 | clean compare：比例 3.285 s、制动 3.403 s，Δ+0.118 s，末距差 0.0924 m；旧值 3.478/3.597 s、0.0942 m |
| 专项故障 16 episode 分类正确 | 仍可用 | clean faults 16 episode 全预期分类，接触 4/4 PhysX |
| layered E 类 19/25 越界 | 已被 E 修复替代 | E 诊断报告；final_run3 E 25/25 |
| layered C 类 1 越界（C-021） | 已被 C 修复替代 | final_run4 C 25/25 |
| layered C/D/E 逐 episode 时间与 C-021 | 不可用（auto-reset 污染） | 见 C 诊断报告与 layered 报告修订 |
| tuning 候选选择 | 待重验（数据不足） | 无逐 step；候选 A 配置未保留；未重跑，最终比较用既有冻结参数 |

旧文件与 hash 未覆盖；本索引不改变历史运行方式（headless 记录保留）。
