# 地标 post-evaluation 诊断：评价定义审计、reference 失败分解与 MS1/TINY 分析（2026-11-04）

> **状态：** POST_EVAL_DIAGNOSIS / INCOMPLETE（只读诊断；TINY 盲标已完成并判定 INCOMPLETE/FAIL；**不是**重跑 final、**不是**能力认证、**不修改**旧 exploratory 结果、不提升任何 Gate）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §7.4/§7.5/§7.7/§9.1/§11.1/§20.2/§20.11；任务定义 LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md（presence/reference/identity/joint 分母）
> **证据域：** 离线分析（旧 exploratory final predictions.jsonl + labels_v1.json + 帧图像 + dev 标签）；无 Isaac 运行、无模型推理重跑、无板端/SITL/HIL/实飞；旧 final 输出保持原字节
> **最后核对：** 2026-11-04

旧结果（presence P1.000/R0.916、reference coverage 62/218=0.284、joint 71/238=0.298、anchor 正确子集 1.95px、bearing 0.30 度）**原样保留**；本文只做新口径分解与诊断，不构成新评价结论，不得用新口径宣布旧实验通过。

**复算一致性：** 模块 src/boom_birds/evaluation/landmark_posteval.py 用同一 landmark_metrics.evaluate_frame/summarize 代码路径重算，并与旧 metrics.json 逐字段比对 **33/33 一致**（presence 218/0/20/41、coverage 62/218、joint 71/238、anchor 分布等全部复现），之后才做分解。同期 evaltool 的 EVAL_DEFINITION_AUDIT_20261104 独立复算的四项分离、119 错误锚点、87 翻转、GT_UNOBSERVABLE 口径与本报告一致（交叉验证）。

---

## 0. 结论先行

1. **旧 joint 是两种能力的和，不是定位率**：joint 71 = 定位成功 62 + “GT 参考不可见且模型正确拒绝”9。joint 分母 238 含 20 个 GT 参考不可见正例；定位精度只能用参考可用分母 218。composite 0.298 ≠ 定位 0.284 ≠ 拒绝 0.450，三者单列。
2. **reference 失败主因不是漏检、不是横向 bearing**：156 个 reference 失败 = 错误锚点 119（76.3%）+ kpt 置信度抑制 28（17.9%）+ 可用参考上漏检 9（5.8%）。119 错误锚点中 88 个纵向主导（|dy|>=|dx|）；错误子集 dy 中位 +2.67px、dx 中位 -0.95px。
3. **3px 2D 判定与水平 bearing 判定大量翻转**：181 个已发射 kpt 中，2D 失败但 bearing<=1.074 度的有 **87**；2D 通过但 bearing 超标 0；<=3 度时 119 个 2D 失败全部 bearing 通过。按 bearing 单轴：<=1.074 度可用 149/218=0.683、<=3 度 181/218=0.830（新诊断口径，不替换旧 3px 0.284）。
4. **失败随尺度非单调，近距大目标与远景小目标两端都差**：TINY 1/15=0.067、SMALL 18/91=0.198、MEDIUM 36/85=0.424、LARGE 7/27=0.259；最差族 lmf_near 3/23=0.130。dev train 中 LARGE 目标=0 → **近距/大目标覆盖缺口 CONFIRMED**（候选 A）。
5. **C1 v=0 占位监督 = SUSPECT；C2 letterbox 对齐 = REJECTED**。28 个抑制帧 kpt 置信度全在 [0.2408,0.4954]（中位 0.3975），9 个“检测到但 GT 参考不可见”帧 <=0.2787；tau_kpt=0.5 是 PROPOSED_NOT_FROZEN、正切在可分区间 → 直接原因是可用性阈值未标定（候选 B），不是 v=0 监督已证因果。
6. **标注同源性已量化**：final 标签 218/218 个参考点与严格绿光最大 4 连通块质心重合（中位 0.022px、P90 0.050px、max 0.071px），218/218 记录 green_pixels 与实测面积完全一致、218/218 最近连通块即最大连通块 → GT 参考与模型 cue **同源**，标签锚点可被严格绿光规则逐帧复现；因此该误差不是独立物理精度，且无法用该 GT 独立验证模型“看绿光”的物理能力。
7. **MS1 preliminary**：map-native 带绿灯柱与中央塔图像线索可区分（细长平顶+侧挂灯+蓝侧条 vs 宽锥塔身+顶灯架+居中绿顶灯+R+阶梯底座）；但单类 tower 输出无身份判别通道，30/30 inner_north val 保存预测只给 1 个候选（只检中央塔），MS1 在保存预测中未被检出 → 风险未验证（identity INCOMPLETE），非已观测误配。
8. **TINY/4-10px 盲复标结果：TINY 标尺不可盲标**。22 帧中 annot 盲标 14 帧 undecidable（63.6%，全 LOW），其中 **12/12 个 9.3-14px TINY 正例全部 undecidable**；预注册 presence 一致率 8/22=0.364（<0.90 FAIL）、bbox IoU 中位 0.434（<0.50 FAIL）、kpt 中位 0.823px/P90 2.159px（PASS，同源绿光）；8 个可判定帧 presence/ref-availability 一致 8/8。→ TINY（9.3-14px）标签只能靠采集投影先验，不是独立可视觉复现的 GT；小绿 cue（3-49px，目标 21-124px）参考点可复现。

