# 地标感知任务定义、轻量学习方法选型与数据/部署可行性（shadow，2026-11-04）

> **交付状态：** 选型、数据规范、标注样例/质检、部署只读可行性、下一次有界训练计划均完成；**没有训练模型、没有安装训练依赖、没有新增 GUI 采集、没有感知/导航达标声明**。
> **主候选：** YOLOv8n-pose（AGPL-3.0，许可待评审）；**备选：** YOLOX-Nano 检测 + 绿灯 anchor（Apache-2.0，anchor 仍为经典阶段）。
> **不采用分割：** 当前 V2.2 消费者没有 mask 需求。

## 0. 现场

- 分支 `feat/v2.2-simulation-perception`；核对 HEAD `f7496e6`；工作树干净；旧报告中的分支字段不代表当前状态。

## 1. 评价口径审查（追加勘误）

详见 `DSH_GEOMETRY_GREEN_ERRATA_20261104.md`，原报告/verify/hash 不覆盖。

- v2 测试：18 正例，9 个 localization 标注子集，**3 joint TP**。
  - **3/9** 是定位子集联合达标率；
  - **3/18** 是全部正例中已确认达标的下界；
  - 9 个未标定位置正例只能计入 presence，不能判定位失败；5 个无输出、3 个 static B 已标注但未 joint、3 个 static A 无输出，另有 9 个未标注，**不能写成 15 个失败**。
- anchor `.036°`：
  - 实际样本 **4 个成功 detection**（route 3、static B 1）；joint TP 只 3；
  - route 参考点在 v1 手工错估，v2 通过视觉/绿色灯位置修正；算法 anchor 同样来自绿色视觉，**不是独立物理测量**；
  - 320×240、fx=160 时 1 px≈0.358°，.036°≈0.1 px，远低于手工标注可靠性；不宣称亚像素实物精度；
  - 成功样本误差不能代表全部正例。
- 低召回、bbox 不准、身份不确定是三类问题：
  - 低召回：5/18 正例 UNKNOWN（static A 绿灯面积 8 < 固定阈值；static B 几何拒绝）；
  - bbox 不准：localization 子集 3/9，static B 唯一检测 IoU .266；
  - 身份不确定：12 个测试负例无 FP，但样本小，开发期存在相似绿色结构；
  - **不能因为 bbox 差就自动推出需要分割**；V2.2 当前消费者没有 mask 输入需求。

## 2. V2.2 消费者实际需求与最小接口

依据设计 §7.4/§7.5/§7.7/§7.8/§9.1/§10.1（`docs/design/RMUC2027_UAV_V2_2.md`）：

```text
上游 front_rgb 观测（v2 header/context/timestamp/payload hash）
        |
        v
地标感知：身份/可见性/绿灯参考点/图像方位（bbox 辅助）
        |
        v
区域/地标关联消费者：可见地标假设、区域候选、粗略朝向
        |
        v
Mission/区域级决策；不直接发 setpoint
```

回答：

| 问题 | 结论 |
| --- | --- |
| 需要地标身份吗？ | **需要**；区域/地标接力必须知道哪个地标，错误匹配比漏检更危险（§7.6/§20.12.1） |
| 需要哪个稳定物理参考点？ | 当前资产的**塔顶绿色灯中心**；不可见时没有 anchor，必须 UNKNOWN/拒绝 |
| 图像方位还是世界方位？ | 感知只输出**图像方位**；世界方位需要外部姿态/地图变换，不在本消费者内伪造 |
| bbox 是检测辅助还是下游消费？ | **辅助**，用于检测质量/可见性/门控；下游地标关联主要消费身份/可见性/参考点/bearing |
| 真的需要 mask 吗？ | **不需要**；当前设计没有 mask 消费者 |
| 遮挡/参考点不可见/多目标歧义？ | 显式拒绝：`OCCLUDED/REFERENCE_UNAVAILABLE/MULTIPLE_CANDIDATES/TARGET_AMBIGUOUS`，保留原因，不续期旧结果 |

