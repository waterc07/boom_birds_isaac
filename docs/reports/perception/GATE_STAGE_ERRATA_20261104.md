# 阶段门执行审计与勘误：候选 A 未进入 3 seed 的原因（2026-11-04）

> **状态：** ERRATA（只追加，不修改旧协议/旧报告/旧结论字节）
> **来源章节：** V2.2 §20.9/§20.11；configs/perception/landmark_improvement_gate_v1.json；landmark_improvement_protocol_v1.json
> **证据域：** 配置/运行记录/报告只读核对；无新模型推理
> **最后核对：** 2026-11-04

本文件审计上一包（提交 3491cde）的阶段门执行，回答“候选 A pilot 为 Δ+0.074 且误匹配/覆盖满足，为何未进入 3 seed”。结论：**这是阶段门误用**——把 holdout 门当时套用到了 3-seed 晋级阶段；旧协议/旧报告不修改，本文件追加勘误，并在本包补完应有的 3-seed 阶段验证。

## 1. 原始配置（冻结值，未被修改）

configs/perception/landmark_improvement_gate_v1.json（sha 7c81ae51…，2026-11-04 先于结果冻结）定义了两级门：

| 阶段 | 条件 | 适用 |
| --- | --- | --- |
| pilot_advance_gate | val joint 相对 matched baseline 提升 ≥ **+0.05 绝对**；identity 高置信误配率不恶化；reference coverage 相对 baseline 下降 ≤0.02 | pilot → 3 seed |
| development_to_holdout_gate | val joint ≥0.60；提升 ≥**+0.08**；FMR≤baseline；coverage ≥0.50；最差组不差于 baseline 0.05 以上 | 3-seed 优胜 → holdout |

## 2. 实际执行记录（只读核对）

- 候选 A pilot（15 ep，seed0，v4.1 train）：joint 43/95=**0.453**；matched baseline pilot joint 36/95=**0.379** → Δ=**+0.0737**（≥+0.05 ✔）。
- identity FMR：A **0/39=0.000** vs baseline 9/39=0.231（不恶化 ✔）。
- reference coverage：A 6/41=0.146 vs baseline 6/41=0.146（下降 0，≤0.02 ✔）。
- 结论：候选 A **满足 pilot_advance_gate，应进入 3-seed 阶段**。

## 3. 为什么没有进入 3 seed（根因）

- 执行时 `landmark_improvement_protocol_v1.json` 的 `budget.promotion_gate` 记录了“lead 2026-11-04 澄清：以 +0.08 且 joint≥0.60 为准”，该门槛并 **不是** gate 文件里的 pilot 门，而是 **development_to_holdout_gate** 的数值（+0.08/joint≥0.60）。
- Lead 在同一日期的指令消息中也以“joint ≥+0.08 绝对、identity 误配不恶化、joint ≥0.60 判是否推进 3 seed”传达 → 把 holdout 门误用为 3-seed 晋级门。
- 后果：候选 A 因 Δ+0.0737<+0.08 且 joint 0.453<0.60 被判 FAIL → STOP；**3-seed 阶段验证从未执行**，holdout 也从未被正式评估（holdout freeze 保持 NOT_TRIGGERED）。
- 该误用没有修改 gate 文件本身，但修改了执行判定口径；属于**执行层阶段门误用**，不是数据或模型结论。

## 4. 三个结论必须分开（更正）

| 结论 | 正确表述 |
| --- | --- |
| pilot 可继续 | **成立**：A 满足 pilot 门，应进入 3 seed；上一包 STOP 在此阶段过强 |
| holdout 未获准 | **成立**：holdout 门（+0.08/joint≥0.60/coverage≥0.50）在 3-seed 结果出来前无法评估，因此不能采集/评价 holdout |
| 路线无效 | **不成立**：上一包只证明了“pilot 阶段按错误口径被拦”；路线有效性需要 3-seed + consumer 协议 + holdout 才能判断，不能用未执行的阶段否定整条路线 |

