# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Define additional files to include directly in the distribution folder
added_files = [
    ('.env', '.'),  # Config file
    ('client', 'client'),  # Client module
    ('servers/*.py', 'servers'),  # Server files
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,  # Use the added_files defined above
    hiddenimports=[
        'anthropic',
        'httpx',
        'mcp',
        'openai',
        'python-dotenv',
        'asyncio',
        'argparse',
        'pathlib',
        'typing',
        'dotenv',
        'glob',  # Added for server discovery
        'json',
        'shlex',  # Used by bash_server
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],  # Remove a.binaries, a.zipfiles, a.datas to create a directory-based distribution
    exclude_binaries=True,  # Important for directory-based distribution
    name='deepin-mcp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Create directory-based distribution with executable and all support files
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='deepin-mcp',
) 