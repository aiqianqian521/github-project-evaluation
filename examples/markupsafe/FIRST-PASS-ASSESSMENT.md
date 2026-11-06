# MarkupSafe：人工可接手的静态首评

日期：2026-10-26；审阅方式：Agent 静态阅读，不是独立人审签字。
身份：`pallets/markupsafe@4e111271b1494995708a9e878a10829b5e10c7ba`。
来源：包内 `evidence/repository/github-markupsafe-4e111271.bundle`；逐文件指纹见 `SOURCE-MAP.json`。

## 目标与结论

目标限定为：将未受信普通字符串放入 HTML 文本节点，五种特殊字符转义后保持原文本语义。
静态判断：适合进入独立测试设计，不授予“目标已满足”。`goal_fit=STATIC_REVIEW_CANDIDATE`，业务验收 `NOT_REVIEWED`，部署/执行授权 `BLOCK`。
不包括 URL 方案校验、JS/CSS 字符串安全、任意 HTML 属性、HTML 净化或任意 XML 解析器适配。

| MUST | 源码证据 | 静态判断 | 后续反例与门禁 |
| --- | --- | --- | --- |
| 五字符转义 | `src/markupsafe/_native.py:1` 与 `src/markupsafe/__init__.py:24` | Python 路径可见明确转换表 | F-ESCAPE 与独立逐字符真值比对，不以作者结果作 oracle |
| 不对普通文本引入新标签 | `src/markupsafe/_native.py:3` | 字符替换机制与该目标相符 | F-HTML 使用独立 HTML 解析器验证文本节点 |
| 不误信任对象协议 | `src/markupsafe/__init__.py:42`、`:84` | 有明确安全标记绕过，必须限制调用方输入 | F-TRUST 对不可信 __html__/Markup 的误用必须作为预期拒绝的集成负控 |
| Python/C 两路径一致 | `src/markupsafe/__init__.py:7` | 自动选择扩展或回退；尚未执行任一路径 | F-PARITY；C 编译需独立授权 |
| 可追溯版本与许可证 | `pyproject.toml:3`、`:6`、`:19`、`LICENSE.txt` | 开发快照 3.1.0.dev、BSD-3-Clause、Python>=3.11 | 版本选择/法律批准仍由 owner 完成，不把 classifier 当生产准出 |

## 已知问题与依赖

- `README.md:22` 与 `README.md:23`、`:25` 与 `:26` 的 Hello/hello 不一致，确认为文档差异，未执行实现验证。
- `__html__` 和 Markup 表示调用者主动信任，不是净化器；普通文本 oracle 不适用于已标记安全对象。
- 运行库本体的 Python 路径主要用标准库；构建依赖为 `setuptools>=77`，测试依赖包含 pytest 和条件并发插件，当前未锁定、未安装。
- 包内历史 72/100 与当前离线 62/100 是清单得分，不作为本人工评估评分。
- 需要独立 reviewer、目标/SLO owner、许可批准、可信隔离 worker；没有这些条件只能交 DESIGN，不能开跑 EXECUTE。

## 交接

阅读本目录的三份设计、`ORACLE-SPEC.json` 和 `SOURCE-MAP.json`。首评补全的是可读的目标映射，不将历史 `FIRST-PASS.json` 的 NOT_REVIEWED 篡改为已批准。所有行为用例保持 NOT-RUN。
