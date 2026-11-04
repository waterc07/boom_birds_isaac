# 地标学习训练前闭环与数据准备：训练准入结论（2026-11-04）

> **状态：** INCOMPLETE（整体准入）；训练启动 **BLOCKED**（A1 许可决策待用户；A3/A4/A6/A8 待补齐）
> **来源章节：** V2.2 §7.4/§7.5/§7.7/§7.8/§9.1/§10.1/§13/§20.9/§20.11.1；上一工作包 `HANDOFF_20261104_DSH_LANDMARK_LEARNING_PACKAGE.md`
> **证据域：** 文档 + 配置 + 单元测试 + 离线数据/标注 QA + 仿真 Isaac GUI 采集（**不是**模型效果、板端、导航或 Gate 验收）
> **最后核对：** 2026-11-04

本文件回答一个问题：**现在能不能按冻结协议开始地标模型训练？** 结论是**不能**。原因分两类：
(1) 需用户决策的许可问题（A1，BLOCKED）；(2) 本轮无法由团队补齐的准入缺口（A3/A4/A6/A8，INCOMPLETE）。
本轮没有安装训练依赖、没有下载模型、没有启动训练、没有修改 Isaac 环境；所有 Isaac 运行均为**可见前台 GUI**。

---

## 0. 结论摘要

| 项 | 结论 |
| --- | --- |
| 任务与实验定义 | **已修正并冻结为 PROPOSED**：类别检测与身份关联分离、唯一性假设 U1–U3、困难负例 HN1–HN6、多候选拒绝 M1–M6、presence/reference/identity/joint 判定与分母、warmup 15 / patience 20 / 诊断触发 vs 真正中止、三 seed 仅验证集选模 + 阈值冻结 + 一次性 final 不回调 |
| 现有暴露数据分组 | **机制上可分离 dev train/val（PASS）**，但 held-out 强度 **INCOMPLETE**（val 仅北走廊 1 条 family、575 帧/566 accepted；E 静态视点簇按保守口径整簇入 train） |
| final 候选池 | **已采集并封存（数据/清单/hash PASS，完整语义标签 INCOMPLETE）**：6 个新轨迹/位姿族、297 RGB / **279 accepted**（200–400 内）、GUI 证据完整、0 帧与既有数据 sha 重合 |
| 标注可用性 | **格式 QA PASS、语义可靠性 INCOMPLETE**：盲复标 21 帧/33 旧记录，bbox IoU 0.649、keypoint 1.155 px（0.414°）、语义不可判定率 19.0%、visibility 5/21 分歧；规范缺口已升 spec v2，并在 final 池 34 帧试点中 **QA PASS 34/34** |
| 许可/版本/部署证据 | **证据完整（PASS）**：AGPL-3.0 原文确证、12 项待决、RKNN-Toolkit2 专有许可新发现、RTX 5080 sm_120/torch 2.7.0+cu128 证据、自定义 1-keypoint ONNX/RKNN 路径 **UNKNOWN** |
| 训练准入判定 | **INCOMPLETE**；其中 **A1 = BLOCKED（待用户）**；**训练不得启动** |

**一句话：** 数据与判定口径已经做到“可执行、可审查”，但许可决策未定、final 池完整语义标签与独立人工标注尚未闭合，因此训练准入不是 PASS。

---

## 1. 现场与边界

- 分支 `feat/v2.2-simulation-perception`；核对 HEAD `43fee3e02de57840e54297e8595924e2f213d722`；开工时工作树干净。
- 本轮**没有**：安装训练依赖、下载模型权重、启动训练、修改 `E:\isaac\env_isaaclab`、headless 运行 Isaac、提升任何 BB22 Gate。
- Isaac 采集 2 次（冒烟 1 集 + 正式 6 集），均为可见前台 GUI（D3D12、RTX 5080、驱动 581.80），窗口截图与日志见 `capture_20261104/`。
- 旧证据/旧冻结/旧报告保持原字节；本文件只登记新结论与更正。

---

## 2. 任务与实验定义的修正（对应任务 1）

