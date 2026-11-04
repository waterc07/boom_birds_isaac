# ONNX 三路径端到端一致性：PyTorch / Ultralytics 原生 ONNX / raw-ORT 手工解码（2026-11-04）

> **状态：** BASELINE（host 端三路径一致性与缺陷回归；**不是**模型效果、板端、导航或能力认证）
> **来源章节：** LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md §4（A5/A6 准入证据）；TRAINING_20261104.md §5.1（旧“raw-ORT 端到端未比 = UNKNOWN”）；configs/perception/landmark_export_v1.json（本任务新增导出/对齐策略）
> **证据域：** 隔离 .venv/landmark-train 实际运行（host：val 48 帧 + exploratory final 24 帧抽样 + 54 帧合成几何变体；CPU primary + GPU 敏感性路径）；不含 RKNN/板卡/实机/SITL/HIL
> **最后核对：** 2026-11-04

本文只报告**实际运行**的三路径对齐结果、旧 4.67 px 差异的解释、缺陷回归与 CLI/测试结果。final 池只做只读抽样，**没有**重跑一次性 exploratory final，没有改阈值/标签/模型，没有提升 Gate。

---

## 0. 结论先行

| 项 | 结论 |
| --- | --- |
| 三路径（.pt / 原生 ONNX / raw-ORT） | **PASS**：126 帧（72 帧有 GT）上 observation 决策翻转 **0**、metric joint 翻转 **0**；关键点最大差 **1.40e-4 px**（中位 3.15e-5 px）；ONNX 原生 vs raw-ORT 关键点差 **0.0 px** |
| 图/导出正确性 | **PASS**：同一共享画布上 torch vs onnxruntime raw 最大绝对差 **0.06999**（相对 640 = **1.09e-4**，均值 2.16e-4）；冻结 ONNX 4ee4071d 与重新导出的 65fb75ae 原始输出 **0.0**（字节 sha 不同，数值逐位一致） |
| 旧 4.67 px 是否翻转判定 | **会**（在旧的“混用预处理模式”对比下）：legacy .pt rect vs .onnx square 在 72 帧有 GT 上 **18 次 joint 翻转**（presence 5 / reference 6 / identity 5），关键点最大 **8.17 px**；dynamic_A_north_..._183 上精确复现 **dy=4.667 px** 且 rect 路径 joint PASS、square 路径 joint FAIL |
| 三路径为什么一致 | 三条路径共用同一张 640×640 方形 letterbox 画布（auto=False）、同一 NMS（conf=0.01, IoU=0.7, max_det=300, 单类）、同一冻结阈值（tau_det=tau_conf=0.605476）与同一源图坐标域；raw 路径补齐了 NMS 与 PosePredictor 的 clip+round 后处理 |
| 缺陷回归 | D1 raw 无 NMS、D2 rect/square 混用、D3 PosePredictor box round 未复刻；先写失败回归（ImportError 红态）后修，18 条测试 PASS |
| 旧 eval_onnx 产物 | 不可作模型证据：其 reject_reason 有 **77/134 = MULTIPLE_CANDIDATES**、joint 仅 **4/95=0.042**（pt 为 55/95）、51/95 帧与 pt 翻转；其 ONNX sha **83925f46 当前不存在**，无法复现 |
| 未完成 | RKNN/板端、真实相机、GPU 近 tie 的可复现性、population 级近阈值统计 = **UNKNOWN** |

---

## 1. 现场、授权与纪律

- 仓库 E:\isaac\proj_boom_birds；分支 feat/v2.2-simulation-perception；开工 HEAD 0c27525（工作树含其他 teammate 并行修改，本任务不覆盖）。
- 授权：用户 2026-11-04 授权主候选 YOLOv8n-pose（AGPL-3.0）仅内部有界研究/评测；分发另行决策。本任务不 commit/push、不接控制/PPO、不提升 Gate、不改 Isaac venv。
- 实际运行只在隔离环境 .venv/landmark-train（Python 3.11.9 / torch 2.7.0+cu128 / ultralytics 8.2.0 / onnx 1.22.0 / onnxruntime 1.31.1 / numpy 1.26.4 / cv2 4.10.0 / onnxsim 0.8.1）；Isaac venv 只用于跑仓库 pytest。
- final 池：只读抽样 24 帧；没有写 final 指标、没有重跑 final、没有改标签/阈值。合成变体只用于路径对比，无 GT。

---

## 2. 方法：三条路径 + 两个解释路径

### 2.1 共享预处理（关键设计）

对每一帧先生成唯一的 640×640 方形 letterbox 画布（auto=False、stride=32、pad=114），三条路径消费同一张画布：

