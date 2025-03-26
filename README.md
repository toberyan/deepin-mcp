# Deepin MCP

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

### Installing UV (Recommended)

UV is a fast, reliable Python package installer and resolver. It's recommended for this project:

1. Install UV:
   ```bash
   # Unix (macOS, Linux)
   curl -sSf https://astral.sh/uv/install.sh | bash

   # Windows (PowerShell)
   irm https://astral.sh/uv/install.ps1 | iex
   ```

2. Verify installation:
   ```bash
   uv --version
   ```

For more installation options, visit [UV's official documentation](https://github.com/astral-sh/uv).

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
   Or using UV (recommended):
   ```bash
   uv venv
   uv pip install -e .
   ```
4. Create a `.env` file with your API keys and configuration:
   ```
   # OpenAI API Configuration
   OPENAI_API_KEY=your_openai_api_key
   BASE_URL=https://api.openai.com/v1  # Optional: Use your own OpenAI API proxy
   MODEL=gpt-3.5-turbo  # Optional: Specify the model to use
   ```

5. Install required dependencies:

   Using UV (recommended):
   ```bash
   # Install core dependencies
   uv pip install -e .
   
   # Or install individual packages
   uv add openai  # OpenAI API client
   uv add python-dotenv  # For loading environment variables
   uv add mcp  # Machine Conversation Protocol library
   ```

   Using standard pip:
   ```bash
   pip install openai python-dotenv mcp
   ```

   Each server type may require additional dependencies:
   ```bash
   # For JavaScript servers
   uv add node-fetch  # If connecting to JavaScript MCP servers
   
   # For additional functionality
   uv add asyncio  # For asynchronous operations
   uv add pathlib  # For file path handling
   ```

## Usage

### Quickstart with UV

Get up and running quickly with UV:

```bash
# Clone the repository
git clone https://github.com/yourusername/deepin-mcp-python.git
cd deepin-mcp-python

# Install UV
curl -sSf https://astral.sh/uv/install.sh | bash

# Create a virtual environment and install dependencies
uv venv
uv pip install -e .

# Create .env file (replace with your actual API key)
echo "OPENAI_API_KEY=your_openai_api_key" > .env
echo "MODEL=gpt-3.5-turbo" >> .env

# Run the client with bash server
uv run python client.py servers/bash_server.py

# Or run the task planning system
uv run python planning.py
```

### Basic Usage

Run the client by specifying the path to your MCP server script:

```bash
python client.py path/to/your/server_script.py
```

Or using UV:
```bash
uv run python client.py path/to/your/server_script.py
```

For JavaScript servers:

```bash
python client.py path/to/your/server_script.js
```

Or using UV:
```bash
uv run python client.py path/to/your/server_script.js
```

### Task Planning System

The project includes a powerful task planning system (`planning.py`) that can:
1. Break down complex user requests into sequential tasks
2. Execute tasks automatically using the MCP server
3. Provide detailed execution summaries

To use the task planning system:

```bash
python planning.py
```

Or using UV (recommended):
```bash
uv run python planning.py
```

Example interaction:
```
Welcome to the Task Planning System
This system will break down your request into multiple tasks and execute them sequentially

请输入您的请求 (输入'quit'退出): Create a new directory called 'projects' and copy all .txt files from 'documents' to it

正在分析您的请求...
已将您的请求拆解为 3 个任务:
1. Create a new directory called 'projects'
2. List all .txt files in the 'documents' directory
3. Copy all .txt files from 'documents' to 'projects'

是否执行这些任务? (y/n): y

[Task execution progress will be shown here]

执行总结:
[Detailed summary of the executed tasks will be shown here]
```

The task planning system is particularly useful for:
- Complex file operations
- Multi-step system configurations
- Automated workflow execution
- Batch processing tasks

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

Or using UV:
```bash
uv run python client.py weather_server.py
```

Example query: "查询北京的天气"

Dependencies:
```bash
uv add requests  # For HTTP requests to weather APIs
```

### File Server

The `file_server.py` provides MCP tools for file operations like open, copy, move, rename, delete, and create files.

```bash
python client.py file_server.py
```

Or using UV:
```bash
uv run python client.py file_server.py
```

Example query: "创建一个名为test.txt的文件"

Dependencies:
```bash
uv add pathlib  # For file path handling
```

### Bash Server

The `bash_server.py` provides MCP tools for executing Linux bash commands.

```bash
python client.py bash_server.py
```

Or using UV:
```bash
uv run python client.py bash_server.py
```

Example query: "列出当前目录下的所有文件"

Dependencies:
```bash
uv add shlex  # For shell command parsing
```

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
