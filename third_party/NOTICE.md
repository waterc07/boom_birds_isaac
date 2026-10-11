# 上游审查与来源

当前尚未移植NavRL、OmniDrones或DiffPhysDrone实现到本项目业务包。external仅为忽略的审查副本；固定SHA及所读文件hash见 `env/manifests/upstream.json`。

- Isaac Lab源码：BSD-3-Clause；本项目诊断脚本调用其官方类，未复制环境实现。发行时另核Isaac Sim及远程USD资产条款，不能将Isaac Lab许可扩大到所有资产。
- NavRL：MIT，Copyright (c) 2025 Zhefan Xu。其内嵌OmniDrones控制器另有MIT署名（2023 Botian Xu, Tsinghua University）；以后移植需保留对应许可和修改记录。
- DiffPhysDrone：固定树未发现明确LICENSE/COPYING/NOTICE；当前仅作行为、接口与论文参考，不复制、改写或发布其代码。公开可见不是复制授权。
- RSL-RL：本机安装库源码标BSD-3-Clause，Copyright (c) 2021-2026 ETH Zurich and NVIDIA CORPORATION。当前通过Isaac Lab现成集成使用，不自写PPO。

逐项输入、动作与移植边界见 `docs/reports/p0/UPSTREAM_REVIEW.md`。
