# MarkupSafe 功能测试设计

## 项目画像与证据边界

冻结 `pallets/markupsafe@4e111271b1494995708a9e878a10829b5e10c7ba`。离线恢复路径为 `evidence/repository/github-markupsafe-4e111271.bundle`，逐文件摘要见 `examples/markupsafe/SOURCE-MAP.json`。源码引用均相对恢复后的 checkout，例如 `src/markupsafe/_native.py:1`。本轮只静态阅读，没有安装、导入或执行第三方代码。

## 功能风险地图

五字符遗漏/顺序错、空值和 Unicode、HTML 上下文混用、__html__ 信任边界、Markup 非净化器、C/Python 差异、异常对象、格式化参数、超大输入与重复转义。作者用例只作输入线索，不作独立 oracle。

## 功能用例账本

| ID | 需求/入口 | 前提与输入 | 独立 oracle | 失败信号/证据 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F-ESCAPE | 五字符，`_native.py:1` | 授权隔离中按 ORACLE-SPEC 枚举字符及组合 | 预先冻结逐字符映射拼接，不调用被测库生成期望 | 字节串不等；记录输入/期望/实际/exit | NOT-RUN |
| F-UNICODE | `__init__.py:24` | 空串、中文、emoji、组合字符、NUL | 独立逐字符映射，只改变五种 ASCII 字符 | 非目标字符变化/异常；原始日志 | NOT-RUN |
| F-HTML | 文本节点集成 | 用无害闭合标签样本作为普通字符串 | 独立 HTMLParser，容器只保留一个文本内容且无新增标签 | 节点新增或文本不等；解析器结果 | NOT-RUN |
| F-TRUST | `__init__.py:42` 与 Markup | 普通字符串和带 __html__ 对象成对输入 | 普通字符串必须转义；安全标记会信任，调用方必须拒绝外部可控对象 | 将对象误当普通文本安全即 FAIL；调用方拒绝日志 | NOT-RUN |
| F-PARITY | `__init__.py:7` | 两种路径均在经批准构建的副本中可用 | 分别与固定字符表比对，而非仅两实现互比 | 任一路径偏离独立期望；版本/构建与日志 | NOT-RUN |
| F-ERROR | escape/format | __html__ 或 __str__ 抛异常、自定义对象边界 | 事先冻结异常传播契约，无静默不可信输出 | 吞异常、污染后续调用；异常日志 | NOT-RUN |
| F-MARKUP | Markup/escape_silent/format | 字符串、None、已标记对象与插值 | 预声明 None 契约；插入普通参数按独立表转义 | 不应信任的参数未转义；逐例日志 | NOT-RUN |
| F-RECOVERY | 全入口 | 正常→异常→正常三段、任务中断 | 后续新调用与前置基准相同；中断不复用旧成功 | 恢复不一致或旧证据被覆盖；run_id 证据 | NOT-RUN |

## 环境与准入

Python>=3.11；源码与 SOURCE-MAP 一致；批准的离线依赖镜像、独立 worker、无宿主凭据/生产网络、只读源码、可写工作副本。执行 owner 与 reviewer 未签字，DESIGN-REVIEW-BLOCKED。任何安装/编译/运行必须另行授权。

## 执行顺序与判据

授权与依赖/资源预检→F-ESCAPE/F-UNICODE→F-HTML/F-TRUST→F-PARITY→F-ERROR/F-MARKUP/F-RECOVERY。真值缺失为 BLOCK；任一关键字符或上下文负控失败为 FAIL，不用作者测试洗白。每例留 stdout/stderr/exit 和源/构建/任务指纹。遇到边界失效立即终止，不进入压力阶段。

## 准出与交付

逐例账本、原始证据、失败定位、独立人审、批准的范围/SLO 才能支持对应目标准出。设计完成不代表被测项目通过；当前所有用例 NOT-RUN，部署 BLOCK。
