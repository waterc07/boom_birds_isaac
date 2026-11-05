# T38 近距 MS1（1.3–2.2 m）训练族补采（final，2026-11-05）

> **状态：** 采集 PASS（数据准备，仿真证据域）；标注/训练/模型效果均 NOT RUN
> **来源章节：** task-38（R2 修复：identity MS1 1.4–2.0 m 近距训练 OOD）；landmark_two_class_protocol_v1.json；landmark_two_class_label_spec_v1.json
> **证据域：** Isaac Sim 5.1 可见前台 GUI / DirectX D3D12 / SIM_RENDER_RGB（320×240，90°FOV，4 Hz）；RMUC2027 合成资产 + map-native MS1；无注入
> **最后核对：** 2026-11-05

## 1. 结论先行（final）

- **final run**：`outputs/sensor_shadow/lm_two_class_near_ms1_20261105`（+ `_sensor`），2/2 SUCCESS、`run.complete` **PASS**、无 `summary.error.txt`、可见前台 GUI、无 headless。
- **final pool = 102 accepted**（90–120 内；N=1 全保留）：f1 北视角 49 帧 + f2 东南视角 53 帧；pool 图像：`outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images/`；清单 `t38_pool_selection.json`。
- 两族均为**全新族**：f1 正北视角（MS1 距 1.56–1.89 m、MS1 bbox 未截断帧高 **169.1–207.9 px**、塔 +54.6…+57.8° 在 FOV 外）；f2 东南视角（1.54–1.75 m、**181.1–221.4 px**（1 帧投影 221.4，边缘 1.4 px 超出目标）、塔 −168…−164° 在 FOV 外）。两族位姿/视角不同、MS1 均在 FOV 内、塔均不在 FOV。
- **绿灯可见性（如实记录）**：f1 北视角仅 4/49 帧可见（0–13 px，多数不可见）；f2 东南视角 0/53 帧可见。class1 无 keypoint（v=0，spec），不影响 class1 bbox 监督；不作为“绿灯可用”证据。
- **去重**：final pool 102 帧 vs **24 个既有 `*_sensor` 池 sha256 交集全部 0**；pool 内部 0 重复。
- **与 T19/T30/holdout 差异**：无相同 waypoint 序列；最近起点 f1 距 T30 `lmf_t30_f5_ms1_near_alone_0` 2.14 m（yaw 差 0.68）、f2 距 T19 `lmf_devid_ms1_alone_0` 1.89 m（yaw 差 1.50）。
- **discarded pilot 明确作废**：第一次运行（f1 西南视角，起点距 T19 ms1_alone 仅 0.44 m、与 T19 同区）已改名 `..._pilotA_discarded` + `_sensor`/`_pool`，证据副本归档 `pilotA_discarded/`；**不得作为正式数据**，annot2 在其上标过的 53 帧作废重标。

## 2. 运行现场