| 路径 | 实现 | 后处理 |
| --- | --- | --- |
| A pt_square | ultralytics YOLO(last.pt).predict(画布, imgsz=640, conf=0.01, device=cpu) | ultralytics NMS + PosePredictor（scale_coords；box clip+round）→ evaltool 解码 model→source |
| B onnx_native_square | ultralytics YOLO(last_opset18.onnx).predict(同一画布, device=cpu) | 同 A（同一 ultralytics 后处理） |
| C raw_ort_square | onnxruntime CPU session.run(同一 tensor) | numpy NMS（复刻 ultralytics：score>conf、IoU>0.7 抑制、max_det 300）→ model 空间 clip+round → evaltool decode_candidates |

另有两个解释路径（不参与主判定）：

| 路径 | 实现 | 用途 |
| --- | --- | --- |
| D pt_default_rect | .pt 在原图上默认 predict（ultralytics 对 .pt 单图用 LetterBox auto=True → 320×240 变 640×480） | 旧默认行为 |
| E onnx_native_default | .onnx 在原图上默认 predict（导出图 auto=False → 640×640） | 旧默认行为 |

- **NMS**：conf=0.01 起筛，由 decode 层统一应用冻结 tau_det=0.605476；IoU=0.7、max_det=300、单类 agnostic=False、multi_label=False。
- **坐标域**：全部输出到原图源像素 xywh / keypoint 像素；bearing=atan2(x-cx,fx) 是图像角，不是世界方位。
- **设备策略**：primary 三条路径强制 CPU（--device-pt cpu），避免 GPU/CPU 数值差在近 tie anchor 上改变 NMS 选择；另设 pt_square_gpu 观测路径（本次 0 翻转）。
- **阈值**：仅读冻结文件 configs/perception/landmark_model_freeze_v1.json：tau_det=tau_conf=0.605476、tau_margin=0.1、tau_px=3.0、tau_iou=0.3、tau_kpt=0.5。

### 2.2 样本构成（126 帧）

| 类别 | 帧数 | 说明 |
| --- | ---: | --- |
| real_val | 48 | dev val 分层抽样（present/reference 可用/不可用/负例/截断/多 family） |
| real_final | 24 | exploratory final 只读分层抽样 |
| aspect（合成） | 39 | 320×180 / 240×180 / 180×240 / 320×120 裁剪，非方形输入 |
| edge_truncation（合成+真实标签） | 33 | 以 GT bbox 为锚的右/下边缘裁剪；真实截断帧也打标 |
| multi_candidate（合成） | 8 | 双塔横向拼接（640×240）验证多候选拒绝 |
| keypoint_unavailable | 16 | GT present 但参考点不可用（v=0）的真实帧 |
| near_threshold | 7 | raw-ORT 最高分与 tau_det 相差 ≤0.05 的帧 |
| 有 GT（可算 metric 决策） | 72 | val 48 + final 24 |

合成帧无 GT，只做路径间 observation 决策对比；真实帧同时计算 metric 层 presence/reference/joint 决策。

---

## 3. 结果一：数值与三路径一致性（主判定）

### 3.1 torch vs onnxruntime raw 输出（同一 tensor）

| 指标 | 值 | 分母/说明 |
| --- | --- | --- |
| 比较帧数 | 126 | 所有抽样帧的共享画布 |
| 输出形状 | (1, 8, 8400) 一致 | 形状匹配 |
| max abs diff | **0.069992** | 坐标通道主导（值域 0–640） |
| mean abs diff | 2.159e-4 | 全元素 |
| 相对差（/640） | **1.0936e-4** | 通过判据 ≤1e-3（0.64 输入 px） |
| 每通道 max：box cx/cy/w/h | 0.0118 / 0.0110 / 0.0276 / 0.0700 | — |
| 每通道 max：class score | 3.02e-5 | — |
| 每通道 max：kpt x/y/conf | 0.00415 / 0.00842 / 0.000158 | — |

- 旧结论“raw max_abs_diff 1.22e-4”是未训练 smoke 图的绝对最大值；训练后 checkpoint 的绝对最大值被坐标通道放大（相对仍 ~1e-4）。本报告改用相对判据并保留绝对值，避免把两种口径混为一谈。

### 3.2 冻结 ONNX vs 重新导出 ONNX

- 冻结：outputs/landmark_train/runs/onnx_trained_seed1/last_opset18.onnx，sha **4ee4071d…**（freeze 清单记录值）。
- 重新导出：scripts/landmark_export_onnx.py（opset18、simplify、CPU）→ outputs/perception/onnx_parity_20261104/export/last_opset18_v1.onnx，sha **65fb75ae…**（两次独立导出同 sha）。
- 126 帧原始输出最大差 = **0.0**（逐位一致）→ sha 不同来自序列化/元数据，不是图差异。
- 说明：lead 消息里的 ca28a5c9… 不匹配任何现存文件；landmark_final_eval_protocol_v1.json 文本也写 ca28a5c9，需其 owner 更正（见 §8 勘误）。

