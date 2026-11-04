# 地标标注可用性核验：代理盲复标、差异量化与语义 QA（2026-11-04）

> **状态：** PROVISIONAL（代理盲复标与差异量化完成；结论是**代理标注一致性证据**，不是专家/人工独立审查，不是 sealed test 标签，不构成模型、板端或导航验收）
> **来源章节：** `SYSTEM_ARCHITECTURE_V2_2.md` §7.5（地标接力导航）、§7.6（地标歧义与多假设）、§7.7（可见地标输出）、§7.8（目标相对定位）；标注语义依据 `configs/perception/landmark_annotation_spec_v1.json`
> **证据域：** 离线标注 QA（Isaac sensor-shadow 合成 RGB 320×240 exposed 静态帧；agent 代理复标；无模型训练/推理、无板端、无 SITL/实飞、无导航验收）
> **最后核对：** 2026-11-04（仓库 `E:\isaac\proj_boom_birds`，分支 `feat/v2.2-simulation-perception`，起始 HEAD `43fee3e`；以现场文件为准）

## 0. 结论先行

1. **盲复标完成**：对 21 个去重帧（18 正 / 3 负）按 `landmark_annotation_spec_v1.json` 语义独立标注，产出 [blind_pass/annotations_blind.json](blind_pass/annotations_blind.json)（sha256 `aeb322cd…e487d2`）。盲标期间**未打开**旧标签的几何数值，比较阈值先行冻结在 [blind_pass/pre_registration.json](blind_pass/pre_registration.json)。
2. **格式 QA（独立检查）**：用 `scripts/validate_landmark_annotations.py` 对盲标文件运行 → **PASS**，21/21 条，**0 error / 0 warning**，21 张 QA overlay 生成成功（[blind_pass/qa_report.json](blind_pass/qa_report.json)）。这只证明坐标合法与文件自洽，不证明语义正确。
3. **语义准确性（相对旧标）**：present 21/21 一致；reference_status 21/21 一致（归一化旧字符串后）；visibility 16/21 一致；truncated 仅 sample_v1 有该字段，8/12 一致。**实质语义分歧 5 例**（177、static_b 三帧、206），全部是 **visibility / truncated 口径**（帧边截断是否记为 PARTIAL），几何数值本身仍可接受。**不可判定率 4/21 = 19.0%**（1 例参考点不可见 + 3 例相似结构/身份歧义）。
4. **几何一致性**：bbox IoU 均值 **0.649**（中位 0.654，范围 0.415–0.897，n=18）；绿灯 keypoint 像素差均值 **1.155 px = 0.414°**（中位 1.0 px=0.358°，P90 2.034 px=0.729°，最大 2.236 px=**0.801°**，n=17）；图像 bearing |Δ| 均值 **0.180°**、最大 **0.400°**。按预注册分类：一致 5、可接受偏差 7、实质分歧 5、不可判定 4。
5. **重要发现（旧标签参考点来源）**：旧标签的绿灯参考点与一个**纯颜色阈值质心**几乎重合（中位 0.43 px、均值 0.87 px；17 帧中 10 帧 ≤0.50 px，最小 0.10 px）。这说明旧"手工像素标注"的参考点实际上等价于绿光颜色质心；因此既有 `.036°` anchor 残差是"算法 vs 同一绿色来源"的**循环证据**，不能由标注一致性支撑（详见 §7）。
6. **表达力（本次任务重点）**：当前字段组合**可以**表达"目标存在但参考点不可见"——真实帧 `test_north_0-follow_only_g3_181` 用 `present=true + visibility=PARTIAL + truncated=true + keypoint=null + reference_status=UNAVAILABLE` 表达并 QA PASS；但**不能**表达"参考点为何不可见"、"竞争性绿色候选/相似结构的位置"、"可能存在但不确定"三态。static_c 给出真实相似结构反例。建议 spec v2 增补，见 §8。**后续：v2 已起草并经 lead 2026-11-04 审核批准用于 T6 试点（PILOT 冻结，非最终生产冻结），见 §15。**
7. **代理复标边界**：全部标注由**单个 agent** 完成，不是人工独立复标，也不是专家审查；没有第二标注员，因此没有真正的 inter-annotator agreement 统计。数据为已暴露（exposed）的 Isaac 合成单分辨率帧，**不能**作为 sealed test 或真实相机证据，不提升任何 Gate。

## 1. 范围与样本

### 1.1 复标帧集合（21 帧去重）

| 组（family） | 帧数 | 正/负 | 来源 | 说明 |
| --- | ---: | --- | --- | --- |
| `geo_north_test`（g1） | 3 | 3/0 | `outputs/sensor_shadow/geo_test_sensor` | 航向路线末段，177 右缘截断 |
| `geo_static_a`（g2） | 3 | 3/0 | 同上 | 近距正面静态，目标小 |
| `geo_static_b`（g3） | 3 | 3/0 | 同上 | 斜视/边缘静态，底座出画 |
| `geo_static_c`（g4） | 3 | 0/3 | 同上 | 目标缺失位姿（yaw=π），含相似绿色结构 |
| `reverse_south`（g2） | 3 | 3/0 | `outputs/sensor_shadow/lm_independence_sensor` | 反向接近末段，近距大目标 |
| `north`（g3） | 3 | 3/0 | 同上 | 航向末段，181 无绿灯 |
| `static_test_oblique`（g4） | 3 | 3/0 | 同上 | 斜视静态，整齐目标 |
| **合计** | **21** | **18/3** | 两个 sensor_shadow run | 分辨率均 320×240 |

- 21 帧 = `docs/reports/perception/annotation_sample_v1/` 的 12 帧（9 正 + 3 负）∪ 两份旧标签中**带 bbox/reference 的 9 帧**（geo 的 9 个正例与 sample 的 9 个正例**逐字节相同**，sha256 一致），因此统一引用 `outputs/sensor_shadow/` 下的 canonical 原图路径，避免重复计数。
- 原始标签文件中的 `sealed_test` 标记按 `CURRENT_STATUS.md` 口径在本轮视为**已暴露**：盲标文件的 `source.split` 写 `exposed_development`，并保留 `origin_split_in_freeze` 记录来源，避免"重新 sealed"的误读。