- `configs/perception/landmark_task_interface_proposed_v1.json` 给出 **PROPOSED** 最小输出记录；设计尚未冻结具体 landmark ID/database/visibility contract，不能冒称已冻结。
- 输出禁止世界定位/距离/区域结论；粗略图像 bearing 不能直接用于平移控制。

## 3. 方法选型

最多比较三种；以当前消费者需求为准。

| 候选 | 角色 | 输出匹配 | 标注成本 | 小目标/遮挡 | 参数/输入 | 许可/部署 |
| --- | --- | --- | --- | --- | --- | --- |
| **YOLOv8n-pose** | **主** | bbox + 1 keypoint，直接给身份/可见性/anchor | bbox+1 keypoint；较高 | 单阶段小目标仍吃力；关键点可显式不可见 | nano；640 | AGPL-3.0；RKNN Model Zoo 有 `yolov8_pose` RK3576 例子 |
| **YOLOX-Nano** | 备选 | 仅 bbox；anchor 仍走现有绿色几何阶段 | bbox 较低 | anchor 不受益于学习；容易复现旧失败 | 0.91M、1.08GFLOPs、416 | Apache-2.0；ONNX 支持；RKNN zoo 未列 Nano，UNKNOWN |
| YOLOv8n-seg 类分割 | 不选 | mask 无消费者 | mask 标注最贵 | 遮挡/边界更复杂 | 较大 | AGPL；RKNN 支持但不解决当前决策需求 |

### 官方依据（当前页面/版本）

- YOLOv8 文档：<https://docs.ultralytics.com/models/yolov8>
- Pose 任务/关键点格式：<https://docs.ultralytics.com/tasks/pose>
- 导出（ONNX 等）：<https://docs.ultralytics.com/modes/export>
- Ultralytics AGPL-3.0：<https://github.com/ultralytics/ultralytics/blob/main/LICENSE>
- YOLOX Apache-2.0、Nano 0.91M/1.08GFLOPs：<https://github.com/Megvii-BaseDetection/YOLOX>、<https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE>
- RKNN Model Zoo 支持 RK3576、`yolov8_pose` INT8 75.0 FPS single-core、YOLOX s/m 支持：<https://github.com/airockchip/rknn_model_zoo>
- `yolov8_pose` 例子/转换：<https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolov8_pose>
- RKNN-Toolkit2：<https://github.com/airockchip/rknn-toolkit2>

说明：

- RKNN Model Zoo 是 **Apache-2.0** 代码，但 Ultralytics 代码/权重是 **AGPL-3.0**；自定义权重是衍生作品，闭源分发前必须完成许可评审或商业许可。YOLOX 代码/权重 Apache-2.0，但 COCO 预训练数据和具体权重条款仍需另行核对。
- `yolov8n-pose.pt` v8.2.0 是 RKNN `yolov8_pose` 示例引用的资产；**我们的自定义单关键点塔模型导出/量化在 RK3576 上仍是 UNKNOWN**，官方示例不等于自定义模型验收。
- 不引入大型模型；没有安装或下载任何训练依赖/权重。

## 4. 数据清单、划分与标注样例

### 数据清单

见 `dsh_landmark_data_inventory_20261104.json`。

| 数据集 | episodes | accepted RGB | 说明 |
| --- | ---: | ---: | --- |
| formal6 | 6 | 846 | 旧南侧路线重复/静态；全部暴露 |
| lm_pilot | 3 | 9 | 开发静态视角；暴露 |
| lm_independence | 5 | 598 | dev/reverse/north/static；全部暴露 |
| geo_test | 4 | 195 | 新北侧/静态；全部暴露 |

- 地图：`rmuc2027-isaacsim-20261028`；camera 配置 `sensor_shadow_v1.json`，均为 **PROVISIONAL/asset-specific**。
- 标签：旧 36 test（另有 11 train 标签）、independent 49 test/30 dev、geometry30；**当前没有 sealed 数据**。所有已有数据都可用于训练/开发，但不能恢复为 final test。
- 旧 36、49、30 帧都已被查看/使用；不能跨组随机拆连续帧。

### 划分规则

