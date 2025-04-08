#!/bin/bash

# 编译单个服务器脚本
# 用法: ./compile_server.sh <server_name>
# 例如: ./compile_server.sh bash_server

set -e  # 遇到错误时退出

# 显示帮助信息
function show_help {
    echo "深度机器会话协议(MCP)服务器编译工具"
    echo "用法: $0 <server_name>"
    echo ""
    echo "参数说明:"
    echo "  <server_name>  服务器文件名（不需要.py后缀）"
    echo ""
    echo "示例:"
    echo "  $0 bash_server     # 编译 servers/bash_server.py"
    echo "  $0 weather_server  # 编译 servers/weather_server.py"
    echo ""
    echo "说明:"
    echo "  该脚本会将指定的服务器及其依赖编译到 dist/deepin-mcp/servers 目录中,"
    echo "  以便二进制程序能够正常调用这个服务器。"
    exit 0
}

# 检查命令行参数
if [ "$1" == "" ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    show_help
fi

SERVER_NAME="$1"

# 如果传入的是完整文件名带.py，截取前面的部分
SERVER_NAME="${SERVER_NAME%.py}"

# 检查服务器文件是否存在
SERVER_FILE="servers/${SERVER_NAME}.py"
if [ ! -f "$SERVER_FILE" ]; then
    echo "错误: 服务器文件 $SERVER_FILE 不存在。"
    echo "请确保文件名正确，并且位于 servers/ 目录中。"
    exit 1
fi

echo "====== 深度MCP服务器编译工具 ======"
echo "正在编译服务器: $SERVER_NAME"

# 创建输出目录
DIST_DIR="dist/deepin-mcp/servers"
SERVER_ENV_DIR="dist/deepin-mcp/server_env"
mkdir -p "$DIST_DIR"
mkdir -p "$SERVER_ENV_DIR"

# 确保使用正确的Python环境
PYTHON_CMD="python"
if [ -d ".venv" ]; then
    source .venv/bin/activate
    PYTHON_CMD="python"
fi

# 安装通用依赖到server_env目录 (如果有UV，优先使用)
if command -v uv &> /dev/null; then
    echo "正在使用UV安装依赖..."
    uv pip install mcp openai python-dotenv --target "$SERVER_ENV_DIR"
else
    echo "正在使用pip安装依赖..."
    $PYTHON_CMD -m pip install mcp openai python-dotenv --target "$SERVER_ENV_DIR"
fi

# 复制服务器文件到输出目录
echo "正在复制服务器文件..."
cp "$SERVER_FILE" "$DIST_DIR/"

# 识别服务器特定依赖并安装
echo "正在检查服务器特定依赖..."
SERVER_DEPS=$($PYTHON_CMD -c "
import ast, sys
with open('$SERVER_FILE', 'r') as f:
    tree = ast.parse(f.read())
imports = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for name in node.names:
            imports.add(name.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom) and node.module:
        imports.add(node.module.split('.')[0])
# 排除标准库和已安装的通用依赖
std_libs = {'os', 'sys', 'json', 'time', 'datetime', 'math', 're', 'random', 
            'subprocess', 'shlex', 'typing', 'pathlib', 'glob', 'mcp', 'openai',
            'sqlite3', 'csv', 'logging', 'tempfile', 'configparser', 'io',
            'argparse', 'collections', 'enum', 'uuid', 'base64', 'copy', 'functools',
            'hashlib', 'itertools', 'urllib', 'zlib', 'platform', 'importlib'}
deps = imports - std_libs
print(' '.join(deps))
")

if [ ! -z "$SERVER_DEPS" ]; then
    echo "检测到额外依赖: $SERVER_DEPS"
    if command -v uv &> /dev/null; then
        uv pip install $SERVER_DEPS --target "$SERVER_ENV_DIR"
    else
        $PYTHON_CMD -m pip install $SERVER_DEPS --target "$SERVER_ENV_DIR"
    fi
fi

# 创建服务器wrapper脚本（与build.sh脚本保持一致）
echo "正在创建服务器wrapper脚本..."
cat > "$DIST_DIR/${SERVER_NAME}.wrapper.py" << EOF
#!/usr/bin/env python
# Wrapper script for ${SERVER_NAME}.py
import os
import sys

# Add the server_env to the Python path
server_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server_env'))
sys.path.insert(0, server_env_path)

# Import the actual server code
server_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '${SERVER_NAME}.py'))
with open(server_file, 'r') as f:
    server_code = f.read()

# Execute the server code with the modified path
exec(server_code)
EOF

chmod +x "$DIST_DIR/${SERVER_NAME}.wrapper.py"

# 创建服务器配置文件
echo "正在创建服务器配置文件..."
cat > "$DIST_DIR/${SERVER_NAME}_config.json" << EOF
{
    "name": "${SERVER_NAME}",
    "description": "自动编译的MCP服务器",
    "version": "1.0.0",
    "wrapper": "${SERVER_NAME}.wrapper.py",
    "compile_time": "$(date)"
}
EOF

echo "编译完成！"
echo "服务器文件已安装到: $DIST_DIR/${SERVER_NAME}.py"
echo "服务器包装器位于: $DIST_DIR/${SERVER_NAME}.wrapper.py"
echo "服务器依赖已安装到: $SERVER_ENV_DIR"
echo ""
echo "服务器可通过以下方式调用:"
echo "1. 使用主程序: ./dist/deepin-mcp/deepin-mcp --server ${SERVER_NAME}"
echo "2. 直接运行包装器: python $DIST_DIR/${SERVER_NAME}.wrapper.py"
echo "3. 使用服务器运行脚本: ./dist/deepin-mcp/run_server.sh ${SERVER_NAME}" 