# 地标学习训练前：任务与实验定义（2026-11-04）

> **状态：** PROPOSED（训练前判定契约；不修改合同、不表示模型已训练或达标）
> **来源章节：** V2.2 §7.4/§7.5/§7.7/§7.8/§9.1/§10.1/§13；接口仍为 `configs/perception/landmark_task_interface_proposed_v1.json`（PROPOSED）
> **证据域：** 文档 + 配置 + 后续单元测试/仿真数据（本文件本身不产生能力证据）
> **最后核对：** 2026-11-04

本文件只补齐**训练前必须冻结的语义与判定口径**：类别检测与身份关联的区别、presence / reference / identity / joint 的判定与分母、warmup / 早停 / final 协议、三 seed 选模与一次性 final 规则。方法选型、接口梳理、评价口径勘误已在上一工作包完成（`docs/reports/perception/DSH_LANDMARK_LEARNING_PACKAGE_20261104.md`、`DSH_GEOMETRY_GREEN_ERRATA_20261104.md`），本文件不重复。

**与既有文件的关系：**

- 训练协议部分由 `configs/perception/landmark_training_plan_v2.json` 取代 `landmark_training_plan_v1.json` 的对应内容（v1 保留为历史计划、不再作为执行依据）；
- 数据划分规则仍以 `configs/perception/landmark_data_split_v1.json` 的**分组原则**为准，实际帧清单与 hash 以冻结文件为准；
- 接口/输出字段以 `landmark_task_interface_proposed_v1.json` 为准；本文件不新增合同级字段；
- 标注字段以 `configs/perception/landmark_annotation_spec_v1.json` 为准；本文件规定其**语义判定口径**。

---

## 1. 任务定义：类别检测 ≠ 身份关联

### 1.1 三层证据必须分开记录

| 层 | 含义 | 本轮允许的输出 | 不能推出 |
| --- | --- | --- | --- |
| 类别证据（class） | 画面中存在"塔类结构" | `landmark_class="tower"` + bbox + 分数 | 不能推出是中央塔 |
| 身份证据（identity） | 该结构是已知地标 `RMUC2027_CENTRAL_TOWER_PROPOSED` | `landmark_id=...` **仅当** §1.3 条件满足；否则 `landmark_id=null` + `reject_reason` | 不能由单类输出直接得到 |
| 参考证据（reference） | 塔顶绿灯中心在图像中的位置 | keypoint + `image_bearing=atan2(x-cx0, fx)`；不可见时 `UNAVAILABLE` | 不能推出世界方位/距离/区域 |

- 单类检测器（1 类 `tower`）只提供**类别证据**；把 `class=tower` 直接写成"已识别中央塔"属于把类别当身份，本轮明确禁止。
- 身份关联在本轮是**唯一性假设下的受限能力**，不是已验证的通用地标识别能力；报告必须逐条写明假设与失效条件。

### 1.2 唯一性假设（本轮显式假设，可失效）

| 编号 | 假设 | 依据 | 失效条件 |
| --- | --- | --- | --- |
| U1 | ~~当前合成资产中"塔类结构"至多 1 个实例~~ | 2026-11-04 dev 采集已**证伪**：map probe/实帧发现 map-native 相似结构 MS1（约 (3.0, 4.0)，细长平顶灰柱、侧向绿灯、顶高约 1.78 m） | 已失效 → 身份不能靠"唯一塔实例"；必须多候选拒绝 + 场景/位置先验或显式歧义状态 |
| U2 | ~~中央塔是唯一带绿顶灯结构的塔~~ | 2026-11-04 采集证伪：MS1 也带可见绿灯（西/南侧可见；中央塔在 (11.52, −0.01) 带顶灯架 + 绿顶灯 + R 标识 + 阶梯底座） | 已失效 → 类别 + 绿色 cue 不足以确定身份；identity 评价必须把 MS1 帧作为 HN1 困难负例 |
| U3 | 本轮实验只针对中央塔；其它地标不在范围 | 单地标限定，见上一工作包 | 下游需要多类地标时重新定义 |