### 1.2 参与比较的旧标签记录

| 旧文件 | schema | 本轮匹配记录 | 备注 |
| --- | --- | ---: | --- |
| `configs/perception/geometry_test_labels_v2.json` | `dsh.geometry_test_labels.v2` | 12（9 正 + 3 负） | 无 `truncated/occluded/ambiguous/negative_type` 字段 |
| `configs/perception/landmark_independent_labels_v1.json` | `dsh.landmark_independent_labels.v1` | 9 | 同上，且 `reference_status` 用了非枚举值 |
| `docs/reports/perception/annotation_sample_v1/annotations.json` | `dsh.tower_annotation.v1` | 12（与 geo 的 12 帧重复） | 字段最全，但 `negative_type` 用了非枚举值 |
| **合计** | 3 种 schema | **33 条记录** | 按帧去重后 21 帧 |

## 2. 方法与盲标协议

### 2.1 盲标流程（防泄漏）

1. 只从 `landmark_annotation_spec_v1.json`、`scripts/validate_landmark_annotations.py` 和 `src/boom_birds/evaluation/landmark_annotations.py` 获取字段语义；**未**读取 `annotations.json`、两份 labels 的 bbox/keypoint/参考点数值。
2. 逐帧只看图像（原生 320×240 + 放大视图），按 `present / visibility / truncated / occluded / ambiguous / bbox_xywh / keypoint(x,y,visible) / reference_status / negative_type` 语义独立判断。
3. 用自绘 overlay 反复核对自己的 bbox/keypoint（最多 3 轮，只依据图像，不看旧值），收敛后写死盲标文件。
4. 盲标文件落盘并算 sha 后，才写出 [blind_pass/pre_registration.json](blind_pass/pre_registration.json)（包含分类阈值与 bearing 模型），之后才打开旧标签几何值做比较。

### 2.2 观察辅助（已披露，避免"隐形算法当作人工"）

- 放大视图：3× LANCZOS 全帧 + 原生像素网格；绿色灯区域 16× 最近邻放大 + 5 px 网格刻度（工具脚本见 `blind_pass/protocol/view_helpers.py`、`blind_pass/protocol/crop_grid.py`）。
- 放大窗口的**中心**由一个已披露的纯颜色线索（`g>=90, g-r>=25, g-b>=25`，4 连通）定位；**坐标本身由目视在网格上读取**，不直接采用算法质心。作为敏感性检查，比较脚本同时报告该颜色质心（§7）。
- 未使用任何检测器输出、模板匹配、投影真值或旧标注作为标注依据。

### 2.3 预注册分类阈值（写于打开旧几何值之前）

| 分类 | 判据（预注册，PROPOSED，仅用于本报告） |
| --- | --- |
| 一致 | bbox IoU ≥ 0.70 且 keypoint 差 ≤ 2.0 px（≤0.72°）且语义一致 |
| 可接受偏差 | 0.30 ≤ IoU < 0.70，或 2.0 < keypoint 差 ≤ 4.0 px（0.72–1.43°），语义一致 |
| 实质分歧 | IoU < 0.30，或 keypoint 差 > 4.0 px，或 present/visibility/reference_status/negative_type 语义不一致 |
| 不可判定 | 任一侧参考点不可用（无法算 keypoint 差），或身份被判为歧义，或一侧缺 bbox |

阈值理由：4–8 px 的绿灯核心宽度决定 2 px（约半个灯宽）是合理的独立标注中心差；4 px（≈1.43°）已超过一个灯宽，属不可忽视的标注差；IoU 0.30 沿用 v2 labels 的 `iou_threshold_proposed`，0.70 作为"同一物体框约定一致"的经验线。**注意**：4 px 对应 1.43°，仍远低于下游 PROPOSED 的 5° bearing 门限，因此这些差异首先影响**标注一致性**判断，不等价于下游方位验收失败。

### 2.4 bbox 定义（本报告采用，并记录为口径）

> 可见塔体对象的轴对齐外接框：头部+横臂、锥形塔身、以及随塔体连接的阶梯状底座；在图像边界处裁剪；**不含**周边地面台面/场地平台、地面标线、阴影及无关结构。

这个定义与旧标签口径**不同**：旧框普遍把塔下的场地平台/台面一起框入（见 §5），是本次 bbox 差异的主要来源。

## 3. 格式 QA（与语义准确性严格分开）

### 3.1 盲标文件格式 QA

```powershell
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py `
  --annotations docs/reports/perception/annotation_verify_20261104/blind_pass/annotations_blind.json `
  --root . `
  --overlay-dir docs/reports/perception/annotation_verify_20261104/blind_pass/qa_overlays `
  --output docs/reports/perception/annotation_verify_20261104/blind_pass/qa_report.json
```

| 项目 | 结果 |
| --- | --- |
| 状态 | **PASS** |
| 记录数 | 21（18 正 / 3 负） |
| errors | **0** |
| warnings | **0** |
| QA overlay | 21/21 生成成功 |
| 盲标文件 sha256 | `aeb322cd815ecc03517ec4b6d801d64a1685ef2ba2e53228e9d2a6f6f3e487d2` |
| qa_report sha256 | `7a8796199b5bc0721d203532ed91cb80290649a1830fe7a89fca43bed2418954` |

校验覆盖：image sha/尺寸、schema_version、target.class、bbox 非负且在界内、keypoint 在界内并在框内（±2 px 容差）、正例不得带 negative_type、缺席帧不得带 bbox/keypoint、缺 keypoint 的正例必须 `UNAVAILABLE`、sample 不得声明 `sealed_test`、annotator 非空。**结论：盲标文件在该工具口径下格式自洽（证据域：离线格式检查，样本量 21 帧）；但格式 PASS 不代表语义正确。**