---

## 1. 评价定义审计（先定义，后计算）

### 1.1 四项能力分开统计

| 能力 | 分母 | 规则 | 旧报告是否单列 |
| --- | --- | --- | --- |
| presence | 正例 238 / 负例 41 | DETECTED 且 bbox IoU>=tau_iou 为正；NOT_DETECTED/UNKNOWN/REJECTED 在正例上记 FN 且留在分母 | 是（P1.000/R0.916） |
| identity | precision 分母=claims（218）；recall 分母=正例（238） | claim 存在且 landmark_id 与 GT 一致为 correct；负例上高置信 claim 记 false match | 部分：只报 P1.000，未单列 recall 分母与“池内无已验证相似结构负例” |
| reference availability | 可用 218 / 不可用 20 | 可用：发射 kpt 且 <=tau_px 记 correct；不可用：不发射 kpt 记 correct declaration，发射记 false reference | 是（coverage 62/218、false reference 0/20） |
| localization accuracy | **仅参考可用正例 218** | 已发射 kpt 与 GT 参考点 2D 距离 <=tau_px；漏检/无 kpt 留在分母 | 未单列：62/218 被称作 coverage；正确子集 1.95px 是条件统计 |

### 1.2 joint 显式定义（本任务要求）

joint 分母 = GT 可观测正例且 bbox+reference 标签完整（238）。分解与实测：

| joint 分类 | 含义 | 计数 | 是否进定位误差分母 |
| --- | --- | --- | --- |
| LOCALIZED | 参考可用且 kpt 在 tau_px 内 | 62 | 是 |
| CORRECT_REFUSAL | **参考不可见且模型正确不发射 kpt**（joint-ok） | 9 | **否**（也**不**进 reference coverage 分母） |
| FAIL_PRESENCE | 检测失败（9 个可用参考 + 11 个不可用参考） | 20 | 否（在 presence 分母） |
| FAIL_REFERENCE | 可用参考上错误锚点 119 + 置信度抑制 28 | 147 | 是（已在 218 分母） |
| 合计 | | 62+9+20+147=238 | |

**composite joint = 71/238 = 0.298；定位率 = 62/218 = 0.284；正确拒绝率 = 9/20 = 0.450。**

### 1.3 旧口径问题（发现并单列）