**2026-11-04 采集发现（重要更正）**：U1/U2 已被当前资产/实帧证据推翻。中央塔之外存在 map-native 相似结构 MS1（细长平顶柱 + 侧向绿灯），另有 map probe 在 (−3.0, −4.0) 看到的对称候选（外观未确认）。因此：

- 单类 `tower` + 绿色 cue **不能**建立 `landmark_id`；身份必须依赖多候选拒绝（M1/M2）与场景/位置先验，或显式输出 `TARGET_AMBIGUOUS`/`MULTIPLE_CANDIDATES`；
- 任何 identity/joint 评测必须把 MS1 等相似结构帧计入负例分母；没有验证过的相似结构负例时，identity 结论只能标 INCOMPLETE；
- 旧的"唯一性假设下 identity"表述作废（保留在 DECISIONS/报告历史中），新的规范表述以本节为准。

- 三条假设均为**为实验限定的工程假设**，不是规则结论，也不来自 V2.2 已冻结合同；
- U1/U2 失效时，本实验的 identity/joint 结论作废，需重新冻结任务定义与数据；
- 必须在 final 报告中列出"假设成立/被挑战"的实际证据（困难负例帧、多候选帧计数）。

### 1.3 身份关联规则与多候选拒绝条件（PROPOSED）

身份只在以下条件**同时**满足时输出：

1. 类别 `tower` 候选存在且检测分数 ≥ `tau_det`（阈值在验证集冻结，见 §3.3）；
2. 同帧候选数 = 1；若 ≥2，最高分与次高分之差 ≥ `tau_margin`，否则拒绝；
3. 候选的外观/几何先验与中央塔一致（绿色灯区存在，或 bbox 纵横比/尺度在资产先验范围内）；
4. 参考点可见，或按 §2.2 正确声明 `UNAVAILABLE`；
5. 观测记录有效（非 STALE / DUPLICATE / GENERATION_MISMATCH / INVALID_OBSERVATION）。

拒绝原因（沿用 `landmark_task_interface_proposed_v1.json` 词汇）：

| 编号 | 拒绝条件 | reject_reason |
| --- | --- | --- |
| M1 | 同帧多个候选且分数差 < `tau_margin` | MULTIPLE_CANDIDATES |
| M2 | 候选外观/几何与中央塔先验矛盾（疑似相似结构） | TARGET_AMBIGUOUS |
| M3 | 参考点不可见且无法给出 anchor | REFERENCE_UNAVAILABLE |
| M4 | 遮挡/截断超过策略（`visibility=OCCLUDED` 或截断面积超限） | OCCLUDED / TRUNCATED |
| M5 | 观测过期/重复/代际不匹配 | STALE / DUPLICATE / GENERATION_MISMATCH |
| M6 | 无有效标定或无有效图像 | MISSING_CALIBRATION / INVALID_IMAGE |

- `tau_det`、`tau_margin`、截断面积上限均为 **PROPOSED**，必须在验证集上冻结并写进 final 记录；final 后不得调整。
- 拒绝必须显式写出原因，**不得用 0 值或空 bbox 伪装"没有目标"**。

### 1.4 困难负例（hard negatives）清单

困难负例必须同时进入**验证集**（用于冻结阈值）与 **final 池**（用于评测），并分开报告：

| 编号 | 负例类型 | 采集/构造要求 |
| --- | --- | --- |
| HN1 | 相似结构（其它塔/柱/灯架/绿色反光）出现在画面中，中央塔不在视野 | 新增静态或路线视角；不能只看过道背景 |
| HN2 | 中央塔存在但被完全遮挡，画面只剩相似结构 | 遮挡几何/背向视角 |
| HN3 | 中央塔在画面边缘被截断，只有部分塔身 | 偏航/侧向轨迹 |
| HN4 | 远景小目标（绿光灯仅数个像素），不足以给出可靠 anchor | 远距离或高高度 |
| HN5 | 目标不存在（视野内无塔） | 背向/侧向/其它区域 |
| HN6 | 与中央塔同色但非地标的其它光源/纹理 | 需按实际资产核查，不允许臆造 |

- 负例标注：`present=false` + `negative_type`（TARGET_ABSENT / SIMILAR_STRUCTURE / OTHER_LANDMARK / NONE），不得带 bbox/keypoint；
- "没有检测到"不等于"目标不存在"；下游消费者不得把缺席当反证（接口 guardrail 不变）。