### 3.2 旧标签的格式/口径问题（作为独立发现）

| 问题 | 证据 | 影响 |
| --- | --- | --- |
| 三套 schema 并存 | geo_v2 / ind_v1 / tower_annotation_v1；字段集合不同：geo/ind **没有** `truncated/occluded/ambiguous/negative_type` | 跨文件比较时这些字段"不可比"，本轮按 not_comparable 处理（21 帧） |
| 枚举越界（1） | `landmark_independent_labels_v1` 中 181 帧 `reference_status = "UNAVAILABLE_GREEN_LIGHT_NOT_VISIBLE"`，不在 spec v1 的 `{MANUAL_APPROX, UNAVAILABLE, NOT_APPLICABLE}` 内 | 语义上等价于 `UNAVAILABLE`，但规范不成文且工具会判 warning；本报告比较时做了归一化 |
| 枚举越界（2） | `annotation_sample_v1` 的 3 个负例 `negative_type = "TARGET_ABSENT_HARD_NEGATIVE"`，不在 spec v1 的 `{TARGET_ABSENT, SIMILAR_STRUCTURE, OTHER_LANDMARK, NONE}` 内 | 负例类型无法机器对齐；与本轮盲标的 `SIMILAR_STRUCTURE` 判定冲突（§4.2） |
| bbox 口径未定义 | 见 §5：旧框比盲标框系统性高约 37 px（含场地平台） | bbox IoU 被口径差异拉低；训练标签会继承该口径 |

## 4. 语义准确性（相对旧标，与 §3 格式 QA 分开）

### 4.1 分字段一致率（按帧主记录，21 帧；`landmark_independent_labels_v1` 优先，其余用 geo/sample）

| 字段 | 可比 | 一致 | 不一致 | 不可比 | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| present | 21 | **21** | 0 | 0 | 18 正 + 3 负全部一致 |
| reference_status | 21 | **21** | 0 | 0 | 归一化旧 `UNAVAILABLE_*` 字符串后一致 |
| visibility | 21 | 16 | **5** | 0 | 177、static_b×3、206 |
| truncated | 12 | 8 | **4** | 9 | 仅 sample_v1 有该字段；177、static_b×3 分歧 |
| negative_type | 3 | 0 | **3** | 18 | 仅 sample_v1 负例有该字段；枚举值不兼容 |

### 4.2 语义分歧逐条解释

| 帧 | 字段 | 盲标 | 旧标 | 解释（证据域：图像目视 + 帧边界） |
| --- | --- | --- | --- | --- |
| geo_test_north_0 g1_177 | visibility/truncated | PARTIAL/true | FULL/false | 头部横臂与底座在**右缘被截断**（bbox 触到 x=320），无论"仅塔身"还是"含底座"口径都应记截断；旧标 FULL 属语义遗漏 |
| geo_test_static_b g3_3/4/5 | visibility/truncated | PARTIAL/true | FULL/false | 塔体本体完整，但**连接底座被下缘裁掉**；旧标未记录截断。若旧口径只认"塔身"不认底座，FULL 可自洽——本质是 bbox/对象范围定义分歧 |
| test_reverse_south g2_206 | visibility | FULL | PARTIAL | 盲标把对象限定为塔体+连接底座（完整入画）；旧框把下方场地平台计入并触到帧底（y=240），据此记 PARTIAL。两口径都可自洽，属定义分歧 |
| geo_test_static_c g4_3/4/5 | negative_type | SIMILAR_STRUCTURE | TARGET_ABSENT_HARD_NEGATIVE | 两者都判 present=false；分歧在"负例类型"：画面内确实存在**绿色顶端的相似结构**（见 §8.3），旧值用非枚举字符串。**这 3 帧被判为"不可判定"**（身份/相似结构无法仅凭图像与现有 label 裁定） |

### 4.3 不可判定与处理规则

**不可判定率：4/21 = 19.0%**，其中：

- **1/18 正例（5.6%）参考点不可判定**：`test_north_0 g3_181`——目标存在且可识别，但绿灯在画面内**不可见**（只看到部分头部/横臂与塔身边缘、蓝色灯带），`keypoint=null / reference_status=UNAVAILABLE`；不做猜测，仅参与 bbox 与 presence 统计，不进入 keypoint/bearing 分母。旧标同样 `UNAVAILABLE`（字符串见 §3.2），两侧一致。
- **3/3 负例（static_c）身份不可判定**：present=false 两侧一致，但画面远端存在一个约 6×25 px、顶端带暗绿色（RGB≈137,166,135，仅 1–2 px 达颜色阈值）的锥形结构，以及右侧一个约 20×40 px 深灰柱状结构。它们**不具**中央塔的头部横臂+绿灯特征，方向又与"目标缺失位姿（yaw=π，目标在相机背后）"一致，故判 present=false；但"是否为目标本身/其他地标/相似结构"无法仅凭图像判定 → `ambiguous=true` + `negative_type=SIMILAR_STRUCTURE` + notes 记录坐标。

## 5. 几何一致性

### 5.1 逐帧结果（几何分类 + 语义分类 + 合成分类）