1. **joint 分子混入“正确拒绝”**：71 中 9 个是参考不可见且模型正确拒绝；不能与定位成功相加后当作同一能力。
2. **coverage 62/218 与 joint 71/238 分母不同**：reference coverage 分母是参考可用正例；joint 分母还含 20 个参考不可用正例。
3. **旧“无 kpt 37”是混合类**：37 = 28 个“检测到但 kpt 置信度<tau_kpt 被抑制” + 9 个“可用参考上的漏检”（后者已在 presence FN）；把 37 当单一 reference 原因会掩盖 detection miss。
4. **anchor 正确子集 1.95px 是条件统计**：仅 62/181 个已发射 kpt；全部已发射中位 3.72px、错误子集中位 4.54px；条件中位数不能当无条件精度。
5. **identity P1.000 的分母是 218 claims**；identity recall 分母是 238 正例（0.916）；池内无已验证 HN1/相似结构负例，false-match 分母仅 41 → identity INCOMPLETE。
6. **3px 2D 与消费端水平 bearing 不是同一判据**：3px≈1.074 度，但 2D 含纵向误差；见 §2.4。
7. **GT 参考与模型 cue 同源**：reference_source=COLOR_CUE_ASSISTED、independent_of_detector_cue=false；QA 标记 strict green 227 / relaxed green 43 / 邻居插值 6 / 帧中心回退 3（后者 5+3 为 absent 负例，唯一 present 受影响帧 g2_69 已修正）。本次严格绿光重测显示 final 标签 218/218 锚点可被严格规则复现（§2.5）→ 43 relaxed green 未在 final 标签上留下可测偏差，但“同源”使 GT 不能独立验证物理精度。
8. **GT_UNOBSERVABLE 与模型 UNKNOWN 分支本池未覆盖**：GT_UNOBSERVABLE=0、模型 UNKNOWN/REJECTED=0；规则已实现/测试但本池未行使，属 INCOMPLETE 覆盖（val 数据集口径 14 帧由 evaltool 审计单列）。

---

## 2. reference 失败分解

数据：outputs/perception/final_exploratory_eval_20261104/{predictions.jsonl(sha 8cdfe558…),metrics.json(sha a01c08ec…)} 只读 + labels_v1.json（sha 7115ee04…）。279 帧 = 238 正例 + 41 负例；GT_UNOBSERVABLE=0。冻结阈值 tau_det=tau_conf=0.605476、tau_px=3.0、tau_iou=0.3、tau_kpt=0.5（PROPOSED_NOT_FROZEN）。

### 2.1 分组分母与主因

| 阶段 | 计数 | 占参考可用正例 218 | 说明 |
| --- | ---: | ---: | --- |
| 检测到且 kpt 在 3px 内 | 62 | 28.4% | 旧“正确子集” |
| 检测到但锚点 >3px | 119 | 54.6% | 错误锚点 |
| 检测到但 kpt 置信度<0.5 被抑制 | 28 | 12.8% | 置信度抑制（全部检测 TP） |
| 可用参考上漏检 | 9 | 4.1% | presence FN |
| 参考不可用正例（不在 218 内） | 20 | — | 20/20 正确不发射；9 检测到（joint-ok refusal）+11 漏检 |

主因排序：**纵向/锚点误差 119（156 失败的 76.3%）> kpt 置信度抑制 28（17.9%）> 可用参考漏检 9（5.8%）**。

### 2.2 误差分布（px 与 bearing 分开）

| 子集 | n | 2D px 中位 | P90 | max | bearing 中位 | bearing P90 | bearing max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 全部已发射 | 181 | 3.72 | 5.96 | 8.44 | 0.546 度 | 1.188 度 | 2.248 度 |
| 正确子集 | 62 | 1.95 | 2.82 | 2.99 | 0.301 度 | 0.636 度 | 0.874 度 |
| 错误子集 | 119 | 4.54 | 6.51 | 8.44 | 0.712 度 | 1.355 度 | 2.248 度 |

符号偏差（已发射 181）：dx 中位 -0.699（负 121 / 正 60）、dy 中位 **+1.219**（正 111 / 负 70）；错误子集 dx 中位 -0.95、dy 中位 **+2.67**；正确子集 dy 中位 +0.42。错误锚点 88/119 纵向主导（|dy|>=|dx|），31/119 横向主导。

