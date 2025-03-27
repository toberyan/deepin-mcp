import os
import subprocess
import shlex
import json
from typing import Dict, List, Optional, Union, Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("BashServer")

def validate_command(command: str) -> bool:
    """
    检查命令是否在允许列表中
    
    Args:
        command: 要验证的命令
        
    Returns:
        bool: 命令是否允许执行
    """
    # 修改为允许任何命令
    return True

def sanitize_args(args: List[str]) -> List[str]:
    """
    清理参数，移除可能有害的字符
    
    Args:
        args: 参数列表
        
    Returns:
        List[str]: 清理后的参数列表
    """
    # 不进行过滤，允许所有参数通过
    return args

def is_gui_application(command: str, args: List[str] = None) -> bool:
    """
    判断命令是否为图形界面应用
    
    Args:
        command: 命令名称
        args: 命令参数
        
    Returns:
        bool: 是否为图形界面应用
    """
    # 定义已知的图形界面应用列表
    gui_commands = ['xdg-open', 'gnome-open', 'kde-open', 'firefox', 'chromium', 'eog', 'display', 
                  'evince', 'okular', 'libreoffice', 'gimp', 'vlc', 'mpv', 'gedit', 'nautilus', 'thunar']
    
    # 基础判断：命令本身是否在图形界面应用列表中
    if command in gui_commands or any(cmd in command for cmd in gui_commands):
        return True
    
    # 特别处理xdg-open命令，无论文件类型都以GUI方式运行
    if command == 'xdg-open' or command.startswith('xdg-open '):
        return True
        
    return False

async def execute_bash_command(command: str, args: List[str], timeout: int = 30) -> Dict[str, Union[int, str, str]]:
    """
    执行bash命令
    
    Args:
        command: 要执行的命令
        args: 命令参数列表
        timeout: 命令超时时间（秒）
        
    Returns:
        Dict: 包含执行结果的字典
    """
    # 清理参数
    safe_args = sanitize_args(args)
    
    # 展开命令中的波浪号（~）为用户主目录
    if command.startswith('~'):
        command = os.path.expanduser(command)
    
    # 展开参数中的波浪号（~）为用户主目录
    expanded_args = []
    for arg in safe_args:
        if arg.startswith('~'):
            expanded_arg = os.path.expanduser(arg)
            expanded_args.append(expanded_arg)
        else:
            expanded_args.append(arg)
    
    # 构建完整命令
    cmd = [command] + expanded_args
    
    # 获取用户环境变量
    user_env = os.environ.copy()
    
    # 确保设置必要的X11环境变量
    if 'DISPLAY' not in user_env:
        user_env['DISPLAY'] = ':0'
    
    # 使用通用函数判断是否为图形界面命令
    is_gui_command = is_gui_application(command, expanded_args)
    
    # 如果是图形界面相关命令，确保设置相关环境变量
    if is_gui_command:
        # 设置常见的图形应用环境变量
        user_env['XAUTHORITY'] = os.path.expanduser('~/.Xauthority')
        user_env['XDG_RUNTIME_DIR'] = user_env.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        user_env['DBUS_SESSION_BUS_ADDRESS'] = user_env.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
        
        # 对于图形界面命令，使用分离进程的方式执行
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=user_env,
                start_new_session=True
            )
            return {
                "status": 0,
                "stdout": f"已启动图形界面命令: {command} {' '.join(args)}\n命令已在后台运行，不会阻塞当前会话。",
                "stderr": ""
            }
        except Exception as e:
            return {
                "status": 1,
                "stdout": "",
                "stderr": f"启动图形界面命令失败: {str(e)}"
            }
    
    try:
        # 执行命令
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=user_env,
            shell=False
        )
        
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return {
                "status": process.returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip()
            }
        except subprocess.TimeoutExpired:
            process.kill()
            return {
                "status": 1,
                "stdout": "",
                "stderr": f"错误: 命令执行超时 ({timeout}秒)"
            }
            
    except Exception as e:
        return {
            "status": 1,
            "stdout": "",
            "stderr": f"错误: {str(e)}"
        }