| 帧 | 旧来源 | IoU | keypoint Δ(px) | bearing Δ(°) | bbox 分类 | kp 分类 | 语义 | 合成 |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| geo_north g1_177 | geo_v2 | 0.605 | 1.90 | +0.400 | 可接受 | 一致 | 不一致 | 实质 |
| geo_north g1_182 | geo_v2 | 0.750 | 1.30 | 0.000 | 一致 | 一致 | 一致 | **一致** |
| geo_north g1_188 | geo_v2 | 0.415 | 0.20 | 0.000 | 可接受 | 一致 | 一致 | 可接受 |
| geo_static_a g2_3 | geo_v2 | 0.542 | 1.80 | −0.352 | 可接受 | 一致 | 一致 | 可接受 |
| geo_static_a g2_4 | geo_v2 | 0.536 | 2.24 | −0.352 | 可接受 | 可接受 | 一致 | 可接受 |
| geo_static_a g2_5 | geo_v2 | 0.536 | 2.24 | −0.352 | 可接受 | 可接受 | 一致 | 可接受 |
| geo_static_b g3_3 | geo_v2 | 0.575 | 1.00 | +0.307 | 可接受 | 一致 | 不一致 | 实质 |
| geo_static_b g3_4 | geo_v2 | 0.575 | 1.12 | +0.154 | 可接受 | 一致 | 不一致 | 实质 |
| geo_static_b g3_5 | geo_v2 | 0.575 | 1.00 | 0.000 | 可接受 | 一致 | 不一致 | 实质 |
| reverse_south g2_201 | ind_v1 | 0.897 | 0.81 | +0.026 | 一致 | 一致 | 一致 | **一致** |
| reverse_south g2_206 | ind_v1 | 0.680 | 0.51 | −0.036 | 可接受 | 一致 | 不一致 | 实质 |
| reverse_south g2_212 | ind_v1 | 0.735 | 0.64 | +0.128 | 一致 | 一致 | 一致 | **一致** |
| north g3_181 | ind_v1 | 0.797 | —（不可用） | — | 一致 | 不可判定 | 一致 | 不可判定 |
| north g3_186 | ind_v1 | 0.795 | 1.34 | +0.230 | 一致 | 一致 | 一致 | **一致** |
| north g3_192 | ind_v1 | 0.701 | 1.04 | +0.098 | 一致 | 一致 | 一致 | **一致** |
| static_test_oblique g4_3 | ind_v1 | 0.654 | 0.82 | +0.280 | 可接受 | 一致 | 一致 | 可接受 |
| static_test_oblique g4_4 | ind_v1 | 0.654 | 0.85 | +0.280 | 可接受 | 一致 | 一致 | 可接受 |
| static_test_oblique g4_5 | ind_v1 | 0.654 | 0.82 | −0.070 | 可接受 | 一致 | 一致 | 可接受 |
| geo_static_c g4_3/4/5 | geo_v2 | — | — | — | N/A | N/A | 一致（present=false） | 不可判定（歧义） |

### 5.2 汇总（按帧主记录 n=21；bbox/keypoint 分母各 18/17）

| 指标 | n | mean | median | P90 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bbox IoU | 18 | **0.649** | 0.654 | 0.796 | 0.415 | 0.897 |
| keypoint 像素差 | 17 | **1.155** | 1.000 | 2.034 | 0.200 | 2.236 |
| keypoint 角差（×0.3581°/px） | 17 | **0.414°** | 0.358° | 0.729° | 0.072° | **0.801°** |
| bearing 绝对差 | 17 | **0.180°** | 0.154° | 0.352° | 0.000° | 0.400° |
| bbox 中心 Δx（盲标−旧标） | 18 | +7.56 px | +9.50 | +28.5 | −38.5 | +28.5 |
| bbox 中心 Δy | 18 | −1.19 px | +3.50 | +13.5 | −23.0 | +13.5 |
| bbox 宽差 Δw | 18 | +0.22 px | −2.0 | +19.0 | −31.0 | +33.0 |
| bbox 高差 Δh | 18 | **−35.5 px** | **−37.0** | −24.9 | −75.0 | −4.0 |

分类计数（合成口径）：**一致 5、可接受偏差 7、实质分歧 5、不可判定 4**。其中 bbox 维度 6/12/0/3，keypoint 维度 15/2/0/4（不可判定含 181 与 3 个负例），语义维度 16 一致 / 5 不一致。

### 5.3 偏差原因（对应任务要求逐类说明）

1. **低分辨率/目标小**：`geo_static_a`（bbox 78×75 px，绿灯仅 10–12 px 面积）IoU 0.536–0.542、keypoint 差 1.8–2.24 px；同一静态场景 3 帧旧标参考点恒为 `(140,100)`，而颜色质心在 `(138.7,98.5)` 附近变化 → 小目标下 1–2 px 级中心差不可避免。
2. **截断**：177、static_b、201 的 bbox 在帧边被裁剪，双方对"裁到哪、是否计入底座"选择不同，IoU 0.575–0.605；其中 201 反而 IoU 0.897（旧框也贴边裁剪且口径接近）。
3. **对象范围/口径**：旧框高度系统性大于盲标（中位 −37 px），旧框包含塔下场地平台，是 IoU 均值仅 0.649 的**主因**；宽度几乎一致（中位 −2 px）。
4. **旧框错位**：188 帧旧 bbox `[165,35,155,205]` 相对塔体（盲标 `[125,51,158,130]`）整体右移约 38 px，IoU 0.415；用旧框中心与旧参考点算的图像 bearing 差达 **18.2°**（n=17 中最大）。这说明旧 bbox 标注本身存在对齐误差，"bbox 中心方位"不能当物理参考（与既有勘误一致）。
5. **遮挡**：本批帧**没有**真实遮挡样本（无物体挡住塔身），"遮挡"类原因本轮 **NOT EXERCISED / TBD**，不能从本报告推断遮挡标注一致性。
6. **相似结构**：static_c 有绿色顶端相似结构与深灰柱状结构，导致负例身份不可判定（见 §4.3），不影响其余帧几何。
7. **blur/软边缘**：static_b 底座与地面亮度接近，边缘不确定度约 ±3 px，但 keypoint 仍 1.0–1.1 px。

## 6. 像素尺度与分辨率限制

- 相机模型：320×240、`fx=160`、`cx=160`（与 `dsh_geometry_green_errata` 一致）；**1 px ≈ atan(1/160) = 0.3581°**（光轴处）。
- 绿灯实测尺寸（n=18 正例，颜色阈值最大连通域）：**宽度 4–9 px、高度 3–7 px、面积 10–49 px**。若 letterbox 到 640 输入（2×），对应 **8–18 px 宽、6–14 px 高**。
  - 训练计划中"green light 4–10 px 在 640 输入下是否可分"的措辞存在**像素基准歧义**：按本轮 native 测量，4–10 px 对应 320 原始分辨率；在 640 输入下应是约 8–18 px。建议在 spec/训练计划中显式写明分辨率基准（spec v2 建议项）。