### 1.5 观测状态到指标的映射

| 观测状态（沿用 consumer） | presence 作用 | reference 作用 | identity 作用 |
| --- | --- | --- | --- |
| DETECTED + identity 条件满足 | 计 TP | keypoint 或 UNAVAILABLE 判定 | 可计 identity claim |
| DETECTED 但身份拒绝（M1/M2） | 计 TP（类别对） | 视情况计入 reference | 不计 claim；计"拒绝"单列 |
| DETECTED 但参考点不可见（M3/M4） | 计 TP | 计入 UNAVAILABLE 声明 | 可计 claim（若 U1 条件满足） |
| NOT_DETECTED | 计 FN | 不计 | 计 identity miss |
| UNKNOWN（检测器无法判定） | **不计 TP/FN**，单列 | 单列 | 单列 |
| REJECTED（无效观测） | **不计 TP/FN**，单列 | 单列 | 单列 |

规则：UNKNOWN/REJECTED 必须进分母之外的**覆盖率/原因统计**，不得从报告里删除；也不得当作 TN。

---

## 2. 指标定义与分母

通用规则：

- 分母（正例/N_neg/N_avail/N_unavail/identity-evaluable）必须在 final 前由验收集冻结，final 只读不调；
- GT 只能来自**独立标注**（不是检测器输出，也不能用真值位置投影当标签而未标注）；
- 失败不删除；每类 UNKNOWN/REJECTED 原因都要计数；
- 分层报告：normal / 尺度距离 / 偏航侧向 / 遮挡 / 截断 / 目标不存在 / 相似结构；分组只统计，不用于调参；
- 所有比率必须同时给分子/分母；样本不足写 INCOMPLETE。

### 2.1 presence（目标存在检测）

**GT 不可观测规则（先于四格判定）**：GT 目标被完全遮挡（`occluded=true` 且画面内无可见目标像素）或标注判为不可判定（`undecidable=true`）的帧，**不进入 presence/identity/reference 的 TP/FP/FN/TN 四格与分母**，单列为 `GT_UNOBSERVABLE`；否则"正确行为是看不见"会被误判为 FN。统计时与模型侧 UNKNOWN/REJECTED 分开报告。

- 定义：`present_pred` = 存在 `tower` 类别候选且 bbox 与 GT 塔 bbox 的 IoU ≥ `tau_iou`（辅助阈值 0.3，PROPOSED）。
- TP = GT present 且 present_pred；FN = GT present 且非 present_pred 且未被 UNKNOWN/REJECTED 覆盖；FP = GT absent 且 present_pred；TN = GT absent 且非 present_pred。
- 分母：`N_pos` = 全部 GT present 帧；`N_neg` = 全部 GT absent 帧（含 HN1–HN6）。
- 报告：precision = TP/(TP+FP)、recall = TP/(TP+FN)、UNKNOWN/REJECTED 计数与占比（不计入四格）。
- 边界：presence **不要求 identity**；presence TP 不能写成"已识别中央塔"。

### 2.2 reference（参考点可用性与方位）

两个独立分母，不允许合并：

- `N_avail`：GT present 且参考点实际可见（标注 `keypoint.visible=true`）；
- `N_unavail`：GT present 但参考点不可见（标注 `keypoint=null` + `reference_status=UNAVAILABLE`）。

指标：

| 指标 | 定义 | 分母 |
| --- | --- | --- |
| reference coverage | 正确输出 keypoint（像素误差 ≤ `tau_px`）的帧数 | N_avail |
| false-reference rate | 在 N_unavail 上输出 keypoint 的帧数 | N_unavail（应为 0；>0 是语义错误，不只是精度问题） |
| anchor 像素误差 | median / P90 / max 像素距离 | 正确输出 keypoint 且 GT 可见的子集 |
| anchor 图像方位误差 | median / P90 / max（deg），`atan2(x-cx0, fx)` | 同上 |

像素尺度限制（必须写进报告，不能只报角误差）：