### 2.3 分组（参考可用分母）

| 维度 | 组 | 覆盖 | 备注 |
| --- | --- | ---: | --- |
| 尺度 | TINY（面积<1500） | 1/15=0.067 | 最差尺度；其中 8 帧 kpt 抑制、5 帧漏检 |
| | SMALL | 18/91=0.198 | 主体失败量（53 错误锚点 + 20 抑制） |
| | MEDIUM | 36/85=0.424 | 最好 |
| | LARGE | 7/27=0.259 | 近距大目标失败（16 错误锚点 + 4 漏检） |
| 族 | lmf_near | 3/23=0.130 | **最差族**；错误锚点 dx/dy 混合至 7.6px、kpt 置信度≈1.0 |
| | lmf_backoff | 13/56=0.232 | 远景：16 抑制 + 5 漏检 + 22 错误锚点 |
| | lmf_sweep | 33/111=0.297 | 12 抑制 + 66 错误锚点 |
| | lmf_edge | 13/28=0.464 | 最好（截断但大目标） |
| 截断 | NOT_TRUNCATED | 47/170=0.276 | |
| | TRUNCATED | 15/48=0.312 | 截断不是主因 |
| 可见性 | FULL | 47/170=0.276 | |
| | PARTIAL | 15/48=0.312 | |

族/尺度交互：near（LARGE）与 backoff（TINY 远景）两端都差，MEDIUM 最好 → 失败不单调于尺度，不能用单一“阈值太严”解释。

### 2.4 3px 2D 与 bearing 判定翻转（新诊断口径）

分母 = 181 个已发射 kpt（参考可用正例）。2D 判定 = 距离<=3px；bearing 判定 = |水平 bearing 误差|<=阈值。

| bearing 阈值 | both pass | 2D pass / bearing fail | 2D fail / bearing pass | both fail | 翻转数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.414 度（盲复标噪声 1.155px 等价） | 37 | 25 | 32 | 87 | 57 |
| 1.074 度（3px 等价） | 62 | 0 | **87** | 32 | 87 |
| 3.0 度（旧 geometry/independence PROPOSED） | 62 | 0 | **119** | 0 | 119 |
| 5.0 度 | 62 | 0 | 119 | 0 | 119 |

解读（不宣布通过）：旧 3px 2D 口径把大量“水平方位仍可用、只是纵向小偏差”的帧判失败；按 1.074 度 bearing 口径可用 149/218=0.683，按 3 度 181/218=0.830。旧 3px 结果原样保留。

### 2.5 标注误差 / 坐标变换 / 域差异

- **标注误差（严格绿光重测）**：final 标签 218 个参考点全部命中严格绿光最大 4 连通块质心：距离中位 0.022px、P90 0.050px、max 0.071px；记录 green_pixels 与实测面积 218/218 完全一致；最近连通块=最大连通块 218/218。→ 标签锚点是“同源绿光质心”，不是独立人工像素点；锚点误差下限（相对该 cue）极小，但循环性使其不能作为物理精度证据。
- **坐标变换**：加载器闭环 0.0003px；误差随尺度变化、纵向主导、水平 bearing 几乎全通过；correct 子集 dy 中位 +0.42px vs wrong +2.67px，无统一 dx/dy 偏移 → 无坐标 bug 证据；C2 REJECTED。ONNX 原生 predict kpt 最多 4.67px 差异属 T14 待查风险，不是本次 .pt final 的根因。
- **域差异**：dev train LARGE 目标=0（面积桶 TINY52/SMALL28/MEDIUM25/LARGE0），final LARGE 27 帧覆盖 0.259、near 族 0.130 → 训练分布缺口成立（候选 A）。
- **遮挡**：本池 occluded=0、GT_UNOBSERVABLE=0 → 遮挡类不可评。

