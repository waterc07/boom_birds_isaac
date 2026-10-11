# P0/W00与Task 2核查报告

2026-10-11（Asia/Shanghai）。保留v1.2既定路线；未升级、重装或复制虚拟环境，未安装NavRL/DiffPhysDrone依赖，未访问实机。独立Git基线为 `7de0bb0`，工作分支 `p0-foundation`。

## 现场版本与判断

| 项目 | 当前证据 |
| --- | --- |
| 解释器 | `E:\isaac\env_isaaclab\Scripts\python.exe`，Python 3.11.9；PATH默认Python为另一个解释器 |
| Isaac Sim | 5.1.0.0 |
| Isaac Lab | 源码SHA `b4c321024792976150ca55fddb26fa34480d974e`；VERSION文本2.3.2；发行包isaaclab 0.54.4、tasks 0.11.16、rl 0.5.2，不能混为同一版本号 |
| 源码现场状态 | tracked源码无修改；存在一个既有untracked文件 `2.7.0+cu128`，未删除。启动器存在且hash已保存 |
| PyTorch | 2.7.0+cu128，CUDA构建12.8；CUDA可用，GPU张量求和得到4.0 |
| GPU | RTX 5080，nvidia-smi驱动610.88、显存16303MiB；Kit报告可用显存口径不同，不能混用 |
| PPO | 锁定已有RSL-RL 5.0.1：当前Isaac Lab setup已固定此版本，官方短迭代通过；RNNModel代码支持GRU/LSTM，时序运行未验 |

[host.json](../../../env/manifests/host.json)包含完整版本/路径/命令与工作区状态；[环境清单](../../../env/locks/windows-isaaclab-existing.txt)为现有包快照，不是干净重建保证。上游版本与许可见[差异表](UPSTREAM_REVIEW.md)。

## 实际运行证据

| 检查 | 实际结果 | 证据边界 |
| --- | --- | --- |
| pip check | exit 1，4项冲突 | 环境依赖一致性未通过；短例通过不消除冲突 |
| 官方QuadcopterEnv原配置 | 1环境、100步、exit 0，有 `Failed to clone in Fabric` | 原错误日志保留，不因退出0掩盖 |
| 官方类，关闭Fabric克隆 | 1环境、100步、exit 0，无Error/Traceback，观测[1,12]有限 | 仅运行/步进；不是稳定飞行和速度响应验收 |
| 官方RSL-RL训练入口 | 8环境、seed 0、1迭代、192步、exit 0、生成model_0.pt，无Error/Traceback | 仅后端连接/更新/保存，未重放、未收敛、不是本项目训练 |
| 合同测试 | RED：缺失boom_birds包；GREEN：31 passed | 坐标、水平向量限幅、非法动作、到期边界、任务/原点epoch、时钟域、不可变重发、标准库隔离 |

日志：[原配置](official-quadcopter-smoke.log)、[USD克隆复测](official-quadcopter-usd-smoke.log)、[PPO兼容检查](official-rsl-rl-smoke.log)、[合同RED](contracts-red.log)、[合同GREEN](contracts-green.log)。步进结果：[官方100步](../../../env/manifests/official-quadcopter-usd-smoke.json)；模型路径和hash：[后端记录](../../../env/manifests/ppo-backend.json)。检查point仍在忽略的logs目录，此权重仅用于兼容诊断，不晋升为项目模型。

依赖冲突原样登记：FastAPI 0.115.7要求Starlette <0.46，但现有0.49.1；IPython 9.15.0要求psutil≥7，但现有5.9.8；isaacsim-kernel要求click==8.1.7和typing_extensions==4.12.2，但现有8.4.2和4.16.0。当前未修改。最小处理顺序：若对应入口出现故障，先复现该组件调用，再评估局部版本约束；不运行全局升级修复。

## 已验证入口

在主工作区运行（显式解释器，无需安装本项目包）：

```powershell
& E:\isaac\env_isaaclab\Scripts\python.exe scripts\preflight.py --isaaclab-root E:\isaac\IsaacLab --output env\manifests\host.json
& E:\isaac\env_isaaclab\Scripts\python.exe -u scripts\check_official_quadcopter.py --headless --device cuda:0 --clone-in-usd --steps 100 --output env\manifests\official-quadcopter-usd-smoke.json
& E:\isaac\env_isaaclab\Scripts\python.exe -u E:\isaac\IsaacLab\scripts\reinforcement_learning\rsl_rl\train.py --task Isaac-Quadcopter-Direct-v0 --num_envs 8 --max_iterations 1 --seed 0 --headless --device cuda:0 env.scene.clone_in_fabric=False
& E:\isaac\env_isaaclab\Scripts\python.exe -m pytest -q
```

clone_in_fabric=False仅关闭场景Fabric克隆，不关闭PhysX或Fabric数据读写。官方资产质量约0.0282kg，重力[0,0,-9.81]m/s²，步进0.02s；官方动作是总推力和机体三轴力矩，本项目20Hz速度动作仍需Task 3外环，不直接使用原策略动作。USD资产仅记录URI，资产本体/依赖hash尚待W02追踪。

## 状态与下一项

Task 1环境/上游/后端诊断和Task 2动作合同已有证据；G0最小入口与合同部分通过，依赖一致性保留警告，完整评价manifest未实现。G1及P1–P7均未验。下一项按原Task 3：在该Crazyflie body wrench接口上验证速度→控制器→力/力矩→实际运动，记录前/左/上/yaw阶跃、停止、过期、reset；再进入到点环境。

合同v1在设计最小字段基础上显式增加origin_epoch、clock_id和schema_id，以实际拒绝原点/时钟域切换后的旧动作。未构建模式监督器或MAVLink网关；command_is_valid只表示消息字段/时效有效，不表示允许飞行。
