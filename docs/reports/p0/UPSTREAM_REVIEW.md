# W00 上游审查，2026-10-11

本报告基于固定源码静态阅读，NavRL和DiffPhysDrone均未安装或执行。SHA/逐文件hash见[upstream.json](../../../env/manifests/upstream.json)。

| 上游 | 固定提交 | 许可与兼容边界 |
| --- | --- | --- |
| [NavRL](https://github.com/Zhefan-Xu/NavRL/tree/3725bcc2e7c1be4ecf1455d922299ae85042603a) | 3725bcc2e7c1be4ecf1455d922299ae85042603a | 根MIT；bundled third_party单独核查；README要求Isaac Sim 2023.1.0-hotfix.1 |
| [DiffPhysDrone](https://github.com/HenryHuYu/DiffPhysDrone/tree/271936190b5c2a5e760230e718fa6b167718a5bf) | 271936190b5c2a5e760230e718fa6b167718a5bf | 固定树未见许可证；README测试PyTorch 2.2.2、Python 3.11、CUDA 11.8；对其他版本仅为作者兼容性表述 |

| 来源路径 | 实际内容 | 本项目处理 |
| --- | --- | --- |
| NavRL `isaac-training/training/scripts/env.py` | actor：8维目标方向/距离/速度状态；理想RayCaster距离；最近动态障碍的位置、速度和尺寸来自仿真状态 | P2参考观测/奖励/课程；仿真信息均标ORACLE，P3逐字段替换，不直接认为相机可测 |
| NavRL `training/scripts/ppo.py` | LiDAR CNN+动态障碍MLP+状态融合；Beta分布动作；3轴速度在目标方向框架转换到世界，默认每分量±2m/s | 不复制PPO优化器；本项目统一4维水平FLU速度+yaw_rate、单位圆投影；网络待P3实测 |
| NavRL `training/scripts/train.py`、`cfg/{train,drone,ppo}.yaml` | 旧SimulationApp/TorchRL集成，LeePositionController和VelController(yaw_control=False)，WandB，hummingbird资产 | 不安装旧全栈；只参考速度→控制器→动力学路径，改用当前Isaac Lab资产 |
| NavRL bundled `OmniDrones/.../controllers/lee_position_controller.py`、`utils/torchrl/transforms.py` | root_state→目标速度/可选yaw角→电机命令，四旋翼混控与惯量参数；yaw角不是yaw_rate | MIT控制律可作为P1候选，必须适配当前body wrench接口、姿态约定和yaw_rate跟踪，不能直接接旧motor编号 |
| NavRL `quick-demos/simple-navigation.py`、`ppo.py` | 理想二维圆障碍/射线与简化运动演示、推理入口 | 只作阅读；演示不能代替动力学飞行或真实感知验收 |
| DiffPhysDrone `model.py`、`main_cuda.py` | 单通道深度经逆深度归一化、4倍池化→CNN→192维GRU；训练实际Model(10,6)，no_odom时(7,6)；6个输出拆为3维a_pred和3维v_pred，结合重力/估计误差后驱动动力学 | 参考轻量结构和时序思想；不是RGB单目成果，也不是本项目4维速度动作。默认构造(9,4)不能当实际训练合同 |
| DiffPhysDrone `env_cuda.py`、`src/setup.py` | 自有可微动力学/渲染CUDA扩展，控制加速度及延迟模型 | 首阶段不编译/替换Isaac主框架；许可澄清与L9研究后才评估独立对照 |

NavRL完整checkout失败原因是ROS权重名称含Windows非法冒号。git对象下载成功；采用限定路径git archive提取，archive命令仅临时设置core.protectNTFS=false以读取树，实际只导出合法路径，未修改全局Git设置。该目录不是完整可运行checkout。

结论：保持既定选型。P1优先证明速度执行器；P2参考NavRL静态导航，不提前引入动态障碍真值链；P3再比较真实观测与小网络。未复现原论文性能。