### 3.3 主判定（同画布、同 NMS、同阈值、同坐标域）

| 对比 | observation 决策翻转 | metric joint 翻转 | 关键点 max（px） | 关键点中位（px） | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| A pt_square vs B onnx_native_square | **0** / 126 | **0** / 72 | **1.40e-4** | 3.15e-5 | 图/后端级一致 |
| A vs C raw_ort_square | **0** / 126 | **0** / 72 | **1.40e-4** | 3.15e-5 | raw 路径已复刻 NMS/round |
| B vs C | **0** / 126 | **0** / 72 | **0.0** | 0.0 | 同一 ONNX 数值 |
| A vs A_gpu（设备敏感性） | 0 / 126 | 0 / 72 | 0.0 | 0.0 | 本次 CPU/GPU 同结果；见 §6.3 |

- 关键点配对：A↔B 匹配 90 对（其中 emitted 85 对）；只对 keypoint conf ≥ tau_kpt=0.5 的候选比较位置（低于阈值的候选位置不是消费者可见参考点，避免无意义离群值）。
- 分层核验：实时帧 72（val 48 + final 24）、合成 54；near-threshold 7 帧的 status 翻转 0；多候选 8 帧中检测到的帧在三路径均为 DETECTED + MULTIPLE_CANDIDATES + identity_claimed=false（完全一致）；keypoint_unavailable 16 帧中 14 帧三路径一致 UNAVAILABLE、2 帧一致 VISIBLE；边缘截断帧的 TRUNCATED 决策三路径一致。

---

## 4. 结果二：旧 4.67 px 的解释与“是否翻转判定”

### 4.1 解释链

1. ultralytics BasePredictor.pre_transform：LetterBox(self.imgsz, auto=same_shapes and self.model.pt, stride=...) → .pt 模型（model.pt=True）单图走 auto/rect：320×240 → 640×480 画布；.onnx 模型（model.pt=False）走方形：320×240 → 640×640（pad_y=80）。
2. 两种画布的 anchor 网格不同（640×480 为 60×80/30×40/15×20=6300 anchors；640×640 为 8400），姿势头对 keypoint 的解码基于 anchor 位置 → 同一个目标的关键点可差数 px。
3. 图的数值本身只差 ~1e-4（§3.1），重新导出与冻结 ONNX 原始输出 0.0（§3.2）→ **4.67 px 不是导出/图错误**，而是**预处理模式差异**。
4. 旧对比同时混入“pt 默认 GPU vs onnx CPU”的设备差（一次未复现的 4.24 px 近 tie 现象，见 §6.3），进一步放大了该差异的不可控性。

### 4.2 量化（legacy D vs E，72 帧有 GT）

| 指标 | 值 |
| --- | ---: |
| observation 决策翻转 | 17 / 126 |
| └ presence / reference / identity | 5 / 6 / 5 |
| metric joint 翻转 | **18 / 72** |
| 关键点配对 86 对，max / median | **8.17 px / 1.45 px** |
| 翻转帧分布 | real_val 6；real_final 2；edge_truncation+val 4；edge_truncation+final 4；keypoint_unavailable+edge+val 1；keypoint_unavailable+final+near 1 |

### 4.3 关键帧：dynamic_A_north_0-follow_only_g1_183.png（旧 4.67 px 的同名帧）

| 路径 | keypoint (x, y) px | 与 square 的 dy | joint 判定 | reference_class |
| --- | --- | ---: | --- | --- |
| 方形（A/B/C，三路径一致） | (295.167, 67.811) | — | FAIL | PRESENT_WRONG_ANCHOR（anchor 误差 5.14 px > tau_px 3.0） |
| pt_default_rect（D） | (294.145, 63.144) | **4.667** | **PASS** | PRESENT_AND_AVAILABLE（2.57 px） |
| onnx_native_default（E） | (295.167, 67.811) | 0 | FAIL | PRESENT_WRONG_ANCHOR（5.14 px） |

- 旧记录“kpt 最大 4.67 px（源图）”在此帧精确复现：dy = 67.811 − 63.144 = **4.667 px**。
- 该帧在 legacy 混用模式下 rect PASS / square FAIL → **4.67 px 级差异确实会翻转通过判定**（本帧 1 次；样本内 18/72）。
- 在三路径统一预处理后，A/B/C 一致 FAIL（图本身对该帧就是 anchor 误差 5.14 px，属于模型能力问题，不是导出问题）。

