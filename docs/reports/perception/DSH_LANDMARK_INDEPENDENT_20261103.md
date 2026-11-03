# 自然塔地标消费者：独立定位精度评价与有限鲁棒性改进（shadow，2026-11-03）

> **结论先行：** 软件/预冻结评价/独立核验完成，但**算法未改善**：基线 presence recall 0.444、precision 1.0；多视角+锚点改进 presence recall **0**、precision **0**（2 FP）；两者 localization TP 均为 0。**不具备进入区域/地标关联 shadow 的条件。**
> **证据域：** 新采 5 个前台 GUI Isaac episode + 旧数据审计；离线逐帧评价；无真实传感器/控制/Gate 声明。

## 1. 现场核对

- 分支 `codex/bb22-contact-envelope`；本轮起点 HEAD `3f370cf`（上一包交付）；用户/其他任务修改保留。
- 旧包报告/交接已读；旧结果统计与时间语义沿用 `DSH_SENSOR_SHADOW_ERRATA_20261103.md`，不恢复“physics step 即曝光界”。
- 旧 36 帧测试集重新审计后**不再作为独立测试**，仅作历史/开发回归。
- 新采集 5 个 episode（`dev_south_new`、`test_reverse_south`、`test_north_0`、`test_static_oblique`、`test_static_away`），全部 `SUCCESS/ROUTE_COMPLETE`，前台 GUI/DirectX/D3D12；`run.complete.json` 存在、无 error。
- 本轮数据源：`outputs/sensor_shadow/lm_independence` + `lm_independence_sensor`；开发静态 pilot 在 `lm_pilot`/`lm_pilot_sensor`。

## 2. 旧数据独立性与 TP/方位修订

详见 `DSH_LANDMARK_INDEPENDENCE_AUDIT_20261103.md`。

- 旧四个 route case（route_0/route_1/reset_0/reset_1）waypoints 完全相同；g4/5/6 与 g3 同 seq 相机位置差≤0.006 m，图像 MAE 约 0.5–8.6；**同轨迹重复采集**。
- 旧 846 RGB 中 exact payload hash 重复 **0**；但“hash 不同”不等于轨迹独立。
- 旧标签仅 presence；旧 TP = 正例帧任意检测；未见 bbox 验证；旧 bearing 用 bbox 中心，不是稳定塔特征。
- 因此旧 recall 0.5 和旧测试集**降级为历史/开发回归**，不能继续解释为独立定位/方位精度。

## 3. 标签与 PROPOSED 验收

- 新标签：`configs/perception/landmark_independent_labels_v1.json`，人工代理像素标注；49 test，27 正/22 负，9 localization 子集（bbox + 绿灯参考点；g3 s181 绿灯不可见，reference UNAVAILABLE）。
- IoU 门限 **0.3**、bearing error 门限 **5°** 均为本工作包 **PROPOSED** 验收要求，非比赛指标。
- 目标身份为自然 RoboMaster 中央塔；bbox 为可见塔体近似框；测试未用于模板/阈值选择。
- 方位定义：`atan2(reference_x - cx0, fx)`，camera pinhole 内参，图像角；不是世界方向/距离。
- 标签限制：代理标注、bbox 近似、样本量小；没有用户专家复核，不宣称专家验收。

## 4. 数据与冻结

- 采集计划 v2：`configs/perception/independence_plan_v2.json`（v1 保留；revise 原因记录：v1 every-10 只按目标可见性发现漏 near 窗口，未用检测结果；v2 加最后 12 帧）。
- 新独立 episode：2 条不同路线（reverse_south、north）+ 2 组静止视角（oblique/away），覆盖正常可见、末端接近尺度、偏航/横向、边缘/部分、目标不存在、困难负例（路线中的红/蓝结构）。
- 正式 freeze：`configs/perception/independent_freeze_v3.json` sha256 `6493f653…`，源码 commit `1ecbb9c`；固定 baseline/improved 模板、阈值、标签/划分、IoU/bearing 门限、输入 hash、expected 分母。
- 模板：baseline 旧塔模板；improved 三个 development-only 模板（pilot center/left + dev route near），template meta/hash 记录；test 图像不参与模板裁剪。
- 旧 v1/v2 freeze 保留；正式版本 v3。

