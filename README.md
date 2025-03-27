# Deepin MCP

A client for connecting to MCP (Machine Conversation Protocol) servers and interacting with them using OpenAI language models.

## Overview

This MCP client allows you to:
1. Connect to an MCP server (Python or JavaScript)
2. List and use available tools from the server
3. Interact with the server using natural language queries
4. Process responses with OpenAI's language models
5. Plan and execute complex tasks automatically

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
   curl -LsSf https://astral.sh/uv/install.sh | bash

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
uv run python main.py
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

The project includes a powerful task planning system that can:
1. Break down complex user requests into sequential tasks
2. Execute tasks automatically using the MCP server
3. Provide detailed execution summaries

To use the task planning system:

```bash
python main.py
```

Or using UV (recommended):
```bash
uv run python main.py
```

You can also specify a custom server path:

```bash
python main.py --server path/to/your/server_script.py
```

Or check the version information:

```bash
python main.py --version
```

### Main Entry Point

The project provides a main entry point (`main.py`) that serves as the centralized entry point for the application:

```bash
python main.py
```

Or using UV (recommended):
```bash
uv run python main.py
```

The main entry point:
- Initializes the task planning system
- Provides version information and system description
- Handles exceptions gracefully
- Makes the application more user-friendly
- Allows specifying custom server paths with the `--server` option

Example usage:
```
$ python main.py

====== Deepin MCP 任务规划系统 ======
版本: 1.0.0
描述: 这是一个基于MCP协议的任务规划执行系统
======================================

欢迎使用任务规划执行系统
这个系统会将您的请求拆解为多个任务，并依次执行

已成功连接到服务器: /home/user/deepin-mcp-python/servers/bash_server.py

请输入您的请求 (输入'quit'退出): 
```

Example interaction:
```
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
3. The `TaskPlanner` class breaks down complex requests into tasks
4. The main entry point (`main.py`) provides a user-friendly interface
5. Error handling is implemented throughout for robustness

## Troubleshooting

If you encounter issues:
1. Check your API keys in `.env`
2. Verify the server script path is correct
3. Ensure the server implements the MCP protocol correctly
4. Check console output for error messages
5. Make sure you have required dependencies installed

## License

This project is available under the MIT License.

### Building Executable Binary

You can build a standalone binary executable that can be distributed without requiring Python installation:

#### Using the Build Script

The project includes a build script that simplifies the process:

```bash
# Make the build script executable
chmod +x build.sh

# Run the build script
./build.sh
```

The executable will be created in the `dist` directory as `deepin-mcp`.

#### Manual Build Process

If you prefer to build manually:

1. Install PyInstaller using UV:
   ```bash
   uv pip install pyinstaller
   ```

2. Build the executable:
   ```bash
   pyinstaller --clean deepin-mcp.spec
   ```

3. The executable will be available at `dist/deepin-mcp`

#### Running the Executable

Once built, you can run the executable directly:

```bash
# Run with default settings
./dist/deepin-mcp

# Check version
./dist/deepin-mcp --version

# Specify a custom server
./dist/deepin-mcp --server path/to/your/server_script.py
```

The executable includes all necessary dependencies and can be distributed to systems without Python installed.

### Server Discovery and Selection

The application automatically discovers and loads available server scripts:

1. When starting the application, it searches for server scripts in these locations:
   - The current working directory
   - The `servers` subdirectory
   - The application's executable directory
   - The `servers` subdirectory within the executable directory

2. Available servers can be listed with:
   ```bash
   ./deepin-mcp --list-servers
   ```

3. A specific server can be selected at startup:
   ```bash
   ./deepin-mcp --server bash
   # or by path
   ./deepin-mcp --server /path/to/custom_server.py
   ```

4. Servers can be switched during runtime by typing `switch` at the prompt.

### Server Deployment

When the application is packaged as a binary executable:

1. Server scripts are automatically deployed to the `servers` directory next to the executable
2. The application automatically finds and loads these servers
3. Each server is accompanied by a wrapper script (e.g., `bash_server.wrapper.py`) that ensures proper dependency loading
4. A dedicated Python environment with all necessary dependencies (including the `mcp` module) is created in the `server_env` directory
5. Custom servers can be added by placing them in the `servers` directory with a filename containing "server" (e.g., `custom_server.py`)
6. The `run_server.sh` helper script can be used to directly run any server

#### Running Servers Directly

You can run servers directly using the provided helper script:

```bash
# Run a server by name
./dist/deepin-mcp/run_server.sh bash

# Run a server by file name
./dist/deepin-mcp/run_server.sh bash_server.py

# Run a server by full path
./dist/deepin-mcp/run_server.sh /path/to/your/custom_server.py
```

This is particularly useful for:
- Testing server functionality independently
- Running servers in separate terminals
- Using custom server scripts with the application

#### Server Environment Structure

The packaged application includes a complete environment for the servers:

```
dist/deepin-mcp/
├── deepin-mcp          # Main executable
├── run_server.sh       # Server helper script
├── server_env/         # Python environment for servers
│   ├── mcp/            # MCP module and dependencies
│   ├── openai/         # OpenAI module
│   └── ...             # Other dependencies
└── servers/
    ├── bash_server.py          # Original server script
    ├── bash_server.wrapper.py  # Wrapper that configures path
    ├── file_server.py          # Original server script
    ├── file_server.wrapper.py  # Wrapper that configures path
    └── ...
```

#### Adding Custom Servers

To add custom servers to a packaged application:

1. Create your server script following the MCP protocol
2. Place it in the `servers` directory of the packaged application
3. Create a wrapper script that follows the same pattern as the included wrappers, or run the following command inside the dist/deepin-mcp directory:

```bash
cat > servers/myserver_server.wrapper.py << EOF
#!/usr/bin/env python
# Wrapper script for myserver_server.py
import os
import sys

# Add the server_env to the Python path
server_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server_env'))
sys.path.insert(0, server_env_path)

# Import the actual server code
server_file = os.path.abspath(os.path.join(os.path.dirname(__file__), 'myserver_server.py'))
with open(server_file, 'r') as f:
    server_code = f.read()

# Execute the server code with the modified path
exec(server_code)
EOF
chmod +x servers/myserver_server.wrapper.py
```

4. Run your custom server with the helper script or use it directly from the main application
