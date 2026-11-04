# T25 identity 补充采集：INCOMPLETE 收尾记录（2026-11-04）

> **状态：** INCOMPLETE（T25 formal 未交付；pilot 仅诊断，机位不满足“两者可辨”）
> **来源章节：** task-25（MS1 与中央塔相互遮挡 + 远景 MS1，60–120 accepted RGB）；LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §1.4（HN1/相似结构）；landmark_annotation_spec_v2_1.json；T26 标注报告 §0/§7（28 帧来源判定）
> **证据域：** Isaac Sim 5.1 可见前台 GUI 仿真（pilot run 完成；formal 两次运行在 Isaac/CUDA 运行时失败）；无 headless、无注入、未改 map 资产
> **最后核对：** 2026-11-04

## 1. 结论先行

- **T25 INCOMPLETE**：formal 采集**没有**产生合格的 60–120 accepted RGB 池，也没有 `run.complete.json`。
- **pilot run 完成但不可用**：`outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104`（run.complete PASS，2/2 SUCCESS，**accepted RGB 85** = mutual_overlap 44 + ms1_far 41；RGB 图像 91 含 6 帧 warmup）。图像复核显示机位不合格：①相互遮挡案的近景 MS1 把远景中央塔基本挡住，不能确认“两者可辨”；②远景 MS1 视角被场地中央结构在前景占满（不是干净的远景 MS1）。因此 pilot **只作诊断**，不计入 T25 池。
- **formal 两次失败（Isaac/CUDA 运行时，非 case/loader 问题）**：
  1) attempt1 启动阶段 torch 扩展 import 异常（`module torch has no attribute version`，AppLauncher/kit 启动路径）；
  2) attempt2 进入采集且第一案 mutual_overlap SUCCESS，但第二案开始 **CUDA OOM**（`omni.physx.tensors`: Unable to allocate 671088640 bytes for mGpuContactPairsDev）；无完成标记，残留 34 accepted / 37 张 RGB 图片，只含第一案。
- **按 lead 决定不再重跑**（时间/资源；v5 不依赖 T25）。在 pilot 图像复核后已把 manifest 的两个新 case 机位调好（A：重叠约 10–25%、目标灯在 MS1 轮廓外；B：正西 ~10 m 视角、MS1 居中），但**未再采集验证**，只能记为待办，不作证据。
- **标注用途**：annot 已确认其 28 帧代表帧来自 **pilot run**，整批标 `PROVISIONAL_DIAGNOSTIC_ONLY`，**不并入 v5、不作 GT**（与 T26 报告一致；capture 确认此判定）。
- case manifest 已 append-only 追加 2 case + MID_W 采集辅助区（既有 T15 定义未改），loader 解析 9 cases PASS；manifest sha 链见 `t25_provenance_20261104.json`。
- **holdout**：按要求只准备草案（`holdout_plan/`），未跑 Isaac；当前状态 **DRAFT_NOT_TRIGGERED**（等 lead 最终门判定）。

## 2. 运行环境与入口

