# dev 新族 + HN1/HN2 硬负例采集与四边截断元数据（2026-11-04）

> **状态：** 采集 PASS（可见前台 GUI 合成数据 + 图像/几何条件核实）；标注、训练、板端、导航、Gate 均 NOT RUN，不作能力声明
> **来源章节：** HANDOFF_20261104_DSH_TRAINING_ADMISSION.md §2/§7（dev 暴露数据 val 仅北走廊、HN1/HN2 覆盖不足）；LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §1.4（HN1–HN6 定义）与 §2.1（GT_UNOBSERVABLE 规则）；landmark_training_plan_v2.json（hard_negatives_required / annotation_and_label_policy）；configs/perception/landmark_annotation_spec_v2.json（truncated/occluded、reference_unavailable_reason、GT_UNOBSERVABLE）
> **证据域：** 仿真（Isaac Sim 5.1 可见前台 GUI / DirectX D3D12；SIM_RENDER_RGB shadow；单环境；RMUC2027 合成资产 + 运行时注入的合成 confuser/occluder）
> **最后核对：** 2026-11-04

## 1. 结论先行

- **新 dev 数据**：5 个新族（2 条新内部走廊/接近方向 + 3 个新静态位姿，其中 1 个目标不在视野负例），**accepted RGB 322 帧**；**HN 批次** 2 族（HN1 合成带绿灯相似结构、HN2 合成完全遮挡），**accepted RGB 53 帧**；合计 **375 帧**（任务预算 250–450 内；未抽样，全部保留）。注：HN 批 raw RGB 记录为 59（= 53 accepted + 6 warmup invalid，2 集 × 3 帧），lead 看到的 59 是 raw 记录数，final 池按 accepted 53 计。
- **split（lead 2026-11-04 已批准）**：train = lmf_dev_inner_south_0 + lmf_dev_static_high_0 + lmf_dev_static_negative_0；val = lmf_dev_inner_north_0 + lmf_dev_static_low_0 + HN1 + HN2。**val 首次拥有非北走廊的新走廊 family**（inner_north）。
- **四边截断/green_pixels 元数据**：已对 375 帧逐帧生成（几何预测 + 代表性帧 3× 放大目视）；预测计数 left 24 / right 24 / top 0 / bottom 18；**top 边截断本批未覆盖**，不宣称覆盖。green 像素按“目标绿灯 / 地图原生绿灯柱 / 注入 confuser 绿灯”三类分开计数。
- **HN1**：运行时注入的合成塔状 confuser（柱体 + 顶板 + 绿色自发光灯），27/27 帧 confuser 绿灯可见、中央塔在相机身后/视场外；**不是场地资产、不代表真实赛场分布**。
- **HN2**：运行时注入的合成视觉遮挡墙，26/26 帧 8 个塔体采样点射线全被墙体挡住；**目标存在但完全不可见**，GT 侧应标 present=true + visibility=OCCLUDED + bbox=null + reference UNAVAILABLE（GT_UNOBSERVABLE），**不得当普通负例**。
- **map-native vs injected**：本批发现**地图自带**的带绿灯塔状柱（约 (3.0,4.0,顶≈1.78 m)，非注入）在 inner_north 帧中可见；static_negative 的灰色柱与它是同一结构、从东侧看**看不到绿灯**。**两类必须在报告中分开，不得混称**（§8；同时更正我先前“static_negative 里有带绿灯相似结构”的口头描述：该帧里该结构没有可见绿灯）。
- 不提升 Gate；不接控制；未做标注/训练/模型效果/板端/导航验收。

## 2. 现场与运行环境（实测）

