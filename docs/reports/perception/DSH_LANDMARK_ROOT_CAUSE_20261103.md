# 自然塔感知失败根因诊断与方法去留评审（shadow，2026-11-03）

> **状态：** 诊断/去留评审完成；**无确认的实现缺陷、无生产代码修复**。
> **结论：** 49 帧已降为已暴露诊断数据；模板方法的能力边界已确认，**建议停止继续堆模板**，转向“几何+绿灯 anchor”的最小下一方法。
> **范围：** 纯离线，不重复 Isaac；保持 shadow，不接控制、不提升 Gate。

## 1. 现场核对

- 分支 `codex/bb22-contact-envelope`；实际 HEAD `e01e102`（诊断前）。
- 旧报告/交接、freeze v3、labels、模板、候选/结果均核对；用户及其他任务修改保留。
- 本包不修改旧 freeze/正式结果；新增诊断脚本/报告/证据。
- 没有重新运行 Isaac：现有数据足以区分主要假设；无需补 GUI 探针。

## 2. 方位评价对象一致性

### 2.1 三个对象

| 对象 | 定义 | 是否有物理 anchor |
| --- | --- | --- |
| baseline bearing | `atan2(bbox_center_x - cx0, fx)` | **无**；bbox 中心依赖框大小/形状 |
| improved bearing | 模板 anchor（模板内绿灯中心）映射到图像 | 有，但当候选不覆盖目标时不可评估 |
| label bearing | 人工标注绿灯参考点 `atan2(green_x - cx0, fx)` | 有（代理标注，非专家） |

- 不能把 baseline bbox 中心与标签绿灯中心天然视为同一物理点。
- 标签 bbox 中心与绿灯本身已有 **0.28–5.06°** 差。
- baseline 接受检测的预测 bbox 中心 vs 标签 bbox 中心：**5.65–11.74°**；vs 绿灯：**9.13–11.46°**。
- 因此旧 baseline “绿灯方向误差”不是直接可比；但预测框中心相对标签框中心也有真实偏移，不能把全部问题归因于定义。
- improved 的全局最高候选在 8 个可评估目标帧上 IoU **0–0.202**；它不是目标框，故其 anchor vs 绿灯的 36–51° 差**不能**作为 anchor 映射缺陷证据。

### 2.2 坐标/内参一致性

- 49 帧全部 `320×240×3`，内参统一 `fx=160, cx0=160, fy=160, cy=120`。
- 图像直接读整图；**无 crop/resize/letterbox**；只有模板按尺度 resize。
- bbox 原点为左上，PIL 标签与 cv2 bbox 同坐标；检测器使用灰度图，无 RGB/BGR 色彩通道混淆。
- anchor 定义为 `bbox_xy + anchor_fraction * scaled_template_wh`；模板缩放后 anchor 同步缩放。
- bearing 只做图像 x 方向角 `atan2(px-cx0, fx)`；不是世界方位，不混用 camera optical/body frame。
- 合成图像测试覆盖 scale .5/.8/1.0，bbox/anchor 误差 ≤1 px；当前测试通过。
- **结论：未发现坐标变换/内参/裁剪实现缺陷；不做常数补偿。**

## 3. 模板与候选诊断

模板（development-only；完整裁剪/尺寸/hash 在根因 JSON）：

| 模板 | 尺寸 | 灰度 std | 边缘密度 | 近白占比 | 测试中被选为全局候选 |
| --- | --- | ---: | ---: | ---: | ---: |
| dev_static_center | 150×175 | 28.7 | 5.30% | 0.15% | 43/49 |
| dev_static_left | 110×170 | 31.6 | 5.46% | 0.07% | 0/49 |
| dev_route_near | 140×155 | 26.1 | 5.70% | 0.70% | 6/49 |

- 模板不是近常量图（std≈26–32，edge≈5.3–5.7%），但含灰地板/背景；错误区域可得到 .55–.61 NCC。
- **center 模板主导 43/49，left 模板从未被选中**；多模板 max 并没有带来多样覆盖，反而主要放大同一模板的背景匹配。
- 每帧最高候选、位置、尺寸、模板 ID、原始分数、阈值前后接受均导出到 `candidates.jsonl`。