完整定义见 `docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md`，机器可读协议见 `configs/perception/landmark_training_plan_v2.json`（取代 v1 的训练协议部分）。要点：

### 2.1 tower 类别检测 ≠ landmark_id 身份关联

- 单类 `tower` 输出只是**类别证据**，不能直接写成“已识别中央塔”；身份需要唯一性假设 + 单候选 + 有效参考点处理同时成立。
- 唯一性假设：U1 当前资产至多 1 个塔类实例；U2 中央塔是唯一带绿顶灯的塔；U3 本轮只针对中央塔。任一失效（资产变更/第二个塔/高相似负例）→ identity/joint 结论作废，需重新冻结任务定义。
- 困难负例 HN1–HN6（相似结构、完全遮挡、边缘截断、远景小目标、目标不存在、同色非地标）必须进入 val 与 final 池；本轮 final 池覆盖了 HN3/HN4/HN5，**HN1 只有旧数据 `static_c` 的约 6×25 px 绿色顶端相似结构证据，HN2 完全遮挡未构造**。
- 多候选拒绝 M1–M6（MULTIPLE_CANDIDATES / TARGET_AMBIGUOUS / REFERENCE_UNAVAILABLE / OCCLUDED·TRUNCATED / STALE·DUPLICATE·GENERATION_MISMATCH / MISSING_CALIBRATION·INVALID_IMAGE），`tau_det/tau_margin` 在 val 上冻结。

### 2.2 四类指标的判定与分母（可执行）

定义已落到代码与测试：`src/boom_birds/evaluation/landmark_metrics.py` + `tests/evaluation/test_landmark_metrics.py`（9 条，先红后绿）。

| 指标 | 判定 | 分母 |
| --- | --- | --- |
| presence | TP/FP/FN/TN（bbox IoU≥`tau_iou` 辅助）；UNKNOWN/REJECTED 不计四格；GT 完全遮挡/不可判定帧单列 `GT_UNOBSERVABLE`，不进分母 | `N_pos`=全部 GT present；`N_neg`=全部 GT absent（含 HN1–HN6） |
| reference | coverage（正确 keypoint 数）、false-reference（GT UNAVAILABLE 上仍输出 keypoint）、像素/方位误差 median·P90·max | `N_avail`（GT 参考点可见）、`N_unavail`（GT 存在但参考点不可见）分开 |
| identity | precision/recall、高置信错误匹配率 | claims / `N_pos` / `N_neg`；无相似结构负例时 identity 不可评测 |
| joint | presence 正确 + identity 正确 + reference 处理正确 + 观测有效 | 窄口径 `N_joint_eval`（GT bbox+reference 完整）；同时报全正例下界 `joint_tp/N_pos` 与覆盖率；未标注参考点**不算失败** |

### 2.3 warmup / 早停 / final

- warmup 15 epochs：**不早停、不中止、不因 joint<0.60 直接判不达标**，只记录验证指标；
- 早停 patience 20（warmup 后起算）；joint<0.60 连续 3 次、train/val gap>20pp、验证持续恶化 → **书面诊断审查**，不是自动中止；
- 真正中止：工程失败/标签 QA 失败/泄漏/验证连续 3 次下降到 0.40 以下/导出不可行；
- 三 seed（0/1/2）各自按 val 选 checkpoint；**跨 seed 比较、最终方案选择、阈值冻结只用 val**；随后对预选方案在 sealed final 池执行**一次** final；final 后不回调、不重跑、不改阈值，失败即判 FAIL。

---

## 3. 数据分组与泄漏核查（对应任务 3）

### 3.1 现有暴露数据实况（比旧清单更严重）

以实际文件只读核查（`scripts/verify_landmark_dataset.py`，证据 `docs/reports/perception/dataset_freeze_20261104/landmark_dataset_verify_20261104.json`）：