### 2.6 C1/C2 根因判断

| 候选 | 判断 | 证据 |
| --- | --- | --- |
| C1 v=0 占位不参与 kpt 监督 | **SUSPECT** | 28 个抑制帧 kpt 置信度 [0.2408,0.4954]（中位 0.3975，25 帧>0.3，13 帧>0.4）；9 个“检测到但 GT 参考不可见”帧 [0.1006,0.2787]（中位 0.1751）；tau_kpt=0.5 是 PROPOSED_NOT_FROZEN 且切在可分区间；正确拒绝 20/20 已工作 → v=0 监督是结构缺口，但不是已证直接原因 |
| C2 预处理 letterbox 对齐 | **REJECTED** | 加载器 0.0003px；误差随尺度变化、纵向主导、bearing 几乎全通过；correct 子集 dy 中位 +0.42px vs wrong +2.67px；不接受“坐标 bug”解释 |

---

## 3. MS1 与中央塔可区分性（仅图像证据）

证据：dev 采集 lm_dev_capture_20261104 的 inner_north / static_negative 帧与既有 zoom；frame_conditions.json（逐帧绿簇/投影）；30 个 inner_north val 保存预测（非 final）；本报告 MS1 测量明细见 MS1_VISUAL_CUES_20261104.json。**世界坐标只用于说明两类结构不同一与选帧，不作为身份判据。**

### 3.1 图像线索

| 线索 | MS1（map-native 柱） | 中央塔 | 可测量性 |
| --- | --- | --- | --- |
| 结构外形 | 细长平顶柱、蓝侧条、顶端模块与柱身同宽 | 宽锥塔身 + 顶灯架 + 白色阶梯底座 + R 标识 | 近/中距可测；<=20px 退化 |
| 绿光位置 | 侧挂式，位于顶端模块侧面 | 顶灯架中央、塔身中轴上方 | 相对顶端模块的水平偏移比可测 |
| 顶端模块 | 与柱身同宽、无外伸顶灯架 | 水平顶灯架明显宽于塔身 | 中距可测 |
| 绿光面积 | 近距 36-72px；远景 11-22px | 4.3m 约 6px；10m 约 1px | 随距离变化，单帧不能判身份 |
| 上下关系 | 顶部平坦，绿光不高出轮廓 | 绿光在顶灯架内，高于塔身 | 近/中距可测 |

图像测量（14 个 MS1 可测帧 + 30 个中央塔近距帧，方法=严格绿光定位+结构轮廓 run-span，启发式未标定）：MS1 顶端模块宽 21-51px（中位 29）、灯偏移比 0.121-0.224（中位 0.152）、绿面积 11-69（中位 22.5）、所在帧 target 距离 10.0-11.9m；中央塔近距帧灯偏移比 0.002-0.159（中位 0.046）、投影顶灯架宽 59-68px（4.9-5.4m）。**灯偏移比单帧上界重叠（0.121 vs 0.159）→ 该线索不能单独作分类器；必须多线索联合/多候选拒绝。** 自动轮廓测量对中央塔被蓝条/纹理打断，aspect 数值不可靠，只作定性。

### 3.2 单类 tower 输出不能无条件映射中央塔 ID 的证据

1. **类别不含身份**：模型输出 landmark_class=tower + 单 kpt；decode 的 appearance_check=NOT_EVALUATED、green probe 未使用；identity_claimed 仅由“单候选+score>=tau_det+margin”决定。地图原生存在 MS1（带绿灯、塔状），类别 tower 对 MS1 与中央塔同样成立。
2. **保存预测 30/30 个 inner_north val 帧 candidate_count=1**（只检出中央塔，未检出 MS1）；这只能说明“该模型在保存帧上没有把 MS1 误报为 tower”，不能证明身份判别：没有任何规则把“这是 MS1”编码进拒绝；MS1 未作为正/负训练样本进入 train（train 仅 6 帧 unverified green_blob confuser，verified 0）。
3. **final 池 38 个 similar_negative 帧全部 NOT_DETECTED、0 FP**：该池条件下未触发误报；但池内 verified HN1=0，不能作身份负例分母。
4. **结论**：U1/U2 已被 MS1 证伪；单类输出下任何单检测只能视为“某塔状结构”，identity 必须显式 UNKNOWN，除非有额外 appearance/多候选/先验证据。当前证据不足以下“会误配 MS1”的结论 → identity INCOMPLETE。