- 由尺度反推：keypoint 标注的分辨率极限约 **1 px = 0.358°**，独立复标的实测差均值 **0.414°**、最大 **0.801°**；因此：
  - 既有 `.036°` anchor 残差 ≈ **0.1 px**，**低于标注可复现性约 4–20 倍**，不能由任何标注一致性证据支撑（进一步见 §7）；
  - 若下游要验证 ≤1° 级方位，必须依赖物理标定/更高分辨率/亚像素方法，而不是本数据上的手工标注。
- bbox 面积范围 5,850–39,060 px²（宽 78–210 px、高 75–186 px）：近距大目标几何更稳（reverse/north IoU 0.70–0.90），小目标（static_a）最不稳。

## 7. 旧标签参考点来源与"循环证据"发现

对 17 个有参考点的旧记录，用**同一纯颜色规则**（`g>=90, g-r>=25, g-b>=25`，最大连通域）算质心，与旧参考点比较：

| 分组 | 帧数 | 距离范围 | 观察 |
| --- | ---: | --- | --- |
| route 177/182/188/201/206/212、static_b×3、north 186/192、oblique×3 | 14 | 0.10–2.64 px | 其中 **10 帧 ≤0.50 px**（177=**0.10**、188=**0.13**、186=**0.14**、192=0.20、201=0.21、206=0.26、212=0.28 px） |
| static_a×3 | 3 | 1.83–2.64 px | 旧标 3 帧都用同一 `(140,100)`，而颜色质心小幅变化 |
| 合计 | 17 | 均值 **0.87 px**、中位 **0.43 px**、最大 2.64 px | 与绿灯自身 4–9 px 宽相比，这在 1 px 量级内 |

结论（证据域：离线数值比对，n=17）：
1. 旧标签的"manual pixel inspection / MANUAL_APPROX"参考点**实质等价于绿光颜色质心**（或来自同一绿色 cue 的锚点）；
2. 因此旧报告 `.036°` 的 anchor 残差是"算法 anchor vs 同一绿色来源的标签"，**循环**，不能当作独立物理精度证据；`DSH_GEOMETRY_GREEN_ERRATA` 已指出该点，本轮给出了逐帧数值支撑；
3. 本轮 keypoint "一致性"高，主要说明**颜色质心可复现**，不说明人工语义判断一致性；也无法证明标注与绿色检测器相互独立；
4. 规范建议：标注文件应记录参考点来源（manual / colour-centroid / projection-aid / template-anchor），否则无法区分独立标注与循环验证（spec v2 建议项）。

## 8. 表达力检查：pose/1-keypoint 标签能否表达"目标存在但参考点不可见"

### 8.1 真实帧证据

| 场景 | 真实帧 | 盲标字段组合 | 能否表达（当前 spec v1） |
| --- | --- | --- | --- |
| 目标存在、参考点不可见 | `test_north_0-follow_only_g3_181.png`（右缘截断、只见部分头/臂与塔身边缘，无绿灯）；同帧旧证据图 [occluded_unavailable_ref.png](../evidence_20261103_independent_landmark/occluded_unavailable_ref.png) | `present=true`、`visibility=PARTIAL`、`truncated=true`、`occluded=false`、`bbox=[247,60,73,140]`、`keypoint=null`、`reference_status=UNAVAILABLE` | **能**（QA PASS）。可表达"存在但无参考点"，且不猜测关键点 |
| 目标存在、参考点可见、但帧边截断 | 177、201 | `present=true`、`visibility=PARTIAL`、`truncated=true`、bbox 裁剪、keypoint 正常 | **能** |
| 目标不在画面、存在相似绿色结构 | `geo_static_c` 3 帧 | `present=false`、`visibility=ABSENT`、`ambiguous=true`、`negative_type=SIMILAR_STRUCTURE` + notes 记录相似结构坐标 | **部分能**：可标"缺席+歧义/相似结构"，但**无法记录竞争候选的位置/类别/数量** |
| 目标被其他物体遮挡 | 本批无 | — | **NOT EXERCISED（TBD）**：字段上可用 `occluded=true / visibility=OCCLUDED / keypoint=null / UNAVAILABLE`，但没有真实帧验证，属于未测 |
| 目标部分遮挡 | 本批无 | — | **NOT EXERCISED（TBD）** |
| 多候选（两个同样像塔的结构） | 本批无（仅 static_c 的单相似结构） | — | **无法充分表达**：`ambiguous=true` 只是布尔，无候选列表；§7.6 要求的"多假设"无法从该 schema 传给下游 |

### 8.2 歧义样本处理规则（建议写入 spec v2）

1. 任何身份未定的帧：`ambiguous=true`，**禁止**输出"最像的那个" keypoint；present 的判断必须给理由（notes）。
2. 存在 ≥2 个同等可能候选：`ambiguous=true` 且新增 `candidates[]`（每项 bbox+keypoint+身份置信）；该帧**不进** identity-positive 训练/评估分母，只作为困难样本或显式负例。
3. 目标缺席但画面含任何绿色光候选：`negative_type=SIMILAR_STRUCTURE`，并记录候选位置（否则以绿色为 seed 的检测器在此帧的 FP 无法被计账）。
4. 目标存在但参考点不可见：`present=true`、`keypoint=null`、`reference_status=UNAVAILABLE`，并新增 `reference_unavailable_reason`（`OUT_OF_FRAME | OCCLUDED_BY_OBJECT | FACING_AWAY | TOO_SMALL | NOT_RENDERED`）；没有原因时不得猜测。
5. 截断：`truncated=true` + `visibility=PARTIAL`（帧边裁切导致对象不完整），与 `occluded=true`（物体遮挡）分开记；若两者同时成立，按"遮挡优先、截断另记"处理。
6. 同一物理轨迹连续帧必须同组，同组帧的歧义判定应保持一致（避免相邻帧 label 抖动）。

