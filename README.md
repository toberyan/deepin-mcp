# MCP Client

A client for connecting to MCP (Machine Conversation Protocol) servers and interacting with them using OpenAI language models.

## Overview

This MCP client allows you to:
1. Connect to an MCP server (Python or JavaScript)
2. List and use available tools from the server
3. Interact with the server using natural language queries
4. Process responses with OpenAI's language models

## Setup

### Prerequisites

- Python 3.12 or higher
- OpenAI API key
- MCP server to connect to

### Installation

1. Clone this repository
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -e .
   ```
4. Create a `.env` file with your API keys:
   ```
   OPENAI_API_KEY=your_openai_api_key
   ```

## Usage

Run the client by specifying the path to your MCP server script:

```bash
python client.py path/to/your/server_script.py
```

Or for JavaScript servers:

```bash
python client.py path/to/your/server_script.js
```

### Interactive Mode

Once connected, you can enter queries in the interactive prompt. The client will:
1. Send your query to the language model
2. Process any tool calls requested by the model
3. Return the final response

Type `quit` to exit the interactive mode.

## Available Servers

### Weather Server

The `weather_server.py` provides an MCP tool to query weather information for a specified city.

```bash
python client.py weather_server.py
```

Example query: "查询北京的天气"

### File Server

The `file_server.py` provides MCP tools for file operations like open, copy, move, rename, delete, and create files.

```bash
python client.py file_server.py
```

Example query: "创建一个名为test.txt的文件"

### Bash Server

The `bash_server.py` provides MCP tools for executing Linux bash commands.

```bash
python client.py bash_server.py
```

Available tools:
- `run_bash`: 执行指定的Bash命令并返回结果，支持普通模式和shell模式
- `list_available_commands`: 列出常用的Bash命令
- `get_command_help`: 获取特定命令的帮助信息
- `system_info`: 获取系统信息摘要

这个服务器允许执行任何系统命令，无安全限制。用户可以执行任何bash命令，包括系统管理、文件操作、网络操作等命令。支持用户环境变量、主目录(~)展开，以及shell特性（管道、重定向、通配符等）。

执行模式:
1. 普通模式: 适合执行单个命令
   例如: "执行ls命令，显示当前目录内容"

2. Shell模式: 支持复杂的shell功能
   例如: "使用shell模式执行 find . -name '*.py' | wc -l 命令"
   例如: "使用shell模式和管道统计目录中的文件数量"

Example queries:
- "执行ls命令，显示当前目录内容"
- "查看/etc/hosts文件内容" 
- "使用sudo apt update更新系统"
- "执行find命令查找大文件"
- "使用wget下载文件"
- "显示当前的环境变量"
- "使用shell模式执行 cat file.txt > output.txt"
- "通过管道过滤命令输出结果"

### Error Handling

The client includes error handling for:
- Keyboard interrupts (Ctrl+C)
- Connection errors
- API errors
- Tool execution errors

## Tool Call Error Handling

The MCP client now features a sophisticated error-handling mechanism for tool calls:

1. **Error Detection**: 自动识别工具调用失败的情况，包括通过异常或工具响应中的错误消息。系统能识别多种中英文错误模式，包括"失败"、"不存在"、"无法"、"错误"、"未找到"、"无效"等关键词，以及英文的"error"、"exception"、"failed"等。

2. **Error Analysis**: 使用AI分析错误根本原因并提出潜在解决方案。分析过程关注问题核心，提供简明扼要的分析结果。

3. **Automatic Retry**: 基于错误分析，客户端自动生成修正后的参数或替代方案，重试工具调用。系统使用tool_choice="auto"参数强制模型使用工具，确保始终生成新的工具调用方案。

4. **Multiple Retry Levels**: 实现了多级重试机制。初次失败后会进行智能分析并重试，如果仍然失败，系统会进行最后一次尝试，进一步修正参数重新调用工具。

5. **Focused Responses**: 无论是工具调用成功还是失败，系统都确保模型的回复简洁明了，专注于结果或解决方案，避免不必要的发散讨论。

6. **Temperature Control**: 通过调整模型温度参数，确保错误处理过程中的回复更加可控和专注。

7. **Graceful Fallback**: 如果多次重试都失败，提供有意义的错误消息，包含关于失败原因的详细信息，并提示用户手动修正。

这种强大的错误处理机制即使在工具调用遇到问题时也能保持流畅的对话流程，大大改善了用户体验。与传统简单的错误处理相比，新机制能够智能分析错误并自动尝试修复，让用户感受不到复杂的错误处理过程。用户不需要手动重新尝试，系统会自动进行多次智能重试，直到成功或穷尽所有可能性。

## Development

To extend or modify this client:

1. The `MCPClient` class handles the main functionality
2. The `process_query` method processes queries using the LLM
3. Error handling is implemented throughout for robustness

## Troubleshooting

If you encounter issues:
1. Check your API keys in `.env`
2. Verify the server script path is correct
3. Ensure the server implements the MCP protocol correctly
4. Check console output for error messages

## License

This project is available under the MIT License.