- 320×240、90° HFOV → `fx = 160 px`，`cx0 = 160`；**1 px ≈ 0.358°**；
- 绿灯在 320 图像上实测约 4–10 px → 1.43°–3.58°；640 letterbox 后约 8–20 px；
- PROPOSED 门限 median ≤3°、P90 ≤5° 分别约等于 8.4 px、14 px，**粗于绿灯本身尺寸**，因此不得把该门限内的误差解释为亚像素/实物级精度；
- `SHIFT`/`SIM_UPDATE_SAMPLE_TIME` 不是真实曝光时间；anchor 与 bearing 是**图像域**结论，不是世界方位，也不是 ToF/距离。

### 2.3 identity（地标身份关联）

- claim = 观测输出非空 `landmark_id` 且通过 §1.3 条件；
- identity precision = 正确 claim 数 / 全部 claim 数（分母 = claims）；
- identity recall = 正确 claim 数 / N_pos（分母 = 全部正例；miss/UNKNOWN 计入补数）；
- 高置信错误匹配率 = `landmark_id` 错误且分数 ≥ `tau_conf` 的帧数 / N_neg（分母 = 全部负例，含 HN1–HN6）；
- 单地标限制下的诚实表述：FP 只能来自"非中央塔结构被判定为中央塔"，因此**没有相似结构负例就不能声称 identity 已评测**；当前数据/新采集必须覆盖 HN1–HN6 中的可构造类型。
- U1/U2 失效时 identity 指标作废（见 §1.2）。

### 2.4 joint（联合达标）

单帧 joint 成功 = 同时满足：

1. presence 正确（TP）；
2. identity 正确（§2.3）；
3. reference 处理正确：GT 可见时 keypoint 误差 ≤ `tau_px`；GT 不可见时正确声明 `UNAVAILABLE` 且未输出 keypoint；
4. 观测有效（非 UNKNOWN/REJECTED/过期）。

分母必须**三选一并同时报告**，禁止只报一个数：

| 口径 | 定义 | 读法 |
| --- | --- | --- |
| 窄口径（主） | `joint_tp / N_joint_eval`，N_joint_eval = 正例中 GT bbox+reference 完整可判的帧 | 主判定用；分母必须写清 |
| 全正例下界 | `joint_tp / N_pos` | **下界**，不是失败率；未标注参考点的帧不得算失败 |
| 覆盖率 | `N_joint_eval / N_pos` | 说明有多少正例真正可做联合判定 |

- bbox IoU 是**辅助诊断**，分母 = 有 GT bbox 的正例，不进入 joint 主判定；
- 必须报告 joint 的 UNKNOWN/REJECTED 分布与最差条件（如 HN/截断/远景），不得只报总体均值。

### 2.5 指标输出要求（metrics JSON）

final 与验证报告必须输出：每指标分子/分母/比率；四格混淆矩阵；UNKNOWN/REJECTED 原因计数；按条件分层的同口径数值；最差条件；denominator 快照（所有 N_*）；GT 版本与标注 hash；阈值 `tau_det/tau_margin/tau_iou/tau_px/tau_conf` 与冻结来源。样本不足一律标 INCOMPLETE/PROPOSED，不得写 PASS。

---

### 2.6 标注可靠性与标签口径（与标注工作包联动）

盲复标（代理、21 帧 / 33 条旧记录）给出的可复现性与口径事实，直接约束本文件的阈值和分母：

| 事实 | 数值（n） | 对判定的影响 |
| --- | --- | --- |
| 绿灯 keypoint 复标差 | 均值 1.155 px = 0.414°，最大 2.236 px = 0.801°（n=17） | `tau_px` 不得小于标注噪声；PROPOSED `tau_px = 3 px`（约 1.07°），并在 final 前按此冻结 |
| bbox 复标 IoU | 均值 0.649，范围 0.415–0.897（n=18） | 旧框把场地平台框入，系统性高约 37 px；**bbox 口径必须在训练前冻结且不可新旧混用**（见 spec v2） |
| 图像 bearing 差 | 均值 0.180°，最大 0.400°（n=17） | 与 1 px≈0.358° 一致；不得把 0.1° 级残差当作可验证精度 |
| 语义一致率 | present 21/21，reference_status 21/21，visibility 16/21（5 例 PARTIAL/FULL 分歧） | visibility 口径必须显式化（spec v2），否则 presence/joint 分母不可复现 |
| 不可判定率 | 4/21 = 19.0%（参考点不可见 + 相似结构身份歧义） | 不可判定必须单列，不能算作模型失败或负例 |
| 旧参考点与绿色质心 | 中位 0.43 px（n=17，10 帧 ≤0.5 px） | 旧“手工像素”参考点实质是颜色质心；旧 0.036° anchor 残差是**同源循环证据**，不得作为独立精度结论 |