| 项 | 值 |
| --- | --- |
| 仓库/分支/HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `800c53b0e8c1f075d7492be93c19aab06ef339e7` |
| 采集入口 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`，脚本拒绝 `--headless`；本任务新增可选 scene_injections 支持，见 §14） |
| 模式 | `follow_only` / v2 / `reference_origin_v2` / `measured_hard_reset` |
| GUI/渲染 | 可见前台 GUI；DirectX/D3D12（`--kit_args=--/app/vulkan=false`）；非 headless（run manifest `gui_mode=true`、`gui_evidence.headless=false`） |
| Isaac Sim / GPU / 驱动 | Isaac Sim 5.1.0；RTX 5080 16GB；驱动 581.80（CUDA 13.0） |
| 相机/采样 | `configs/sensors/sensor_shadow_v1.json`（sha256 06a47962…，未改语义）；320×240、90°FOV；`sample_period_steps=5` ⇒ 4 Hz accepted RGB |
| 运行 | batch1 `lm_dev_capture_20261104` 5/5 SUCCESS；batch2 `lm_dev_hn_capture_20261104` 2/2 SUCCESS；均 `run.complete.json` PASS、0 collision/timeout/invalid |

## 3. 新 dev 族（batch1，accepted RGB 322）

| case_id | family | split | accepted RGB | seq | 目标距离 | 目标相对方位 | 条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lmf_dev_inner_north_0` | dev_inner_north | **val** | 155 | 3–157 | 2.18–20.84 m | −42.2°…−2.8° | 新内部北走廊（y≈+3.0，W→E），非北外围 y=5.8/south y=−6.2/E 区侧扫；末段目标贴右缘 |
| `lmf_dev_inner_south_0` | dev_inner_south | **train** | 102 | 3–104 | 2.30–8.84 m | +10.6°…+41.1° | 新内部南侧出返接近（E→y≈−3.0→E）；近→远尺度；早段目标贴左缘 |
| `lmf_dev_static_high_0` | dev_static_high_far | train | 23 | 3–25 | 2.92–3.58 m | −27.6°…−13.5° | 新高位静态视点 z=1.7；目标基本全见 |
| `lmf_dev_static_low_0` | dev_static_low_oblique | **val** | 21 | 3–23 | 1.52–1.95 m | +7.5°…+24.2° | 新近距低斜视位姿 yaw=+0.2 rad；底部出框 |
| `lmf_dev_static_negative_0` | dev_target_out_of_view_negative | train | 21 | 3–23 | —（目标在身后） | — | yaw=+2.2 rad，中央塔不在视野（21/21 帧 BEHIND_CAMERA）；画面内可见地图原生灰色柱（无绿灯，见 §8） |

图像核实（逐族抽帧目视）：inner_north 早段目标被中央场地结构遮挡/过远（目标 20.8 m，绿灯仅偶发 1–2 px），约 seq≥105 后目标逐渐清晰（7.3→2.2 m，绿灯 3→22 px），seq 135–150 贴近右缘（右截断），seq 155–157 回到画面内；inner_south 目标全程可见（96/102 帧检测到目标绿灯），早段贴左缘；static_high/low 目标全见（低斜视底部出框）；static_negative 无目标、无绿灯像素（21/21 帧 green_pixels_total=0）。

## 4. HN 批次（batch2，accepted RGB 53）

| case_id | family | split | accepted RGB | 构造 | 目标状态 |
| --- | --- | --- | --- | --- | --- |
| `lmf_dev_hn1_confuser_0` | dev_HN1_similar_structure | **val** | 27（seq 3–29） | 注入 `hn1_confuser_v1`：柱体+顶板+绿色自发光灯（世界约 (8.5,4.2)），相机 yaw=+π/2 朝 +Y | 中央塔在身后/视场外；confuser 绿灯 27/27 帧可见（3–55 px） |
| `lmf_dev_hn2_occluder_0` | dev_HN2_full_occlusion | **val** | 26（seq 3–28） | 注入 `hn2_occluder_v1`：视觉墙 (0.4×2.4×1.9 m) at (10.6,0,0.95)，位于相机与中央塔之间 | 目标存在但完全不可见：26/26 帧 8 个塔体采样点射线全被墙挡住；画面 0 绿灯像素 |

