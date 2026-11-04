# development 身份/confuser 案例采集（2026-11-04，task-15）

> **状态：** 采集 PASS（可见前台 GUI 合成数据 + 图像/几何条件核实）；标注、训练、模型效果、板端、导航、Gate 均 NOT RUN，不作能力声明
> **来源章节：** task-15（development identity/confuser 案例）；LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §1.2（唯一性假设 U1/U2，已被 map-native MS1 挑战）、§1.4（HN1 相似结构）、§2.1（GT_UNOBSERVABLE）；configs/perception/landmark_annotation_spec_v2_1.json（confusers[]/truncated_edges/green_pixels 判据）；CURRENT_STATUS.md（identity 结论不可认证：final 池无已验证 HN1）
> **证据域：** 仿真（Isaac Sim 5.1 可见前台 GUI / DirectX D3D12 / SIM_RENDER_RGB；RMUC2027 合成资产 map-native MS1 + 复用合成视觉墙注入）
> **最后核对：** 2026-11-04

## 1. 结论先行

- **7 个 case、合计 169 accepted RGB**（lead 控制的 120–180 内；未抽样，全部保留；每 case 19–29 帧）：
  1) 目标单独 24；2) map-native MS1 confuser 单独且绿灯可见 28；3) 二者同框 3 种构图 19/23/22；4) 目标近距截断 24；5) 完全遮挡 29。
- **条件覆盖**（逐帧见 `identity_frame_conditions.json`，逐 case 汇总见 `identity_episode_conditions.json`）：
  - target alone：24/24 帧目标在 FOV 且目标绿灯 ≥11 px；MS1 不在 FOV（相对方位 +141°…+149°）。
  - MS1 alone：28/28 帧 MS1 在 FOV、MS1 绿灯 14–73 px；目标相对方位 −72°…−77°（视场外）。
  - both 构图 1（MS1 近/大左侧 + 目标远/小右侧）：19/19 帧二者均在 FOV 且二者绿灯均可见；目标贴近右缘（18/19 帧右截断）。
  - both 构图 2（MS1 约 6.6 m 左 + 目标约 9.8 m 右，尺度相近）：23/23 帧二者在 FOV；该南/东南视角下 **MS1 绿灯仅 1/23 帧可见**（lamp 朝向相关）；目标绿灯 17/23 帧（远景，≤4 px）。
  - both 构图 3（近 MS1 与远目标几乎同方位）：22/22 帧二者在 FOV；MS1 绿灯 22/22 可见；目标 12 m 远景、目标绿灯仅 3 帧（<3 px → 标注侧应 REFERENCE_TOO_SMALL）。
  - near truncation：24/24 帧目标 1.55–1.85 m；右截断 24、下截断 24、上截断 1。
  - full occlusion：29/29 帧合成墙完全挡住 8 个塔体采样点射线；目标几何在 FOV 但完全不可见（GT_UNOBSERVABLE 候选），全帧 0 green pixel。
- **MS1 是 map-native（非注入）**：约 (3.0,4.0)、结构顶 z≈1.78 m、绿色灯约 z≈1.71 m；本轮不改 map 资产。**注入的只有复用墙 `hn2_occluder_v1`（视觉-only，非 arena 资产、不代表真实分布）**；两类严格分开记录（§6/§7）。
- **去重**：本池 169 帧内部 0 重复；与 18 个既有 `*_sensor` 数据（含 dev batch 337、HN 批 59、final 池 297、formal6/geo/lm_independent 等）sha256 交集**全部为 0**。
- **GUI**：冒烟 1/1 + 正式 7/7 SUCCESS、`run.complete.json` PASS；运行中桌面截图已入库；全程可见前台 GUI/D3D12，未回退 headless。不提升 Gate、不接控制。

## 2. 现场与运行（实测）

