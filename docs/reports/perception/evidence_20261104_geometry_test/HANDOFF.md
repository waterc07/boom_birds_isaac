# 交接：塔体几何＋绿灯参考点消费者（shadow，2026-11-04）

## 状态

- **开发条件在已暴露数据上满足；一次新独立 GUI 测试失败。**
- **最终决策 C：停止此启发式方法，不进入区域/地标关联 shadow。**
- 正式 v2：presence TP13/FP0/FN5/TN12（P1.000/R0.722）；bbox TP3/9；joint TP3/18（全正例 16.7%）；正常静态 A 0/3；anchor 仅在成功检测上表现好（mean .036°），不代表整体。
- `pytest -q`、文档审计与独立核验见下；不接控制，不提升 Gate。

## 1. 实现/开发

- 新 detector：`src/boom_birds/evaluation/tower_geometry.py`
  - 绿光候选 → 邻域饱和结构 bbox → 绿灯顶部/尺寸/纵横比/边缘密度/对称性验证 → 多候选歧义拒绝；
  - 输出 bbox、绿灯 anchor、图像 bearing；score 非概率；distance UNAVAILABLE。
- 开发数据：旧 49 已暴露 + 30 development 帧，全部作开发/诊断。
- 开发条件（`geometry_dev_plan_v2.json`）满足：
  - 49 exposed：presence TP26/27、FP0、TN22、FN1；bbox TP7/9；anchor TP8/8；known green negatives 0 FP；
  - 仅做一次开发参数修正 `min_green_area 8→10`（reverse s103 假绿面积9），之后冻结。
- 新测试计划：`geometry_test_plan_v1.json`；4 个新 episode；前台 GUI/DirectX/D3D12；30 sealed test frames、18 正/12 负、9 localization。

## 2. 标签修正

- v1 `geometry_test_labels_v1.json` 的 route 三帧绿灯参考点手工估计错误；v1 正式运行保留为 **INVALID_LABEL_REFERENCE**（v1 指标 joint1/18、anchor mean11.55°，不作为最终）。
- v2 仅修正这 3 个参考点（视觉复核），bbox/算法/参数不变；`geometry_test_freeze_v2.json`。
- v2 才是有效评价；v1 核验 JSON 也保留。

## 3. 正式 v2 结果

| 指标 | 数值 |
| --- | ---: |
| presence TP/FP/FN/TN | 13/0/5/12 |
| precision / recall | 1.000 / 0.722 |
| 正例成功输出覆盖率 | 13/18 = .722 |
| bbox TP（IoU≥.3） | **3/9** |
| joint TP（bbox+anchor） | **3/9** |
| joint/全部正例 | **3/18 = .167** |
| UNKNOWN / REJECTED | 17 / 0 |
| anchor error（成功检测）mean/median/max | .036°/.006°/.134° |

- `geo_north_test`：presence 12/12，bbox 3/3（仅 localization 子集），无 FP；
- `geo_static_a`：**0/3**（绿灯面积8<min10，泛化失败）；
- `geo_static_b`：1/3，唯一检测 bbox IoU .266；
- `geo_static_c`：0 检测，无 FP。
- 无 FP，但 5/18 正例无输出；UNKNOWN 未删除。
- 开发 vs 测试下降：presence R .963→.722，bbox 7/9→3/9。

## 4. 方法决策

**C：停止此启发式。** 不继续调 min_green_area/bbox 扩张/对称性；这些会在已暴露测试上拟合。路线 presence 12/12 单独不足以支持关联。

下一候选不本包实现：目标专用轻量分割/实例模型，输入 RGB+intrinsics，输出 tower mask/bbox/green anchor；需 3–4 条新轨迹、200–400 帧 mask/bbox 标注；CPU/轻量 GPU；独立 sealed test；若 joint 仍低则停止感知推进。不默认大型模型，不启动训练。

## 5. 测试/核验/证据

- 单元测试：`tests/evaluation/test_tower_geometry.py`（检测、纯绿色拒绝）。
- 开发：`scripts/evaluate_geometry_dev.py` / `dsh_geometry_dev_eval_20261104.json`。
- 正式运行/核验：`scripts/run_geometry_test.py`、`scripts/verify_geometry_test.py`；v2 verify PASS 17 checks。
- 报告：`DSH_GEOMETRY_GREEN_20261104.md`。
- 证据：`evidence_20261104_geometry_test/`（correct route joint TP、static A miss、static B unknown/wrong bbox、negative、GUI、labels/freeze/plan/verify、中间样本、hashes）。
- v1 无效：`dsh_geometry_test_verify_20261104.json`；v2 有效：`dsh_geometry_test_verify_v2_20261104.json`。

## 6. 边界

- 保持 shadow；不接控制/SLAM/VIO/PPO/真实相机/板端/SITL/HIL/实机，不提升 Gate。
- 绿灯外观是当前合成资产视觉先验，不是比赛规则保证；硬件参数待测。
- 本包没有为了增加运行次数重复 Isaac；4 个新 episode 后不再采集。