## 5. 有限改进

保留旧单模板为 **baseline**。仅两项改进：

1. **多视角模板库**：3 个 development-only 模板，多模板/多尺度 max NCC；
2. **模板 anchor bearing**：以模板内绿灯 anchor 映射到图像参考点，输出 bearing；不再把 bbox 中心当稳定物理点。

- 阈值 **0.65** 只用 development 标签选择；测试后未调阈值、未放宽规则。
- 未引入模型训练/大型视觉框架；仍只输出图像结果/方位，distance `UNAVAILABLE`。

## 6. 正式评价（同一封存测试集，配对）

测试帧：49（27 正/22 负）；frame-level。

| 方法 | TP | FP | FN | TN | precision | recall | UNKNOWN | REJECTED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline（旧模板） | 12 | 0 | 15 | 22 | 1.000 | **0.444** | 0 | 0 |
| improved（多视角+anchor） | 0 | 2 | 27 | 20 | 0.000 | **0.000** | 0 | 0 |

### 按 family

| family | 帧/正/负 | baseline detected pos | baseline FP | improved detected pos | improved FP |
| --- | --- | ---: | ---: | ---: | ---: |
| reverse_south | 22/12/10 | 0/12 | 0 | 0/12 | 1 |
| north | 21/12/9 | 9/12 | 0 | 0/12 | 1 |
| static_test_oblique | 3/3/0 | 3/3 | 0 | 0/3 | 0 |
| static_test_away | 3/0/3 | 0 | 0 | 0 | 0 |

- baseline 只在 north/静态斜视工作；在 reverse 接近方向全部漏检。
- improved 在所有测试正例上均未达到阈值；在 north/reverse 的非目标结构各产生 1 个 FP（score≈0.65），是开发集困难负例不足导致的过拟合。

### 定位 / 方位

- localization 子集 9 帧，reference 可用 8 帧（north s181 绿灯不可见）：
  - baseline：IoU/bbox 多数可接受（如 0.60–0.67），但 bearing error 全部 >5°，localization TP **0/8**；bearing error mean **10.44°**、median 10.46°、max 11.46°。
  - improved：localization 子集内没有 accepted DETECTED，bearing error **无可评估值**；不能说改进方位。
- 结论：baseline 的 presence 检测存在，但**定位/方位未达标**；improved 没有带来改善，反而更差。

### 失败样例

- `correct_presence_bearing_error.png`：presence TP，但 bearing error 约 9.1°，localization FN。
- `localization_bearing_error.png`：bbox IoU 0.605，bearing error 约 11.5°，localization FN。
- `miss_reverse.png`：目标可见，baseline 在 reverse 末端漏检。
- `false_positive_improved.png`：improved 把非目标结构当塔，score 0.651。
- `occluded_unavailable_ref.png`：north 边缘/部分目标，绿灯参考点不可见。
- `unknown_rejected.png`：WARMUP 拒绝样例（非 test 标签帧）。
- 证据：`docs/reports/perception/evidence_20261103_independent_landmark/`。

## 7. 时间 / reset 回归

- 复用 `SIM_UPDATE_SAMPLE_TIME`；输出 exposure `UNKNOWN`；旧 v1 输入归一化显式标 legacy；age 仅采样/消费度量，不是完整采集延迟。
- 消费者 generation 变化重置 gate/sequence/cache；结果带 frame/payload hash、generation、context、有效期、算法/模板/阈值、拒绝原因；`shadow_only=true`、`control_participation=NONE`、distance unavailable。
- 未重跑完整接触/动作故障矩阵；单测仍覆盖重复、旧帧、过期、generation/context、无效样本与真值隔离。
- 新 run 的 warmup 记录被拒绝，不进入测试指标但保留在结果/拒绝分母。