@mcp.tool()
async def run_bash(command: str, args: str = "", use_shell: bool = False) -> str:
    """
    执行指定的Bash命令并返回结果
    
    Args:
        command: 要执行的命令
        args: 命令参数（空格分隔）
        use_shell: 是否使用shell执行命令（启用管道、重定向等功能）
        
    Returns:
        str: 命令执行结果
    """
    # 检查命令是否有效
    if not command:
        return "错误: 未指定命令"
    
    # 获取用户完整环境变量
    user_env = os.environ.copy()
    
    # 确保设置必要的X11环境变量
    if 'DISPLAY' not in user_env:
        user_env['DISPLAY'] = ':0'
    
    # 处理命令中的波浪号(~)
    if not use_shell and command.startswith('~'):
        command = os.path.expanduser(command)
    
    # 处理命令可能包含参数的情况
    cmd_parts = shlex.split(command) if ' ' in command and not args else [command]
    cmd_name = cmd_parts[0]
    cmd_args = cmd_parts[1:] if len(cmd_parts) > 1 else []
    
    # 为非shell模式的cmd_name处理波浪号
    if not use_shell and cmd_name.startswith('~'):
        cmd_name = os.path.expanduser(cmd_name)
    
    # 解析参数字符串为列表
    if args:
        arg_list = shlex.split(args)
        cmd_args.extend(arg_list)
    
    # 在非shell模式下处理参数中的波浪号(~)
    if not use_shell:
        processed_args = []
        for arg in cmd_args:
            if arg.startswith('~'):
                processed_args.append(os.path.expanduser(arg))
            else:
                processed_args.append(arg)
        cmd_args = processed_args
    
    # 使用通用函数判断是否为图形界面命令
    is_gui_command = is_gui_application(cmd_name, cmd_args)
    
    # 如果是图形界面相关命令，确保设置相关环境变量
    if is_gui_command:
        # 设置常见的图形应用环境变量
        user_env['XAUTHORITY'] = os.path.expanduser('~/.Xauthority')
        user_env['XDG_RUNTIME_DIR'] = user_env.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        user_env['DBUS_SESSION_BUS_ADDRESS'] = user_env.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
    
    # 如果使用shell模式，直接将命令和参数合并
    if use_shell:
        full_command = command
        if args:
            full_command += " " + args
        
        # 对于图形界面命令使用分离进程的方式执行
        if is_gui_command:
            try:
                # 添加nohup和后台执行符号&使命令在后台运行
                background_cmd = f"nohup {full_command} >/dev/null 2>&1 &"
                
                # 调用系统shell执行后台命令
                subprocess.Popen(
                    background_cmd,
                    shell=True,
                    env=user_env,
                    start_new_session=True
                )
                
                return f"已启动图形界面命令: {full_command}\n\n命令已在后台运行，不会阻塞当前会话。"
                
            except Exception as e:
                return f"启动图形界面命令失败: {str(e)}"
        
        # 非图形界面命令，按原方式执行
        try:
            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                env=user_env
            )
            
            stdout, stderr = process.communicate(timeout=30)
            
            # 格式化输出
            output = []
            if stdout:
                output.append(f"标准输出:\n{stdout.strip()}")
            if stderr:
                output.append(f"标准错误:\n{stderr.strip()}")
            
            status_msg = "成功" if process.returncode == 0 else "失败"
            output.append(f"命令执行{status_msg}，退出码: {process.returncode}")
            
            return "\n\n".join(output)
        
        except subprocess.TimeoutExpired:
            return "错误: 命令执行超时 (30秒)"
        except Exception as e:
            return f"错误: {str(e)}"
    
    # 非shell模式处理
    
    # 对于图形界面命令使用分离进程的方式执行
    if is_gui_command:
        try:
            # 构建完整命令
            cmd = [cmd_name] + cmd_args
            
            # 使用分离进程的方式启动
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=user_env,
                start_new_session=True
            )
            
            return f"已启动图形界面命令: {cmd_name} {' '.join(cmd_args)}\n\n命令已在后台运行，不会阻塞当前会话。"
            
        except Exception as e:
            return f"启动图形界面命令失败: {str(e)}"
    
    # 非图形界面命令，按原方式执行
    result = await execute_bash_command(cmd_name, cmd_args)
    
    # 格式化输出
    output = []
    if result["stdout"]:
        output.append(f"标准输出:\n{result['stdout']}")
    if result["stderr"]:
        output.append(f"标准错误:\n{result['stderr']}")
    
    status_msg = "成功" if result["status"] == 0 else "失败"
    output.append(f"命令执行{status_msg}，退出码: {result['status']}")
    
    return "\n\n".join(output)