- 实际 **13 个 `*_sensor` 目录 / 3002 RGB 帧 / 2909 accepted**；旧 inventory 只列 4 个数据集 / 1702 帧 → **漏列 9 个目录 / 1300 帧**（含 lm_pilot_north、debug_all6、gui_evidence2 等）。
- 3002 帧 / 2940 唯一 sha；31 个重复簇全部是每集 warmup 前 3 帧（accepted=false，同组内），**跨组/跨 split 重复 0**；逐帧 PNG 字节复算 **3002/3002 一致**。
- 旧 `landmark_data_split_v1.json` 声称的划分存在**同走廊 family 泄漏**（geo 北 vs lm 北跨 train/val），且未登记 lm_pilot_north 等目录 → 已由冻结版本修正。

### 3.2 dev 划分冻结（可供未来训练使用）

- `configs/perception/landmark_split_freeze_v1.json`（canonical sha256 `47b535f4…`）：19 组 / 6 family；train 5 组 1290 帧 / val 5 组 605 帧 / test 0 / excluded 9 组 1107 帧。
- `configs/perception/landmark_split_freeze_v2.json`（canonical sha256 `269d9a65…`，**保守版、训练前应采用**）：E 静态视点簇整簇入 train，val 只保留北走廊 family；**train 7 组 1320 帧（1272 accepted） / val 3 组 575 帧（566 accepted） / excluded 9 组 1107 帧（1071 accepted）**。
- 结论：现有数据**可以形成机制互斥的 dev train/val**（组/连续帧/family 校验 0 error）；但 val 仅北走廊 1 条 family、静态视点每 pose 仅 3 accepted 帧 → **held-out 强度 INCOMPLETE**，只能用于 checkpoint 选择，不能当作独立验证结论。
- 历史 `sealed_test` 字段只是历史名字（49/30 帧已被查看复用）；**当前 dev 数据无 sealed 剩余**，hash ≠ sealed。

### 3.3 final 候选池（新采集，sealed test-only）

- 清单：`configs/perception/landmark_final_pool_seal_v1.json`（freeze_sha256 `cedbbc7e…`）；6 个新族 sealed test-only，**297 RGB / 279 accepted**（18 帧 warmup 保留在清单、accepted=false，不入训练/评测）；抽样规则 **N=1 全保留**（非分数选择，>400 的备用固定步长规则已写入）。
- 条件覆盖（独立复算）：距离 1.458–8.367 m；方位 −40°…+25°；右缘截断 26/28 帧（edge）；近距 1.46–1.78 m（green 26–41 px）；远景 ≥7 m 绿光 0–1 px（backoff 30 帧 ≤3px）；目标缺席 41 帧（similar_negative 38 + side_negative 3）；相似结构仅“中央场地结构”，**无已验证的带绿灯相似塔**；**未构造场景结构完全遮挡**。
- 交叉校验：与 dev 全部 **13 目录 / 3002 帧（2940 唯一 sha）** 跨 run 帧 sha 交集 **0**；与 dev freeze（v2）**frame/family/group/dataset root 重叠 0**；池内 0 个跨族重复（6 条组内 warmup 重复均为 accepted=false）。
- 局限：`lmf_edge_0` 起点距 pilot_east_center 0.30 m（yaw 差 34°）、`lmf_similar_negative_0` 距 pilot_east_away 0.54 m（同 yaw 但旧为 dev-only 单点）→ 图像 sha 不同但属最接近暴露数据的族，已登记。
- 试点标注（T6）：按固定 midpoint systematic 规则从 6 族抽 **34 帧**（25 正 / 9 负），参考点可用 21 / 不可用 4（远景 green≤2 px → REFERENCE_TOO_SMALL），截断 10（near 底部 5 + edge 右缘 5），undecidable/ambiguous/occluded 均 0（未虚构）；v2 校验 **PASS 34/34、0 error/0 warning**；标签在 ignored `outputs/perception/landmark_final_annotations_20261104/`，仓库只存清单/hash/overlay。详见 `annotation_verify_20261104/FINAL_POOL_PILOT_ANNOTATION_20261104.md`。
- `MID` 区域只是 case/goal 校验用观测区，**不是** V2.2 区域拓扑，下游不得消费。