`configs/perception/landmark_data_split_v1.json`：

- 组单位 = 物理轨迹族 × 采集 session × 相机/渲染版本；
- 同路线 reset、连续帧、静态轻微渲染差异 **同组，不跨 train/val/test**；
- 当前已有数据只用于 train/val；最终 test 必须是**新轨迹族**（≥3 个新组，含 normal/scale/yaw/截断遮挡/目标不存在/困难负例）；
- 200–400 帧只是预算，不是独立性证明；报告组数、正负样本、视角/条件分母。

### 标注规范与样例

- 规范：`configs/perception/landmark_annotation_spec_v1.json`；
- 样例：`docs/reports/perception/annotation_sample_v1/`，**12 帧（9 正/3 负）**，来自既有暴露 development/test 图像；人工近似标注，非用户专家复核，非 sealed；
- 字段：身份、presence、visibility（FULL/PARTIAL/OCCLUDED/ABSENT/UNKNOWN）、truncated、occluded、ambiguous、bbox、绿灯火 keypoint、reference_status、negative_type、uncertainty；
- **不能**用 bbox 中心代替参考点；keypoint 不可见必须 `UNAVAILABLE`；absent 不得带 bbox/keypoint。
- 质检工具：`scripts/validate_landmark_annotations.py`；输出 `annotation_sample_v1/qa_report.json`：
  - 12 条，QA **PASS**，0 errors，0 warnings；
  - 检查 image sha/dim、bbox/keypoint bounds、absent geometry、duplicate、source split、overlay；
  - 坐标变换测试：letterbox 640、roundtrip、hflip 的 bbox/keypoint 均通过单元测试。
- 样例不是训练集；只验证数据加载/坐标/缺失标签处理。

## 5. 部署可行性（只读）

详见 `dsh_landmark_deployment_feasibility_20261104.json`。

- Isaac venv 未修改，未安装/升级任何包，未运行训练/新 GUI。
- 主机：Python 3.11.9；torch 2.7.0+cu128、torchvision 0.22.0、onnx 1.22.0、OpenCV 4.11、Pillow 11.3；**无 onnxruntime、无 ultralytics、无 rknn**；RTX 5080 16GB；C/E 盘充足；未发现 .onnx/.pt/.rknn。
- 无训练权重/无 ultralytics，**未做模型加载/前向/导出**；不能把未训练链路当效果证据。
- 隔离环境计划（不执行）：`.venv/landmark-train`，候选 pin `ultralytics==8.2.0 / torch 2.7.0 / torchvision 0.22.0 / onnx 1.22.0`；AGPL 评审前不分发。
- RKNN：官方 Model Zoo 2.5.0/RKNPU SDK ≥2.5.0 支持 RK3576 和 `yolov8_pose` 示例；**自定义塔关键点模型导出/INT8 量化/板端延迟 = UNKNOWN**。没有 RK3576 板卡，不能做板端验收；主机 CPU/GPU 不能替代。
- 本包不等同完整 Student/板端可行性验收；不触发 PPO/大规模训练。

## 6. 下一次有界训练实验计划

详见 `configs/perception/landmark_training_plan_v1.json` 与 `landmark_yolo_pose_v1.yaml`（路径为计划，尚不存在）。

### 固定项

- 主模型：**YOLOv8n-pose**，Ultralytics v8.2.0 资产；AGPL-3.0（许可评审前置）。
- 输入：RGB 原图 320×240 → letterbox 640×640；输出 1 类 `tower` + 1 个 `green_roof_light_center` keypoint；bbox 辅助；无 mask/距离。
- 标注：bbox + 1 keypoint + visibility；负例空 label；原位图像坐标，变换可逆。
- 数据：现有暴露数据分 train/val groups；新增 **≥3 个新轨迹族、200–400 帧**，冻结为 final sealed test；不把连续帧随机拆组。
- 训练：最多 100 epochs，batch16，imgsz640，AMP，seeds **0/1/2**，early-stop patience20；每 epoch/checkpoint 用验证集选 best（验证 joint 优先，FP 次之）；最终测试只跑一次。
- 导出/部署：ONNX opset18，ONNX 与 PyTorch 输出一致性；RKNN `convert.py rk3576 i8` 为计划，未运行；量化后验证下降>5% 则停止/重建。
- 资源：RTX 5080 可用；300 帧 ×100 epoch ×3 seeds 为小时级预估值，不承诺；训练框架/环境需隔离安装并冻结。

