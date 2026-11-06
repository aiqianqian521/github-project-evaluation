# r4 逐项修复与回归

基于2026-10-26真实工作流暴露的问题；不覆盖r3，不改写原25 PASS/1 FAIL/2 BLOCK账本。当前机器计数与实测结果见audit/r4及ACCEPTANCE.json。

| 项目 | 修复与回归 | 关闭边界 |
| --- | --- | --- |
| P1 Gradle/Java漏识别 | exact build.gradle/KTS + 同模块Java/Kotlin主源与命名测试；逐文件SHA；真实冻结Apktool 41→71；正例、helper/无模块/未跟踪/软链接/预算负控 | 约定静态证据漏检修复，不等于Java测试已执行；非常规布局继续显式缺口 |
| 中文AI画画零分 | 版本化精确别名自动扩展，原词保留；最多3查询，每查询预算可见；literal禁用 | 这3个已知意图可复现，不宣称任意中文语义召回 |
| 运镜硬件/画画资源榜误入围 | 支持三个明确意图的MATCH/UNKNOWN/REJECT元数据角色分流；原始高分噪声保留，不填满名单；正反例与失败来源回归 | 修复自动名单角色门禁，不宣称通用语义分类或实测全网精度 |
| 采样64MiB被当硬上限 | 稀疏优先、无普通clone回退、隔离临时树；结束后精确字节/数量验收，超预算不接收；真实本地双文件超限/超时、失败/软链接/commit负控 | 接收产物上限可保证；获取期瞬态仍非硬磁盘配额。require-hard-quota在网络前BLOCK，硬配额需外部worker |

## 最短复现

```sh
export OPENSSL_BINARY=/absolute/trusted/openssl3
python3 -B tools/handoff_check.py --output ../fresh-r4-acceptance
python3 -B skills/github-project-evaluation/scripts/discover.py 'AI画画' --source multi --max-pages 2 --verify-top 1 --cache-dir ../fresh-private-cache --output-dir ../fresh-search
```

联网前检查robots/rate；multi中GitStar目录限制及分页预算会保留PARTIAL。首评只读源码、不执行上游。角色MATCH/证据71分均不能自动批准部署。

## 必须保留的未准出事项

真实Loop调度器E2E、Linux隔离集成、通用worker/cgroup/硬磁盘配额、独立发行者签名、人审/许可批准和生产容量SLO不由本次修复授予。旧故障/环境BLOCK与新代码回归PASS分开记账。

## 独立复测新增并修复

- P1：git status可能运行仓库clean filter。已移除status调用，直接比较HEAD/index及原始blob，不运行filter；受控marker负控。
- P1：skip-worktree/assume-unchanged可隐藏改动。已对实际物化文件逐字节校验Git blob，包括这些标记；变更/暂存/缺失负控，稀疏缺失不冒充源码证据。
- P2：跨词合并按最高分保留过期镜像。已按GitHub权威和获取时间选摘要，再重算所有词的分与角色；反向image-to-text/零Stars冲突负控。

原独立失败报告与修复后复测分开保留，不能用新结果覆盖旧失败。

- 独立第二轮P1：Git replace可将B树绑定到A的上游SHA。所有只读Git操作禁用replace，同时验证原始commit/tree对象摘要；replace、松散commit对象和root tree替换负控均须BLOCK。
- 冻结策略收紧：ignored但实际物化的未跟踪文件也BLOCK；不能将旧版本“忽略但不给分”预期继续套用。历史回归失败保留，新合同明示。