标注协议要求（训练前冻结，写入 spec v2）：

- **bbox 对象范围**：可见目标结构本身（塔体 + 顶部灯架），不含地面/场地平台/阴影；截断帧只覆盖图像内可见部分并置 `truncated=true`；
- **参考点不可见**：`present=true` + `keypoint=null` + `reference_status=UNAVAILABLE` + 显式 `reference_unavailable_reason`；不得用 bbox 中心或猜测坐标代替；
- **不可判定**：`undecidable=true` 单列，默认不进正例，也不计入失败；
- **歧义/多候选**：`ambiguous=true` + 候选列表（bbox/绿点/来源标记）；默认不进正例；
- **训练标签映射（YOLO 1-keypoint）**：keypoint visibility 只用 0/1；参考点不可见时保留 bbox + 占位坐标 + `v=0`；`v=0` 不进入 anchor/coverage 分母；目标缺席用空标签并显式列清单；sidecar 记录 truncated/occluded/ambiguous/reference_status/reference_unavailable_reason；
- **代理局限**：单代理盲复标 ≠ 专家或人工独立审查；要验证方位精度需 ≥2 名独立人工标注 + 仲裁或物理标定（用户/组织决策，不在本轮可补齐范围）。

以上阈值与口径在 §3.1 预注册中与其他哈希一起冻结；任何改动必须重新预注册。

## 3. 训练、选模与 final 协议

### 3.1 预注册（训练前必须冻结）

训练开始前一次性冻结并记录 hash：数据清单与分组、标签文件、`landmark_yolo_pose_v1.yaml`、模型/代码版本、超参（seeds/epochs/batch/imgsz/AMP/patience）、**选模规则**、**阈值冻结方法**、**final 协议与失败判定**、环境 pin。任何一项变更都必须作废本次预注册并重新编号，不能事后改。

### 3.2 warmup 与早停（避免训练初期误停）

| 项目 | 规则 | 状态 |
| --- | --- | --- |
| warmup | 前 `W=15` epochs 为 warmup：照常记录验证指标，但**不早停、不中止、不据此宣布不达标** | PROPOSED |
| 早停起点 | warmup 结束后的第一次评估才启动 patience 计数 | PROPOSED |
| 早停 patience | 20 epochs 无提升（提升口径 = 预注册的验证 joint 窄口径） | PROPOSED |
| 诊断触发（非自动中止） | warmup 后验证 joint < 0.60 连续 3 次评估、或 train/val 差距 >20 个百分点、或验证持续恶化，触发**一次书面诊断审查**并记录结论 | PROPOSED |
| 真正中止条件 | 工程失败（显存/数据损坏/环境不可复现）；标签 QA 失败；发现泄漏；warmup 后验证指标连续 3 次评估下降且低于 0.40；导出/量化不可行（若该轮包含导出） | PROPOSED |

- 明确禁止："训练初期 joint<0.60 就直接停止并写成方法失败"——这既违反 warmup 定义，也混淆了训练未收敛与能力不达标。
- 早停/中止必须记录触发 epoch、验证指标序列、判据和 review 结论。

### 3.3 三 seed 协议（仅验证集比较、选模、冻结阈值）

1. 同一冻结配方训练 seed 0/1/2，三个独立 run；
2. 每个 seed 内部：按验证集 joint 窄口径选 best checkpoint；并列时取验证集 FP 更低者；
3. **跨 seed 比较只用验证集**；选择规则（预注册）：取验证集 joint 最高者，并列取 FP 更低，再并列取 seed 小者；必须同时报告全部 3 seed（含最差），不得只报最好；
4. 在选定 checkpoint 上，用验证集输出分布**冻结阈值**：`tau_conf` 取满足验证 precision ≥0.95 的最小分数（PROPOSED）；`tau_margin`、`tau_px`、`tau_iou` 同法在验证集冻结并写清；
5. 冻结后：阈值、checkpoint、代码、数据清单、预处理参数全部记录 hash，进入 final；
6. 验证集不参与 final，也不得被重标为 final。