### 4.4 结论

- **旧 4.67 px 会造成实际判定翻转**，但前提是混用两种预处理模式（旧 pt 默认 rect vs onnx 默认 square）。
- 统一画布后，三路径的差异降到 1.4e-4 px 且 0 翻转；因此旧差异应归因于预处理/设备口径不统一，不能归因于 ONNX 导出或 raw 解码图。

---

## 5. 结果三：旧 eval_onnx 产物复核（证明 raw 路径缺陷 D1）

旧产物（不是本任务新跑，只读复核）：

| 产物 | 模型 | joint（窄口径） | presence | reject_reason 统计 |
| --- | --- | ---: | --- | --- |
| outputs/landmark_train/runs/onnx_trained_seed1/eval_pt/metrics.json | last.pt d4ffe49a… | **55/95 = 0.579** | TP75/FP10/FN20/TN15 | REFERENCE_UNAVAILABLE 39、TRUNCATED 10、None 71、MISSING_IMAGE 14 |
| outputs/landmark_train/runs/onnx_trained_seed1/eval_onnx/metrics.json | ONNX **83925f46…（当前不存在）** | **4/95 = 0.042** | TP74/FP11/FN21/TN14 | **MULTIPLE_CANDIDATES 77**、REFERENCE_UNAVAILABLE 4、None 39、MISSING_IMAGE 14 |

- 两产物 95 个 joint 帧中 **51 帧翻转**；旧 eval_onnx 的 joint 失败分解为 **IDENTITY 69 / PRESENCE 21 / REFERENCE 1**。
- 根因：旧 run_onnx_backend 把 8400 anchors 直接送 decode_candidates，**没有 NMS** → 同一目标多个重叠候选 → MULTIPLE_CANDIDATES（margin < 0.1）→ identity 不 claim → joint 在 IDENTITY 处失败。这是解码缺陷，不是模型/图证据。
- 该 ONNX 文件 sha 83925f46 已不存在，且与冻结 4ee4071d 不同 → 旧 eval_onnx 结论不可复现、不得引用为模型效果。

---

## 6. 缺陷、失败回归与修复

### 6.1 红态（先写失败回归）

- 先写 tests/evaluation/test_landmark_onnx.py（18 条），首次运行：ImportError: cannot import name 'landmark_onnx'（模块尚未实现）→ 记录红态；随后实现模块与脚本转绿（17 passed）。

### 6.2 三个缺陷

| 编号 | 缺陷 | 证据 | 回归测试 | 修复 |
| --- | --- | --- | --- | --- |
| D1 | raw-ORT 路径无 NMS，多锚点候选触发 MULTIPLE_CANDIDATES | 旧 eval_onnx：77/134 帧 MULTIPLE_CANDIDATES、joint 4/95 vs pt 55/95、51/95 帧翻转 | test_raw_decode_claims_identity_after_nms（无 NMS → reject；NMS 后 → identity claim） | raw 路径先做与 ultralytics 同语义的 numpy NMS，再 decode |
| D2 | .pt 与 .onnx 默认预处理模式不同（rect 640×480 vs square 640×640） | legacy 对比 17 obs / 18 joint 翻转；frame_183 dy=4.667 | test_letterbox_rect_mode_differs_from_square + §4 全量对比 | 三路径共用一张方形画布（auto=False） |
| D3 | PosePredictor.postprocess 对 box 做 clip+round（整数像素），raw 路径未复刻 → 贴边帧 TRUNCATED 判定翻转 | 早期 smoke：3/20 帧 reject_flip（仅 TRUNCATED 差异） | test_pose_predictor_box_rounding_is_mirrored | raw 解码在 model 空间 clip+round 后再逆 letterbox |

- 说明：D3 是“同 NMS/同后处理”的一部分；修复后贴边帧 TRUNCATED 决策与两条 ultralytics 路径一致（0 翻转）。

### 6.3 设备近 tie（未复现，保留为 UNKNOWN 风险）

- 早期一次未受控运行（pt 自动 GPU vs onnx CPU）在 lmf_sweep_0-follow_only_g1_10.png 上出现 **4.24 px** 关键点差、1 次 joint 翻转；两个竞争 anchor 的分数差仅 **2.7e-5**。
- 复测（outputs/perception/onnx_parity_20261104/gpu_repeatability.json）：该帧 3 次 CPU pt + 5 次 GPU pt + 3 次 CPU onnx 全部一致（0.0 px），未能按需复现。
- 缓解：primary 三路径强制同一设备（CPU）；GPU 路径仅作观测。
- 残余风险：GPU 卷积算法/工作区选择在跨进程时是否 bit-stable 未做穷举，**UNKNOWN**；任何用 GPU 推理做“最终判定”的流程都应先固定设备与 determinism 设置。

