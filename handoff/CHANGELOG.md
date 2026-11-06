# r4 (2026-10-26)

当前修复见 [R4-REPAIR.md](R4-REPAIR.md)，原r3记录保留如下。

# r3 补充与修复

2026-10-26；基于 r2 扩展，不覆盖原 r5/r2。

| 原审查项 | r3动作 | 证据/状态 |
| --- | --- | --- |
| F1 原生成功状态被错误复用 | v2绑定spec/源码/HEAD/runner/解释器及直接文件argv；恢复前校验日志；坏/旧状态保留并BLOCK | manifest/source/外部脚本/log/坏JSON/旧schema/链接负控 |
| F2 缓存.new软链接覆盖 | 0700私有目录、随机独占0600临时文件、fsync+原子替换；快照也走同路径 | 预置.new链接目标不变、共享目录拒绝负控 |
| F3 依赖与平台条件 | doctor分core/portable/full；显式OpenSSL绝对路径；非Linux隔离器结构化BLOCK | Ed25519实际签验+缺依赖full BLOCK，真实Linux/Loop仍待环境 |
| F4 stage/plan混淆 | plan_status/remaining与计数分开，validate_output要求完整计划 | 两阶段首步PENDING、末步PASS，业务仍不获准出 |
| F5 数量口径 | 机器生成passed/skipped/errors等；历史文档不重写 | 新summary.json为准，旧118条/3跳过=115成功 |
| F6 项目交接材料不足 | 补MarkupSafe静态MUST映射、source map、oracle设计、功能/压力/交接三件套 | 离线恢复逐文件匹配、validate_design；审阅/执行未假签 |
| F7 编译缓存/发行约定 | 排除pyc，加入精确文件清单、依赖组件/来源、可重复构建与干净解包验收 | 两次归档摘要一致、额外文件与篡改负控 |

新增防御：日志独占创建与每文件硬上限，阶段结束清理同进程组；这些不替代外部worker或进程树cgroup，不能承诺拦截setsid/所有副作用。

独立接手测试额外发现四个新交接工具只按词法absolute路径检查包外输出，祖先软链接可绕过不可变发行边界。已改为解析真实目标后判定，四工具均增加包外最小夹具回归；首次复现记录保留在audit/r3/independent-review。此防护不承诺抵抗同用户并发恶意替换目录的原子竞态，执行环境仍须可信。

旧根入口在r3中仅作历史阅读。全部业务用例保持NOT-RUN；没有运行第三方仓库、真实压力或旧服务器命令。明确待办而非伪称关闭：真实Loop调度E2E、Linux隔离集成、通用worker审计、独立发行签名、上游自有脚本授权和接收方人审。
