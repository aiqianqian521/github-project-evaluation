# 环境、依赖与支持矩阵

## 运行层次

| 档位 | 依赖 | 本次验证范围 |
| --- | --- | --- |
| core | Python>=3.11、Git、标准库 | 哈希校验、缓存离线重放、只读首评/设计结构检查 |
| portable | core + 支持Ed25519的可信OpenSSL3 | 工具单元回归；Loop显式测试容器；3项Linux集成跳过 |
| full | portable + Linux + 显式可信BWRAP_BINARY + 外部Loop与合同摘要pin | 适配器合同/有限namespace探针；无调度器E2E承诺 |
| production | 项目专属审批、oracle、锁定依赖、经审计worker/cgroup、独立review | 本包不授予，必须另立任务 |

本次portable在macOS ARM64/Python3.14.2/OpenSSL3.6.1实际执行；Python3.11+是代码最低要求而非所有小版本已测声明。Linux full 尚未在本次现场验证。Windows不支持fcntl/resource，未列入支持范围。

## OpenSSL

不替换系统二进制、不偷偷下载。默认找PATH中的openssl，或设置 `OPENSSL_BINARY` 为经核实的绝对路径。doctor检查签名算法，测试再实际生成、签名和验签。macOS自带LibreSSL往往不满足，doctor portable返回2是正确结果；已安装Homebrew OpenSSL示例见README。

## 外部Loop

本包不包含Loop引擎。先由维护人从可信发行渠道提供真实引擎，核实其版本、完整发行摘要与审批来源；本包只校验以下合同文件pin，不声称它能认证整个引擎。

```sh
export LOOP_TEST_ENGINE_ROOT=/absolute/path/to/reviewed/loop-engine
# 从独立可信渠道获取预期摘要，不要把本机现算值自动当可信锚。
export LOOP_CONTRACT_SHA256='<approved sha256 of adapters/task_runner.py>'
export BWRAP_BINARY=/absolute/path/to/reviewed/bwrap
python3 -B tools/doctor.py --profile full
python3 -B tools/run_tests.py --profile full --output ../r3-full-tests
```

缺依赖或pin不匹配时full不导入伪引擎，也不退回portable，直接BLOCK/退出2。即使合同单测成功，checkpoint/retry/journal/副作用幂等等调度器E2E仍需另测。

## 缓存和原生状态迁移

缓存目录0700、调用者拥有；条目0600；并发写中数据与元数据不匹配会拒绝/降级，不保证共享缓存事务一致。旧缓存复制到新private目录后可重放，不更改原件。

native state v2绑定spec原始字节、源码树与Git HEAD/clean状态、执行器、可执行文件及直接文件argv、平台。状态/日志必须是有界普通文件，恢复时核对摘要。不兼容旧v1，不能靠补字段将旧成功变为新批准。完整运行时依赖树、系统库和解释器import路径不是全量锁定，仍需外部不可变worker镜像/依赖锁。

## Python依赖

工具本身仅标准库，无pip安装步骤和网络依赖解析。Git/OpenSSL/bwrap为外部二进制，不应混入“pip依赖锁”。第三方样本的pytest/setuptools等未安装、未代其锁定；样本仅静态分析。
