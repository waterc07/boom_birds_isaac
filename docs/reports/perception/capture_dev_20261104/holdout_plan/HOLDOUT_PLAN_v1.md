# new holdout 采集草案（case manifest draft v1，未冻结、未采集）

> **状态：** PROPOSED / DRAFT（NOT_TRIGGERED：按 lead 当前口径不采集，等最终门判定）
> **来源章节：** task-15/task-25 后续 holdout 要求（≥3 全新族、200–400 accepted、覆盖近距/远景/截断/MS1/同框歧义/目标缺席）；LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS_20261104.md §holdout 门；annotation spec v2.1
> **证据域：** 文档 + 离线几何/loader/重合性检查（无图像、无 Isaac 运行、无模型）
> **最后核对：** 2026-11-04

## 1. 结论先行

- 已按要求写出 **new holdout case manifest 草案**（7 个全新族，覆盖要求的 6 类条件），**预测 394 accepted 帧**（目标 200–400，PREDICTED 未实测）。
- **采样规则已在采集前冻结**（见 §4），避免“看结果再选帧”。
- **loader 语法检查 PASS**（7 cases 全部解析通过，goal 均在 goal region 内）。
- **与既有族重合性核查**：与 7 个既有 case 配置（sensor_shadow / lm_pilot / lm_independence / geo_test / final_pool_v1 / dev_v2 / identity_v1）**无相同 waypoint 序列**；最近起点距离 0.22–3.0 m，其中 H2/H4 起点邻近需在采集时确认视角不同（见 §6）。
- **未采集**：当前按 lead 状态 NOT_TRIGGERED；不跑 Isaac。若 GO，按 §7 执行并交付。

## 2. 族与条件矩阵（草案）

文件：`HOLDOUT_CASE_MANIFEST_DRAFT_v1.json`（schema `boom_birds.map_cases.v2`，无注入，MS1 为 map-native）

| 族/case | 位姿/路线 | 预测帧 | 目标距离 | MS1 距离 | 覆盖条件 |
| --- | --- | --- | --- | --- | --- |
| `holdout_sw_inner_corridor_0` | W→E 新内南走廊（y≈−5.2） | 163 | 3.4–21.2 m | 7.1–14.3 m | 正常/尺度/远景小目标 |
| `holdout_nw_inner_corridor_0` | E→W 新内北走廊（y≈+5.0，面朝 +X 后退） | 176 | 2.5–20.3 m | 1.6–12.7 m | 正常/尺度/远景/边缘截断（过渡段）/新接近方向 |
| `holdout_near_static_0` | E 新近距静态姿态 | 9 | 1.9–2.1 m | 7.4–7.6 m | 近距 1.5–3 m/底部截断 |
| `holdout_far_small_target_0` | W 新远景静态姿态 | 6 | 20.6–20.7 m | 12.6–12.7 m | 远景小目标 |
| `holdout_ms1_confuser_alone_0` | NE 新视角（MID 辅助区，约 4.3–4.9 m） | 17 | 151.6–158.1°（视场外） | 4.3–4.9 m | MS1 confuser 单独 |
| `holdout_both_ambiguous_0` | SE 新视角（约 6.3 m / 7.6 m） | 16 | 5.9–6.4 m | 7.4–7.8 m | 目标+MS1 同框歧义/右缘截断 |
| `holdout_target_absent_0` | E 新目标缺席姿态 | 6 | 146.1–150.1°（后方） | 6.3 m | 目标缺席/相似结构无绿灯 |

- 合计 **预测 394 帧**（PREDICTED_NOT_MEASURED）：按实测约 0.55 m/s 路线速度 + 4 Hz accepted 估算；实际以采集后计数为准。
- H2 有 1 个 waypoint 目标方位 −60.8°（短暂出视场），作为“过渡/截断”帧；H6 目标方位 −45.0…−41.2°，目标中心在画面右缘附近并有部分截断（两者仍同框）。
- 无合成注入；未修改 map 资产；MID 是采集辅助观察区，不是 V2.2 真实区域拓扑。

## 3. 与既有族不重复的依据

- 既有族：south corridor A / north corridor / inner-north（y≈3.0）/ inner-south（y≈−3.0）/ E 区 sweep 与静态 / final 池各族 / identity v1 与 T25。
- 新族使用 **新走廊带 y≈−5.2 与 y≈+5.0**（既有走廊之间）与 **新静态/视角姿态**（H3/H4/H5/H6/H7），并新增“面朝 +X 后退”的新接近方向。
- 机器核查（`holdout_overlap_vs_existing_families.json`）：**无相同 waypoint 序列**；最近起点距离：H1 0.45 m（dev_south_new）、H2 0.28 m（dev_static_negative，yaw 差 2.20）、H3 0.22 m（lmf_side_negative，yaw 差 1.67）、H4 0.82 m（dev_inner_north，yaw 差 0.05）、H5 2.15 m、H6 3.0 m、H7 0.61 m。
- 注意：H4 与既有 inner_north 起点 0.82 m/同方向，但为**静态远景姿态**（非走廊路线），采集时需确认画面与既有 family 明显不同；H2/H3 起点邻近但 yaw/路线不同。图像 sha 去重必须在采集后补做（当前无数据可查）。

