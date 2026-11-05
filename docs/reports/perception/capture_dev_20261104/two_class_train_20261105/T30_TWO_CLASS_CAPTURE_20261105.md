# T30 two-class 训练批量采集（8 个全新族，2026-11-05）

> **状态：** 采集 PASS（数据准备，数据域仿真）；标注/训练/模型效果/消费者评估均 NOT RUN，不作能力声明
> **来源章节：** task-30；configs/perception/landmark_two_class_protocol_v1.json（PRE_REGISTERED_2026_11_05_BEFORE_TRAINING）；landmark_two_class_label_spec_v1.json（frozen）；LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS_20261104.md（旧包封闭）
> **证据域：** Isaac Sim 5.1 可见前台 GUI / DirectX D3D12 / SIM_RENDER_RGB（320×240，90°FOV，4 Hz）；RMUC2027 合成资产 + map-native MS1；**无合成注入**
> **最后核对：** 2026-11-05

## 1. 结论先行

- 采集 **8 个全新轨迹族**，run **8/8 SUCCESS/ROUTE_COMPLETE**，`run.complete.json` **PASS**、无 `summary.error.txt`，全程可见前台 GUI、无 headless、无注入、未改 map 资产。
- **实测 raw accepted 492**（RGB 图像 516 含 24 帧 warmup）超出 420 上限，按**采集前冻结的确定性规则**（每 case 按序列顺序保留 3/4，keep where i%4!=3）得到 **pool = 373 accepted**（300–420 内；每族 39–50），pool 图像副本：`outputs/sensor_shadow/lm_two_class_train_20261105_pool/images/`；raw 保留在同一 run 的 `_sensor` 中。
- 条件覆盖（raw → pool）：①塔近距 1.73–2.56 m ②塔中距 4.54–5.15 m ③塔远景 10.14–10.90 m ④塔边缘截断（左截断 49/64 raw）⑤MS1 单独近/中距 2.88–3.39 m、塔不在 FOV ⑥MS1 单独远景 9.06–9.81 m + 边缘截断（MS1 中心出画 25/66 raw）⑦塔+MS1 同框 51/51 raw、部分重叠 0.147–0.347 ⑧目标缺席负例（塔与 MS1 均不在 FOV，0 green px）。
- **与旧族区分**：与 8 个既有 case 配置（sensor_shadow / lm_pilot / lm_independence / geo_test / final_pool_v1 / dev_v2 / identity_v1 / holdout 草案）**无相同 waypoint 序列**；最近起点距离与 yaw 差见 §5（f1/f4 起点邻近、f7 与 T19 same_bearing 同侧视角但重叠/尺度不同，均已在报告中记录）。
- **sha 去重**：pool 373 帧与 **22 个既有 `*_sensor` 数据池交集全部 0**；pool 内部 0 重复。
- 本批是**训练数据**：未标注、未训练、未评估；class1 为 map-native MS1，**永不映射到 central-tower landmark_id**；class1 无关键点（v=0）。

## 2. 运行现场

