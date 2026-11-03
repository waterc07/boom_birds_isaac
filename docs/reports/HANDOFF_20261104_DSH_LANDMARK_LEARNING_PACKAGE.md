# 交接：地标感知任务定义、模型选型与有界训练实验包（2026-11-04）

## 状态

- 现场：分支 `feat/v2.2-simulation-perception`，核对 HEAD `f7496e6`；工作树干净；旧报告中的旧分支字段不代表当前状态。
- **完成**：评价口径审查/勘误、V2.2 消费者接口、模型选型、数据清单/划分、标注规范+样例+QA、只读部署可行性、下一次有界训练计划。
- **未做**：没有启动训练、没有安装训练依赖、没有新增 GUI 采集、没有感知/导航达标声明。
- 保持 shadow；不接控制、不做 SLAM/VIO/PPO/真实相机/PX4/板端/SITL/HIL/实机，不提升 Gate。

## 1. 评价口径审查

- v2 测试 18 正例、9 个 localization 标注、3 joint TP：
  - 3/9 = localization 子集联合达标率；
  - 3/18 = 全部正例中**已确认**达标下界；
  - 9 个未标定位置正例不能判定位失败；不能把 3/18 读成 15 个失败。
- anchor `.036°` mean 来自 **4 个成功 detection**（route 3 + static B 1；joint 3），route refs 曾在 v1 错估，v2 通过绿色视觉修正；算法 anchor 同源绿色，不是独立物理测量；320×240 下 .036°≈0.1 px，不宣称亚像素实物精度。
- 低召回（5/18 UNKNOWN）、bbox 差（3/9）、身份不确定是不同问题；不能仅凭 bbox 差推分割。
- 勘误文件：`docs/reports/perception/DSH_GEOMETRY_GREEN_ERRATA_20261104.md`；旧报告/hash 保留。

## 2. 任务与接口

- 上游：front_rgb v2 观测 + intrinsics + 静态地标先验；
- 感知输出：landmark 身份/可见性/绿灯 keypoint/图像 bearing；bbox 辅助；无 mask/距离；
- 下游：区域/地标关联消费者更新可见地标/区域假设/粗略朝向，不直接发 setpoint；
- 身份必需、参考点为绿灯中心、图像 bearing 不是世界 bearing、bbox 非下游主消费、mask 当前不需要；
- 遮挡/参考点不可见/多目标歧义显式拒绝；
- 接口是 **PROPOSED**（`configs/perception/landmark_task_interface_proposed_v1.json`），V2.2 具体 landmark ID/DB/visibility contract 未冻结。

## 3. 选型

- **主候选：YOLOv8n-pose**，bbox+1 keypoint，640；Ultralytics v8.2.0；**AGPL-3.0**，闭源分发/权重使用需法律评审或商业许可；RKNN Model Zoo 2.5.0 有 `yolov8_pose` RK3576 示例（官方示例 INT8 75 FPS single-core），但自定义单关键点模型导出/量化未验证。
- **备选：YOLOX-Nano**，0.91M/1.08GFLOPs/416，Apache-2.0；仅 bbox，anchor 仍走绿色经典阶段；ONNX 有支持，但 RKNN zoo 未列 Nano → UNKNOWN。
- **不选分割**：V2.2 当前没有 mask 消费者；标注/计算成本无对应决策收益。
- 官方引用已在报告列出：Ultralytics docs/license、YOLOX GitHub/license、RKNN Model Zoo、RKNN Toolkit2。

## 4. 数据

- 清单：`docs/reports/perception/dsh_landmark_data_inventory_20261104.json`
  - formal6 6 ep/846 RGB；lm_pilot 3/9；lm_independence 5/598；geo_test 4/195；全部暴露；
  - 旧 36/49/30 帧均已查看，**无 sealed 剩余**。