## 4. 冻结的采样规则（采集前）

`sampling_rule_frozen`（写入草案）：
- 默认 **N=1**（保留全部 accepted 帧）；
- 若实测 accepted 总数 >400，则对每个 family 按序列顺序做**固定步长**抽取：保留位置 1, 1+k, 1+2k, …，k = ceil(总数/400)；不使用检测器分数、不使用随机；
- 该规则与每 family 最终帧数必须写进 provenance 后才允许进入标注/训练；
- 不因标注难度或模型表现回头改规则。

## 5. 覆盖条件对照

| 要求 | 覆盖族 | 说明 |
| --- | --- | --- |
| 近距 1.5–3 m | H3 | 目标 1.9–2.1 m，预期底部截断 |
| 远景小目标 | H4（20.6 m）、H1/H2 远端 | 目标绿灯可能 <3 px，标注侧按 REFERENCE_TOO_SMALL |
| 边缘截断 | H2 过渡段、H3 底部、H6 右缘 | 采集后用四边截断几何表核实 |
| MS1 confuser 单独 | H5 | 4.3–4.9 m；绿灯可见性按帧记录（该方向可能不可见，需明确写出） |
| 目标+MS1 同框歧义 | H6 | 约 6.3/7.6 m 近同尺度；两结构均需可辨 |
| 目标缺席 | H7 | 目标在后方；MS1 远观众在但无绿灯（相似结构负例） |

## 6. 已知风险（采集前明确）

1. H1/H2 新走廊的地面净空未在 GUI 中实测（仅用 0.5 m 地图探针网格估算；y≈−5.2 与 +5.0 带内存在少量台阶/坡道，需采集时逐 waypoint 目视/物理净空确认）。
2. H4/H7 预测仅 6 帧（静态短姿态）；如实际 <6 帧需延长 patrol 或接受少量帧（holdout family 级样本仍需 ≥4 帧）。
3. H5 从东北视角看 MS1，绿灯可能不可见（T15 证据：灯朝向西/南西可见）；若不可见，H5 仅作“结构 confuser 单独”而非绿灯 confuser，报告中必须区分。
4. H2 目标在 1 个 waypoint 出视场（−60.8°）；该段帧按“目标缺席/过渡”标注，不作为同框证据。
5. 实测总帧数可能略超 400（预测 ±10%），触发 §4 步长规则；需在 provenance 记录实际总数与每族保留数。
6. 去重只做了位姿/waypoint 层面；图像 sha 去重、与 18+ 既有 sensor 池的重复检查必须在采集后补做。

## 7. 若 GO 的执行计划（本草案冻结后）

1. 将草案提升为正式 config（如 `configs/scenarios/landmark_holdout_cases_v1.json`，需 lead 更新写域/审批）。
2. 可见前台 GUI 运行 `scripts/run_dynamic_eval.py --cases <holdout config> --sensor-shadow <dir>`（`--only-cases` 全 7 族；禁 headless），记录 HEAD/driver/命令。
3. 运行中抓桌面窗口截图；结束后校验 `run.complete.json` PASS、无 `summary.error.txt`；逐帧记录 camera pose/四边截断/green_pixels（strict v2.1 + legacy）/MS1 归属/confusers。
4. 若实测 >400：应用 §4 冻结步长并记录；若 <200：报告 INCOMPLETE 并说明原因（不得硬凑）。
5. 图像 sha 去重 vs 既有 18+ `*_sensor`；与既有 family 重合性复核。
6. 输出 capture 证据：run manifest/summary/complete、帧条件表、截断/绿灯、GUI 截图、provenance、hashes；send_message lead/annot/datafreeze。
7. 全程不 commit/push、不改 map 资产、不接控制/PPO、不提升 Gate。

## 8. 证据文件（本草案阶段）

- `HOLDOUT_CASE_MANIFEST_DRAFT_v1.json`（草案 manifest，schema v2，7 cases）
- `holdout_overlap_vs_existing_families.json`（与 7 个既有配置的起点/waypoint 重合性机器核查）
- `HOLDOUT_PLAN_v1.md`（本文件）
- 说明：草案阶段没有图像/帧条件/去重 sha 数据（未采集），不得写成已具备的 holdout 证据。

## 9. 状态

- **NOT_TRIGGERED**：按 lead 当前口径不采集；等最终门判定后再决定是否 GO。
- 若最终判定 NO-GO/暂停：本草案保留为设计记录，不产生任何数据或能力声明。