## 5. 四边截断与 green_pixels 元数据（后处理生成，不阻塞采集）

- 方法：用 8 点塔体模型（灯、顶板两端/顶、塔身基座两角、底座两角）经记录的 camera pose+内参投影，得到每帧 u/v 跨度；越界即记 `left/right/top/bottom` 截断（目标在视场外/身后时记 NOT_APPLICABLE，不误报）。green 像素用文档化阈值 `G>100, G>1.25R, G>1.15B` 检测并按三类归属分别计数（目标绿灯 / 地图原生绿灯柱 / 注入 confuser 绿灯）。
- 预测计数（375 帧）：left 24、right 24、top 0、bottom 18；逐帧字段见 `frame_conditions.json`，逐 case 汇总见 `episode_conditions.json`。
- **目视确认**（3× 放大裁剪，`truncation_crops/`）：
  - inner_south g2_3（左缘）：塔身/顶板左侧被左边界裁掉 → left 截断确认；
  - inner_north g1_140（右缘）：顶板右臂到达/越过右边界 → right 截断确认；
  - static_low g4_3（下缘）：塔身延续到画面底、底座不可见 → bottom 截断确认；
  - g1_150 右缘、g4_12 下缘为第二组确认帧。
- **top 截断本批为 0**（预测与目视均未出现），不宣称 top 边覆盖。
- static_high 有 2 帧（g3_10/11）预测右边界越界 1.5–6.5 px（轻微），未单独放大目视，按预测记录。
- 已知局限：几何预测使用近似塔体模型（塔体尺寸未标定）；截断判据以投影为准、以目视为辅，不是标注真值；最终以 annot 的标注为准。

## 6. HN1 构造记录（合成 confuser，val-only）

- **注入实现**：case 文件内 `scene_injections.hn1_confuser_v1` → runner 仅在该 case episode 激活；USDGeom prim，`PreviewSurfaceCfg` 材质（diffuse + emissive），**无 rigid body / 无碰撞（visual-only）**；不改 map 资产、不改 sensor_shadow 配置语义。prim 路径（run2 manifest 记录）：`/World/DevInjection_hn1_confuser_v1_part00..03`。
- **部件（世界位姿/尺寸/材质）**：
  - pedestal：cuboid (0.9,0.9,0.2) @ (8.5,4.2,0.18)，diffuse (0.72,0.72,0.72)；
  - body：cylinder r=0.30 h=1.5 @ (8.5,4.2,1.03)，diffuse (0.55,0.56,0.58)；
  - top_bar：cuboid (1.5,0.18,0.12) @ (8.5,4.2,1.84)，diffuse (0.45,0.46,0.48)；
  - green_light：sphere r=0.10 @ (8.5,4.2,1.93)，diffuse (0.10,0.65,0.15)，**emissive (0.05,0.9,0.10)**；
  - 材质均为 `PreviewSurfaceCfg`，roughness 0.4–0.6，metallic 0；材质参数与最终定义以 `landmark_dev_cases_v2.json` 为准。
- **相机-目标-结构关系**：相机在 E 区 (8.4–8.9, −0.2–0.8, 1.2–1.3)，yaw=+π/2 朝 +Y；中央塔相对方位 −86°…−105°（身后/视场外）；confuser 相对方位 −1.7°…+5.4°、距离 3.5–4.5 m（画面中央）。
- **声明**：该 confuser 是**本采集专用的合成干预**，不是 arena asset，**不代表真实赛场相似结构分布**；label 侧按 `present=false + negative_type=SIMILAR_STRUCTURE + candidates[]`（候选里记录该 confuser 与 SYNTHETIC_INJECTED 标记）。
- **帧 id（27）**：见 `hn1_frames_and_labels.json`（完整列表）。

## 7. HN2 构造记录（完全遮挡，val-only / GT_UNOBSERVABLE 候选）

