# 输出、错误与接口契约

## 工具退出码

`doctor`：0=所选档位前提具备；2=BLOCK。`verify_release`：0=文件集合/内容相符；1=FAIL。`run_tests`：0=所选单测档位符合预期；1=失败/错误；2=缺依赖或非预期跳过。`offline_acceptance`：0=冻结证据与负控符合预期；1=不符。`handoff_check`：0=技术交接三项检查通过；1=有检查失败。Python用法错误通常退出2。

发现CLI的2/PARTIAL可保留有效候选。离线验收脚本会明确检查它是预期退出，而不是忽略错误。不能将工具退出0统一映射“项目PASS”。

## 结构版本

保留上游 `project-discovery.v1`、`project-first-pass.v1`、`project-tests.evidence.v2`、`project-tests.execution.v1` 等格式；后两者完整性/结构通过不保证审批语义。

新增 `native-test.state.v2`：schema/binding/stages/elapsed。旧schema、未知stage、无效elapsed、坏JSON、软链接或摘要不符均BLOCK，不改写旧状态。stdout/stderr每文件上限1,000,000字节，触达上限记FAIL。输入树总量64MB/20,000普通项的保守上限，超过应拆分或人工设计新边界，不无限读取。

单次 `TaskResult.status=completed` 仅指当前stage完成；`raw_output.plan_status=PENDING` 表示未完成全部计划，`remaining_stages`和metrics明确列出；只有全部计划stage成功时validate_output才为真。`project_verdict`仍NOT_ACCEPTED，不自动批准业务或部署。

## 原始失败保留

不得修改 `process/` 与旧 `audit/` 中的历史记录。r3验证单独保存在 `audit/r3`。测试JSON精确区分discovered/passed/failures/errors/skipped/import_errors，不把115成功+3跳过写成118通过。

## 发行完整性与身份

SHA256SUMS校验全部常规文件、不含自身，拒绝额外文件和链接。归档以固定mtime/uid/gid/模式、排序与gzip时间0构建。旁车摘要无签名，必须通过独立渠道取得预期值才有更强来源可信度。当前不提供签名者身份、法律批准或外部透明日志。