@mcp.tool()
async def list_available_commands() -> str:
    """
    列出所有可用的Bash命令
    
    Returns:
        str: 可用命令列表
    """
    return """所有系统命令均可使用。

常见的有用命令包括：
- ls：列出目录内容
- cd：切换目录
- mkdir：创建目录
- rm：删除文件或目录
- cp：复制文件或目录
- mv：移动或重命名文件或目录
- cat：查看文件内容
- grep：搜索文件内容
- find：查找文件
- chmod：修改文件权限
- ps：查看进程
- kill：终止进程
- wget/curl：下载文件
- tar：压缩或解压文件
- ssh：远程登录
- sudo：以管理员权限执行命令

图形界面相关命令（将在后台运行）：
- xdg-open：使用默认应用打开文件
- firefox/chromium：网页浏览器
- eog/display：图片查看器
- evince/okular：PDF查看器
- libreoffice：办公套件
- vlc/mpv：媒体播放器
- gedit：文本编辑器
- nautilus/thunar：文件管理器

执行方式:
1. 普通模式: 默认方式，适合执行单个命令
   示例: run_bash("ls", "-la")

2. Shell模式: 支持管道、重定向、通配符等shell特性
   示例: run_bash("ls -la | grep .txt", use_shell=True)
   示例: run_bash("cat file.txt > output.txt", use_shell=True)
   示例: run_bash("find . -name '*.py' | wc -l", use_shell=True)

您可以使用任何系统支持的命令，无限制。"""

@mcp.tool()
async def get_command_help(command: str) -> str:
    """
    获取特定命令的帮助信息
    
    Args:
        command: 命令名称
        
    Returns:
        str: 命令帮助信息
    """
    if not command:
        return "错误: 未指定命令"
    
    output = [
        f"命令: {command}",
        f"描述: {command}命令的帮助信息",
        f"用法: 请参考下方系统帮助信息"
    ]
    
    # 获取用户环境变量
    user_env = os.environ.copy()
    
    # 确保设置必要的X11环境变量
    if 'DISPLAY' not in user_env:
        user_env['DISPLAY'] = ':0'
    
    # 使用通用函数判断是否为图形界面命令
    is_gui_command = is_gui_application(command)
    
    # 如果是图形界面相关命令，确保设置相关环境变量
    if is_gui_command:
        # 设置常见的图形应用环境变量
        user_env['XAUTHORITY'] = os.path.expanduser('~/.Xauthority')
        user_env['XDG_RUNTIME_DIR'] = user_env.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        user_env['DBUS_SESSION_BUS_ADDRESS'] = user_env.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
    
    # 获取命令的帮助信息
    try:
        process = subprocess.Popen(
            [command, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=user_env
        )
        stdout, stderr = process.communicate(timeout=5)
        if stdout:
            output.append("\n系统帮助信息:")
            output.append(stdout)
        elif stderr:
            output.append("\n系统帮助信息:")
            output.append(stderr)
    except Exception as e:
        output.append(f"\n获取帮助信息时出错: {str(e)}")
    
    return "\n".join(output)

@mcp.tool()
async def system_info() -> str:
    """
    获取系统信息
    
    Returns:
        str: 系统信息摘要
    """
    info = []
    
    # 获取用户环境变量
    user_env = os.environ.copy()
    
    # 确保设置必要的X11环境变量
    if 'DISPLAY' not in user_env:
        user_env['DISPLAY'] = ':0'
    
    # 获取系统信息
    commands = {
        "操作系统": ["uname", "-a"],
        "主机名": ["hostname"],
        "IP地址": ["hostname", "-I"],
        "内核版本": ["uname", "-r"],
        "CPU信息": ["cat", "/proc/cpuinfo"],
        "内存信息": ["free", "-h"],
        "磁盘使用": ["df", "-h"],
        "已登录用户": ["who"],
        "当前时间": ["date"],
        "运行时间": ["uptime"]
    }
    
    for label, cmd in commands.items():
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=user_env
            )
            stdout, stderr = process.communicate(timeout=5)
            
            if process.returncode == 0 and stdout:
                # CPU 和磁盘信息太长，只取摘要
                if label == "CPU信息":
                    lines = stdout.strip().split("\n")
                    filtered = [line for line in lines if "model name" in line]
                    if filtered:
                        stdout = filtered[0]
                    else:
                        stdout = "无法获取CPU型号"
                
                info.append(f"{label}: {stdout.strip()}")
        except:
            info.append(f"{label}: 无法获取")
    
    return "系统信息摘要:\n\n" + "\n\n".join(info)

if __name__ == "__main__":
    mcp.run(transport='stdio') 