| 项 | 值 |
| --- | --- |
| 仓库/分支/HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `0c27525b312ddce022d4a2a28345f1074cf9d0c5` |
| 入口/模式 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`；脚本拒绝 `--headless`）/ `follow_only` / v2 / `reference_origin_v2` / `measured_hard_reset` |
| GUI/渲染/驱动 | 可见前台 GUI；DirectX/D3D12（`--kit_args=--/app/vulkan=false`）；Isaac Sim 5.1.0；RTX 5080 16GB；驱动 581.80 |
| 相机/采样 | `configs/sensors/sensor_shadow_v1.json`（sha256 06a47962…，未改语义）；320×240、90°FOV；`sample_period_steps=5` ⇒ 4 Hz |
| case manifest | `configs/scenarios/landmark_dev_identity_cases_v1.json`（loader 实际解析通过，7 cases，含 MID 采集辅助区与 hn2 注入定义） |
| 正式运行 | `outputs/sensor_shadow/lm_dev_identity_capture_20261104`（+ `_sensor`），7/7 SUCCESS，0 collision/timeout/invalid |
| 冒烟 | `outputs/sensor_shadow/lm_devid_smoke_20261104`（lmf_devid_ms1_alone_0），PASS 28 帧 |

## 3. case 条件矩阵（169 accepted RGB）

| case_id | 条件 | accepted RGB | seq | 目标距离 | 目标绿灯 | MS1 距离 | MS1 绿灯 | 四边截断 L/R/T/B | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `lmf_devid_target_alone_0` | target_alone | 24 | 3–26 | 2.43–3.01 m | 24/24 帧（11–20 px） | 6.99–7.48 m（不在 FOV） | 0 | 0/0/0/0 | 目标单独、无 confuser 干扰 |
| `lmf_devid_ms1_alone_0` | map_native_confuser_alone | 28 | 3–30 | 9.40–10.19 m（不在 FOV） | 0 | 1.36–1.81 m | 28/28 帧（14–73 px） | 0/0/0/0 | MS1 独大，绿灯清晰可见 |
| `lmf_devid_both_scale_lateral_0` | both_in_frame_scale_lateral | 19 | 3–21 | 9.43–9.90 m | 19/19 | 1.64–2.08 m | 19/19 | 0/18/0/0 | MS1 近/大左侧 + 目标远/小右侧（目标贴右缘） |
| `lmf_devid_both_mid_similar_scale_0` | both_in_frame_similar_scale | 23 | 3–25 | 9.42–10.15 m | 17/23（远景 ≤4 px） | 6.11–6.82 m | 1/23（南/东南视角绿灯不可见） | 0/0/0/0 | 近同尺度、双方位中间 |
| `lmf_devid_both_same_bearing_0` | both_in_frame_same_bearing_stack | 22 | 3–24 | 12.07–12.63 m | 3/22（12 m，<3 px） | 2.77–3.29 m | 22/22 | 0/0/0/0 | 近 confuser 与远目标几乎同方位 |
| `lmf_devid_target_near_trunc_0` | target_near_truncation | 24 | 3–26 | 1.55–1.85 m | 24/24（33–74 px） | 8.18–8.53 m | 0 | 0/24/1/24 | 右+下截断强、上截断仅 1 帧 |
| `lmf_devid_full_occlusion_0` | full_occlusion | 29 | 3–31 | 2.47–3.09 m（几何在 FOV） | 0 | 6.82–7.60 m | 0 | 0/0/0/0（目标不可见） | 29/29 帧墙完全遮挡；GT_UNOBSERVABLE 候选 |

- 逐帧字段：camera pose/quat、target/MS1 距离与相对方位、FOV 状态、8 点塔体投影与四边截断、strict v2.1 green_pixels（g≥90, g−r≥25, g−b≥25，最大连通域）与 legacy 规则 green 计数、目标/MS1 归属的 green 像素、confusers[]、注入墙投影与遮挡判定。
- 代表帧（给 annot2 的 ≤72 帧固定规则抽样，共 **62 帧**）：见 `identity_representative_frames.json`（每 case 前 2+后 2+等步长，非检测器分数选择）。

## 4. 图像核实（逐 case）

- **target alone**：`lmf_devid_target_alone_0-follow_only_g1_12.png` 等，中央塔正面完整，画面内无 MS1/无其它塔状物；目标绿灯清晰（11–20 px）。
- **MS1 alone**：`lmf_devid_ms1_alone_0-follow_only_g2_10.png` 及 `identity_zoom/…ms1_alone_green_lamp_x3.png`：细长灰色柱 + 顶部绿色灯清晰可见；中央塔不在画面（其方位 −72°…−77°）。
- **both 构图 1**：`lmf_devid_both_scale_lateral_0-follow_only_g3_12.png` 及 zoom：MS1 近/大在左（绿灯可见），中央塔远/小在右（贴近右缘）。
- **both 构图 2**：`lmf_devid_both_mid_similar_scale_0-follow_only_g4_12.png`：左侧灰色柱（MS1，绿灯该视角不可见）与右侧中央塔小目标并存，二者尺度相近、均在画面中部。
- **both 构图 3**：`lmf_devid_both_same_bearing_0-follow_only_g5_12.png` 及 zoom：近处 MS1 居中偏大（绿灯可见），远处中央塔在其左侧/上方小尺度可见。
- **near truncation**：`lmf_devid_target_near_trunc_0-follow_only_g6_12.png` 与右缘/下缘放大裁剪：目标 1.55–1.85 m，塔身右缘被截、底座出下边界。
- **full occlusion**：`lmf_devid_full_occlusion_0-follow_only_g7_12.png`：画面为合成墙，无塔体、无绿灯；目标仅存在于场景配置（GT_UNOBSERVABLE）。

## 5. 四边截断与 green_pixels 元数据（后处理生成，不阻塞采集）

- 截断方法：8 点塔体模型（灯/顶板两端与顶/塔身基座两角/底座两角）经记录 camera pose+内参投影；目标在视场外/身后记 NOT_APPLICABLE，不误报。
- 计数（169 帧）：left 0、right 42（C1 18 + D 24）、top 1（D，轻微）、bottom 24（D）；逐帧见 `identity_frame_conditions.json`，逐 case 见 `identity_episode_conditions.json`，含逐帧帧号见 `identity_four_side_truncation.json`。
- 目视确认（3× 放大，`identity_truncation_crops/`）：D 右缘（塔身/顶板越右界）、D 下缘（底座出下界）、C1 右缘（远目标贴右界）。
- green 像素：同时记录 **strict v2.1 规则**与 legacy 采集规则；并区分目标绿灯 / MS1 绿灯 / 其他（未归属）。strict 规则下 B（MS1 alone）14–73 px、A（目标 alone）11–20 px、D（近距目标）33–74 px；C2/C3 远景目标 <3 px（标注侧应 REFERENCE_TOO_SMALL）。
- 局限：几何投影使用近似塔体模型；截断为 capture-side 预测 + 代表帧目视，不是标注真值；annotator 与 capture 元数据冲突时按 spec v2.1 以标注为准。

## 6. map-native MS1 记录（非注入）

见 `identity_ms1_confuser_record.json`：

- **世界位姿估计**：约 (3.0, 4.0)；结构顶 z≈1.78 m（GUI map probe 0.5 m 网格下射线命中，collision_019）；绿色灯约 z≈1.71 m；位置不确定度约 0.1 m。
- **外观**：细长灰色柱（宽约 0.5 m，估计值）、平顶模块、蓝色侧条，顶部侧向绿色灯；高度约 1.83 m。
- **绿灯可见性（本批）**：西/西南视角（MS1 alone、both 构图 1）与西/西北视角（both 构图 3）可见；南/东南视角（both 构图 2）基本不可见。**灯朝向相关，精确朝向 UNKNOWN**；2026-11-04 dev 批的东侧 static_negative 视角同样看不到绿灯。
- **与中央塔区别**：中央塔 (11.52,−0.01) 宽锥塔身 + 1.7 m 顶灯架 + 屋顶绿灯 (z≈1.25–1.3) + R 标识 + 白色阶梯底座；MS1 细长平顶柱 + 侧向绿灯，无顶灯架/无 R 标识。
- **验证边界**：verification_source = WORLD_POSE_OR_MAP_DB（map probe + 多帧投影一致），verification_scope = CAPTURE_GEOMETRY_AND_MAP_PROBE_ONLY_NOT_HUMAN_REVIEW；最终 verified 判定仍属 annot2/lead。

## 7. 注入记录（复用合成墙 `hn2_occluder_v1`，非 map-native）

见 `identity_injection_record.json`；仅用于 full occlusion case：

- prim：`/World/DevInjection_hn2_occluder_v1_part00`（run manifest `scene_injections.prim_paths` 记录）；仅该 case episode 激活；visual-only USDGeom cuboid（无 rigid body / 无碰撞）。
- 几何/位姿：wall cuboid (0.4,2.4,1.9) m @ (10.6,0.0,0.95)（x 10.4–10.8、y ±1.2、z 0–1.9）；材质 diffuse (0.62,0.62,0.64)、roughness 0.7、无 emissive。
- 相机-塔-墙关系：相机巡逻盒 x 8.3–9.0 / y −0.8–0.3 / z 1.0–1.1；塔参考点 (11.52,−0.01,1.25)；29/29 帧 8 个塔体采样点射线全被墙挡住。
- **声明**：合成干预、非 arena 资产、不代表真实赛场分布；map 资产未修改。
- **GT 标注指引**：`present=true + visibility=OCCLUDED + occluded=true + bbox=null + keypoint=null + reference_status=UNAVAILABLE + reason=REFERENCE_OCCLUDED`；指标侧 **GT_UNOBSERVABLE**（不进四格/分母、不是普通负例）。图像本身无法证明墙后目标存在，present=true 来自场景配置。

## 8. 去重与重合核查

- 图像 sha256：本池 169 帧内部 0 重复；与 18 个既有 `*_sensor` 目录（含 `lm_dev_capture_20261104` 337、`lm_dev_hn_capture_20261104` 59、`lm_final_candidate_20261104` 297、formal6/geo/lm_pilot/lm_independence 等）交集**全部 0**（`identity_dedup_vs_existing.json`）。
- 位姿/航点：与 6 个既有 case 配置（含 dev v2 与 final v1）无相同 waypoint 序列；最短起点距离与 yaw 差见 `identity_overlap_vs_existing.json`（起点邻近不等于轨迹同一性）。
- 与既有 dev/HN 批区别：本批是**身份判别构图**（目标单独 / MS1 单独 / 同框 3 构图 / 近距截断 / 完全遮挡），不是新走廊或尺度族；同轨迹不重复刷帧（每 case 为一条小巡逻构图，帧间视角连续变化）。

## 9. 交下游（lead / annot2 / datafreeze）

- **lead**：是否把 7 个 identity case 作为 dev 身份判别数据（train/val 由 annot2/datafreeze 按组分配）；MS1 是否正式确认为 verified confuser；full occlusion 标注处理方式确认（本报告建议 GT_UNOBSERVABLE）。
- **annot2**（≤72 代表帧）：用 `identity_representative_frames.json`（62 帧、固定规则）；标注时按 spec v2.1：
  - A 目标全见、参考点可用（green 11–20 px）；
  - B MS1 为 confuser（verified 证据见 `identity_ms1_confuser_record.json`），central target absent → 若采用 SIMILAR_STRUCTURE 需 verified confuser，否则 TARGET_ABSENT + confusers[]；
  - C1 两者同框（目标贴右缘 → truncated_edges.right=true；MS1 绿灯可见）；C2 两者同框但 MS1 绿灯不可见（别把不可见写成没有结构）；C3 近 MS1（绿灯可见）+ 远目标（green<3 → REFERENCE_TOO_SMALL）；
  - D 近距截断：right=true、bottom=true，top 仅 1 帧需目视裁定；
  - E 全遮挡：GT_UNOBSERVABLE（present=true/visibility=OCCLUDED/reference UNAVAILABLE），不是普通负例。
- **datafreeze**：case=一个 group，**整 case 分配 train 或 val**，不拆帧；本批标 DEVELOPMENT、非 sealed、不进 final；帧清单与 sha 用 `identity_frame_conditions.json` 的 image_sha256 + 原始图路径 `outputs/sensor_shadow/lm_dev_identity_capture_20261104_sensor/images/<frame_id>.png`。

## 10. 失败/重试与 GUI 证据

- 冒烟 1/1 PASS（lmf_devid_ms1_alone_0，28 帧）；正式 7/7 PASS；`run.complete.json` 存在、无 `summary.error.txt`；本批无失败、无重试。
- GUI：正式运行中桌面截图 → `identity_gui_window.png`（Isaac Sim 5.1.0 标题栏 + 运行中视口/Console）与 `identity_desktop_1280x720.png`；run manifest `gui_mode=true`/`headless=false`。冒烟运行的 GUI 状态由 `identity_smoke_manifest.json`（gui_mode=true/headless=false）与冒烟日志证明；冒烟期间的桌面截图未捕捉到窗口（时序原因，已如实记录，不作为 GUI 证据）。
- 全程未使用 headless；未安装/改动训练依赖；未改 Isaac venv。

仓库测试（2026-11-04）：`E:/isaac/env_isaaclab/Scripts/python.exe -m pytest -q` 在收集阶段被并行工作流的 `tests/evaluation/test_landmark_posteval.py`（import `landmark_posteval` 尚未落地）中断；忽略该在研文件后：**1032 passed / 2 failed**（77.67 s）；两条失败均来自并行工作流（`test_exposure_registry_v2_downgrades_old_final_to_development`、`test_shipped_cli_config_is_valid_and_repository_relative`），与本任务（只新增 case config + docs 证据）无关。本任务未修改合同/评价行为、未新增测试。

## 11. 证据文件与哈希

目录 `docs/reports/perception/capture_dev_20261104/`（原始帧/obs 留在 ignored outputs）：

- `identity_cases_v1.json`（case 清单副本）
- `identity_manifest.json` / `identity_summary.json` / `identity_complete.json` / `identity_sensor_summary.json`
- `identity_smoke_manifest.json` / `identity_smoke_summary.json` / `identity_smoke_complete.json`
- `identity_frame_conditions.json`（169 帧逐帧）、`identity_episode_conditions.json`、`identity_four_side_truncation.json`、`identity_truncation_crops/`
- `identity_ms1_confuser_record.json`、`identity_injection_record.json`、`identity_zoom/`
- `identity_representative_frames.json`（62 帧代表帧）、`identity_split_and_usage.json`
- `identity_dedup_vs_existing.json`、`identity_overlap_vs_existing.json`、`identity_failures_and_retries.json`
- GUI：`identity_gui_window.png`、`identity_desktop_1280x720.png`（冒烟窗口截图未捕捉到 Isaac 窗口，已不使用；冒烟 GUI 由 manifest/日志证明）
- `identity_hashes.json`、`identity_evidence_sha256.txt`、`identity_provenance_20261104.json`
- 样例帧：`identity_samples/`

## 12. 边界与未验证

- 仅仿真证据域：合成 RMUC2027 资产 + SIM_RENDER_RGB（PROPOSED 相机参数），非 OV9782 实物、非真实光照/分布。
- MS1 为 map-native 资产结构；其 verified confuser 最终判定由 annot2/lead 决定；本报告只提供 map probe + 投影证据。
- 合成墙为视觉-only 注入，不代表真实遮挡物分布；full occlusion 的 GT 为场景导出、非图像可观测。
- 截断为 capture-side 几何预测 + 代表帧目视，不是标注真值；top 边仅 1 帧候选。
- 未做标注、训练、模型效果、板端、导航/Gate；不得把本数据准备写成感知能力。

## 13. 变更记录

- 新增 `configs/scenarios/landmark_dev_identity_cases_v1.json`（7 cases + MID 采集辅助区 + 复用 hn2 注入定义）。
- 本次**未修改** `scripts/run_dynamic_eval.py`（scene_injections 运行时可注入支持已在 2026-11-04 dev 批落地并提交）；未修改 loader / sensor_shadow 配置语义 / map 资产。
- MID 为采集辅助区（case 校验用），不是 V2.2 真实区域拓扑。