- **注入实现**：`scene_injections.hn2_occluder_v1`；单个 `cuboid` 视觉墙（visual-only，无碰撞），prim `/World/DevInjection_hn2_occluder_v1_part00`，仅在该 case episode 激活。
- **遮挡物几何/位姿**：wall cuboid size (0.4, 2.4, 1.9) m，center (10.6, 0.0, 0.95)（x 10.4–10.8、y −1.2…+1.2、z 0–1.9）；材质 diffuse (0.62,0.62,0.64)、roughness 0.7、无 emissive。
- **相机-塔-遮挡物关系**：相机巡逻盒 x 8.8–9.3、y −0.5…0.8、z 1.0–1.1；中央塔参考点 (11.52,−0.01,1.25)。对巡逻盒内相机姿态，8 个塔体采样点（灯、顶板两端/顶、塔身基座两角、底座两角，z 0.03–1.62）到墙面的视线全部落在墙体范围内；墙顶 1.9 m 使塔体顶部需 z>2.36 m 才可能从墙顶露出（当前塔体远低于此），故 26/26 帧完全遮挡。
- **GT 标注指引（重要）**：这些帧属“目标存在但完全不可见”，标注应为 `present=true + visibility=OCCLUDED + occluded=true + truncated=false + bbox=null + keypoint=null + reference_status=UNAVAILABLE + reference_unavailable_reason=REFERENCE_OCCLUDED`；指标侧按 spec v2 单列 **GT_UNOBSERVABLE**，**不进入 presence/identity 四格与分母，也不得当作普通负例（TN）**。
- **认识论边界**：图像本身无法证明墙后存在目标；present=true 来自**已记录的场景配置**（合成墙 + 已知中央塔世界位姿），因此这是“场景导出的不可观测真值”，须与“图像可观测正例”分开记录。
- **帧 id（26，全部为 GT_UNOBSERVABLE 候选）**：lmf_dev_hn2_occluder_0-follow_only_g2_3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28（完整结构见 `hn2_gt_unobservable_frames.json`）。

## 8. map-native vs injected：两类相似结构必须分开

| 类别 | 是什么 | 位置/外观 | 证据帧 | 使用规则 |
| --- | --- | --- | --- | --- |
| **map-native（非注入）MS1** | 场地资产自带的带绿灯塔状柱 | 约 (3.0,4.0)，结构顶 z≈1.78 m（map probe 下射线命中，collision_019），绿色灯约 z≈1.71 m；细长灰色柱（宽约 0.5 m，估计）、平顶模块、蓝色侧条，**绿灯只从西/南侧可见** | inner_north g1_90 等（绿灯像素最高 55，seq 4–91）；东侧看同一柱无绿灯（static_negative g5_3/12/23，0 green px；放大图 `zoom/`） | 作为地图原生相似结构证据（HN1 类）；标注时可作 SIMILAR_STRUCTURE 候选，但**不得**称为注入 confuser |
| **map-native 对称候选 MS2** | map probe 在 (−3.0,−4.0) 同高（1.78 m）结构 | 外观 UNKNOWN（本批未看到） | 无 | 仅记录候选，不宣称可见 |
| **injected 合成 confuser HN1** | 本采集运行时注入的柱+顶板+绿灯 | (8.5,4.2)，见 §6 | hn1 27 帧 | 仅 HN1（val）；合成干预、非 arena 资产 |
| **injected 合成 occluder HN2** | 运行时注入的视觉墙 | (10.6,0,0.95)，见 §7 | hn2 26 帧 | 仅 HN2（val）；目标完全不可见（GT_UNOBSERVABLE） |