**独立 development 证据（annot2 T19/T16b，对照用，不参与本报告推理）**：62 帧 development identity 标注（labels_identity_dev.json sha 79fd1745…）按图像外观区分：target_alone 9、ms1_alone 9（negative_type=SIMILAR_STRUCTURE + verified MS1 confuser，verified=WORLD_POSE_OR_MAP_DB）、both_* 26（target+MS1 同框，全部可区分）、full_occlusion 9（GT_UNOBSERVABLE）；目标 22-42px 时 62/62 可区分、ambiguous=0。这说明**近/中距存在可用的外观线索**（支持 §3.3 的 PROPOSED 观测量），但 22px 以下（本报告 TINY 盲标 9.3-14px 全 undecidable）线索不可靠；且该批为 agent 代理标注、development，不是认证负例。

### 3.3 建议拒绝规则观测量（PROPOSED，未验证）

1. **多候选 margin**：top1-top2 < tau_margin 时 identity=UNKNOWN（已实现；tau_margin=0.1 PROPOSED、val 0 多候选帧 → 未标定）。
2. **绿 cue 相对几何**：灯偏移比 + 顶端模块/柱身宽度比 + 顶灯架存在性联合先验；超先验即 UNKNOWN。
3. **绿光面积与结构尺寸**：远景绿光<=3px 时不下身份结论，直接 UNKNOWN。
4. **appearance gate 未评估即不声明 identity**：当前 NOT_EVALUATED 仍 claim；建议改为“无 appearance 证据 → landmark_id=null/UNKNOWN”，以召回换 false-match 风险下降。
5. 以上全部 PROPOSED；必须在新数据上预注册验证，不能用本 exploratory 池调参。

---

## 4. TINY / 4-10px 盲复标（已完成，比较由 diag 独立计算）

- 清单（盲版）：docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json（sha256 fc3508de…）；内部 role key：TINY_BLIND_REANNOTATION_KEY_20261104.json（annot 未读）。22 帧，图像 sha 预校验 22/22。annot 盲标文件：docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json（sha256 be08ca8b…，v2.1，22 条，QA PASS 22/22）。比较明细：TINY_BLIND_DISAGREEMENT_20261104.json。
- 样本：12 TINY 正例（bbox max side 9.3-14px；dev 最小 9.3px，4-8px 纯目标在 dev 中不存在 → 该区间 UNKNOWN/外推）+ 6 小绿 cue 正例（green_pixels 3-49，目标 bbox 21-124px）+ 4 absent 对照。抽样池 64/97/64，按 family 轮转确定性选择；只读 development 标签。
- 盲标结果（22 帧）：present 6 / undecidable 14（63.6%，全部 LOW confidence）/ absent 2；keypoint 6；confusers 10（verified=false）；未读原标注/模型预测/旧 final。

| 预注册指标 | 观测 | 分母 | 门限 | 判定 |
| --- | ---: | ---: | ---: | --- |
| presence 一致率（严格，undecidable 不剔除） | 8 | 22 | >=0.90 | **FAIL（0.364）** |
| presence 一致率（仅可判定帧） | 8 | 8 | — | 1.000（但只覆盖 8/22） |
| reference availability 一致率（可判定帧） | 8 | 8 | >=0.90 | PASS（覆盖仅 36.4%） |
| keypoint 欧氏距离 中位 / P90 / max | 0.823 / 2.159 / 2.159 px | 6 | 中位<=2、P90<=4 | **PASS（同源）** |
| bbox IoU 中位 / P90 | 0.434 / 0.668 | 6 | 中位>=0.50 | **FAIL** |
| 截断一致率（可判定帧） | 6/8 | 8 | — | 0.750 |