### 3.4 访问边界与封存诚实性

- 标注者可以看 test 图（标注需要），但 **test 内容/结果不得用于模型或阈值开发**；final 只跑一次、只报告。
- 只凭 sha256 登记**不等于 sealed**；同一执行者既标注又开发时，只能声称**流程隔离 + hash 承诺**，不能声称第三方独立或盲态证明。
- final 池完整语义标签**尚未生产**（见 §5）；标签文件将放 ignored 外部目录，仓库只存路径+hash+统计。

---

## 4. 标注可用性（对应任务 2）

报告：`docs/reports/perception/annotation_verify_20261104/ANNOTATION_VERIFICATION_20261104.md`；盲标：`blind_pass/annotations_blind.json`（21 帧去重 / 18 正 / 3 负，sha `aeb322cd…`）。

### 4.1 格式 QA 与语义准确性分开

| 检查 | 结果 |
| --- | --- |
| 格式 QA（`validate_landmark_annotations.py`，盲标文件） | **PASS 21/21，0 error / 0 warning** |
| bbox 复标一致性 | IoU 均值 **0.649**，范围 0.415–0.897（n=18）；旧框系统性高约 37 px（把塔下场地平台框入） |
| 绿灯 keypoint 复标差 | 均值 **1.155 px = 0.414°**，最大 2.236 px = 0.801°（n=17） |
| 图像 bearing 差 | 均值 0.180°，最大 0.400°（n=17） |
| 语义一致 | present 21/21；reference_status 21/21；**visibility 16/21**（5 例 PARTIAL/FULL 分歧）；不可判定 4/21 = **19.0%** |

- 像素尺度限制：fx=160、1 px≈0.358°；绿灯 native 4–9 px（640 letterbox 后约 8–18 px）；标注可复现性约 0.4–0.8°，**无法验证旧 0.036°（≈0.1 px）**。
- 循环性发现：旧参考点与纯颜色阈值质心几乎重合（中位 0.43 px，n=17）→ 旧 “manual pixel” 参考点实质等于绿光颜色质心，旧 anchor 残差是**同源循环证据**，不能当独立精度。
- 本报告明确：这是**单代理盲复标**，不是专家或人工独立审查；不代表真实标注员一致性。

### 4.2 pose 标签能否表达“目标存在但参考点不可见”

- **可表达**：真实帧 `test_north_0-follow_only_g3_181` 用 `present=true + visibility=PARTIAL + truncated=true + keypoint=null + reference_status=UNAVAILABLE` 表达且 QA PASS。
- **不可表达**（旧 v1 缺口）：参考点不可见的原因、竞争绿色候选/相似结构位置、“可能但不确定”三态、多候选列表。
- 已据此升 `configs/perception/landmark_annotation_spec_v2.json`（Lead 已评审用于试点）：bbox 对象范围的冻结定义、visibility/truncated 优先级、`reference_unavailable_reason` 枚举、`undecidable` 三态、`candidates[]`、标注来源/独立性字段、像素基准；并明确 YOLO 1-keypoint 映射（v∈{0,1}；参考点不可见→bbox+占位坐标+v=0 且不进 anchor/coverage 分母；absent 空标签显式列清单；ambiguous 默认不进正例；sidecar 记录截断/遮挡/歧义/参考状态）。
- 训练前必须冻结 bbox 口径：**只框可见塔体+灯架（含相连阶梯底座），不含场地平台/地面/阴影**；新旧口径不可混用。

---

## 5. final 池标签状态与访问边界

- 状态：**PILOT_ONLY（34/279）**。seal 中 `annotation_status.full_semantic_labels = NOT_PRODUCED`；本轮只做分层试点标注（T6，34 帧），用于验证 spec v2 可执行性，**不作为完整 test 标签**、不用于任何阈值/训练开发。
- 试点暴露出 3 个需在完整标注前处理的可执行性问题：P1 采集元数据只记左右截断（near 底部截断未进元数据）、P2 参考点可用性缺像素判据（本轮预声明 green_pixels≥3）、P3 “TARGET_ABSENT + 可见但未验证相似结构”缺干净状态 → 应出 **spec v2.1** 后再生产 279 帧完整标签（本轮不改写 v2 字节）。
- 试点标注与完整标注的隔离声明：同一执行者标注与未来开发 → 只有流程隔离 + hash 承诺；不声称第三方独立封存。
- 完整标签生产需要独立的标注工作（用户决定是否投入，见 §8）。