- **更正**：我先前在批次汇报里说“static_negative 里出现的是地图自带带绿灯相似结构”不准确——static_negative 帧里出现的确实是 map-native 结构（与 inner_north 的 MS1 为同一物），但**从该视角看不到绿灯**（像素级 green=0）。带绿灯的 map-native 证据在 **inner_north** 帧中。
- **与中央塔的区别（MS1）**：中央塔在 (11.52,−0.01)，宽锥形塔身 + 1.7 m 顶灯架 + 约 1.25–1.3 m 高的绿顶灯 + “R”标识 + 白色阶梯底座；MS1 为细长平顶柱 + 侧向绿灯，无顶灯架/无 R 标识。
- **对唯一性假设的意义（记录，不下结论）**：当前资产至少存在 MS1（及对称候选 MS2）这类带绿灯的塔状结构，**挑战训练协议 U1（最多一个塔类实例）/U2（只有中央塔有绿灯）**；是否把它计入“塔类”以及如何更新 U1/U2 属 lead/决策事项，本采集只记录资产观测。

## 9. 不重合与去重核查

- **图像 sha256**：本池 375 帧内部 0 重复；与既有全部 17 个 `*_sensor` 目录（含 formal6/geo_test/lm_pilot/lm_independence/lm_pilot_north/旧 debug/gui_evidence、2026-11-04 final 候选池 297 帧等）**交集全部为 0**（`dedup_vs_existing.json`）。
- **轨迹/位姿**：与既有 5 个 case 配置文件（含 final 池）无任何相同 waypoint 序列；最近起点位姿为 0.28–1.12 m（多为不同 yaw 或不同族；详见 `overlap_vs_existing_families.json`）。两条新走廊位于 y≈+3.0 / y≈−3.0（非 north y=5.8、非 south y=−6.2、非 E 区侧扫族）。
- **split 约束**：物理轨迹/位姿族为组单位，不跨 train/val；HN1/HN2 为 val-only 合成族，**不得进入 sealed final 池**。

## 10. 失败、重试与限制

- 两次冒烟失败均已修复并保留诊断（详见 `failures_and_retries.json` 与 `failure_hn1_smoke_*.txt`）：
  1) `Prim.GetActive` 不存在 → 改 `Prim.IsActive()`；
  2) 注入生成循环变量 `index` 覆盖了环境 `index` tensor → 改名 `part_index`。
- 冒烟顺序：非注入 static_low 冒烟 PASS（21 帧）；HN1 注入冒烟 PASS（27 帧）；随后 batch1 5/5、batch2 2/2 正式运行全部 PASS。未回退 headless。
- **exit code 说明**：PowerShell 包装对两次失败的 python 冒烟也记录了 exit=0；以**完成标记 run.complete.json 与 summary.error.txt** 为准（PASS 有标记，FAILED 无标记），不依赖退出码。
- **GUI 证据限制**：batch1 有运行中桌面截图（窗口可见）；batch2（HN）未另拍运行中桌面截图，其 GUI 状态由 run manifest（gui_mode=true/headless=false）与通过的同管线冒烟证明；全流程无 headless。
- 其他限制：合成资产/模拟相机；4 Hz 相关帧；塔体几何模型近似；top 截断未覆盖；HN 为合成干预非真实分布；未做标注/训练/板端/导航。

仓库测试（2026-11-04）：`E:/isaac/env_isaaclab/Scripts/python.exe -m pytest -q` → **969 passed, 0 failed**（47.96 s）。本任务未修改合同/评价行为、未新增测试；`scripts/run_dynamic_eval.py` 的注入改动未触碰既有 case 路径（无 `scene_injections` 时逻辑不生效）。

## 11. 证据文件

目录 `docs/reports/perception/capture_dev_20261104/`（原始帧/obs jsonl 留在 ignored outputs）：