- 分层：**tiny_positive 12/12 全部 undecidable（presence 严格一致 0/12）**；small_green_cue 6/6 可判定且 presence 一致、HIGH confidence（kpt 0.82px 中位、IoU 0.434）；control_absent 4 帧中 2 可判定且均正确、2 undecidable。
- 解释：9.3-14px TINY 目标在无采集投影先验的盲标下**不可可靠判定 presence/身份**（14/22 不可判定，不能从分母剔除）；原 TINY 标签的 bbox_source=PROJECTION_AID_CALIBRATED 是标签可得的必要条件，属投影助记而非独立视觉标注。小绿 cue 的参考点（green 3-49px，目标较大）可复现（0.82px 同源），但 bbox 仍达不到预注册 0.5 IoU。**TINY annotatability = INCOMPLETE/FAIL（量化下限：presence 严格 0.364、bbox IoU 0.434）**；该结论适用于 9.3-14px dev 标尺，final TINY（bbox 27.8-33.7px）标尺不同，不能直接外推。4-10px 纯目标区间在 development 中不存在 → UNKNOWN。
- 对改进候选 A 的含义：近/中距目标可盲标（6/6 HIGH），TINY 不可 → 数据侧应补近距大目标、避免依赖 <14px 目标作为独立视觉 GT。

---

## 5. 改进候选根因映射（≤2 个）

| 候选 | 对应根因（状态） | 内容（不增大网络/不堆阈值） | 验证方式 |
| --- | --- | --- | --- |
| A. 近距/大目标覆盖补齐 | **CONFIRMED**：dev train LARGE 目标=0，final LARGE 覆盖 7/27=0.259，最差族 lmf_near 3/23=0.130（错误锚点 4.2-7.6px、kpt 置信度≈1.0，非阈值问题） | 补采/标注近距（1.5-2m）大目标 development 帧；或有界尺度增强（box/kpt 同步一致变换） | val-only：新 LARGE 子集 joint/定位覆盖；新 sealed 数据最终评价 |
| B. 参考可用性决策标定/监督 | **CONFIRMED（操作性根因）**：tau_kpt=0.5 抑制 28 个可用参考帧（kpt conf 0.2408-0.4954），而 9 个真不可用帧 <=0.2787；tau_kpt 属 PROPOSED_NOT_FROZEN、从未在 val 标定。C1（v=0 监督）=SUSPECT，可作为实现路线之一，不是已证直接原因 | 在 val 上以“参考可用性”为目标标定 tau_kpt（或显式可用性判据决定是否发射 kpt）；如需训练侧，给 present+reference-unavailable 帧显式“无 kpt”目标（v=0 占位改为显式负目标需新协议） | 仅 val 标定；新 sealed 数据一次评价；不得改旧 final 阈值或重跑 |

不推荐：无依据增大网络、加分割、在未新增数据前堆阈值。C2（letterbox 对齐）不构成候选（REJECTED）。

---

## 6. 证据与文件