### PROPOSED 消费者门限

- identity/presence precision ≥0.95、recall ≥0.85；
- high-confidence false match ≤0.5%（沿用 V2.2 初始建议，但当前样本无法认证；样本不足标 INCOMPLETE）；
- keypoint visible coverage ≥0.90；
- anchor bearing median ≤3°、P90 ≤5°（相对图像参考点，不宣称世界角/实物）；
- joint all-positive ≥0.80；bbox IoU≥0.3 作辅助；
- 报告 UNKNOWN/REJECTED、覆盖率和全部正例分母；未标注定位样本单列，不删除。

### 停止条件

- 验证 joint <0.60 或无改善；
- train/val 差 >20 个百分点/持续过拟合；
- 20 epoch 无验证改善；
- ONNX/RKNN 导出失败，或量化后验证下降 >5 个百分点；
- final sealed test 未达门限，测试后不得回调参数；
- 标注/QA 显示身份/keypoint 不可靠，或不足 3 个独立组。

### 复现命令（计划，未执行）

```text
# isolated env; do not modify E:/isaac/env_isaaclab
python -m venv .venv/landmark-train
.venv/landmark-train/Scripts/pip install ultralytics==8.2.0 torch==2.7.0 torchvision==0.22.0 onnx==1.22.0
yolo pose train model=yolov8n-pose.pt data=configs/perception/landmark_yolo_pose_v1.yaml epochs=100 imgsz=640 batch=16 seed=0 patience=20 project=outputs/landmark/train
yolo pose val model=best.pt data=configs/perception/landmark_yolo_pose_v1.yaml imgsz=640
yolo export model=best.pt format=onnx imgsz=640 opset=18 simplify=True
# separate Linux RKNN env; planned
python rknn_model_zoo/examples/yolov8_pose/python/convert.py best.onnx rk3576 i8
```

- 未实现命令明确标为计划；本包不承诺模型一定优于现有方法。
- 如果 AGPL 不能接受，先运行 backup YOLOX-Nano 检测 + 绿灯 anchor；其 anchor 仍是经典阶段，不能假设解决以前的问题。

## 7. 未确认项

- 自定义 tower one-keypoint pose 的标注一致性/可见性定义、640 输入下 4–10 px 绿灯的可分性；
- RK3576 自定义 ONNX 关键点模型的算子/量化/延迟/热稳定；官方示例不能替代；
- UA V2.2 landmark ID/RegionGraph/VisibilityConstraints 具体值；当前接口是 PROPOSED；
- 现有地图/资产绿灯外观是否代表真实赛场（当前仅资产视觉先验，规则/BOM 保持 UNKNOWN/RULE-CHECK）；
- 数据规模是否足以认证 ≤0.5% false match；当前样本明显不足，最终报告应按 INCOMPLETE/PROPOSED 处理。

## 8. 证据与结论

- 评价勘误：`DSH_GEOMETRY_GREEN_ERRATA_20261104.md`
- 任务/接口：`configs/perception/landmark_task_interface_proposed_v1.json`
- 选型：`configs/perception/landmark_model_selection_v1.json`
- 数据清单：`dsh_landmark_data_inventory_20261104.json`
- 划分：`configs/perception/landmark_data_split_v1.json`
- 标注规范/样例/QA：`configs/perception/landmark_annotation_spec_v1.json`、`annotation_sample_v1/`
- 部署可行性：`dsh_landmark_deployment_feasibility_20261104.json`
- 训练计划/数据 yaml：`configs/perception/landmark_training_plan_v1.json`、`landmark_yolo_pose_v1.yaml`
- 本包结论：完成有界实验包；**不表示模型已训练、感知达标或导航可用**。