### 3.4 一次性 final（不得回调）

- 只对**预先选定**的方案在**已封存 final 池**上执行一次；
- final 前记录：artifact hash、阈值、数据清单/hash、代码 commit、环境、运行命令、开始/结束时间；
- final 只报告，不修改任何东西（包括文档中的门限、阈值、选模规则、数据）；
- final 不达标即判定该配方 FAIL，**不得根据 final 结果回调、重训、换阈值或重跑**；再次评测必须使用新的封存数据并重新预注册；
- final 结论必须写清分母、UNKNOWN/REJECTED、最差条件与像素尺度限制，不得把 final 结果写成"赛场/板端/导航能力"。

### 3.5 泄漏与访问边界（与数据工作包联动）

- final 池图像/标签在 final 前不进入训练/验证/阈值推导；标注者可以查看 final 图像（标注需要），但 final 内容与结果不得用于模型或阈值开发；
- 同一执行者既标注又开发时，只能声称**流程隔离 + hash 承诺**，不得声称第三方独立封存；无法形成可信隔离时如实标记；
- 只凭 sha256 登记不等于 sealed；报告必须说明存储位置、访问者与隔离手段及其局限。

---

## 4. 训练准入门槛（admission）与效果门槛分离

**准入 ≠ 效果，探索启动 ≠ 能力认证。** 本轮（2026-11-04 二阶段）把判定拆成两套：

- **探索实验启动条件（E1–E5）**：决定"能否开始并完成有界内部探索实验"。代理标注、有限样本、缺少 RK3576 板卡只能**限制结论强度**，不作为无条件否决；满足即可开跑，但报告必须写明限制。
- **最终能力认证条件（C1–C8）**：决定"结论能否作为对外/验收级能力"。缺一项就标 INCOMPLETE 或限定为 exploratory，不得写成认证通过。

因此同一轮可以出现"探索实验完成、结果可用，但认证条件 INCOMPLETE"的合法状态；不得因为 C 项未闭合而停止 E 阶段已可执行的工作，也不得用 E 阶段结果冒充 C 认证。

| 编号 | 准入项 | 要求 | 证据来源 | 状态 |
| --- | --- | --- | --- | --- |
| A1 | 许可决策 | 主/备方案的使用与分发许可风险已由用户决策或书面接受；不擅自认定接受 AGPL | 许可证据清单 + 用户决策记录 | 待用户决策 |
| A2 | 数据组独立 | 现有暴露数据可形成独立 train/val 组；无同一轨迹跨组 | dev 划分冻结 + 校验输出 | 见冻结报告 |
| A3 | final 池封存 | ≥3 个新轨迹族、200–400 帧，覆盖 §1.4 条件；分组/清单/标签/hash 冻结 | final 池封存清单 | 见冻结报告 |
| A4 | 标注语义 | 标注规范可表达 presence/visibility/reference/ambiguity；盲复标差异已量化；代理局限已声明 | 标注可用性报告 | 见标注报告 |
| A5 | 版本/硬件/导出证据 | 拟用版本 pin、RTX 5080 与 CUDA 兼容性、自定义 1-keypoint 导出路径有证据或明确 UNKNOWN | 许可与部署证据 | 见证据报告 |
| A6 | 协议预注册 | §3.1 全部内容冻结并有 hash | 本文件 + 训练计划 v2 + 冻结文件 | 待 final 池完成后冻结 |
| A7 | 环境隔离方案 | 隔离训练环境方案确定，不改 Isaac venv | 部署证据 | 见证据报告 |
| A8 | 样本量/统计可行性 | 现有数据足以支撑 ≥3 独立组与可判定的 false-match 分母，或明确报告 INCOMPLETE | 数据冻结报告 | 见冻结报告 |

判定规则：

