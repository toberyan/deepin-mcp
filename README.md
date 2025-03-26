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
