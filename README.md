# Brooks Model MCP

统一的 Codex、Claude 与 Grok 直接会话 MCP 服务，面向 VS Code、Claude Code 及其他支持 stdio MCP 的客户端。

## 设计

三个入口相互隔离：

- `mcp-codex`：调用本机 Codex CLI，复用 `~/.codex` 中的认证、模型与思考强度；默认启用原生实时网页搜索。
- `mcp-claude`：调用本机 Claude Code CLI，复用 `~/.claude` 中的认证与模型；暴露按次思考强度并默认允许 `WebSearch`/`WebFetch`。
- `mcp-grok`：调用 OpenAI 兼容的 Grok API；默认模型与思考强度由 server 环境配置，默认通过 Responses API 使用 `web_search`。

Codex 和 Claude 使用上游 CLI 的原生 session/thread。Grok API 通常无服务端会话，本项目使用本机 SQLite 保存消息历史并提供可续接 session。

## 对话、长文本与权限

- 三个首轮工具都返回 `sessionId`，后续分别传给 `codex_reply`、`claude_reply`、`grok_reply` 即可连续对话。
- Codex/Claude 的输入通过 stdin 传给 CLI，Grok 通过 HTTP JSON 发送；代码不按字符数静默截断输入。
- Codex 使用原生 JSONL 事件流，Claude 使用 `stream-json`；server 会消费实时事件并通过 MCP progress notification 发送节流后的状态摘要。状态摘要不包含 prompt、模型正文或命令输出。
- 最终响应仍是一次完整的结构化 MCP 结果，不是多次 token 结果。客户端只有在调用时提供 progress token 且实现了相应 UI 时才会展示中间状态；超长输出仍宜分轮索取，需要产出大型文档时，只在明确授权写入后交给 Codex 保存到工作区。
- Codex/Claude 的上下文管理由各自 CLI 负责。Grok 将本地 SQLite 中的完整消息历史随续聊请求重发，达到模型上下文上限后应开启新 session 或先请求压缩摘要。
- 默认权限是只读：Codex 默认 `sandbox=read-only`，Claude 固定 `permission-mode=plan` 且只开放读取和网页工具，Grok 不开放本地文件工具。
- 只有 Codex 可在单次调用中显式指定 `sandbox=workspace-write`。不建议让多个外部模型并发修改同一工作区；更稳妥的模式是三者研究/审查，主代理统一落盘。
- 三者的 `web_search` 参数默认均为 `true`，可按调用设为 `false`。搜索能力仍受上游账号、组织策略及兼容 API endpoint 支持情况约束。

## 超时与取消

- Codex/Claude 没有总运行时限，只受“连续无任何输出”的空闲时限约束，默认 300 秒。只要 stdout 或 stderr 仍间歇产生数据，调用就可以无限运行。
- 通过 `MODEL_MCP_CLI_IDLE_TIMEOUT_SECONDS` 调整空闲阈值；值必须为正数。旧的 `MODEL_MCP_CLI_TIMEOUT_SECONDS` 不再读取，也不会形成隐藏的 900 秒上限。
- 达到连续静默阈值或 MCP 调用被取消时，server 会终止当前上游进程并清理管道；Windows 使用 Job Object 回收整个子进程树。
- Grok 使用 `GROK_TIMEOUT_SECONDS` 控制 HTTP connect/read/write/pool 超时，默认 180 秒。无响应超时不会自动重试；明确的临时 HTTP 状态或连接失败仍受 `GROK_MAX_RETRIES` 约束。
- 超时只关闭当前无响应调用，不关闭 MCP server。后续仍可发起新 session；超时 turn 不应继续复用，避免上游历史处于不确定状态。
- MCP progress 是可选通知，不保证覆盖宿主客户端自身设置的固定工具调用硬超时。如果宿主仍在某个固定时长中止调用，需要同时调整宿主的 MCP/tool timeout 配置。

## 安全边界

- API key、token、SQLite session、日志和本地配置不会进入 Git。
- prompt 通过 stdin 传给 Codex/Claude，不拼接 shell 命令。
- Codex/Claude 默认只读。
- Grok key 只从 server 进程环境读取，不接受 MCP 工具参数传入，也不会在诊断结果中回显。

## Conda 环境

Conda 仅用于开发、测试和发布前验收，不进入 MCP 客户端启动链：

```powershell
conda env create -f environment.yml
conda activate mcpserver
pytest
ruff check .
```

已有环境可更新：

```powershell
conda activate mcpserver
python -m pip install -e ".[dev]"
```

## MCP 配置

客户端配置严格使用 `uvx --from git+https://...`，与 Claude Code 中现有 Git MCP 的配置方式一致。生产配置必须锁定 tag 或 commit：

```json
{
  "servers": {
    "codex": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Brooks-Sem/mcpserver.git@v0.1.0",
        "mcp-codex"
      ]
    },
    "claude": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Brooks-Sem/mcpserver.git@v0.1.0",
        "mcp-claude"
      ]
    },
    "grok": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Brooks-Sem/mcpserver.git@v0.1.0",
        "mcp-grok"
      ],
      "env": {
        "GROK_API_URL": "${input:grok-api-url}",
        "GROK_API_KEY": "${input:grok-api-key}",
        "GROK_MODEL": "grok-4",
        "GROK_REASONING_EFFORT": "high"
      }
    }
  }
}
```

完整模板位于 `configs/`。新机器只需安装 Git、uv、Codex CLI 和 Claude Code CLI；`uvx` 会从 Git tag 创建并缓存隔离环境。

不要在长期配置中省略 `@v0.1.0`。直接跟随 `main` 会让未经本机验收的更新自动进入三个 MCP server。

## Grok 配置

Grok 没有被本项目依赖的本地 CLI 会话层。server 从进程环境读取：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `GROK_API_URL` | OpenAI 兼容 API base URL | 必填 |
| `GROK_API_KEY` | API key，只允许本机配置 | 必填 |
| `GROK_MODEL` | server 默认模型 | `grok-4` |
| `GROK_REASONING_EFFORT` | 默认思考强度：low/medium/high/xhigh/max | `high` |
| `GROK_REASONING_FIELD` | 兼容 endpoint 的请求字段；空值表示不发送 | `reasoning_effort` |
| `GROK_TIMEOUT_SECONDS` | 请求超时 | `180` |
| `GROK_MAX_RETRIES` | 可重试请求次数 | `3` |

`grok` / `grok_reply` 工具允许按次覆盖 `model` 与 `reasoning_effort`，但不接受 key 或 API URL 参数。Grok session 存储于本机 SQLite，不上传 Git。

## 验证

```powershell
.\scripts\doctor.ps1
conda run -n mcpserver pytest
conda run -n mcpserver ruff check .
```

发布后验证远程 tag：

```powershell
uvx --from "git+https://github.com/Brooks-Sem/mcpserver.git@v0.1.0" mcp-doctor
```