---

## 7. 交付物、CLI 与测试（可复现）

### 7.1 新增版本化文件（本任务写域）

| 文件 | 作用 | sha256 前缀 |
| --- | --- | --- |
| scripts/landmark_export_onnx.py | 真实 CLI：.pt → ONNX（opset/imgsz/simplify/device 可配），记录 sha/opset/节点/IO，torch vs ORT 数值校验，默认拒绝覆盖 | d6632b32… |
| scripts/landmark_onnx_parity.py | 真实 CLI：三路径 + 两个解释路径 + 设备敏感性 + 合成变体；输出 JSON 证据与逐帧 detail | 34f320ec… |
| src/boom_birds/evaluation/landmark_onnx.py | 纯 numpy/cv2 库：letterbox 几何、NMS、raw 解码、决策比较、配对；供测试与脚本复用 | 6c409587… |
| configs/perception/landmark_export_v1.json | 导出/对齐策略与容差；仅 repo 相对路径，无本机私有绝对路径 | 50ca3676… |
| tests/evaluation/test_landmark_onnx.py | 18 条回归（红→绿，含 venv 端到端集成 1 条） | 3dd73fa7… |
| docs/reports/perception/onnx_parity_20261104.json | 版本化证据 JSON（T14 输出 + artifact_notes；T29 追加 t29_candidate_A 段后 sha 更新，T14 顶层字段/数字未改） | fd820c1d… |

训练/停止器/阈值冻结/数据准备 CLI 由 teammate “train” 交付（scripts/landmark_train_cli.py、scripts/landmark_freeze_thresholds.py、configs/perception/landmark_train_cli_v1.json）；本任务未重写该文件，只在其 --help 冒烟层验证可执行。两文件写域已通过 team message 协调。

### 7.2 真实命令（本次实际运行）

~~~powershell
$py = '.venv\landmark-train\Scripts\python.exe'
$env:TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD = '1'

# 1) 导出 + 数值校验（实际执行，exit 0）
& $py scripts\landmark_export_onnx.py --config configs/perception/landmark_export_v1.json --out outputs/perception/onnx_parity_20261104/export/last_opset18_v1.onnx --json-out outputs/perception/onnx_parity_20261104/export/export_evidence.json --overwrite --verify

# 2) 三路径对齐（实际执行，exit 0 = PARITY_PASS）
& $py scripts\landmark_onnx_parity.py --onnx outputs/landmark_train/runs/onnx_trained_seed1/last_opset18.onnx --alternate-onnx outputs/perception/onnx_parity_20261104/export/last_opset18_v1.onnx --out-dir outputs/perception/onnx_parity_20261104/full --evidence-out docs/reports/perception/onnx_parity_20261104.json --overwrite
~~~

- parity CLI 默认参数：val 48 / final 24 / synthetic base 8 / near-threshold 16（实际抽到 7）；样本策略在 config 的 parity.sample_policy 中，全部为 repo 相对路径。
- 证据 JSON 关键字段：raw_numeric_parity、onnx_equivalence、pairwise、device_sensitivity、scenarios、near_threshold、self_check、conclusion、artifact_notes；逐帧证据在 ignored outputs/perception/onnx_parity_20261104/full/parity_detail.json（b4bc2a91…）。

### 7.3 测试与其它校验

| 项目 | 结果 |
| --- | --- |
| pytest -q tests/evaluation/test_landmark_onnx.py（Isaac venv） | **18 passed**（25.6 s，含 1 条 venv 端到端集成） |
| 全仓 pytest -q（Isaac venv） | **1058 passed in 87.95 s（最终复跑，0 failed）**；含本任务 18 条；先前 1 条 teammate “train” 的 config 绝对路径失败已由其修复 |
| scripts/planning/audit_documents.py | 见 §9 交付核对（本次运行） |
| 导出校验 | opset18、graph_nodes 见 export_evidence；raw 相对差 **5.77e-6**，verdict overall=true |
| deliverable 额外门 | self_check.passed=true（raw_parity_ok / onnx_equivalence_ok / 三对 primary 的 decision 与 keypoint 均 ok） |

---

## 8. 勘误（对旧结论追加，不改旧文件）