### 8.3 发现的规范缺口（spec v1 → v2 建议）

> **状态：** 下列缺口已落成 spec v2（`configs/perception/landmark_annotation_spec_v2.json`，sha256 `b0b7dae6…72f749`）；lead 2026-11-04 审核批准用于 T6 试点（PILOT 冻结，非最终生产冻结）。字段与规则见 §15。

lead 批准时补充的分母规则（v2 `quality_gate.denominator_rules`）：**GT 完全遮挡或 undecidable 的帧不进入检测 TP/FP/FN/TN 四格，单列 `GT_UNOBSERVABLE`（与模型侧 UNKNOWN 分开），presence/joint 报告必须显示该计数**；T6 试点只允许 `AGENT_PROXY + SELF_CHECKED`，不得写成 HUMAN_REVIEWED/ADJUDICATED。

| # | 缺口 | 证据 | 建议 |
| --- | --- | --- | --- |
| G1 | bbox 对象范围未定义（塔身 vs 含底座 vs 含场地平台） | 旧 vs 盲标高差中位 −37 px；IoU 0.415–0.897 | 定义唯一范围；新增 `bbox_extent` 枚举；训练标签必须同口径 |
| G2 | visibility 与 truncated/occluded 语义重叠 | 5 例 visibility 分歧全部源于截断口径；旧 schema 无 truncated 字段 | 明确三者关系与优先级；visibility 只描述遮挡，截断单独记 |
| G3 | 无"参考点为何不可用"字段 | n181/occluded_unavailable_ref 真实帧 | 新增 `reference_unavailable_reason`（枚举） |
| G4 | `present` 只有布尔，无"可能/不确定"三态 | static_c 相似结构 | 新增 `present=UNKNOWN` 或 `presence_confidence` 枚举 |
| G5 | 无竞争候选/相似结构位置字段 | static_c 有绿色顶端相似结构 | 新增 `candidates[]`（bbox+keypoint+类型），供 §7.6 多假设与 FP 计账 |
| G6 | `negative_type` 枚举与旧文件不一致 | sample_v1 用 `TARGET_ABSENT_HARD_NEGATIVE` | 升版时统一枚举并强校验；旧文件保留原字节 |
| G7 | `reference_status` 枚举被旧文件突破 | ind_v1 用 `UNAVAILABLE_GREEN_LIGHT_NOT_VISIBLE` | 工具对非枚举值应 error 而非仅 warning |
| G8 | 无标注来源/独立性字段 | 旧参考点=颜色质心（§7） | 新增 `reference_source`（manual / colour-centroid / projection-aid / template-anchor），禁止把 aid 当独立真值 |
| G9 | 截断时 bbox 裁剪/外推规则未写 | 177/sb/201 | 明确"bbox 在帧边裁剪，不外推" |
| G10 | 像素尺度基准未写清（native vs 640 输入） | §6 的 4–10 px 歧义 | spec 与训练计划显式写分辨率与 letterbox 变换记录 |

## 9. 对 YOLO 1-keypoint 训练标签映射的明确建议

**前提**：主候选仍是 YOLOv8n-pose（1 类 `tower` + 1 keypoint `green_roof_light_center`，kpt_shape `[1,3]`），标签由本规范的人工/代理标注导出，**导出必须显式、可逆**并保留来源像素坐标。

### 9.1 映射规则（source 320×240 → letterbox 640，scale=2、pad_y=80）

| 标注状态 | YOLO 标签 | 建议 |
| --- | --- | --- |
| present=true 且参考点可见 | bbox + `(kx*2, ky*2+80, v=1)` | v=1；bbox 同变换；记录 scale/pad |
| present=true 且参考点不可见（n181 类） | bbox + `(x_placeholder, y_placeholder, v=0)` | **v=0**；坐标用占位（建议 bbox 中心）并在数据集 README/元数据写明"非参考估计"；v=0 样本**不进** anchor/bearing 评估分母，也不作为关键点回归目标 |
| present=false（负例） | 空标签文件（无 bbox） | 必须显式列入图像清单/清单哈希，不允许静默丢弃；negative_type 记在 sidecar |
| ambiguous=true | **默认不进** positive 训练集 | 或列为单独困难集；禁止用"最像候选"的 keypoint 训练 |
| truncated=true | bbox 在帧边裁剪 + v 按可见性 | YOLO 标签无法表达 truncated → sidecar JSON 记录，用于分层报告 |

补充约束：
1. **v 取值只用 0/1**：本数据无法可靠区分"visible / occluded / out-of-frame"，用 v=2 会造成伪精度。
2. **不得把 bbox 中心写进 v=1**：spec 明确"bbox center is not the reference point"；本轮实测旧 bbox 中心与旧参考点的 bearing 差均值 3.4°、最大 18.2°，若混用会引入 >5° 级系统误差。
3. **keypoint 覆盖率分母必须定义**为 `present=true 且 reference_status=MANUAL_APPROX` 的帧（本批为 17/18 可评估；n181 不计入），否则会把"参考点不可见"误算成模型漏检。
4. **sidecar 元数据**（按图像 basename 键）：`present/visibility/truncated/occluded/ambiguous/reference_status/reference_source/negative_type/group_id`；YOLO 标签本身丢语义，报告分层与 FP 归因依赖 sidecar。
5. **bbox 口径必须先冻结**：若训练沿用旧标签（含场地平台），模型会学到"塔+平台"框；若改用本报告口径（仅塔体+连接底座），必须整批重导，不能混用。spec v2 已定义口径，导出器 `yolo_pose_target()` 已实现并有单测（§15）。
6. **letterbox/翻转可逆性**：使用 `src/boom_birds/evaluation/landmark_annotations.py` 的 `letterbox_annotation` / `hflip_annotation` / `roundtrip_letterbox`（既有测试通过），导出时把 scale/pad 写入 manifest。
7. **negatives 与歧义帧的划分**：建议把 static_c（相似结构负例）保留在评估集并单独报告 FP，不并入普通负例平均值。