| 项 | 值 |
| --- | --- |
| 仓库/分支/HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `47d1063b94dc779e87e1f6be7d6210b489a85395` |
| 入口/模式 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`；拒绝 `--headless`）/ `follow_only` / v2 / `reference_origin_v2` / `measured_hard_reset` |
| GUI/渲染/驱动 | 可见前台 GUI；DirectX/D3D12；Isaac Sim 5.1.0；RTX 5080 16GB；驱动 581.80 |
| case manifest（新文件） | `configs/scenarios/landmark_two_class_near_ms1_cases_v1.json`（2 cases，loader PASS；CAP_FIELD 为采集辅助观察区，非真实区域拓扑） |
| final run | `outputs/sensor_shadow/lm_two_class_near_ms1_20261105`（+ `_sensor`），结束 2026-11-05T12:30:41 |
| final pool | `outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images`（102 帧） |

## 3. 两族条件（final，102 accepted）

| case | 视角 | pool 帧 | MS1 距离 | MS1 bbox 高（未截断） | bbox 宽 | 截断（帧） | 塔 FOV | MS1 green 可见帧 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `lmf_t38_f1_ms1_near_north_0` | 正北 → 南 | 49 | 1.56–1.89 m | 169.1–207.9 px | 47.6–73.4 px | 下 5（其余 0） | 0/49 | 4/49（0–13 px） |
| `lmf_t38_f2_ms1_near_se_0` | 东南 → 西北 | 53 | 1.54–1.75 m | 181.1–221.4 px | 43.1–73.7 px | 下 6（其余 0） | 0/53 | 0/53 |

- 逐帧：`t38_frame_conditions.json`（frame_id、image_sha256、camera pose/quat、MS1 距离/方位/FOV、MS1 bbox 投影 uv/宽高、四边截断、塔距离/方位/FOV、strict v2.1 + legacy green、MS1/塔 green 归属、green clusters）。
- 逐族汇总：`t38_episode_conditions.json`；pool 清单：`t38_pool_selection.json`（N=1，102 帧）。
- 说明：bbox 高为 8 角点投影，底部截断帧（f1 5、f2 6）投影到画面外，故“全部帧”高上限 224.2/230.7 px；未截断帧在 140–220 目标内（f2 单帧 221.4 为 1.4 px 边缘超出）；标注 bbox 为真值。

## 4. 与既有族 / discarded 的区分

- 机器核查（`t38_overlap_vs_existing_families.json`，覆盖 sensor_shadow / lm_pilot / lm_independence / geo_test / final_pool_v1 / dev_v2 / identity_v1(T19) / T30 / holdout 草案）：**无相同 waypoint 序列**；最近起点：f1 距 T30 f5 2.14 m（yaw 差 0.68），f2 距 T19 ms1_alone 1.89 m（yaw 差 1.50）。
- **discarded pilot**（`lm_two_class_near_ms1_20261105_pilotA_discarded{,_sensor,_pool}`）：f1 原西南视角起点距 T19 ms1_alone 0.44 m（同区同视角），**不满足“全新族”**，作废；其 108 帧与条件表仅归档于 `pilotA_discarded/`，不得使用；annot2 在 discarded 上标注的 53 帧作废。
- **T38 与 T19/T30 不同的关键点**：距离更近（1.54–1.89 m vs T19 1.36–1.81 m 相近但视角/轨迹不同：f1 正北、f2 东南 vs T19 西南；T30 f5 为东北 4.3–4.9 m）；bbox 更大（169–208 px vs T30 中距）。

## 5. 去重 / GUI / 完整性

- final pool 102 帧 vs **24 个既有 `*_sensor`**：sha256 交集 **0**；pool 内 0 重复（`t38_dedup_vs_existing.json`）。
- `run.complete.json` PASS、2/2 SUCCESS、0 collision/timeout/invalid；GUI 证据 `t38_gui_window.png`（Isaac 5.1 标题栏 + 运行中视口；完整桌面在 run `_evidence/desktop_t38_run.png`）；manifest `gui_mode=true`/`headless=false`。

## 6. 下游交接

- **annot2**：用 **final pool**（102 帧，`t38_pool_selection.json` 的 `pool_frame_ids`）重标 shard；frame_conditions 用本目录 `t38_frame_conditions.json`（final，12:30 后生成）；class1 keypoint 恒 v=0；f1/f2 底部截断帧按 spec 标 truncated_edges.bottom；green 可见性按条件表（f1 4 帧、f2 0 帧，不因此否定 class1）。
- **annot**：T38 final 与 T19/T30 的族差异见 §4；discarded pilot 不得引用。
- **datafreeze**：final 批次 = 新训练数据（102 帧 pool、新 config、新 run）；discarded pilot 不登记；旧文件未覆盖（pilot 证据归档于子目录）。
- **train**：R2 近距 MS1 训练数据就绪（f1 49 + f2 53，MS1 bbox 169–208/181–221 px），标注完成前不要开始质量训练；class1 不映射 central-tower ID。
- **lead**：R2 唯一阻塞项（近距 MS1 训练数据）已交付 final；无模型/训练/消费者结论。

## 7. 证据文件（本目录）

- `T38_NEAR_MS1_CAPTURE_20261105.md`（本报告）
- `t38_cases_manifest.json`、`t38_manifest.json`/`t38_summary.json`/`t38_complete.json`/`t38_sensor_summary.json`/`t38_gui.log`
- `t38_frame_conditions.json`（final 102 逐帧）、`t38_episode_conditions.json`、`t38_pool_selection.json`
- `t38_dedup_vs_existing.json`、`t38_overlap_vs_existing_families.json`
- `t38_gui_window.png`
- `t38_provenance_20261105.json`（含 final vs discarded）、`t38_hashes.json`、`t38_evidence_sha256.txt`
- `pilotA_discarded/`（作废 pilot 的 10 份证据副本，仅审计）

## 8. 边界与未验证

- 仅仿真证据域（合成资产 + SIM_RENDER_RGB，PROPOSED 相机参数）；不是 OV9782/真实赛场。
- 本批仅采集与几何/颜色条件；**标注、训练、模型、消费者链、板端、导航、Gate 均 NOT RUN**。
- 截断/bbox 为 capture-side 几何投影 + 代表帧目视，不是标注真值；与标注冲突以 spec v2.1 为准。
- 未 commit/push；未接控制/PPO；未修改 Isaac venv/map 资产/旧证据（旧 t38 文件仅归档到 pilotA_discarded）。