| 项 | 值 |
| --- | --- |
| 仓库/分支/HEAD | `E:\isaac\proj_boom_birds` / `feat/v2.2-simulation-perception` / `3491cde1832358f75bc15cab9c4ce0ff4d886d8d` |
| 入口/模式 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`；脚本拒绝 `--headless`）/ `follow_only` / v2 / `reference_origin_v2` / `measured_hard_reset` |
| GUI/渲染/驱动 | 可见前台 GUI；DirectX/D3D12（`--kit_args=--/app/vulkan=false`）；Isaac Sim 5.1.0；RTX 5080 16GB；驱动 581.80 |
| case manifest | `configs/scenarios/landmark_dev_identity_cases_v1.json`（append-only 至 9 cases：T15 的 7 个 + T25 的 2 个） |
| pilot run | `outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104`（+ `_sensor`），PASS 2/2 |
| formal run | `outputs/sensor_shadow/lm_dev_identity_capture_t25_20261104_formal`（+ `_sensor`），**无 run.complete** |

## 3. pilot run（仅诊断）

| case | accepted RGB | seq | 目标距离 | MS1 距离 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `lmf_devid_mutual_overlap_0` | 44 | 3–46 | 11.78–12.98 m | 2.42–3.62 m | 图像复核：近景 MS1 与远景中央塔前后重叠过度，目标不能清楚辨别 |
| `lmf_devid_ms1_far_0` | 41 | 3–43 | 16.21–17.29 m | 10.11–11.09 m | 图像复核：视野被 map-native 中央结构在前景占据，不是干净的“远景 MS1” |

- 逐帧条件（pilot）保留为诊断：`t25_frame_conditions_pilot.json` / `t25_episode_conditions_pilot.json`；其中 mutual_overlap 记录到 31 帧重叠≥0.10、20 帧≥0.25，但该几何预测不能替代“目标可辨”的图像判定，实际图像判定为不合格。
- 去重（pilot 85 accepted 帧）：与 20 个既有 `*_sensor` 数据 sha256 交集**全部 0**（`t25_pilot_counts_and_dedup.json`）。
- GUI 证据：`t25_gui_window_pilot.png`（pilot 运行中窗口截图，含 Isaac 5.1.0 标题栏）；pilot manifest `gui_mode=true`/`headless=false`。

## 4. formal 失败记录

| 尝试 | 时间/结果 | 证据 |
| --- | --- | --- |
| attempt1 | 启动阶段失败：torch 扩展 import 异常（`AttributeError: module 'torch' has no attribute 'version'`，kit 启动路径），无 run.complete | `t25_formal_failure_torch_import_attempt1.txt` |
| attempt2 | 进入采集；第一案 SUCCESS；第二案开始时 CUDA OOM（`omni.physx.tensors` 分配 640 MB contact pairs 失败）；无 run.complete，残留 34 accepted/37 图片（仅第一案） | `t25_formal_failure_cuda_oom_attempt2.txt`、`t25_formal_summary_error.txt`、诊断窗口 `t25_gui_window_formal_attempt2.png` |

- 结论：失败发生在 **Isaac/CUDA 运行时层**（当时的并行训练任务挤压 GPU/RAM），不是 case manifest/loader/机位语法问题；loader 对 9 cases 解析 PASS。未回退 headless，未改 Isaac venv，未改 map 资产。

## 5. 机位修正记录（未再采集）

pilot 图像复核后对 manifest 的两个 T25 case 做了 append-only 的机位修正（未影响 T15 既有 case）：

- mutual_overlap：patrol 收拢到重叠约 10–25% 的区域，yaw 固定使目标绿灯位于 MS1 轮廓之外；
- ms1_far：改到正西约 10 m 视角（MS1 居中、中央结构移到左侧独立位置），距离 10 m 在要求的 8–12 m 内。

上述修正**未得到采集验证**：T25 formal 失败后按 lead 决定停止，不再重跑。

## 6. 与既有数据/标注的边界

- T25 **无正式 accepted 池**：不得把 pilot/formal 残留帧并入 v5、不得作为 val_identity GT、不得用于模型或阈值决策。
- annot 的 28 帧（每 case midpoint systematic 14）来自 pilot run，标注文件在 ignored `outputs/perception/dev_annotations_20261104/identity_t25/`，整批 `PROVISIONAL_DIAGNOSTIC_ONLY`；capture 确认该来源判定。
- MS1 是 map-native 结构（非注入）；本任务未使用任何合成注入；MS1 的 world pose/验证引用 T15 的 `map_native_structures.json`。

## 7. 证据文件（docs/reports/perception/capture_dev_20261104/）

- 报告/记录：`T25_CAPTURE_INCOMPLETE_20261104.md`、`t25_provenance_20261104.json`、`t25_pilot_counts_and_dedup.json`
- pilot：`t25_pilot_manifest.json` / `t25_pilot_summary.json` / `t25_pilot_complete.json` / `t25_pilot_sensor_summary.json` / `t25_pilot_gui.log`、`t25_frame_conditions_pilot.json`、`t25_episode_conditions_pilot.json`
- formal 失败：`t25_formal_summary_error.txt`、`t25_formal_gui.log`、`t25_formal_failure_torch_import_attempt1.txt`、`t25_formal_failure_cuda_oom_attempt2.txt`
- manifest：`t25_cases_manifest_after_t25.json`（当前副本；T15 旧副本 `identity_cases_v1.json` 保持不变）
- GUI：`t25_gui_window_pilot.png`、`t25_gui_window_formal_attempt2.png`（诊断）
- 哈希：`t25_hashes.json`、`t25_evidence_sha256.txt`

## 8. 边界与未验证

- 仅仿真证据域；合成资产 + SIM_RENDER_RGB（PROPOSED 相机），非 OV9782 实物/真实分布。
- T25 INCOMPLETE：无正式条件表（四边截断/green_pixels 的正式 T25 表不成立）；pilot 条件表仅诊断。
- 未做标注结论/训练/模型/板端/导航/Gate；不得作任何能力声明；不提升 Gate。

## 9. holdout 草案（未采集）

- 草案：`holdout_plan/HOLDOUT_CASE_MANIFEST_DRAFT_v1.json`（7 个全新族、预测 394 帧、采样规则先冻结、loader PASS、与既有族重合性检查见 `holdout_plan/holdout_overlap_vs_existing_families.json`）。
- 计划说明：`holdout_plan/HOLDOUT_PLAN_v1.md`。
- 状态：**DRAFT_NOT_TRIGGERED**（按 lead：等最终门判定；不跑 Isaac）。
