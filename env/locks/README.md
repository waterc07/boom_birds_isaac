# 已有 Windows Isaac 环境快照

解释器：`E:\isaac\env_isaaclab\Scripts\python.exe`。禁止用PATH中的另一个Python运行仿真。

`windows-isaaclab-existing.txt` 是P0运行前 `python -m pip freeze --all` 的原样包清单，不是经验证可全新安装的跨平台lockfile。editable源码仍依赖 `E:\isaac\IsaacLab`，其提交、工作区状态和启动器hash在 `../manifests/host.json`。保存清单不等于修复环境；已存在的4项pip check冲突见P0报告。

首轮PPO固定已有 `rsl-rl-lib==5.0.1`、`torch==2.7.0+cu128`、`isaacsim==5.1.0.0`；源码提交为主版本依据，VERSION文本和Python发行包版本分开记录。不升级、不完整安装NavRL/DiffPhysDrone。

P0单环境用USD克隆（`scene.clone_in_fabric=False`），保留物理仿真及Fabric I/O。并行规模增加后需重新测资源和隔离正确性；当前8环境仅证明短PPO集成运行。
