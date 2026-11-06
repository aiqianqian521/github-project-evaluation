# MarkupSafe DESIGN 交接

设计完成 ≠ 测试通过。当前 DESIGN-REVIEW-BLOCKED；没有人审批准、执行授权或生产部署结论。

| 材料 | 来源 | 责任与用途 |
| --- | --- | --- |
| 冻结仓库与版本 | `evidence/repository/github-markupsafe-4e111271.bundle` | 接手维护者离线恢复，不运行源码 |
| 逐文件身份 | `examples/markupsafe/SOURCE-MAP.json` | 验证源码摘要与引用，不能代替上游实时身份 |
| 目标适配初审 | `examples/markupsafe/FIRST-PASS-ASSESSMENT.md` | Agent 静态建议，需独立人审 |
| 预声明 oracle | `examples/markupsafe/ORACLE-SPEC.json` | 先冻结预期，禁止从被测输出回填 |
| 功能/压力计划 | `examples/markupsafe/FUNCTIONAL-TEST-DESIGN.md`、`examples/markupsafe/PRESSURE-TEST-DESIGN.md` | 仅设计，全部 NOT-RUN |

## 五项独立审阅

| check | reviewer | evidence | decision | owner/retest |
| --- | --- | --- | --- | --- |
| source 来源与逐文件指纹 | 接收方独立审阅者待指定 | SOURCE-MAP 与 offline_acceptance 日志 | PENDING，不自签 | 接收方维护负责人；恢复后核对全部引用 |
| risk 风险到用例映射 | 项目 owner 待指定 | 功能 F-ESCAPE 至 F-RECOVERY | PENDING，不自签 | 项目 owner；确认目标与上下文 |
| oracle 独立真值 | 非作者测试的审阅者待指定 | ORACLE-SPEC 与独立解析器设计 | PENDING，不自签 | 测试负责人；冻结期望后签字 |
| load 容量与边界 | 资源/负载 owner 待指定 | P-BASE 至 P-RECOVERY 与拟议上限 | PENDING，EXECUTE BLOCK | 资源 owner；签 SLO、隔离/配额和停止条件 |
| redact 敏感信息 | 数据/安全审阅者待指定 | 合成输入策略、无生产凭据声明 | PENDING，不自签 | 数据/安全负责人；检查实际运行日志 |

## 执行授权表（必须由接收方填写）

当前状态：NOT_AUTHORIZED。审批人、审批时间/工单、允许 argv、禁止动作、网络边界、数据范围、运行环境摘要、总预算和紧急停止 owner 均须具体填定。缺任一项停在 DESIGN，不复制历史账号/口令，不自动执行测试/构建/压力命令。

## 已知 BLOCK 与下一步

上游身份未在本次重新在线验证；依赖未离线锁定；独立 oracle/负载阈值和法律批准未签字；真实 C/Python 路径和压力未执行。接收方先运行只读 offline_acceptance，决定是否继续授权测试，再新建 run_id；旧失败和历史 PARTIAL 必须保留。
