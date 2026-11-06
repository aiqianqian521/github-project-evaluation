# 有界项目测试执行器（Linux 试点，不是通用安全认证）

`scripts/run_isolated_cases.py` 在有**单独测试授权**、已冻结的本地 Git checkout、在线可核验的上游 commit、事前写好的 `project-tests.run.v1` 测试规格和可信 Linux `bubblewrap` 可执行文件时自动运行最多 20 项用例。执行器不会自行从 GitHub 克隆项目，也不会因首评分高就自动选择执行项目命令。未配齐任一条件拒绝运行；本机没有全局预装 bwrap 时可以在工作区使用经审阅的系统包路径，**不要从待测仓库加载隔离器**。

规格必须恰好包含 `schema`、`repository`、`commit`、`cases`；每例恰好包含唯一的 `case_id`、参数数组 `argv`（**不通过 shell 执行**）、事前固定的 `expected_exit_code`、`timeout_seconds`（1–30）和 `memory_mib`（128–1024）。先记录规格 SHA-256，再把该值传给 `--expected-spec-sha256`；此值绑定本地文件内容，**不代表外部审批签名**。在 Skill 根目录执行：

`python3 scripts/run_isolated_cases.py --spec <frozen-spec.json> --expected-spec-sha256 <spec-sha256> --checkout <clean-git-checkout> --output-dir <fresh-outside-checkout> --bwrap <trusted-bwrap-binary>`

执行前对 checkout 作静态检查，并经 GitHub 实时 commit API 验证 origin 与 HEAD；失败时不执行用例。每次执行前进行强制命名空间预检，确认宿主 `/home`、`/etc` 不可见、工作区只读及网络隔断，并通过 `bwrap --info-fd` 核对 PID/挂载/网络等命名空间信息；预检失败即保留证据、退出 2。每例单独启动无网络命名空间，挂载只读 `/usr` 和 checkout，只给 `/tmp` 32 MiB tmpfs，不绑定宿主可写目录。文件输出上限 1 MB/文件、文件描述符、每进程虚拟内存/CPU、墙钟超时均有限额；超时或退出码与预期不一致时停止后续用例。**此处的 RLIMIT_NPROC 为同一宿主账户的限制，不是可靠的容器级 PID/cgroup 配额；内存也是每进程地址空间限制，而非容器聚合上限。**

输出目录持有 `preflight.*`、每例 `.stdout/.stderr/.exit/.namespace.json`、`manifest.json` 和 `RUN.json`。执行器调用本 Skill 的 `project-tests.evidence.v2` 完整性检查；只有身份核验、命名空间预检、用例执行及本地证据均正常，才记录 `execution_gate=RECORDED`，**不是业务 PASS**。所有结果保持 `candidate_acceptance=NOT_REVIEWED`、`deployment_test_gate=BLOCK`；非零的预期退出码也不表示用例实现了真实业务 oracle。`bubblewrap` 对被信号终止的项目可能返回 `128+signal`；因此退出码 128–255 一律阻断，即使规格错误地将其设为预期值。stdout 的语义应由独立审阅者按事前指标核对。

局限：这里没有经过独立安全审计的 seccomp/cgroup/镜像供应链证明，不保证能安全运行恶意 fork bomb、内核漏洞 PoC、需要数据库/网络/设备/长时负载的任何项目；用户不应把它当成可信的“任意 GitHub 仓库通用沙箱”。需要这些能力时在专用虚拟机/隔离账户中另设计门禁。Skill 离线 Loop 首评适配器不自动调用执行器，不能将 Loop `COMPLETE` 当成测试完成。禁止将凭证、生产网络、实盘资金交给测试实例。