---

## 6. 许可、版本与部署证据（对应任务 4 的“检查证据”部分）

证据：`docs/reports/perception/license_evidence_20261104/LICENSE_AND_EXPORT_EVIDENCE_20261104.md` + JSON（37 条 evidence / 12 条 pending decision）。区分【来源陈述】【项目决策】【未确认解释】。要点：

| 项 | 结论 | 分类 |
| --- | --- | --- |
| Ultralytics v8.2.0 LICENSE | 与 FSF AGPL-3.0 文本逐字节一致（34523 B，sha256 `0d96a4ff…`）；README 为 AGPL-3.0 + Enterprise 双许可 | 【来源陈述】 |
| AGPL §13 / 权重衍生性 / 闭源分发 | 条文已取证，**适用性未决**；不得替用户认定接受 AGPL | 【未确认解释】 |
| `ultralytics==8.2.0` | PyPI 2024-04-17，License 字段 AGPL-3.0，requires torch≥1.8 | 【来源陈述】 |
| 自定义 1-keypoint pose | `kpt_shape` 从 data yaml 读取、代码路径合法；但 17-kpt 预训练头不会迁移，官方无 1-point 示例 → 训练/导出 **PROPOSED/UNKNOWN** | 【来源陈述】+【未确认解释】 |
| YOLOX-Nano | 代码 Apache-2.0 确证；权重与 COCO 条款原文未取得 → **UNKNOWN**；只作备选、**不自动切换** | 【来源陈述】/【未确认解释】 |
| RKNN | Model Zoo 为 Apache-2.0 且存在 `yolov8_pose` RK3576 示例；**RKNN-Toolkit2 实为 Rockchip 专有 RKNN SDK License（新发现）**；官方 75 FPS 只是官方示例基准 | 【来源陈述】 |
| 自定义 1-kpt ONNX/RKNN | `convert.py` 硬编码 COCO 标定与节点名、demo 假定 17 点 → **UNKNOWN（PD-008）** | 【未确认解释】 |
| RTX 5080 | compute capability 12.0（sm_120）；驱动 581.80；torch 2.7.0+cu128 arch list 含 sm_120；官方 cu128 Win cp311 wheel 存在 | 【来源陈述】+本机只读事实 |
| 8.2.0 × torch 2.7 | 无官方兼容声明、未实测（torch.load 默认 weights_only=True）→ **UNKNOWN**；需隔离 venv 最小 smoke（PD-009，本轮未授权未做） | 【未确认解释】 |

既有无证据包有 4 条更正已登记（含“`model_artifacts_found: none`”不准确：仓库有 2 个无关 `.pt`；但“无地标权重/无 .onnx/.rknn”结论仍成立）。

---

## 7. 训练准入逐项判定

