#!/bin/bash

# Exit on error
set -e

# Display info
echo "Starting build process for deepin-mcp..."

# Activate environment if needed (uncomment if necessary)
# source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
uv pip install pyinstaller anthropic httpx mcp openai python-dotenv

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/

# Build the binary
echo "Building binary..."
pyinstaller --clean deepin-mcp.spec

# Create servers directory in the right location
echo "Setting up servers directory..."
mkdir -p dist/deepin-mcp/servers

# Copy server files from _internal to servers directory
echo "Copying server files to the correct location..."
find dist/deepin-mcp/_internal/servers -name "*.py" -exec cp -v {} dist/deepin-mcp/servers/ \;

# Create a Python venv with required packages for servers
echo "Creating Python environment for servers..."
mkdir -p dist/deepin-mcp/server_env
uv pip install mcp openai python-dotenv --target dist/deepin-mcp/server_env

# Create wrapper scripts for each server
echo "Creating server wrapper scripts..."
for server_file in dist/deepin-mcp/servers/*.py; do
    base_name=$(basename "$server_file")
    wrapper_path="dist/deepin-mcp/servers/${base_name%.py}.wrapper.py"
    
    # Create a wrapper script that adds the server_env to the path
    cat > "$wrapper_path" << EOF
#!/usr/bin/env python
# Wrapper script for $base_name
import os
import sys

# Add the server_env to the Python path
server_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server_env'))
sys.path.insert(0, server_env_path)

# Import the actual server code
server_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '$base_name'))
with open(server_file, 'r') as f:
    server_code = f.read()

# Execute the server code with the modified path
exec(server_code)
EOF
    
    # Make wrapper executable
    chmod +x "$wrapper_path"
done

# Create a bash helper script to run the servers
cat > dist/deepin-mcp/run_server.sh << 'EOF'
#!/bin/bash
# Helper script to run a server with the correct environment
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SERVER_NAME="$1"
PYTHON_EXECUTABLE="$(command -v python)"

if [[ "$SERVER_NAME" == *".py" ]]; then
    # Full path or filename provided
    if [[ "$SERVER_NAME" == *"/"* ]]; then
        # Full path provided
        SERVER_PATH="$SERVER_NAME"
    else
        # Just filename provided
        SERVER_PATH="$SCRIPT_DIR/servers/$SERVER_NAME"
    fi
else
    # Just server name provided without .py extension
    if [ -f "$SCRIPT_DIR/servers/${SERVER_NAME}_server.wrapper.py" ]; then
        SERVER_PATH="$SCRIPT_DIR/servers/${SERVER_NAME}_server.wrapper.py"
    elif [ -f "$SCRIPT_DIR/servers/${SERVER_NAME}.wrapper.py" ]; then
        SERVER_PATH="$SCRIPT_DIR/servers/${SERVER_NAME}.wrapper.py"
    else
        echo "Server $SERVER_NAME not found"
        exit 1
    fi
fi

# Check if wrapper exists, if not use the .py file
WRAPPER_PATH="${SERVER_PATH%.py}.wrapper.py"
if [ -f "$WRAPPER_PATH" ]; then
    SERVER_PATH="$WRAPPER_PATH"
fi

# Execute the server with correct Python
echo "Running server: $SERVER_PATH"
$PYTHON_EXECUTABLE "$SERVER_PATH"
EOF

chmod +x dist/deepin-mcp/run_server.sh

# Make the executable file executable
echo "Making files executable..."
chmod +x dist/deepin-mcp/deepin-mcp

# Create a simple wrapper script for easier execution
echo "Creating wrapper script..."
cat > dist/run-deepin-mcp.sh << 'EOF'
#!/bin/bash
# Run the deepin-mcp application from its directory
cd "$(dirname "$0")/deepin-mcp"
./deepin-mcp "$@"
EOF

chmod +x dist/run-deepin-mcp.sh

# Display success message
echo "Build completed successfully."
echo "The executable is available at: dist/deepin-mcp/deepin-mcp"
echo "For easier use, run: ./dist/run-deepin-mcp.sh"
echo "To run a server directly, use: ./dist/deepin-mcp/run_server.sh <server_name>" 