| 内容 | 路径/说明 |
| --- | --- |
| 旧 final 预测（只读） | outputs/perception/final_exploratory_eval_20261104/predictions.jsonl（sha 8cdfe558…） |
| 旧 final 指标（只读） | outputs/perception/final_exploratory_eval_20261104/metrics.json（sha a01c08ec…） |
| final exploratory 标签（只读） | outputs/perception/final_exploratory_20261104/labels_v1.json（sha 7115ee04…） |
| dev 标签（只读） | outputs/perception/dev_annotations_20261104/labels_{train,val}.json |
| 诊断模块 | src/boom_birds/evaluation/landmark_posteval.py |
| 模块测试 | tests/evaluation/test_landmark_posteval.py（20 passed；先失败后实现） |
| 正式 diagnostics JSON | docs/reports/perception/posteval_20261104/POSTEVAL_DIAGNOSTICS_20261104.json |
| MS1 图像测量 JSON | docs/reports/perception/posteval_20261104/MS1_VISUAL_CUES_20261104.json |
| TINY 盲复标清单/判据 | docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json |
| TINY role key（annot 不得读） | docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_KEY_20261104.json |
| TINY 盲标分歧 JSON | docs/reports/perception/posteval_20261104/TINY_BLIND_DISAGREEMENT_20261104.json |
| TINY 盲标文件（annot 交付） | docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json（sha be08ca8b…） |
| identity development 标注（annot2，对照） | docs/reports/perception/annotation_verify_20261104/IDENTITY_DEV_ANNOTATION_20261104.md |
| 代表性 overlays（11 张，约 0.54MB） | docs/reports/perception/posteval_20261104/overlays/（worst_anchor/wrong_anchor/no_keypoint/presence_miss/correct_refusal/correct） |
| 可复现脚本 | docs/reports/perception/posteval_20261104/scripts/（inspect_*、prelim_*、make_tiny_plan、measure_ms1） |
| 交叉验证 | docs/reports/perception/EVAL_DEFINITION_AUDIT_20261104.md/.json（evaltool，独立复算） |

复现命令：

    cd E:\isaac\proj_boom_birds
    $env:PYTHONPATH='src'
    E:\isaac\env_isaaclab\Scripts\python.exe src\boom_birds\evaluation\landmark_posteval.py ^
      --labels outputs\perception\final_exploratory_20261104\labels_v1.json ^
      --predictions outputs\perception\final_exploratory_eval_20261104\predictions.jsonl ^
      --old-metrics outputs\perception\final_exploratory_eval_20261104\metrics.json ^
      --images-root . ^
      --out docs\reports\perception\posteval_20261104\POSTEVAL_DIAGNOSTICS_20261104.json ^
      --overlays-dir docs\reports\perception\posteval_20261104\overlays

**验证状态（2026-11-04 20:3x）：**

- 模块测试：pytest -q tests/evaluation/test_landmark_posteval.py → **20 passed**（先失败后实现）。
- 模块复算：reproduction_check **match=True**（33 字段，tolerance 1e-9），即分解前旧数字被完整复现。
- 文档审计：python scripts/planning/audit_documents.py → **PASS**。
- 全仓库 pytest：**1053 passed, 2 failed**；两个失败均在他人并行 WIP 测试（tests/evaluation/test_landmark_dataset.py::test_exposure_registry_v2_downgrades_old_final_to_development、tests/evaluation/test_landmark_train_cli.py::test_shipped_cli_config_is_valid_and_repository_relative），不在本任务写域、与本报告改动无关；**不声称全绿**。

---

## 7. 限制与待补

1. **TINY 盲复标已回**（§4）：结论为 TINY annotatability INCOMPLETE/FAIL；4-8px 纯目标在 development 中不存在 → UNKNOWN；未与外部队列/人工标注复核。
2. **MS1 自动轮廓测量为启发式未标定**：aspect 被蓝条/纹理打断、只有灯偏移比与绿面积可用；不能作分类器，只作线索。
3. **无独立物理精度**：GT 与模型 cue 同源，正确子集 1.95px 不是物理定位精度。
4. **单次、exploratory、非 sealed**：C1–C8 未闭合；本报告不改变认证结论。
5. **GT_UNOBSERVABLE/模型 UNKNOWN 分支本池未行使**；遮挡类不可评。
6. **候选 A/B 尚未验证**：只能 val 预注册 + 新 sealed 数据评价，不得用旧 exploratory 池调参或重跑。

## 8. 不声明

不声明旧实验通过、不声明模型效果达标、不声明 identity 能力、不声明认证/sealed final/板端/导航；不修改旧 final 预测/指标/标签/hash；不重跑旧 final；不据本报告调参或提升 Gate。