| 项 | 值 |
| --- | --- |
| 仓库/分支/HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `47d1063b94dc779e87e1f6be7d6210b489a85395` |
| 入口/模式 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`；脚本拒绝 `--headless`）/ `follow_only` / v2 / `reference_origin_v2` / `measured_hard_reset` |
| GUI/渲染/驱动 | 可见前台 GUI；DirectX/D3D12（`--kit_args=--/app/vulkan=false`）；Isaac Sim 5.1.0；RTX 5080 16GB；驱动 581.80 |
| case manifest（新文件，不覆盖旧文件） | `configs/scenarios/landmark_two_class_train_cases_v1.json`（8 cases，loader PASS；`CAP_FIELD` 仅为采集辅助观察区，不是 V2.2 真实区域拓扑） |
| run | `outputs/sensor_shadow/lm_two_class_train_20261105`（+ `_sensor`），8/8 SUCCESS，0 collision/timeout/invalid；结束 2026-11-05T00:25:50 |
| pool | `outputs/sensor_shadow/lm_two_class_train_20261105_pool/images`（373 帧；选择清单 `t30_pool_selection.json`） |

## 3. 8 族与条件矩阵（raw 492 → pool 373）

| 族 case | 设计条件 | raw 帧 | pool 帧 | 目标距离 | MS1 距离 | 目标在 FOV | 目标 green 帧 | MS1 在 FOV | 截断（四边计数 raw） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `lmf_t30_f1_tower_near_alone_0` | ①塔单独近距 1.5–3 m | 66 | 50 | 1.73–2.56 m | 7.12–8.13 m（不在 FOV） | 66/66 | 66/66（16–39 px） | 0 | R 22 / B 16 |
| `lmf_t30_f2_tower_mid_alone_0` | ②塔单独中距 3–6 m | 63 | 48 | 4.54–5.15 m | 4.82–5.70 m（不在 FOV） | 63/63 | 63/63（4–9 px） | 0 | 0 |
| `lmf_t30_f3_tower_far_alone_0` | ③塔单独远景 8–12 m | 62 | 47 | 10.14–10.90 m | 5.13–6.11 m（不在 FOV） | 62/62 | 23/62（0–3 px） | 0 | 0 |
| `lmf_t30_f4_tower_edge_trunc_0` | ④塔边缘截断（近距） | 64 | 48 | 2.37–2.98 m | 7.75–8.55 m（不在 FOV） | 49/64（中心出画=截断） | 51/64 | 0 | L 49 / T 4 / B 4 |
| `lmf_t30_f5_ms1_near_alone_0` | ⑤MS1 单独近/中距（塔不可见） | 59 | 45 | 8.93–9.60 m（不在 FOV） | 2.88–3.39 m | 0 | 0 | 59/59 | 0（MS1 green 0：东北视角灯不可见） |
| `lmf_t30_f6_ms1_far_trunc_0` | ⑥MS1 单独远景+截断 | 66 | 50 | 17.22–17.86 m（不在 FOV） | 9.06–9.81 m | 0 | 0 | 41/66（其余中心出画=截断） | MS1 右缘截断；MS1 green 33/66 |
| `lmf_t30_f7_both_near_far_0` | ⑦塔+MS1 同框、近→远、部分重叠 | 51 | 39 | 13.41–16.15 m | 4.05–6.77 m | 51/51 | 1/51（远景 <3 px） | 51/51 | 0；重叠 0.147–0.347，51/51 帧 ≥0.05 |
| `lmf_t30_f8_target_absent_neg_0` | ⑧目标缺席负例 | 61 | 46 | 4.81–5.41 m（不在 FOV） | 8.78–9.39 m（不在 FOV） | 0 | 0 | 0 | 0；全帧 0 green px |

- 条件表：`t30_frame_conditions.json`（492 帧逐帧，含 `in_pool` 标志；camera pose/quat、目标/MS1 距离与相对方位、FOV、8 点塔体投影与四边截断、strict v2.1 green_pixels + legacy 计数、目标/MS1 归属 green、重叠分数）；pool 汇总 `t30_pool_episode_summary.json`；raw 汇总 `t30_episode_conditions_raw.json`。
- 代表帧（每族 1 张可复核）：f1 `g1_36`、f2 `g2_35`、f3 `g3_33`、f4 `g4_35`、f5 `g5_32`、f6 `g6_36`、f7 `g7_28`、f8 `g8_33`（在 `_sensor/images`）。

## 4. 条件解读与已知限制

- ④ 边缘截断：目标中心出画 15/64 帧，四边几何左截断 49 帧（近距目标大半出左缘）；标注侧应 `truncated_edges.left=true`，中心出画帧按 spec v2.1 处理（不臆造 keypoint）。
- ⑤ MS1 近景来自东北视角，**绿灯不可见（0 green px）**：class1 按 label spec 无关键点（v=0），因此不影响 class1 监督；但该族不能作为“绿灯可用的 confuser 近景”证据，报告中如实标注。
- ⑥ MS1 远景 9.06–9.81 m，41/66 帧在 FOV，其余为 MS1 中心出画的边缘截断帧（含 33/66 帧可见绿灯，0–7 px）。
- ⑦ 同框：MS1 在前景（4.05–6.77 m），塔在远景（13.41–16.15 m）；重叠 0.147–0.347，MS1 未完全挡住塔（塔体左右两侧均可见）；但塔的绿灯在 13–16 m 只有 1/51 帧达到 strict green 阈值——即“**部分重叠不遮挡结构判据，但塔的关键点绿灯在远景下常低于阈值**”，标注侧应对塔 keypoint 视 v=0 处理（refusal 正确）。该族与 T19 same_bearing 的区别：T19 为 MS1 2.8–3.4 m + 塔 12.1–12.8 m 且**无重叠**；本族 MS1 4.1–6.8 m + 塔 13.4–16.2 m 且**部分重叠**，起点/航点不同（最近起点 1.02 m，yaw 差 0.06）。
- ⑧ 负例：塔与 MS1 均在 FOV 外（方位 155–163° / −124…−120°），0 green px；作为 target-absent 负例，不当作同框样本。

## 5. 与既有族的差异（机器核查）

- 与 8 个既有配置的 **相同 waypoint 序列：无**（`t30_overlap_vs_existing_families.json`）。
- 最近起点（距离 / yaw 差）：f1 `lmf_backoff_0` 0.21 m / 0.25；f2 `lmf_similar_negative_0` 1.46 m / 3.04；f3 `lmf_devid_both_mid_similar_scale_0` 1.57 m / 0.69；f4 `geo_test_static_c` 0.11 m / 2.89；f5 `holdout_ms1_confuser_alone_0` 4.30 m / 1.11；f6 `lmf_devid_ms1_far_0` 3.16 m / 1.09；f7 `lmf_devid_both_same_bearing_0` 1.02 m / 0.06；f8 `holdout_both_ambiguous_0` 2.07 m / 3.04。
- 说明：起点邻近不等于族相同；f1（近距巡逻环 vs backoff 轨迹）、f4（边缘截断巡逻 vs 静态 c，yaw 差 2.89）轨迹/视角不同；f7 与 T19 same_bearing 同侧视角但重叠/尺度/航点不同（见 §4）。
- 与 holdout 草案：8 族全部属于不同的位姿/巡逻环，无相同族；holdout 草案仍未采集（NOT_TRIGGERED），本批不与之混用。

## 6. MS1 / 注入边界

- **MS1 是 map-native 资产结构**（约 (3.0,4.0)，顶 z≈1.78 m；非注入，map 资产未修改）；class1 语义见 protocol：MS1 **永不映射到 central-tower landmark_id**。
- 本批 **无任何合成注入**（`injection_used=false`）；`scene_injections` 为空。
- 未改 loader / sensor_shadow 配置语义 / map 资产 / 旧文件；新 case 配置为新文件。

## 7. 采样与 pool 规则（采集前冻结）

- manifest 中 `sampling_rule.status = FROZEN_BEFORE_CAPTURE`：默认 N=1；若实测 >420 则每 case 按序列顺序固定步长保留。
- 实测 492 > 420 → 应用 **确定性 3/4 规则**（keep where index%4!=3，按 sequence 顺序），得到 373，逐族 39–50。规则与结果写入 `t30_pool_selection.json`；不使用检测器分数/随机/人工挑选。
- 下游使用 pool 副本（`lm_two_class_train_20261105_pool/images`）作为训练集，raw 保留供审计；若后续需要不同采样需另立新规则并重写 provenance（不回改本规则）。

## 8. 去重

- **pool 373 帧 vs 22 个既有 `*_sensor` 目录：sha256 交集全部 0**（`t30_dedup_vs_existing.json`）。
- pool 内部 unique sha = 373（0 重复）。

## 9. run/GUI 完整性

- `run.complete.json`：PASS、completed=true、`summary_error_file=false`；8/8 episode SUCCESS/ROUTE_COMPLETE；无 collision/timeout/invalid。
- GUI 证据：`t30_gui_window.png`（Isaac Sim 5.1.0 标题栏 + 运行中视口 + GPU 面板；run 中途桌面截图裁剪）；完整桌面截图保留在 run 的 `_evidence/desktop_t30_run.png`。
- manifest 记录 `gui_mode=true`、`headless=false`；全程未使用 headless。

## 10. 下游交接

- **annot2**（two-class label spec v1）：按 `t30_pool_selection.json` 的 373 帧 pool 标注；每帧 `tower_present`/`ms1_present`/`instances[class,bbox,truncation,occluded,keypoint,v,reference_available]`；class1 keypoint 恒 v=0；塔绿灯不可见时 v=0 + reference_available=false（refusal 正确）。重点核对：f4 left 截断、f6 MS1 右缘截断、f7 部分重叠但塔结构左右可见/塔绿灯常低于阈值、f8 负例（两目标均缺席）。
- **train**：两训练类目（class0 central_tower / class1 similar_structure_ms1），class1 不映射 central-tower ID；执行前按 protocol 的 engineering smoke（nc=2、kpt_shape[1,3]、class1 keypoint loss mask）先做。
- **datafreeze**：本批为**新训练数据批次**（非旧预算、非旧快照复用）；pool 373 帧；manifest/config/provenance/hash 见 §11；旧文件未被覆盖（新 config 文件 + 新 evidence 子目录）。
- **annot**：如需与 T19 identity 数据对照，注意本批 f5/f7 的 green 可见性限制已记录。

## 11. 证据文件（`docs/reports/perception/capture_dev_20261104/two_class_train_20261105/`）

- `T30_TWO_CLASS_CAPTURE_20261105.md`（本报告）
- `t30_cases_manifest.json`（config 副本）、`t30_manifest.json`/`t30_summary.json`/`t30_complete.json`/`t30_sensor_summary.json`/`t30_gui.log`
- `t30_frame_conditions.json`（492 逐帧 + in_pool）、`t30_episode_conditions_raw.json`、`t30_pool_episode_summary.json`、`t30_pool_selection.json`
- `t30_dedup_vs_existing.json`、`t30_overlap_vs_existing_families.json`
- `t30_gui_window.png`
- `t30_provenance_20261105.json`、`t30_hashes.json`、`t30_evidence_sha256.txt`

## 12. 边界与未验证

- 仅仿真证据域（合成资产 + SIM_RENDER_RGB；PROPOSED 相机参数），不是 OV9782/真实赛场/真实光照分布。
- 本批仅有采集与几何/颜色条件；**标注、训练、模型、消费者链、板端、导航、Gate 均 NOT RUN**，不得把数据准备写成感知能力或提升 Gate。
- 条件为 capture-side 几何预测 + 代表帧目视核对，不是标注真值；与标注冲突时以 spec v2.1 标注为准。
- 未 commit/push；未接控制/PPO；未修改 Isaac venv；未触碰旧包/旧协议/旧 hash。
