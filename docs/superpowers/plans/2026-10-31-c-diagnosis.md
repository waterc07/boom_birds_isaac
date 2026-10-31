# C 类动态实体残留越界诊断计划（2026-10-31）

> **状态：** DONE（根因为评价 episode 边界缺陷；已修复并回归）
> **来源章节：** docs/design/RMUC2027_UAV_V2_2.md §8.6、§13.5、§20.2、§20.11；HANDOFF_20261031_E_DIAGNOSIS.md §6
> **证据域：** 单元测试 + 仿真模型；不含真实感知、SITL/HIL、实机
> **Gate：** 不提升任何 Gate；本轮只处理 C 类残留 OUT_OF_BOUNDS 诊断与证据支持的最小修复

## 目标

1. 找到 C_dynamic-8000-021 的失败机制，建立可重复最小回放（≥3 次）与 ≥2 个成功对照。
2. 单因素对照：原始场景 / 移除实体 / 冻结实体 / 禁用实体碰撞；检查实体状态写入、接触传感、时间顺序、reset 与终止判定。
3. 若确认实现缺陷：加可失败回归测试、最小修复、标记旧结果限制、重跑受影响场景；若为真实能力失败则保留并说明机制。
4. 共享评价逻辑变更时回归 A–E 125；独立核验；提交与交接。

## 已知线索（待验证）

- 失败 episode C_dynamic-8000-021（seed 8021）：156 步，OUT_OF_BOUNDS/ENV_ALTITUDE_LIMIT，min_z 0.1038 m，无接触记录。
- 原始 step 数据在 step 30 出现瞬移到 (0,0,0.5) 且速度/姿态归零，随后继续记录 126 步。
- Isaac QuadcopterEnv._reset_idx 在整环境 reset 时随机化 episode_length_buf（训练去同步用），评估运行若沿用它会在 episode 中途触发 time_out 并静默 auto-reset。
- 运行器此前只读取 terminated，忽略 truncated 与 auto-reset 后的状态。

## 判定纪律

- 不预设实体/控制器缺陷；不用“无接触记录”直接断言无接触。
- 不改冻结场景、阈值、失败分母；旧结果保留并标注适用性。
- 区分移除实体 / 禁用碰撞 / 固定实体 / 改变运动方式四类对照。

## 写域

- 新增 `scripts/diag_e_class.py` 扩展（legacy buffer、实体模式、reset 诊断）。
- `scripts/run_sim_baseline.py` 分层评价循环：episode 边界清理、truncated 处理。
- `src/boom_birds/evaluation/episodes.py`：clear_episode_buffers。
- `tests/evaluation/test_episode_buffers.py`。
- 报告与交接：docs/reports/c_diagnosis/。

## 验收

- ≥3 次失败复现 + ≥2 成功对照；A/B/C/D 单因素对照完成。
- 根因有时间序列与源码证据；修复有失败→通过回归与 C 25 回归；共享逻辑变更则 A–E 125 回归。
- 独立核验、pytest/审计/diff、中文提交、不推送。