1. **TRAINING_20261104.md §5.1 / HANDOFF**：“evaltool 的 raw-onnxruntime 解码路径本轮未做端到端比对，标 UNKNOWN/未验证” → 本报告已补齐：旧 eval_onnx 产物确实存在，但其结果（joint 4/95）是无 NMS 的解码缺陷，且其 ONNX sha 83925f46 已不存在；旧 eval_onnx 数字不得作为模型证据。三路径在当前实现下 0 翻转。
2. **旧“4.67 px 不是图错误”** 的结论方向正确，但归因需细化为 rect/square 预处理模式差异（精确 dy=4.667 于 frame 183），并补充：该差异在旧混合模式下会翻转判定（本样本 18/72 joint）；统一画布后差异降到 1.4e-4 px。
3. **旧 “raw max_abs_diff 1.22e-4”** 是 smoke 未训练图的绝对 max；训练后 checkpoint 绝对 max 0.06999（坐标通道主导），相对 1.09e-4。两者口径不同，后续必须写清“绝对/相对、哪个 checkpoint”。
4. **ONNX sha 口径（已按 lead 2026-11-04 决定统一）**：冻结/协议统一使用 **4ee4071d…**（最终磁盘文件，freeze 清单记录值）；重新导出 65fb75ae… 与冻结文件的 raw 输出逐位一致（0.0），已在 JSON artifact_notes 中注明“数值等价、sha 差异来自序列化”；lead 早期消息与 final_eval_protocol 文本里的 ca28a5c9… 是更早一次导出的瞬时值（每次重导出会重写文件），不应继续引用；weights/last.onnx 另有 adb65b7c…，onnx_check/best_opset18.onnx 是 smoke 图 b35f571f…，均不是冻结证据。
5. **labels_val 漂移（按 lead 2026-11-04 决定记录，不改写历史冻结）**：冻结 v1 记录 c3944e08…（134 帧）是历史字节，保留不改；parity 运行当时读取的 labels_val.json 为 8c215597…（163 帧）；其后 T19 identity 批次曾短暂变为 231 帧 6ade12bd…，annot2 稳定化为当前 163 帧 4e8e877e…，并导出固定评测用 labels_val_validation163.json（sha **a9bfda8f…**，163 帧）作为**新基线**。本报告只做路径对比，不重算阈值/指标，因此不构成对旧 val 指标的改写；完整时间线见 JSON artifact_notes.labels_val_erratum。
6. **旧 eval_onnx 模型文件缺失**：83925f46 不存在于当前 outputs，无法复现；若需要保留该历史证据，请从备份恢复或在报告中明确标注“不可复现历史产物”。

---

## 9. 交付核对（本次实际结果）

- 版本化证据：本文件 ONNX_PARITY_20261104.md + [onnx_parity_20261104.json](onnx_parity_20261104.json)（sha fd820c1d…，286904 bytes；含 artifact_notes 与 T29 追加段；T14 顶层字段/数字未改，合并前副本 sha 4cbcabc0… 存于 ignored outputs）。
- ignored 运行产物：outputs/perception/onnx_parity_20261104/{full/parity_detail.json, export/export_evidence.json, gpu_repeatability.json, parity_run.log, pytest_full.log}；版本化 JSON + 版本化脚本/配置即可复现，不依赖 ignored 脚本。
- 全部关键数字带分母：126 帧总样本 / 72 GT 帧 / 90 关键点配对 / 17 legacy observation 翻转 / 18 legacy joint 翻转 / 7 near-threshold / 8 multi-candidate。
- 未提升 Gate、未接控制、未跑 PPO、未改 Isaac venv、未 commit/push。

## 10. UNKNOWN / 未完成（明确声明）

- RKNN 转换/INT8/板端延迟/热稳定：**UNKNOWN / NOT RUN**（无 RK3576 板卡；RKNN-Toolkit2 专有许可，未安装）。
- 真实相机/真实赛场分布、真实曝光与运动模糊：**UNKNOWN**。
- GPU 近 tie 的跨进程可复现性：仅一次未复现观察，**UNKNOWN**；本轮 primary 已固定 CPU。
- 近阈值样本的 population 估计：仅 7 帧抽样，不是分布统计。
- exploratory final 池只读抽样 24 帧，不是 final 指标、不是 sealed、不是认证。
- 旧 eval_onnx artifact（83925f46）缺失 → 其历史结论不可复现。
- 全仓 pytest 最终复跑为 1058 passed / 0 failed（87.95 s；train 修复其 config 路径断言后）；本任务测试自身 18/18 PASS。

## 11. 使用边界

本报告是 host 端导出/解码一致性证据：证明“ONNX 图与 .pt 数值等价、raw 解码与 ultralytics 后处理在统一预处理下等价、旧 4.67 px 差异来自预处理模式且会翻转判定”。它不证明模型效果达标、不证明 RK3576 可部署、不证明真实相机可用、不构成导航/Gate 验收；final/val 的数字边界仍以对应报告为准。

