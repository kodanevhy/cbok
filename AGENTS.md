# CBoK Project Rules

本文件是 CBoK 仓库的项目级常驻规则，作用域为整个仓库。

## Scriptlet 复用

- 新增或修改涉及 shell、远端主机、Kubernetes、Git、proxy、ZSphere、部署/拷贝/备份等流程时，优先复用 `scriptlet/`。
- 可复用的 shell 逻辑应放进 `scriptlet/lib/*.sh`，并从 `scriptlet/bootstrap.sh` 统一 source/export；不要把可复用流程散落成一次性的内联 bash。
- Python 命令需要调用 shell 流程时，优先通过 `bash -lc "source scriptlet/bootstrap.sh; ..."` 调用已有函数。
- 远端执行前应确保远端脚本可用：命令类方法有地址参数时优先使用 `@args.requires_remote_scriptlet("address")` 或显式调用 `self.ensure_remote_scriptlet(address)`。
- 新增 scriptlet 函数时保持幂等、可组合：使用明确参数，失败时返回非 0 或 `die`，日志走 `log_info`/`log_warn`/`log_debug`，依赖命令用 `require_cmd` 检查。

## 新增 `cbok` CLI 命令规范

- CLI 入口在 `cbok/cmd/main.py`，命令按类别挂到 `CATEGORIES`；新增类别时创建/扩展 `cbok/cmd/<category>.py` 中的 `*Commands` 类，并注册到 `CATEGORIES`。
- 新增命令使用 `BaseCommand` 子类的公开方法实现；方法名就是命令名，避免下划线开头，避免和 `BaseCommand` 公开方法重名。
- 每个命令必须有清晰 docstring，参数用 `@args.args(...)` 声明，命令说明用 `@args.action_description(...)` 保持帮助信息可读。
- 命令方法应返回进程退出码：成功返回 `0`，可恢复/用户输入类错误返回非 0；避免在深层 helper 中随意 `sys.exit()`，除非已有同类代码模式要求。
- 用户输入、路径、远端地址等进入 shell 前必须正确引用；Python 拼 shell 字符串时使用 `shlex.quote`，能用参数列表时优先用参数列表。
- 复杂流程放到领域模块或 `scriptlet` 中，`cbok/cmd/*` 只负责参数解析、日志、调用编排和返回码映射。
- 远端命令、部署命令、会修改环境状态的命令应有前置校验、明确日志和失败返回码，避免静默部分成功。
- 新增命令后至少做一次最小验证：`cbok <category> <command> --help` 可用；有实际逻辑的命令补充相应单元测试或可复现的手动验证说明。
