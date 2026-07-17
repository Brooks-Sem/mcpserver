# Brooks Model MCP

统一的 Codex、Claude 与 Grok 直接会话 MCP 服务，面向 VS Code、Claude Code 及其他支持 stdio MCP 的客户端。

## 设计

三个入口相互隔离：

- `mcp-codex`：调用本机 Codex CLI，复用 `~/.codex` 中的认证、模型与 API endpoint。
- `mcp-claude`：调用本机 Claude Code CLI，复用 `~/.claude` 中的认证、模型与 API endpoint。
- `mcp-grok`：调用 OpenAI 兼容的 Grok API；默认模型与思考强度由 server 环境配置，工具调用可按次覆盖。

Codex 和 Claude 使用上游 CLI 的原生 session/thread。Grok API 通常无服务端会话，本项目使用本机 SQLite 保存消息历史并提供可续接 session。

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