---

## 12. T29 增量：候选 A（3-seed 选定 seed2/last）三路径对齐

> **状态：** COMPLETED_CANDIDATE_A（host 端三轮径一致性/决策层证据；不是效果认证、不是 sealed final、不是板端/导航验收）
> **来源章节：** T22 stage verification（候选 A 3 seed 选定 seed2/last，val joint 60/95=0.6316）；本文件 §2–§7 的三路径方法；configs/perception/landmark_export_v1.json
> **证据域：** 隔离 .venv/landmark-train；186 帧（real val 48 + old exploratory final 24 只读 + identity 文档 62 + 合成 52；134 帧有 GT）；CPU primary；无板端/实机
> **最后核对：** 2026-11-04

### 12.1 候选模型与选中依据

| 项 | 值 |
| --- | --- |
| 候选 | candidate_A_3seed（T22 阶段验证，v4.1 train 固定快照，seeds 0/1/2，≤60 epoch，仅 val_main 选模） |
| 选定模型 | outputs/landmark_train/runs/stage_verify_v5/seed2/seed2/weights/last.pt；sha256 6b86ef1f…；6403273 bytes |
| 选中依据 | val_main eval_last joint：seed2 **60/95=0.6316**（P1.000/R0.821/ref_cov 0.561/FMR 0.000）；seed0 49/95=0.516；seed1 43/95=0.453；选择规则=val joint 最高→FP 更低→seed 更小 |
| selection evidence | outputs/landmark_train/runs/stage_verify_v5/seed2/bounded_evidence_seed2.json（sha256 cc102be3…；parity evidence 记录其 sha 与 selected_weights_sha256） |
| train 运行 | 55 epoch（early stop at 55，best 35），6.356 s/epoch，349.6 s，AMP，batch16，imgsz640 |
| 限制 | 仅 val_main 选模/阈值；未读 final/holdout；非能力认证 |

### 12.2 导出与验证（真实 CLI，exit 0）

- 命令：scripts/landmark_export_onnx.py --model <candidate>.pt --out outputs/perception/onnx_parity_20261104/t29_candidateA/candidateA_last_opset18.onnx --json-out .../export_evidence.json --overwrite --verify
- ONNX：sha256 **a15b9af9…**，12549686 bytes，opset 18，graph nodes 272，simplify=true，input [1,3,640,640]。
- 数值校验：torch(CPU) vs onnxruntime(CPU) 同一画布 raw max |Δ|=?（export 判定 relative=1.478e-6 通过；atol 判据为 relative）；verdict overall=true。
- 说明：configs/perception/landmark_export_v1.json 的 source_weights_sha256 仍钉 T14 冻结模型（d4ffe49a…）；候选模式通过 --candidate-label 记录 pin 不匹配并改用实际 sha（evidence 的 pt_sha_pin_check.enforced=false，非静默忽略）。

### 12.3 三路径对齐（186 帧，PARITY_PASS）

样本：real val 48 + old exploratory final 24（只读）+ identity 文档 62（全部；ms1_similar 9、ms1_both 26、target_absent 9、occluded 9）+ 合成 52（aspect/edge/multi）；134 帧有 GT；near_threshold 2。运行 223.4 s（CPU，5 路径/帧）。

| 指标 | 值 | 分母/说明 |
| --- | --- | --- |
| self_check | **PASS** | raw_parity + onnx_equivalence(null) + 三对 primary 的 0 翻转门 |
| torch vs onnxruntime raw | max abs **0.020782**；relative **3.247e-5** | 186 帧，通过（≤1e-3 相对） |
| A pt_square vs B onnx_native_square | observation 翻转 **0/186**；joint 翻转 **0/134**；kpt max **8.22e-5 px** | primary |
| A vs C raw_ort_square | 翻转 **0/186**；joint **0/134**；kpt max **8.22e-5 px** | primary |
| B vs C | 翻转 **0/186**；joint **0/134**；kpt **0.0 px** | primary |

### 12.4 决策层矩阵（T29 重点：身份/拒绝/bearing，不止 raw）

三对 primary 的 10 个决策层全部 **0 翻转**（分母 186 帧 / 134 GT）：

| 层 | A vs B | A vs C | B vs C |
| --- | ---: | ---: | ---: |
| presence | 0 | 0 | 0 |
| reference | 0 | 0 | 0 |
| identity_claim | 0 | 0 | 0 |
| identity_gt（identity_correct） | 0 | 0 | 0 |
| false_claim（GT 缺席帧） | 0 | 0 | 0 |
| reject_reason | 0 | 0 | 0 |
| invalid_status（UNKNOWN/REJECTED） | 0 | 0 | 0 |
| bearing | 0 | 0 | 0 |
| bearing_presence | 0 | 0 | 0 |
| joint | 0 | 0 | 0 |