- 划分：`configs/perception/landmark_data_split_v1.json`；组=物理轨迹族×session×渲染版本；同轨迹 reset/连续帧/相同静态画面同组；test 必须新轨迹族（≥3 组、200–400 帧、覆盖 normal/scale/yaw/遮挡/负例）。
- 标注规范：`configs/perception/landmark_annotation_spec_v1.json`；bbox+1 keypoint+visibility/truncation/ambiguity；absent 不带几何；keypoint 不可见标 UNAVAILABLE。
- 样例：`docs/reports/perception/annotation_sample_v1/` 12 帧（9 正/3 负），代理近似标注、非 sealed/非专家；QA PASS，0 errors/0 warnings；overlay 已生成。
- QA 工具/测试：`scripts/validate_landmark_annotations.py`、`src/boom_birds/evaluation/landmark_annotations.py`、`tests/evaluation/test_landmark_annotations.py`；letterbox/roundtrip/hflip 全部通过。

## 5. 部署可行性（只读）

- Isaac venv 未修改；未安装/升级。
- Python 3.11.9；torch 2.7.0+cu128、onnx 1.22.0、cv2 4.11、Pillow 11.3；**无 ultralytics/onnxruntime/rknn**；无 .onnx/.pt/.rknn；RTX 5080 16GB；磁盘充足。
- 无训练权重/无 ultralytics，**未做模型加载/前向/导出**；不能当效果证据。
- 隔离环境计划（未执行）：`.venv/landmark-train`，pin ultralytics 8.2.0/torch 2.7.0/torchvision 0.22.0/onnx 1.22.0。
- RK3576：官方 Model Zoo 支持 `yolov8_pose`；我们的自定义模型/INT8/板端延迟 **UNKNOWN**；无板卡，非 Student 板端验收。
- 证据：`dsh_landmark_deployment_feasibility_20261104.json`。

## 6. 下一次有界训练实验

- 计划：`configs/perception/landmark_training_plan_v1.json`、`landmark_yolo_pose_v1.yaml`（路径/集为计划，尚不存在）。
- 主：YOLOv8n-pose v8.2.0；1 类 + 1 keypoint；640 letterbox；最多 100 epochs/batch16/seeds0-2/early stop20；验证选 best；final test 一次。
- 数据：现有暴露数据训练/验证；新增 ≥3 新轨迹族、200–400 帧，冻结 final sealed test；不做连续帧随机拆分。
- PROPOSED 门限：identity precision≥.95/recall≥.85；high-confidence false match≤.5%（样本不足须 INCOMPLETE）；keypoint coverage≥.90；anchor median≤3°/P90≤5°；joint≥.80；bbox IoU≥.3 辅助。
- 停止：验证 joint<.60/无改善；过拟合；ONNX/RKNN 失败/量化掉 >5 点；final 不达标（不得回调）；标注不可靠/独立组不足。
- 计划命令明确未执行；不承诺模型优于现有方法；AGPL 未解决前不得分发/训练产物。

## 7. 未确认项

- green light 4–10 px 在 640 输入下是否可分；自定义 1-keypoint 标注一致性；
- RK3576 自定义 ONNX/量化/延迟/热稳定 UNKNOWN；
- V2.2 landmark DB/RegionGraph/visibility contract 未冻结；
- 当前合成资产绿光不等于真实赛场规则；
- current data insufficient to certify false-match ≤0.5%.

## 8. 文件/提交

- 报告：`docs/reports/perception/DSH_LANDMARK_LEARNING_PACKAGE_20261104.md`
- 勘误：`docs/reports/perception/DSH_GEOMETRY_GREEN_ERRATA_20261104.md`
- 接口/选型/划分/训练计划：`configs/perception/landmark_task_interface_proposed_v1.json`、`landmark_model_selection_v1.json`、`landmark_data_split_v1.json`、`landmark_training_plan_v1.json`
- 数据清单/部署：`docs/reports/perception/dsh_landmark_data_inventory_20261104.json`、`dsh_landmark_deployment_feasibility_20261104.json`
- 标注：`configs/perception/landmark_annotation_spec_v1.json`、`annotation_sample_v1/`
- 工具：`scripts/validate_landmark_annotations.py`、`src/boom_birds/evaluation/landmark_annotations.py`
- 分支 `feat/v2.2-simulation-perception`；未推送；无关修改保留。
