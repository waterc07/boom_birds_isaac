# ADR-003：最少工具与版本锁定

2026-10-09，PROPOSED选型，构建/运行NOT RUN。

## 主选择与版本证据

Windows保留既有Isaac；首阶段WSL2 Ubuntu24.04运行PX4 SIH与同宿主网关，标准库合同＋[pymavlink官方仓库](https://github.com/ArduPilot/pymavlink)。不增加ROS2、Pegasus或Isaac运行时桥。其理由是首阶段只需要真实飞控模式/控制链，不需要真实图像或并行训练。

PX4候选v1.17.0提交d6f12ad1c4f70ad3230afd7d86e971421e02fef4，2026-10-09远端tag核实；[版本SIH说明](https://docs.px4.io/v1.17/en/sim_sih/)提供`make px4_sitl sihsim_quadx`，无实板即可运行。[官方WSL环境](https://docs.px4.io/main/en/dev_setup/dev_env_windows_wsl)作为候选安装依据，实施前固定提交脚本/子模块/依赖；Python3.12/pymavlink精确版本及wheel哈希经兼容测试后锁定，不假称当前已安装。

代价：WSL需独立安装/磁盘/账户；但同宿主先避开跨Windows网络和图形负担。源码在Linux文件系统，Windows主编辑以Git版本交接。既有Isaac依赖冲突只影响后续Isaac阶段，当前不修它来建立S0。

## 备选触发

| 备选 | 触发 | 代价/退出 |
| --- | --- | --- |
| 独立Ubuntu24.04 | WSL宿主条件不满足且无法修复 | 新宿主成本；保留同版本/日志合同，不维护双基线 |
| 官方Gazebo | SIH不能满足已定义的传感器/视觉/模型需要，或已确认版本后端阻碍 | 增加仿真依赖/场景模型；保留网关合同；不是遇编译错误就切 |
| Isaac合成数据/并行研究 | 真实感知失败需要数据，或策略学习已通过G4 | 先处理版本/资产/依赖，再小规模资源测试；基础步进不算训练通过 |
| Pegasus/运行时桥 | 必须在其受支持组合验证真实PX4视觉闭环且其他后端不足 | 独立兼容验证和维护成本；Windows未测试不能当受支持；不可用就保留未放行 |

实板MicoAir target/固件/ESC协议与SITL候选分别登记。厂商文档不能证明某固件组合已过台架；BDShot问题关闭、补丁提议或板上支持不等于锁定PX4版本可用。先验证当前实板配置，具体刷写后续授权。

细节见[首阶段执行计划](../design/04_FIRST_TASK.md)及[工作区](../design/05_WORKSPACE.md)。