## 10. 局限与不可声称

- **代理复标**：单 agent 独立复标，非专家、非人工独立审查，无第二标注员、无仲裁；本报告的"一致性/分歧"是**代理自洽性检查**，不是标注员间一致性（IAA）统计，不能外推为人工标注质量。
- **数据边界**：21 帧暴露数据、单一 320×240/fx=160 合成相机、7 个 family、来自 2 个 sensor_shadow run；不含真实 OV9782 图像、不含真实遮挡帧、不含夜间/运动模糊/反光等真实退化；**不能**作为 sealed test、真实相机或导航证据。
- **语义不可完全核验**：static_c 的身份歧义（绿色顶端相似结构）无法仅凭本批数据裁定；真实遮挡场景未测（TBD）。
- **坐标精度**：盲标目视读数不确定度约 ±1.5 px（bbox ±3 px）；bbox 口径本身是判断项，不是客观量。
- **不声称**：不声称旧标签"错误"（除 177 截断缺失可判定为语义遗漏外，其余分歧多为口径差异）；不声称模型效果、板端、导航、Gate 达标；不声称 0.036° 类亚度精度可被标注验证。
- 本轮未启动 Isaac、未改 `outputs/` 原始帧、未安装依赖、未训练、未 commit/push。

## 11. 证据清单

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| [blind_pass/annotations_blind.json](blind_pass/annotations_blind.json) | 盲标主文件（21 帧，spec v1 schema） | `aeb322cd815ecc03517ec4b6d801d64a1685ef2ba2e53228e9d2a6f6f3e487d2` |
| [blind_pass/pre_registration.json](blind_pass/pre_registration.json) | 分类阈值预注册（打开旧几何值之前） | `1c7fb4ce84e503e48aceb469dcb1113b5495e28d86628754d384f9773a842313` |
| [blind_pass/qa_report.json](blind_pass/qa_report.json) | 格式 QA 结果（PASS 21/21） | `7a8796199b5bc0721d203532ed91cb80290649a1830fe7a89fca43bed2418954` |
| [blind_pass/qa_overlays/](blind_pass/qa_overlays/) | 校验工具生成的 21 张 overlay | 见 qa_report |
| [blind_pass/overlays/](blind_pass/overlays/) | 盲标 bbox+keypoint 可视化（2×，21 张） | 逐帧见文件 |
| [annotation_verification_20261104.json](annotation_verification_20261104.json) | 逐帧/逐记录完整比较（33 条旧记录，含颜色质心敏感性） | `05517137d98a5f043ab716607e87c7f6b1509fc46ff325d8e573da72b8ea7f21` |
| [compare_overlays/](compare_overlays/) | 盲标（红）vs 旧标（蓝）叠加对比（21 张） | 逐帧见文件 |
| [blind_pass/protocol/decisions_final.json](blind_pass/protocol/decisions_final.json) | 盲标决策表（最终） | `b6e8ca63b1b34d2899c8d0fd40b270e6cf8812898bb66708da570954df78e62c` |
| [blind_pass/evidence/](blind_pass/evidence/) | 关键灯位/边界/相似结构放大证据（8 张 + README 说明） | 逐文件 |
| `configs/perception/landmark_annotation_spec_v2.json` | v2 规范（lead 2026-11-04 批准，T6 PILOT 冻结） | `b0b7dae6300086fbcdc6bdf08033f8abd47381695e3d12a900f313a93372f749` |
| [blind_pass/protocol/v2_example_annotations.json](blind_pass/protocol/v2_example_annotations.json) | v2 校验示例（3 帧真实帧：FULL+可见参考点 / PARTIAL+UNAVAILABLE / ABSENT+相似结构候选） | `b7a8d2b4e118271d0b5bc38bd9ff2ffba1ef65ee112db3579e5225c272decbb7` |
| [blind_pass/protocol/v2_example_qa_report.json](blind_pass/protocol/v2_example_qa_report.json) | v2 校验结果：PASS 3/3，0 error / 0 warning | `927fc2381cbe3200654fb4aa9d7710d5913ac3e6b1f056b6c6168ebc27ea3db5` |
| `scripts/compare_landmark_annotations.py` | 比较与统计脚本 | `1650b2f3727eaf8e65a7ab72eeeed35cd3ce36764f303652b764a7153e4421cb` |

## 12. 复现命令（离线，无需 Isaac）

```powershell
$py = 'E:\isaac\env_isaaclab\Scripts\python.exe'
cd E:\isaac\proj_boom_birds

# 1) 格式 QA（盲标文件）
& $py scripts/validate_landmark_annotations.py `
  --annotations docs/reports/perception/annotation_verify_20261104/blind_pass/annotations_blind.json `
  --root . `
  --overlay-dir docs/reports/perception/annotation_verify_20261104/blind_pass/qa_overlays `
  --output docs/reports/perception/annotation_verify_20261104/blind_pass/qa_report.json

# 2) 盲标 vs 旧标比较（输出 JSON + 对比 overlay）
& $py scripts/compare_landmark_annotations.py
```

## 13. 版本化与偏差记录