上一包 LANDMARK_DIAGNOSIS_AND_IMPROVEMENT_RESULTS 中“STOP 本版实验”仍可作为**该次执行记录**保留，但其“路线建议/停止原因”须按本勘误读：应读作“pilot 门误用导致的提前停止”，而不是路线被证伪。

## 5. 相关审计项

### 5.1 训练期间标签漂移

- 事实：v4 训练开始后 labels_val.json 从 163 帧（sha 8c215597…）被并行标注更新为 231 帧（sha 6ade12bd…，含 identity DEVELOPMENT 68 帧），train 首轮 eval 读到中间态且数据集缺图 → joint 0.21/0.27 判 INVALID，弃用；后续用稳定文件 labels_val_validation163.json（sha a9bfda8f…）。
- 风险：依赖 ignored 可变标签文件不能作为唯一复现依据。
- 措施（本包执行）：不可变运行快照——训练/评测启动前、选模前、结束后分别校验数据/标签/spec/protocol sha；任一变化即判该运行 INVALID；快照清单入版本库（configs），可变文件只作数据源。

### 5.2 TINY 结论收敛

- 22 帧盲复标：presence 严格 8/22=0.364、TINY 正例 12/12 undecidable、bbox IoU 中位 0.434。
- 正确表述：**在当前样本与代理标注方法下，9–14 px 目标不可可靠标注**；不是“TINY 目标在物理上不可检测”，也不是“所有小目标均不能评价”。
- 分母规则：保留全域分母；分别报告 GT 不确定（undecidable）、预测拒绝（UNKNOWN/REJECTED）、适用域（可标注帧）三列；**不得删除难例**，不得用只保留可判定帧的方式提高认证结果。

### 5.3 旧结果用途登记

- 旧 exploratory 结果、旧协议、旧预测、旧 hash 全部保留；旧 STOP 结论作为历史执行记录保留，本勘误不覆盖其字节。
- 旧 exploratory 池已登记 DEVELOPMENT_TRAIN（v4.1）与已暴露 development；不得再作 final/sealed。

## 6. 本包更正与执行

1. 按旧协议补完候选 A 的 3-seed 阶段验证（≤60 epoch/seed，仅 val 选模/阈值）；报告每 seed/最差 seed/最差组。
2. 另行预注册 **consumer 协议**（身份+参考点可用+水平 bearing+有效观测）及其独立的 pilot/3-seed/holdout 门，不与旧 3px 协议混用；旧协议按旧门判定，新协议按新门判定。
3. 若 consumer development 门通过 → 连续推进新 holdout（≥3 新族、200–400 帧、采样先冻结、只评一次）；未通过 → 保留失败证据并停止**该版**实验，不把某阶段未完成写成整条架构被证伪。
4. 不再事后修改旧协议/旧报告；本勘误与后续新结论单独成文。

## 7. 本包执行结果（2026-11-04 收尾补记）

- 候选 A 3 seed 阶段验证已完成（stage_verify_v5）：seed0 49/95=0.516、seed1 43/95=0.453、seed2 60/95=**0.632（选定）**；baseline 38/95=0.400。
- 旧 3px 协议 holdout 门：5 项全部 PASS（joint≥0.60、Δ+0.232、FMR 0≤0.180、coverage 0.561≥0.50、worst-group 0.56 vs 0.00）。→ 上一包“A 未进 3 seed”确为阶段门误用；A 在旧协议下是有效改进。
- 消费者协议 holdout 门：FAIL（身份确认通道缺失；strict_unknown 下 consumer 成功=0；appearance gate 在 pipeline 预测框不可迁移；two-class detector NOT RUN）→ 本包 holdout NOT_TRIGGERED。
- 结论三分：pilot 可继续（成立）；holdout 未获准（消费者协议依据成立）；路线无效（不成立，需 two-class 身份通道后再判）。