| 编号 | 准入项 | 状态 | 依据 |
| --- | --- | --- | --- |
| A1 | 许可决策 | **BLOCKED（需用户）** | AGPL 义务与衍生解释未决；不擅自认定接受，不自动切备选 |
| A2 | 数据组独立 | **PASS（机制）/ held-out INCOMPLETE** | dev freeze v2：0 error；但 val 仅北走廊 1 family、静态视点 3 帧/pose |
| A3 | final 池封存 | **INCOMPLETE** | 分组/清单/hash/帧数 PASS（6 族 279 accepted、0 重叠）；试点 34 帧 v2 标注 PASS；**完整语义标签仍 PENDING（34/279）**、HN1/HN2 未闭合 |
| A4 | 标注语义 | **INCOMPLETE** | spec v2 已升并在 34 帧试点 QA PASS；差异已量化；但仅单代理、无独立人工审查，visibility 5/21 分歧，P1–P3 待 v2.1 |
| A5 | 版本/硬件/导出证据 | **PASS（证据域）** | 版本 pin、AGPL 原文、sm_120/torch、导出路径证据齐；自定义 1-kpt 导出明确 UNKNOWN |
| A6 | 协议预注册 | **INCOMPLETE** | 定义/训练计划 v2/冻结文件已备；final 池完整标签与阈值冻结前置未闭合 |
| A7 | 环境隔离方案 | **PASS（方案）** | 隔离 venv 方案与 pin 已写；本轮未执行（遵约束） |
| A8 | 样本量/统计可行性 | **INCOMPLETE** | 279 帧/6 族满足“数据准备”预算；但 identity 高置信错误匹配率分母不足、无带绿灯相似结构负例 → 不能认证 ≤0.5% |

**整体判定：INCOMPLETE。** 训练启动**不得**进行：A1 是用户决策（BLOCKED），A3/A4/A6/A8 未闭合。即使 A1 解决，也需先完成 final 池完整标注与独立审查/仲裁（或明确接受代理标注的局限并写进 final 记录），才能执行 A6 预注册并开训。

---

## 8. 需要用户决定的最少事项

1. **许可路线（D1）**：主候选 YOLOv8n-pose 采用 AGPL-3.0 路线（内部有界训练/后续分发义务由用户确认），还是购买商业许可，还是切换到 Apache-2.0 的 YOLOX-Nano 备选（不自动切换；备选 anchor 仍为经典阶段）。此项同时决定"许可未决期间是否允许内部有界训练"（PD-004）与后续隔离 venv 兼容性 smoke（PD-009）。
2. **标注与封存的独立性（D2）**：final 池完整语义标注与模型开发是否允许同一执行者完成；若不允许，需要另派标注者；以及是否接受"hash 承诺 + 流程记录"作为封存证据（不是第三方独立封存）。若要方位精度成为独立结论，需投入 **≥2 名独立人工标注 + 仲裁或物理标定**。
3. **原始数据留存（D3）**：279 帧 final 池与 3002 帧 dev 原始包（含 ignored 的 PNG/observations）是否需要在仓库外/远端做**带 hash 备份**，以保证后续可复验；9 个未登记 debug/evidence 目录默认保留原字节且 excluded，是否另行归档。

其余事项（spec v2 细节、dev split 保守版、T6 试点范围、Gaps 的补齐顺序）已由 Lead 在本轮决定并记录，不需要用户裁决。

---

## 9. 尚未完成 / 下一步（不自动开始）

- spec v2.1（P1 四边截断元数据、P2 参考点可用判据、P3 未验证 confuser 表达）→ 再生产 final 池完整语义标签（279 帧）+ 独立审查/仲裁；
- HN1（带绿灯相似结构）与 HN2（完全遮挡）覆盖补充采集；
- 8.2.0×torch 2.7 隔离环境兼容性 smoke、自定义 1-keypoint ONNX 导出与 RKNN 转换（板卡缺失 → UNKNOWN）；
- A6 预注册最终冻结与训练执行（需 A1–A8 闭合后，另行开工/预注册）；
- 任何模型效果、板端、导航、Gate 结论均 **NOT RUN**。

---

## 10. 验证命令与结果（本轮实测）

| 命令 | 结果 |
| --- | --- |
| `E:\isaac\env_isaaclab\Scripts\python.exe -m pytest -q` | 基线 HEAD 811 passed；本轮最终 **872 passed**（含新增 dataset/metrics/annotations v2 回归） |
| `python scripts/planning/audit_documents.py` | **PASS**（exit 0） |
| `python scripts/verify_landmark_dataset.py` | **PASS**，frame_total 3002，0 error |
| `python scripts/verify_landmark_dataset.py`（final 池，`--seal ...`） | **PASS**，0 error（6 组内 warmup 重复为 accepted=false） |
| 采集运行 | 冒烟 1/1 + 正式 6/6 `SUCCESS/ROUTE_COMPLETE`，0 collision/timeout/invalid；`run.complete.json` PASS |
| 文档审计 + git diff 复核 | 提交前执行，见提交记录 |