- 盲标为**独立一次 + 自检两轮**：只依据自己生成的 overlay 调整 bbox 口径与坐标，未打开旧几何值；最终文件 sha 见 §11。
- 比较脚本首版曾把"旧 schema 缺失字段（truncated/negative_type）"误当语义不一致，导致分类全部偏向"实质分歧"；已改为"不可比"并区分 bbox/keypoint/语义三个维度后重跑。**该修正只影响统计口径，不影响任何原始标注或旧标签字节。**
- 预注册阈值在打开旧值前冻结；本轮未因看到旧值而修改阈值或盲标坐标。
- 旧标签、sample、freeze 文件均保持原路径与字节，未修改 `outputs/` 原始帧。
- **2026-11-04 v2 规范**：新增 `configs/perception/landmark_annotation_spec_v2.json`（v1 保留不动）；`src/boom_birds/evaluation/landmark_annotations.py` 增加 v1/v2 dispatch、v2 严格校验与 `yolo_pose_target()` 导出器；`tests/evaluation/test_landmark_annotations.py` 新增 19 条 v2 测试（先失败后实现）。lead 审核批准用于 T6 试点并记录在 v2 文件 `lead_review` 字段。

## 14. 给 lead/下游的建议与待决事项

1. **spec v2（已决定）**：lead 2026-11-04 决定升版并批准用于 T6 试点；G1/G2/G3/G5 等已落成字段与规则，见 §15。T6 反馈若需改动出 v2.1 并记录差异，不改写本次记录。
2. **训练标签口径必须在训练前冻结**：旧 bbox 与盲标 bbox 的高差中位 37 px，混用会导致模型/评估不一致；建议 spec v2 定口径后统一重导。
3. **独立标注不可缺**：本轮证明"标注自洽"≠"独立真值"——旧参考点实质=颜色质心。若要验证方位精度，需要至少 2 名独立人工标注 + 仲裁，或物理标定真值；**.036° 类结论在人工标注上不可达**。
4. **扩展样本**：本批无真实遮挡帧、无多候选帧；若训练/评估需要 occluded/多假设覆盖，应在 T1 新采集池中显式补采（与 task-6 试点标注衔接）。
5. **static_c 负例身份**：建议用世界位姿/地图结构（landmark DB）复核该帧远端绿色顶端结构是否为同塔或其他结构；在裁定前该负例应作为"similar-structure hard negative"单独报告，不与普通负例合并。

## 15. spec v2 规范与校验实现（2026-11-04，lead 已批准用于 T6 试点）

- **规范文件**：`configs/perception/landmark_annotation_spec_v2.json`（v1 保留原字节不动）；sha256 `b0b7dae6300086fbcdc6bdf08033f8abd47381695e3d12a900f313a93372f749`；状态 **PILOT_FROZEN_LEAD_APPROVED_2026-11-04_NOT_FINAL_PRODUCTION**。
- **lead 评审记录**：v2 文件内 `lead_review` 字段逐条记录 4 个 open items 的裁定：① bbox_scope 原样批准（含塔头/灯架、收分塔体、与塔体相连的阶梯底座；不含场地平台/地面/画线/阴影/无关结构；截断只框图像内可见部分、不外推）；② 完全遮挡 present=true 且无 bbox 批准（该帧不作 bbox 正例训练）；③ HUMAN_REVIEWED/ADJUDICATED 本轮不可用 → PROPOSED/待 user，T6 只允许 AGENT_PROXY + SELF_CHECKED；④ 当前内容为 T6 **PILOT 冻结**，反馈需改动出 v2.1，不改写本次记录。
- **新增分母规则**：GT 完全遮挡/undecidable 帧不进入检测 TP/FP/FN/TN，单列 `GT_UNOBSERVABLE`（与模型侧 UNKNOWN 分开），presence/joint 报告必须显示该计数；keypoint/anchor 分母仅含 `present=true 且 reference_status=MANUAL_APPROX` 帧。
- **校验实现**：`src/boom_birds/evaluation/landmark_annotations.py` 的 `validate_document()` 按 schema_version 分派 v1/v2（v1 行为不变），新增 v2 严格校验（bbox/截断/可见性组合、reference 枚举与不可用原因、present/undecidable 三态、ambiguous+candidates、annotator 来源、pixel_basis、分组字段）；`yolo_pose_target()` 实现 §9 的 1-keypoint 导出（v∈{0,1}、v=0 占位坐标、absent/ambiguous/undecidable 不写正例、sidecar 字段）。
- **校验脚本**：`scripts/validate_landmark_annotations.py` 现同时支持 v1/v2，qa_report 增加 `document_schema_version`；v2 overlay 会绘制 candidates。
- **证据与结果**：
  - v2 示例文档（3 帧真实帧）→ **PASS 3/3，0 error / 0 warning**（`blind_pass/protocol/v2_example_qa_report.json`）；
  - v1 盲标文件回归 → **PASS 21/21**（`blind_pass/qa_report.json`）；
  - pytest：`E:\isaac\env_isaaclab\Scripts\python.exe -m pytest -q` → **872 passed**（2026-11-04；含新增 19 条 v2 单测）。
- **向后兼容**：v1 文档仍通过原校验逻辑；旧标签文件未改动（其非枚举值按 v2 规则会被拒绝，符合 G6/G7 的收紧决定）。
- **边界**：v2 为 T6 试点冻结，不是最终生产冻结；v2 示例与 T6 标签均为 agent 代理标注，非专家/人工独立审查，不能作为模型效果或导航验收。
- **T6 试点（2026-11-04）**：按 v2 完成 34 帧分层试点标注与校验（PASS 34/34，0 error/0 warning），见 [FINAL_POOL_PILOT_ANNOTATION_20261104.md](FINAL_POOL_PILOT_ANNOTATION_20261104.md)；标签在 ignored 的 `outputs/perception/landmark_final_annotations_20261104/labels_v1.json`（sha `fe8d47d0…c8942`）。试点反馈提出 P1–P7 可执行性问题（四边截断元数据、参考点可用判据、TARGET_ABSENT+未验证 confuser 表达等），是否升 v2.1 由 lead 决定；本轮未改写 v2 记录。

---

**证据域汇总：** 本文所有数字均为**离线标注 QA** 证据（exposed Isaac 合成 320×240 图像、agent 代理复标、n=21 帧/33 条旧记录）；不含真实相机、模型训练/推理、板端、SITL/HIL、实飞或导航验收，不提升任何 BB22 Gate。
