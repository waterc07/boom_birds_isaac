# v1.2 必需技术与学习路线

目标是能理解、修改和验证项目所用部分。每个学习单元都交付一个小结果；不用先系统学完机器人、视觉或RL全部课程。时间为初学者粗估的专注小时，按掌握程度跳过，通过产物证明即可。

| 单元 | 阶段与必要性 | 要掌握什么 | 可检查产物 | 建议投入 |
| --- | --- | --- | --- | --- |
| L0 Python工程与Git | P0，必须 | venv/解释器、包导入、配置、Git提交/分支、日志、pytest基本使用 | 能重现一次运行，列出解释器/依赖/配置差异 | 6–12h |
| L1 飞行状态与坐标 | P0/P1，必须 | 位置/速度/加速度区别，FLU/FRD/ENU/NED，yaw与yaw_rate，四元数顺序 | 手算并测试前/左/上与转向，解释一个速度阶跃响应 | 6–10h |
| L2 Isaac Lab任务 | P1，必须 | vector env、reset、action decimation、step_dt、传感器/资产、terminated/truncated | 改官方四旋翼例为无障碍到点，输出逐episode指标 | 8–16h |
| L3 PPO最小知识 | P1/P2，必须 | actor/critic、观测/动作、reward、rollout、GAE、clip、归一化、训练验证划分 | 解释一次学习曲线及失败；识别站住刷奖励和真值泄漏 | 8–16h |
| L4 NavRL阅读 | P0/P2，必须 | 环境、动作、障碍表达、奖励、推理入口与依赖 | 一页复用/移植/不采用表，每项指向上游文件和SHA | 4–8h |
| L5 视觉与传感基础 | P3，必须 | 相机内外参、视场/像素、曝光、时间戳、RGB/深度差异、光流尺度 | 给出目标像素与停止距离预算；解释双目开销分项 | 8–16h |
| L6 小网络与部署 | P3/P5，必须 | CNN/MLP/GRU作用、hidden reset、张量shape、actor导出、数值对照、P95/P99 | 小策略在候选CPU重放，输出全链性能和导出误差 | 8–16h |
| L7 PX4融合与接口 | P5，必须但不阻塞P1 | 光流/测距有效性、速度Offboard、MAVLink模式/ACK/时间、失联配置 | 坐标/时效/模式/估计失效注入报告 | 6–12h |
| L8 相对视觉与任务 | P4/P6，必须 | 机库/基地/装甲身份、ROI、相对几何、置信与失锁、数据划分 | 完成一次重捕获/对准重放及双阵营误识别分析 | 8–16h |
| L9 可微物理 | 有证据才深入 | differentiable dynamics、BPTT、梯度衰减、模型误差 | 原版DiffPhysDrone小实验与PPO同条件对照 | 8–20h，非启动前置 |

L0–L8总量只是学习量级估计，和工程实现有重叠，不能简单加在路线工期后。先L0/L1和L2入门即可开工，L3边做W03边学，L5–L8按工作包到来学习。

## 阅读顺序和官方入口

1. [Isaac Lab文档](https://isaac-sim.github.io/IsaacLab/)：先找本机版本对应的环境创建、RL任务、四旋翼示例；复制示例前核版本。
2. [PyTorch教程](https://pytorch.org/tutorials/)：只读张量、模型、梯度、保存加载；随后读所选PPO库的配置和训练循环，不并行学习多库。
3. [NavRL](https://github.com/Zhefan-Xu/NavRL)：README→配置→环境/观测/动作→奖励→推理；具体路径固定于上游审查表。
4. [DiffPhysDrone模型](https://github.com/HenryHuYu/DiffPhysDrone/blob/master/model.py)与[训练](https://github.com/HenryHuYu/DiffPhysDrone/blob/master/main_cuda.py)：先能画出输入输出与控制量，不急于重写可微CUDA。
5. [PX4 1.17 Offboard](https://docs.px4.io/v1.17/en/flight_modes/offboard)、[光流](https://docs.px4.io/v1.17/en/sensor/optical_flow)、[EKF2](https://docs.px4.io/v1.17/en/advanced_config/tuning_the_ecl_ekf)：P5按用到的功能读。
6. [OpenCV相机标定](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html)：P3/P4读标定与投影，用来理解尺度/像素而非先建设SLAM。

## 暂缓学习

完整ROS2生态、全局SLAM/VIO、点云建图、复杂MPC、CUDA内核开发、Transformer/VLM、扩散策略、多机RL和飞控底层重写都不是首阶段前置。某项实验失败确实需要时，再添加专项学习卡。

## 学习记录模板

每项记录：当前问题；读到的版本/章节；做的最小例子；观察到的结果；仍不理解的一点；如何影响本项目。放docs/reports/learning/Lx-日期.md。不要以看完视频数量或课程时长作为掌握标准。