- **PASS**：A1–A8 全部有可复核证据且无待用户决策项；
- **INCOMPLETE**：存在可由本团队继续补齐的缺口（例如 final 池未标注完、证据不足），不涉及用户决策；
- **BLOCKED**：存在必须由用户决策或外部条件才能解除的项（例如 AGPL 接受与否、商业许可、RK3576 板卡），本轮无法补齐。

---

### 4.1 探索实验启动条件（E1–E5）

| 编号 | 条件 | 状态（2026-11-04） |
| --- | --- | --- |
| E1 | 许可：主候选仅内部有界研究已获用户授权；分发另行决策；不写成许可已解决 | **满足（用户 2026-11-04 授权，记录见训练协议 v2）** |
| E2 | 数据：dev 有可训练标注与 val 标注；exploratory test 有完整标注；允许代理标注但必须披露，不得称专家真值 | 目标：本轮完成（annot/annot2/capture） |
| E3 | 工具链：标签转换、letterbox 逆变换、推理解码、分层评价入口可运行；UNKNOWN/REJECTED 分母审计通过 | 目标：本轮完成（evaltool） |
| E4 | 环境：独立 venv、版本与许可记录、GPU/单关键点 smoke 通过；不改 Isaac venv | 目标：本轮完成（train） |
| E5 | 协议：预注册数据/源码/预算/阈值/种子/final 规则冻结；final 只评一次不回调 | 目标：本轮完成 |

E 阶段允许的结论措辞："内部有界探索实验结果（代理标注、有限样本、仿真域）"；禁止措辞："认证通过""sealed final""板端/导航能力"。

### 4.2 最终能力认证条件（C1–C8）

| 编号 | 条件 | 缺口处理 |
| --- | --- | --- |
| C1 | 许可分发决策（AGPL 接受/商业许可/切换备选）已完成 | 未决 → 认证 INCOMPLETE；不擅自认定 |
| C2 | 独立人工标注（≥2 人）+ 仲裁，或物理标定参考点 | 无 → 只能代理标注/exploratory |
| C3 | 认证级 sealed final：未被模型/阈值开发触碰、独立轨迹族、完整标签 | 无 → 认证 INCOMPLETE；现有 6 族池已降级 exploratory |
| C4 | 分母充足（false-match ≤0.5% 有足够负例；关键条件每层样本足够） | 不足 → 指标 INCOMPLETE，报告分母与不确定性 |
| C5 | RK3576 板端：自定义 1-keypoint RKNN 转换/INT8/延迟/热稳定 | 无板卡 → UNKNOWN，不阻塞主机实验 |
| C6 | 真实相机/真实场地分布（非合成资产） | 缺 → 仿真域结论，不外推 |
| C7 | 跨 session/多次重复稳定性 | 缺 → 单次结果，标 INCOMPLETE |
| C8 | 与 V2.2 合同、规则原文、版本矩阵对齐 | 缺 → 不提升 Gate |

### 4.3 与 A1–A8 的映射

- A1（许可）→ E1 + C1；A2（独立组）→ E2 + C3；A3（final 封存）→ C3；A4（标注语义）→ E2 + C2；A5（版本/GPU/导出）→ E4 + C5；A6（预注册）→ E5；A7（环境隔离）→ E4；A8（样本量）→ C4。
- 本轮执行判定：**E 阶段按上表逐项推进；C 阶段在本轮结束判定（预计 C1–C4、C6–C8 多数 INCOMPLETE，C5 UNKNOWN）**。

## 5. 变更与引用

| 文件 | 关系 |
| --- | --- |
| `configs/perception/landmark_training_plan_v2.json` | 本文件 §3 的机器可读版本；取代 v1 的训练协议 |
| `configs/perception/landmark_data_split_v1.json` | 分组原则不变；实际清单以冻结文件为准 |
| `configs/perception/landmark_annotation_spec_v1.json` | 字段定义不变；本文件规定语义判定 |
| `configs/perception/landmark_task_interface_proposed_v1.json` | 输出词汇来源；本文件不新增合同字段 |
| `configs/perception/landmark_model_selection_v1.json` | 选型结论沿用；主/备切换必须经用户决策 |

- 本轮不安装训练依赖、不下载模型、不启动训练；本文件只冻结判定口径；
- 任何阈值/口径修改必须新编号并说明是否作废既有 final 计划。