## 8. 独立核验

- `scripts/verify_independent_landmark.py` → `docs/reports/perception/dsh_independent_landmark_verify_20261103.json`：**PASS，30 checks**；从 labels/results/freeze 重算 presence、localization、bearing、family 分母、输入/源码/模板/labels hash、shadow/时间边界。
- 旧/新独立审计：`dsh_independence_audit_20261103.json`。
- 未依赖缓存 summary；freeze/input/source/template/labels hash 均检查。
- 本轮测试/文档审计见交接；不因 PASS 核验而宣称算法达标。

## 9. 限制与结论

- 新测试集只有 49 帧/4 个 family；positive 27、localization 8 可评估；**样本不足**，不能使用大样本统计措辞。
- improved 失败原因：开发集模板/视角覆盖不足；阈值 0.65 由 dev 选定但测试视角分布不同；困难负例被模板匹配误报。没有用测试结果调阈值。
- 未做区域识别/区域图/地标数据库/SLAM/VIO/定位/控制；只有单自然塔、图像 bbox/方位，无目标距离。
- 相机配置/安装/曝光仍 PROPOSED；无真实硬件时间戳/标定；无真实传感器/板端/PPO/PX4/SITL/HIL/实机；不提升 Gate。
- **不具备进入“区域/地标关联 shadow”的条件**：presence 不足（尤其 reverse）、定位/方位未达标、无区域/多假设/关联合同；下一阶段应先扩大 independent 视角覆盖、完善 labels/region topology，再谈关联。

## 10. 距区域/地标导航还缺什么 / 下一步最少测量

- 地标数据库/区域拓扑：塔 ID、世界坐标/区域、可见性、方向先验、多假设管理；
- 真实 OV9782 镜头/CSI/分辨率/FOV/畸变、内参、安装外参；
- 相机-主机时间戳/曝光与端到端延迟；
- 多视角、遮挡、尺度、困难负例的独立标注（尤其 reverse 方向）与更大独立样本；
- 若需距离：合法 VL53L8CX/深度采样与几何定义；
- 当前只需真实相机/镜头/CSI/标定与时间同步的最小测量；不要求先补齐全部硬件。

## 11. 证据

- 报告/审计：本文件、`DSH_LANDMARK_INDEPENDENCE_AUDIT_20261103.md`、`dsh_independence_audit_20261103.json`。
- freeze/labels/templates：`configs/perception/independent_freeze_v3.json`、`landmark_independent_labels_v1.json`、`independent_templates/`。
- 核验：`dsh_independent_landmark_verify_20261103.json`。
- 样例：`evidence_20261103_independent_landmark/`（TP/FN/FP/遮挡/UNKNOWN、labels/template/freeze/verify/audit）。
- 原图/结果：`outputs/sensor_shadow/lm_independence_sensor/`、`outputs/perception/independent_v3_baseline/`、`independent_v3_improved/`（gitignored；hash 归档）。


## 12. 版本化失败/修正

- `independent_freeze_v1.json`（source `18ae544`）后首次 improved 运行因注入检测器时残留 `Path(None)` 初始化缺陷失败；未产生正式指标。修复提交 `f3f8b23`，生成 v2。
- v2 运行后独立核验发现 localization 统计把 **NOT_DETECTED 候选**的 bbox/bearing 也计入误差；修复为只使用 accepted DETECTED（提交 `1ecbb9c`），生成正式 `independent_freeze_v3.json`。
- 修正只涉及消费者初始化和核验统计，**没有根据封存测试结果调整模板、阈值或验收门限**；v1/v2 freeze 与失败保留，v3 为正式结果。此前 v2 的 verifier 结果不作为正式依据。