- body bearing：primary 对上 max |Δbearing| = **1.59e-5°**（A↔B/A↔C），B↔C=0.0°；远低于 tau_bearing_deg=0.01° 与消费端 3° 口径。
- identity 统计（每路径相同）：DETECTED 98 / NOT_DETECTED 88；claims 94；wrong_claims（claim 且 identity_correct 非真）**0**；claims_on_absent（GT 缺席帧上仍 claim）**21**。
  - 关键判读：claims_on_absent=21 说明三路径**一致地**在负例上产生 identity claim——这是模型单候选+分数门的行为，**不是路径差异**；“一致”不等于“身份正确”；因此身份能力仍只能 UNKNOWN/appearance-gated，不能因 0 翻转而宣布 identity 达标。
- 拒绝层：三路径 reject_reason/invalid_status 完全一致；边缘截断帧 56、keypoint_unavailable 51 帧的拒绝分布逐路径相同（0 翻转）。

### 12.5 MS1、多候选、近阈值

| 场景 | 帧数 | 三路径分布（完全相同） | 判读 |
| --- | ---: | --- | --- |
| ms1_similar（目标缺席、MS1 相似结构） | 9 | 每路径均 NOT_DETECTED 且 claim=False | 该模型样本内不误报 MS1；不证明身份判别（MS1 训练负例仍缺） |
| ms1_both（目标+MS1 同框） | 26 | DETECTED 且 reason=None 6；DETECTED 且 REFERENCE_UNAVAILABLE 6；NOT_DETECTED 14；每帧 candidate_count=1 | 同框场景未产生第二候选差异 |
| multi_candidate（合成双塔） | 34（含 26 个 ms1_both 打标） | candidates=1 reason=None 7；candidates=1 REFERENCE_UNAVAILABLE 7；candidates=0 17；**candidates=2 且 MULTIPLE_CANDIDATES 3** | 真实出现多候选拒绝的 3 帧在三路径完全一致（拒绝语义不被导出/解码改变） |
| near_threshold（|top score−tau_det|≤0.05） | 2 | 三对 primary status 翻转 0 | 样本少，不作 population 结论 |

### 12.6 旧 legacy 预处理解释（仍成立）

- legacy 对比（pt_default_rect vs onnx_native_default）：joint 翻转 **17/134**；kpt max **7.860 px**；bearing max |Δ| **1.860°**。
- 与 T14 结论一致：legacy 差异来自 .pt rect（640×480）与 .onnx square（640×640）预处理模式；统一画布后 primary 0 翻转。候选 A 也未改变这一归因。
- T14 旧数字（4.67px 关键帧等）不改，见 §4。

### 12.7 结论与边界

- 候选 A（seed2/last）ONNX 导出与 raw 解码在 186 帧上与 .pt/原生 ONNX **10 个决策层全部 0 翻转**；身份 claim/拒绝 reason/bearing 均无路径差异；图/导出/解码一致性 by host-side evidence：**PASS**。
- 这**不**说明候选 A 效果达标、身份可用、板端可部署或导航可用：identity 仍不可认证（MS1/负例/claim-on-absent 21）；RKNN/板端/真实相机 UNKNOWN；final/holdout 未读。
- 与 T22 关系：候选 A 3 seed 阶段验证的选模只来自 val_main；本 T29 结果只是“导出/解码不改变判定”，不改 T22 的阶段门结论。
- 工具扩展：landmark_onnx.py 新增 identity/rejection/bearing 决策层；landmark_onnx_parity.py 新增 identity 文档/MS1/多候选场景、--candidate-label/--selection-json/--tau-bearing-deg/--expected-pt-sha；self_check 增加 10 层 0 翻转门。向后兼容 T14 字段。
- 验证：tests/evaluation/test_landmark_onnx.py **18 passed**（含 venv 端到端集成）；全仓 pytest **1101 passed**（T29 时点，4:29；T14 时点为 1058，历史保留）；scripts/planning/audit_documents.py PASS。
- JSON 合并：docs/reports/perception/onnx_parity_20261104.json 追加 t29_candidate_A 段（T14 顶层字段/数字未改；合并前副本 sha 4cbcabc0… 存于 outputs/perception/onnx_parity_20261104/t29_candidateA/t14_evidence_before_candidateA_merge.json；合并后 sha fd820c1d…）。
- 证据路径：ignored outputs/perception/onnx_parity_20261104/t29_candidateA/{candidateA_last_opset18.onnx, export_evidence.json, parity/evidence.json, parity/parity_detail.json, parity.log}。
