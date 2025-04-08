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

# Make the executable file executable
echo "Making files executable..."
chmod +x dist/deepin-mcp/deepin-mcp

# Display success message
echo "Build completed successfully."
echo "The executable is available at: dist/deepin-mcp/deepin-mcp" 