### 阈值/候选分层

- 27 个测试正例中：
  - 18 帧只有 presence 标签、无 bbox，目标重叠不可评估；
  - 9 个 bbox 可评估正例：
    - 4 个有 target-overlap 候选但低于 0.65（0.528–0.592）；
    - 5 个 target-overlap 候选非常低（0.342–0.499）；
    - **0 个正确目标候选达到 0.65**。
- 全局最高分候选常落在空白/地板/其他结构（IoU 0–0.2，score 约 .55–.61）。
- 阈值扫描（仅诊断，不用于正式验证）：

| 阈值 | baseline TP/FP/FN/TN | improved TP/FP/FN/TN |
| --- | --- | --- |
| .50 | 13/4/14/18 | 27/22/0/0 |
| .55 | 12/0/15/22 | 15/22/12/0 |
| .60 | 11/0/16/22 | 4/20/23/2 |
| .65 | 11/0/16/22 | **0/2/27/20** |
| .70 | 9/0/18/22 | 0/0/27/22 |

- .65 不是“唯一失手点”：降低阈值会引入大量硬负例误报，且仍不能稳定获得正确候选。
- 测试测试帧的 gate 状态：0 UNKNOWN / 0 REJECTED；REJECTED 只有 warmup。**不是 gate/generation 抑制。**

### 尺度

- target bbox 宽/模板最大宽度比最高 **1.82×**；部分 reverse 近距目标大于模板最大尺度。
- 诊断性额外尺度 1.3/1.5/1.8/2.0：
  - north s192 target score .485→**.627**；north s186 .528→.554；
  - reverse 仍约 .34–.43，未达 .65；static 仍 .589。
- 尺度是部分贡献（north），**不是唯一根因**；reverse 主要是模板外观/背景/视角不匹配。

## 4. 有界消融

| 消融 | 设置 | 结果 |
| --- | --- | --- |
| A | 旧 baseline 原样 | presence TP12/FP0/FN15/TN22（P1/R.444） |
| B | **当前代码 + 旧模板 + 旧参数 .55** | 对 613 帧与 A 状态 **0 不一致**；**复现成功** |
| C1 | 单个 center 模板 .65 | TP0/FP2；.55 TP15/FP22 |
| C2 | 单个 left 模板 .65 | TP0/FP0；.55 TP0/FP0 |
| C3 | 单个 route near 模板 .65 | TP0/FP0；.55 TP0/FP4 |
| D | 三模板 max（当前 improved） | 阈值 .65 TP0/FP2；.55 TP15/FP22；center 主导 |
| E | anchor 坐标单独验证 | 合成图像 .5/.8/1.0 通过；真实测试无正确候选，无法评价 anchor 精度 |

B 消融排除“新代码把旧模板路径改坏”的实现缺陷假设；C/D 表明模板库未增加有效不同视角，反而被单一模板/背景匹配主导。

## 5. 根因树

```text
improved 独立测试退化
├─ 评价定义
│  └─ baseline bbox center ≠ green anchor: 旧 green-bearing 不直接可比
│     （但预测框中心相对标签框中心仍有 5.65-11.74° 偏移，不能全归因定义）
├─ 实现/坐标 (EXCLUDED/NOT CONFIRMED)
│  ├─ B 当前代码+旧模板+旧参数复现 A，0 状态差异
│  ├─ 图像/内参/bbox/anchor 坐标合成测试通过
│  └─ 无 crop/resize/letterbox/符号/单位/帧混用问题
├─ 阈值 (SECONDARY, NOT SOLE)
│  ├─ 4 个 target-overlap 候选 .528-.592 < .65
│  ├─ 降低阈值 .55 时 TP15/FP22，.60 时 TP4/FP20，无好工作点
│  └─ 仍无法把正确目标候选变成稳定排序第一
├─ 模板/候选 (PRIMARY)
│  ├─ center 模板主导 43/49；left 0；不同视角覆盖失败
│  ├─ 全局最高候选常为非目标结构/背景（IoU 0-0.2）
│  ├─ target-overlap 候选分数低（0.34-0.63），最高未达阈值
│  ├─ 目标宽度最大 1.82× 模板最大尺度（部分贡献）
│  └─ 多模板 NCC 分数未校准/不可分，错误区域也约 .6
└─ Gate/generation (EXCLUDED)
   └─ 测试帧 0 UNKNOWN / 0 REJECTED；拒绝仅 warmup
```

