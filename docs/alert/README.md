# 注册式采集与检测

数据库保存来源、板块、检查项、异常策略、通知渠道和模型配置；导入文件只用于初始化或显式更新。模型与采集/检测独立，未选模型不影响采集。模块导入和 CLI 帮助不会启动 worker。

## 准备与注册

先在目标数据库按项目流程应用已跟踪的 alert 迁移，再运行注册。迁移会修改数据库，本次开发验证仅使用隔离 SQLite，没有迁移现场数据库。CLI 保持项目既有 master 分支启动检查；开发 worktree 的帮助测试只在测试进程中 mock 该检查。

```bash
cbok alert register
cbok alert list --kind all
cbok alert list --kind registry
```

默认注册腾讯要闻、财经、科技，每个板块有 page、feed、article 三个检查，间隔 300 秒。默认不创建通知收件人或模型配置。重复注册保留管理员改过的配置、启停状态、异常策略及渠道关联。只有 `--update` 才替换导入文件中明确提供的字段。

```bash
cbok alert register --file docs/alert/example.toml
cbok alert register --file docs/alert/example.toml --update
```

相对 `--file` 路径按实际 `CBOK_CONF` 文件所在目录解析；文件内的 `catalog` 路径按导入文件所在目录解析。支持 `.json` 和 `.toml`。Section 用 `source` key 引用来源；Check 用 `source` + `section` key 引用板块；来源的 `notification_channels` 是渠道 key 列表。导入在一个事务内完成；重复 key、无效引用、未知注册名、非正间隔及无效内置契约会报错并回滚。

## 手动运行

```bash
cbok alert collect --source tencent --section news --limit 5
cbok alert list --kind checks
cbok alert check --id 1
cbok alert check --id 1 --apply
cbok alert check --id 1 --apply --notify
```

采集只 upsert `CollectedItem`，不进入旧 Topic/模型/通知流程。`--limit` 范围为 1–100。

`check` 默认只记录本次 `CheckRun`，不修改事件、正式连续计数、下次执行时间或待投递记录。`--apply` 将结果纳入状态机；`--notify` 必须与 `--apply` 一起使用，才会为本次检查入队并调用通知投递。投递调用会处理已有到期队列，因此可能同时发送其他检查留下的有效待发通知。结果为 fail/unknown 表示检测发现问题；命令正常完成仍返回 0，参数/执行错误返回非零。

## 周期执行

```bash
cbok alert run --once
cbok alert run --interval 60
```

显式 worker 每轮顺序扫描到期项并投递已有队列。`--once` 只执行一轮，省略它将持续运行，Ctrl-C 退出。单项间隔来自数据库 `interval_seconds`；CLI `--interval` 控制扫描间隔。并发检查受数据库租约保护，单项失败不会中断其他检查。

可选 `cbok.conf` 配置：

```ini
[alert]
monitor_enabled = false
model_profile =
detector_paths =
```

`monitor_enabled=true` 允许既有 runserver 周期任务机制每 60 秒执行检测和投递，默认关闭。显式 `alert run` 是用户主动启动的 worker，不要求启用此开发 gate。不要同时无意启动多个 worker。额外检测插件目录用逗号分隔，相对 `CBOK_CONF` 解析，始终保留内置插件目录。

## 模型与通知

示例文件中的渠道、模型均禁用。启用 email 渠道前需配置有效收件人，SMTP 继续使用 CBoK 已有 `[email]` 设置。模型凭据只保存 `api_key_env` 环境变量名，不能内嵌 key；只有显式选中的后端才会初始化，失败不会自动切换后端。

```bash
cbok alert model_check --profile local-model --prompt '返回一个简单的 JSON 对象'
```

这条命令会实际调用模型，可能产生费用。旧 Topic 流程使用 `[alert] model_profile` 指定启用的 DB profile；未选择时报配置错误。检测与采集不会调用模型。

## 扩展

新增检测器只需在内置目录或配置的插件目录放置独立目录，包含 `manifest.toml` 和 Python 脚本，再注册对应 DB Check；无需修改核心 import。manifest 示例：

```toml
name = "custom_health"
protocol_version = 1
entrypoint = "check.py"
timeout = 10
max_output_bytes = 65536
```

脚本读取 stdin 单个协议 v1 JSON，stdout 返回 `{protocol_version,status,issues}`。status 为 pass/fail/unknown；pass 不得含 issues，非 pass 必须有 issues。issue 包含 `code`、`rule_id`、`message`，code 必须存在于中心异常目录或数据库 `AnomalyType`。脚本不应访问应用数据库或发送通知。

新异常类型可在中央 TOML 的 `[anomalies.CUSTOM_CODE]` 下定义并导入 `catalog`，也可通过 `anomaly_types` 登记 DB 元数据及策略。相同 code 的已有 DB 策略优先，普通同步不覆盖管理员配置。已有 `source_contract` 支持 required、equals、nonempty、type、min_items、html_selector；参数化增加检查不需要修改框架。需要新判断逻辑时新增检测脚本。

通知先持久化待投递记录，再由注册渠道发送；未配置启用渠道时仍保存检测及事件。过时或已被配置变更替代的待发事件会取消。SMTP 发送成功后进程若在记录成功前崩溃，仍可能重复投递；不能保证端到端严格恰好一次。

### 运行时隔离与投递边界

扫描只固定候选集合，每一项领取时重新读取时钟；检测租约为插件 timeout + 60 秒，投递租约为 360 秒。慢前项不会缩短后项租约。

运行时插件发现容错：坏 TOML、入口缺失只让对应检测不可用；重名时冲突名称全部不可用，其他健康插件继续执行。坏插件每次扫描最多记录 100 条有界诊断；可通过 `discover_detectors(paths, strict=False, diagnostics=[])` 获取同样诊断。注册/列举默认严格校验，便于部署前发现错误。

恢复或配置替代会取消尚未开始的旧投递；持有有效租约的发送者保留确认权。SMTP 成功后仍记录 `sent`。如果发送过程中已恢复，仅在该次恢复显式允许通知、当前策略允许且配置仍有效时，为该成功渠道补入恢复通知。`Incident.recovery_notify` 持久保存该次恢复的授权，`check --apply` 不带 `--notify` 不会因稍后发送完成而补发恢复。配置替代不代表恢复。失败返回后按当前状态取消或退避重试。

email 渠道可配置 `timeout`（秒，默认 30，必须为有限数且 `0 < timeout <= 30`），传给实际 Django SMTP 连接；旧邮件 API 调用不受影响。这个值约束每次 socket 操作，不是整个发送的硬总时限；大量收件人、多次协议交互、DNS 与持续缓慢响应仍可能延长总时长。360 秒数据库租约不能中断发送；严格总时限需要额外的传输/进程监督。扩展渠道的工厂和 `send` 必须在总计 300 秒内返回或抛错，并为 I/O 与重试设置预算，给落库保留 60 秒。不要把无法约束的阻塞实现注册成同步渠道。

新增 `0003_incident_recovery_notify` 迁移，已有事件默认不授权延迟恢复通知；已存在的 recovery 队列保持其既有状态。使用现有迁移流程升级，测试 SQLite 成功不代表现场迁移已完成。