- case 清单副本 `landmark_dev_cases_v2.json`（sha256 以 `hashes.json` 为准；当前 sha256 = 10b55544e4d6565dd1520e699f7c51aaded8bc6fc305f452d3000c566f2db1bc）
- 两批运行证据：`run1_manifest/summary/complete/sensor_summary`、`run2_hn_manifest/summary/complete/sensor_summary`；冒烟 PASS 证据 `smoke_batch1_*`、`smoke_hn1_*`
- 逐帧四边截断/green/投影：`frame_conditions.json`（375 帧）、`episode_conditions.json`、`four_side_truncation_confirmation.json` + `truncation_crops/`（6 张）
- HN：`hn1_frames_and_labels.json`、`hn2_gt_unobservable_frames.json`
- map-native：`map_native_structures.json` + `zoom/`（2 张：inner_north MS1 绿灯、static_negative 同结构无绿灯）
- 去重/重合：`dedup_vs_existing.json`、`overlap_vs_existing_families.json`
- 失败/重试：`failures_and_retries.json`、`failure_hn1_smoke_first.txt`、`failure_hn1_smoke_second.txt`
- GUI：`gui_window_batch1_20261104.png`、`desktop_batch1_1280x720.png`
- 结构化采集/拆分/HN 记录：`provenance_20261104.json`；哈希清单：`hashes.json`、`evidence_sha256.txt`
- 样例帧（每族 2–3 帧）：`samples/`
- 关键 sha256：cases `<见 hashes.json>`；`frame_conditions.json`、`observations.jsonl` 的 sha 在 `provenance_20261104.json artifacts_sha256` 与 `hashes.json` 中记录。

## 12. 交下游（datafreeze / annot2）

- **datafreeze（T12）**：按 lead 批准的 split plan 冻结 v3：train 3 组（inner_south / static_high / static_negative），val 5 组（inner_north / static_low / HN1 / HN2）；帧清单与 sha 用 `frame_conditions.json`（375 帧，`image_sha256`）+ 各 run `*_sensor` observations；组=物理轨迹/位姿族，不跨 split；HN1/HN2 标 val-only、合成、不得进 final。
- **annot2**：
  - 正向族：inner_north 早段目标被场地结构遮挡/过远（绿灯 0–2 px），标注时参考点可能 UNAVAILABLE；seq≥105 后目标清晰；右缘截断帧别忘 `truncated=true`。
  - inner_south 早段目标贴左缘（truncated=true），中后段正常。
  - static_low 底部出框（truncated=true）。
  - static_negative：目标缺席负例；画面内有 map-native 灰色柱（无绿灯），可记 SIMILAR_STRUCTURE 候选但注明 map-native/非注入。
  - HN1：`present=false + negative_type=SIMILAR_STRUCTURE`，候选记录注入 confuser，注明 SYNTHETIC_INJECTED。
  - HN2：26 帧按 **GT_UNOBSERVABLE**（present=true/visibility=OCCLUDED/reference UNAVAILABLE），不要标普通负例；帧 id 见 §7。
- 本批不提供模型/阈值/导航结论；标注前仍应按 spec v2/v2.1 与 lead 指示执行。

## 13. 边界与未验证

- 仅仿真证据域；合成资产 + SIM_RENDER_RGB（PROPOSED 相机），非 OV9782 实物、非真实光照/分布。
- 未做标注、训练、模型效果、ONNX/RKNN、板端、PX4/SITL/HIL、实机、导航/Gate；不得把本数据准备写成感知能力。
- HN1/HN2 为合成干预，只能用于受控困难负例覆盖，不得外推真实赛场分布；HN2 的 GT 为场景导出、不是图像可观测。
- 四边截断为几何预测+目视代表帧，不是标注真值；top 边未覆盖。

## 14. 代码改动记录（仅运行时注入支持）

- 文件：`scripts/run_dynamic_eval.py`（本任务 write scope 内）。
- 改动：新增可选 `scene_injections` 解析/生成/按 episode 激活/在 manifest 记录；prim 为 visual-only USDGeom（Cuboid/Cylinder/Sphere + `PreviewSurfaceCfg`），不写 map 资产、不改 loader、不改 sensor_shadow 配置语义。
- 无注入定义的旧 case 文件行为不变（未出现 `scene_injections` 时该逻辑不生效）；本批通过的两次冒烟与两批正式运行均使用同一脚本版本。