## 6. 方法去留决策

### 决策：**停止模板方法作为主候选**

- 不继续增加同场景模板：会需要大量视角/背景覆盖，且会放大误报；没有证据表明“再增加几个模板”能解决 reverse/edge/困难负例。
- 不在已暴露 49 帧上调阈值或重新拟合阈值；不在旧冻结上改参数。
- 旧 baseline/improved 结果保留为历史/诊断；49 帧降级为已暴露诊断数据，不用于未来“独立”声明。

### 下一方法（具体方案，未在本包实现）

**几何 + 绿灯 anchor 检测器**（传统 CV，无学习模型）：

1. 输入仍为 RGB、内参、静态塔形状/颜色先验；
2. 边缘/Hough 或轮廓找塔体近竖直边与梯形/四边形结构，按宽高比、左右对称、底宽顶窄过滤；
3. 在候选上半区用 HSV 找绿色顶灯 blob；
4. 校验绿灯相对塔体的位置（顶部中心）与塔体尺度；
5. 输出 bbox + 绿灯 anchor bearing；无绿灯/几何冲突 -> `UNKNOWN/NOT_DETECTED`，不输出距离、不接控制；
6. 先合成坐标测试，再在新冻结数据上评价；阈值/参数不得用测试回调。

**验证成本：**

- 3–4 个新独立 GUI episode（reverse/north/oblique/away），40–60 帧独立标注（bbox + 绿灯）；
- 离线 CPU 评价、无训练、无大型模型；
- 冻结参数/规则后再跑一次独立测试；若仍达不到预先声明 IoU/ bearing 且误报不可接受，则**停止本阶段感知推进**，转回区域拓扑/真实相机标定，而不是继续堆模板。

## 7. 测试与独立核验

- 新增合成 anchor 尺度回归：scale .5/.8/1.0 的 bbox/anchor 位置 ≤1 px；
- 根因脚本：`scripts/diagnose_landmark_failure.py`
- 独立核验：`scripts/verify_landmark_root_cause.py` → `dsh_landmark_root_cause_verify_20261103.json`：**PASS，43 checks**，包含候选重算、阈值 sweep、坐标差、B 复现、模板/输入 hash。
- `pytest -q` 结果见交接/最终答复；文档审计 PASS；本包 diff 检查。
- 没有新增 Isaac 运行；没有新测试集。

## 8. 证据

- 根因 JSON：`docs/reports/perception/dsh_landmark_root_cause_20261103.json`
- 独立核验：`docs/reports/perception/dsh_landmark_root_cause_verify_20261103.json`
- 候选逐帧/逐模板/逐尺度：`docs/reports/perception/evidence_20261103_root_cause/candidates.jsonl`
- 证据目录：`evidence_20261103_root_cause/`（模板、错误候选、目标候选低于阈值、baseline 中心偏移、root cause/verify/labels）
- 旧报告追加勘误：`DSH_LANDMARK_INDEPENDENT_ERRATA_20261103.md`
- 交接：`HANDOFF_20261103_DSH_LANDMARK_ROOT_CAUSE.md`

## 9. 边界

- 不接控制、不做 SLAM/VIO/PPO/真实硬件/板端/SITL/HIL/实机，不提升 Gate。
- 不输出区域/定位/距离结论；硬件参数仍待测，不是本离线诊断阻塞。
- 诊断/回归只使用已暴露数据并明确标注；没有为了“跑更多次”采新数据。
