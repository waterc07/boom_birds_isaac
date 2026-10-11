# ADR-003：单一训练主环境与隔离部署

2026-10-11，v1.2。替代旧“WSL/PX4 SIH先行”顺序。

主工程在现有Windows Isaac Lab环境基础上验证并锁定；P0复测官方例和依赖，选一个已有兼容PPO集成。不安装NavRL指定旧Isaac去替换现有环境，不全局升级PyTorch/CUDA。版本和命令以本机核实结果写入env manifest。

DiffPhysDrone/其他上游固定版本放external，仅在有明确对照问题时建立隔离环境。PX4 SITL在P5使用兼容的WSL2或Linux，构建留在Linux文件系统；不是P1训练前置。最终机载环境独立，只安装推理/采集/协议必需依赖。

不默认引入ROS2、Pegasus、Gazebo或运行时桥；确需PX4与视觉闭环联仿时，再按兼容证据选择一种路径并记录代价。P0环境失败允许最小隔离修复，不连带重建所有工具链。

路径和代码交接见[工作区](../design/05_WORKSPACE.md)。当前未初始化Git、未新建环境、未运行训练，不能提供伪造锁版本或HEAD。