---

## 11. 证据路径索引

| 内容 | 路径 |
| --- | --- |
| 任务与实验定义 | `docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md` |
| 训练协议 v2 | `configs/perception/landmark_training_plan_v2.json` |
| 指标定义代码/测试 | `src/boom_birds/evaluation/landmark_metrics.py`、`tests/evaluation/test_landmark_metrics.py` |
| dev 划分冻结 v1/v2 | `configs/perception/landmark_split_freeze_v1.json`、`landmark_split_freeze_v2.json` |
| 数据校验工具/证据/报告 | `src/boom_birds/evaluation/landmark_dataset.py`、`scripts/verify_landmark_dataset.py`、`docs/reports/perception/dataset_freeze_20261104/` |
| final 池封存 | `configs/perception/landmark_final_pool_seal_v1.json`、`docs/reports/perception/dataset_freeze_20261104/FINAL_POOL_SEAL_20261104.md` |
| 采集与 GUI 证据 | `configs/scenarios/landmark_final_cases_v1.json`、`docs/reports/perception/capture_20261104/` |
| 标注可用性 | `docs/reports/perception/annotation_verify_20261104/`（含 final 池试点 `FINAL_POOL_PILOT_ANNOTATION_20261104.md`） |
| 标注规范 v2 | `configs/perception/landmark_annotation_spec_v2.json` |
| 许可/部署证据 | `docs/reports/perception/license_evidence_20261104/` |
| 原始采集（ignored） | `outputs/sensor_shadow/lm_final_candidate_20261104{,_sensor}/` |

**边界声明：** 本文所有数值都是**数据准备/格式 QA/仿真采集/证据核查**结果，不构成模型效果、板端、导航或规则合规验收；官方示例（RKNN 75 FPS 等）不是我们的模型指标。

---

## 12. 2026-11-04 二阶段执行更新（探索实验已完成，认证仍 INCOMPLETE）

- **判定拆分**：本文 §4 的 A1–A8 已拆成探索启动条件 E1–E5 与认证条件 C1–C8（见任务定义 §4.1/§4.2）。用户已授权主候选**仅内部有界研究**（分发另行决策），因此 E 阶段全部执行；C 阶段多数仍 INCOMPLETE/UNKNOWN。
- **实际执行**：隔离 venv（torch 2.7.0+cu128 / ultralytics 8.2.0）→ GPU 单关键点 smoke → 小样本过拟合（修正标签 bug 后 PASS）→ ONNX opset18（主机数值一致）→ pilot（3.677 s/epoch）→ **3 seed × 60 epoch 有界训练** → 仅 val 冻结阈值 → **一次性 exploratory final**（279 帧，只读一次）。
- **结果**：val joint 0.484/0.579/0.442（选中 seed1）；final exploratory：presence P1.000/R0.916、reference coverage 0.284、joint 0.298、identity P1.000（池内无已验证 HN1，不作认证）。计划效果门未达到，按不回调规则停止。
- **新证据**：§3.3 的 final 6 族池降级为 exploratory（34 帧试点污染 6/6 族，0 untouched）；采集发现 map-native 绿灯相似结构 MS1 → **U1/U2 唯一性假设证伪**，identity 认证 INCOMPLETE。
- **认证状态**：C1 INCOMPLETE（分发未决）、C2 INCOMPLETE（单代理）、C3 INCOMPLETE（无未触碰 sealed final）、C4 INCOMPLETE（负例分母 41）、C5 UNKNOWN（无板卡）、C6 INCOMPLETE（合成域）、C7 INCOMPLETE（单次）、C8 INCOMPLETE。
- 详细数字、命令、hash 与限制见 [LANDMARK_EXPLORATORY_RESULTS_20261104.md](LANDMARK_EXPLORATORY_RESULTS_20261104.md) 与 [training 报告](training_20261104/TRAINING_20261104.md)。

