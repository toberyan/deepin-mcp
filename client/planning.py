import asyncio
import os
import sys
import json
import glob
import re
from typing import List, Dict, Optional, Any
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

from client.client import MCPClient

# 加载环境变量
load_dotenv()

class TaskPlanner:
    def __init__(self):
        """初始化任务规划器"""
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY 未设置")
        
        self.client = OpenAI(
            api_key=self.openai_api_key,
            base_url=self.base_url
        )
        
        # 初始化MCP客户端
        self.mcp_client = MCPClient()
        
        # 默认配置
        self.default_config = {
            "servers": {},
            "config": {
                "auto_load_enabled": True,
                "default_server": "bash"
            }
        }
        
        # 默认配置文件路径
        self.config_file = self._get_config_file_path()
        
        # 加载服务器配置
        self.server_config = self.load_server_config()
        
        # 更新服务器路径并查找新的服务器
        self.update_server_paths()
        
        # 获取默认服务器路径
        self.server_path = self.get_default_server_path()
        
        if not self.server_path:
            raise FileNotFoundError("找不到任何可用的服务器脚本")

    def _get_config_file_path(self) -> str:
        """获取配置文件路径"""
        # 检查是否在打包环境中运行
        is_packaged = getattr(sys, 'frozen', False)
        
        # 获取可能的配置文件路径
        search_paths = [
            Path.cwd() / "server_config.json",
            Path(sys.argv[0]).resolve().parent / "server_config.json"
        ]
        
        # 可执行文件所在目录（针对PyInstaller打包的应用）
        if is_packaged:
            search_paths.append(Path(sys.executable).resolve().parent / "server_config.json")
        
        # 检查配置文件是否存在
        for path in search_paths:
            if path.exists():
                return str(path)
        
        # 如果配置文件不存在，使用工作目录下的路径
        return str(Path.cwd() / "server_config.json")

    def load_server_config(self) -> Dict[str, Any]:
        """加载服务器配置"""
        if not os.path.exists(self.config_file):
            print(f"\n服务器配置文件不存在: {self.config_file}")
            print("将创建默认配置文件...")
            
            # 保存默认配置到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.default_config, f, ensure_ascii=False, indent=2)
            
            return self.default_config.copy()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 确保配置结构完整
            if "servers" not in config:
                config["servers"] = {}
            if "config" not in config:
                config["config"] = self.default_config["config"]
            
            return config
        except Exception as e:
            print(f"\n加载服务器配置文件失败: {str(e)}")
            print("将使用默认配置...")
            return self.default_config.copy()

    def save_server_config(self) -> bool:
        """保存服务器配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.server_config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"\n保存服务器配置文件失败: {str(e)}")
            return False

    def update_server_paths(self) -> None:
        """更新服务器路径并查找新的服务器"""
        # 查找可用的服务器
        self.available_servers = self.find_available_servers()
        
        # 更新配置中的服务器信息
        for server_name, server_path in self.available_servers.items():
            if server_name not in self.server_config["servers"]:
                # 添加新发现的服务器
                self.server_config["servers"][server_name] = {
                    "path": server_path,
                    "description": f"{server_name}服务器",
                    "enabled": True,  # 默认启用
                    "default": False
                }
            else:
                # 更新服务器路径
                self.server_config["servers"][server_name]["path"] = server_path
        
        # 保存更新后的配置
        self.save_server_config()

    def find_available_servers(self) -> Dict[str, str]:
        """
        查找所有可用的服务器脚本
        
        Returns:
            Dict[str, str]: 服务器名称到路径的映射
        """
        server_paths = {}
        is_packaged = getattr(sys, 'frozen', False)
        
        # 获取可能的搜索路径
        search_paths = [
            "*.py",
            "servers/*.py",
            str(Path(sys.argv[0]).resolve().parent / "*.py"),
            str(Path(sys.argv[0]).resolve().parent / "servers" / "*.py")
        ]
        
        # 添加打包环境特有的路径
        if is_packaged:
            executable_dir = Path(sys.executable).resolve().parent
            search_paths.extend([
                str(executable_dir / "*.py"),
                str(executable_dir / "servers" / "*.py"),
                str(executable_dir / "servers" / "*.wrapper.py")
            ])
        
        # 跳过的文件名
        skip_files = ['main.py', 'client.py', '__init__.py', '__main__.py']
        
        # 搜索所有路径
        for pattern in search_paths:
            for server_path in glob.glob(pattern):
                server_file = Path(server_path)
                
                # 跳过主程序文件、客户端文件等
                if server_file.name in skip_files:
                    continue
                
                # 获取服务器名称
                server_name = None
                if server_file.name.endswith('.wrapper.py'):
                    # 对于包装器脚本，去除.wrapper.py后缀
                    server_name = server_file.name[:-11]  # 移除".wrapper.py"
                    if server_name.endswith('_server'):
                        server_name = server_name[:-7]  # 移除"_server"
                elif "server" in server_file.name.lower():
                    # 对于常规脚本，检查文件名是否包含"server"
                    server_name = server_file.stem
                    if server_name.endswith('_server'):
                        server_name = server_name[:-7]  # 移除"_server"
                
                # 如果确定了服务器名称，将路径添加到可用服务器列表
                if server_name:
                    server_paths[server_name] = str(server_file.resolve())
        
        # 如果在打包环境中运行，优先使用包装器脚本
        if is_packaged:
            run_server_script = self._find_run_server_script()
            
            if run_server_script:
                # 如果找到run_server.sh，替换所有路径为使用它的命令
                updated_paths = {}
                for name, path in server_paths.items():
                    if path.endswith('.wrapper.py'):
                        # 已经是包装器脚本，保持不变
                        updated_paths[name] = path
                    else:
                        # 使用run_server.sh脚本
                        server_file = Path(path).name
                        updated_paths[name] = f"{run_server_script} {server_file}"
                
                # 使用更新后的路径
                if updated_paths:
                    server_paths = updated_paths
        
        return server_paths
        
    def _find_run_server_script(self) -> Optional[str]:
        """查找run_server.sh脚本"""
        for root in [Path(sys.executable).resolve().parent, Path.cwd()]:
            script_path = root / "run_server.sh"
            if script_path.exists():
                return str(script_path)
        return None

    def get_default_server_path(self) -> Optional[str]:
        """
        获取默认服务器路径
        
        Returns:
            Optional[str]: 默认服务器路径
        """
        # 从配置中获取默认服务器
        default_server = self.server_config["config"]["default_server"]
        
        # 检查默认服务器是否存在且已启用
        if (default_server in self.server_config["servers"] and 
            self.server_config["servers"][default_server]["enabled"]):
            server_info = self.server_config["servers"][default_server]
            
            # 检查路径是否存在
            if os.path.exists(server_info["path"]):
                return server_info["path"]
            
            # 如果路径不存在，尝试使用available_servers中的路径
            if default_server in self.available_servers:
                return self.available_servers[default_server]
        
        # 如果默认服务器不可用，尝试找到第一个启用的服务器
        for server_name, server_info in self.server_config["servers"].items():
            if server_info["enabled"]:
                # 检查路径是否存在
                if os.path.exists(server_info["path"]):
                    return server_info["path"]
                
                # 如果路径不存在，尝试使用available_servers中的路径
                if server_name in self.available_servers:
                    return self.available_servers[server_name]
        
        # 如果没有找到启用的服务器，使用第一个可用的服务器
        if self.available_servers:
            return next(iter(self.available_servers.values()))
        
        return None

    def list_available_servers(self) -> List[str]:
        """列出所有可用的服务器"""
        return list(self.server_config["servers"].keys())
    
    def get_server_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有服务器的状态"""
        return self.server_config["servers"]

    def _update_server_config(self, server_name: str, key: str, value: Any) -> bool:
        """更新服务器配置中的特定键值"""
        if server_name in self.server_config["servers"]:
            self.server_config["servers"][server_name][key] = value
            self.save_server_config()
            return True
        return False

    def enable_server(self, server_name: str) -> bool:
        """启用服务器"""
        return self._update_server_config(server_name, "enabled", True)

    def disable_server(self, server_name: str) -> bool:
        """禁用服务器"""
        return self._update_server_config(server_name, "enabled", False)

    def set_default_server(self, server_name: str) -> bool:
        """设置默认服务器"""
        if server_name in self.server_config["servers"]:
            # 清除之前的默认服务器
            for name in self.server_config["servers"]:
                self.server_config["servers"][name]["default"] = False
            
            # 设置新的默认服务器
            self.server_config["servers"][server_name]["default"] = True
            self.server_config["config"]["default_server"] = server_name
            self.save_server_config()
            return True
        return False

    def set_server(self, server_name: str) -> bool:
        """设置要使用的服务器"""
        # 检查是否是已知的服务器名称
        if server_name in self.server_config["servers"]:
            # 先检查配置中的路径是否存在
            server_path = self.server_config["servers"][server_name]["path"]
            if os.path.exists(server_path):
                self.server_path = server_path
                return True
            
            # 如果路径不存在，尝试使用available_servers中的路径
            if server_name in self.available_servers:
                self.server_path = self.available_servers[server_name]
                return True
            
            print(f"\n警告: 服务器 '{server_name}' 配置中的路径不存在: {server_path}")
            return False
        
        # 检查是否是路径而非名称
        if os.path.exists(server_name):
            self.server_path = str(Path(server_name).resolve())
            return True
        
        # 检查是否在打包环境中运行
        if getattr(sys, 'frozen', False):
            run_server_script = self._find_run_server_script()
            
            if run_server_script:
                # 尝试使用服务器名称构造run_server.sh命令
                self.server_path = f"{run_server_script} {server_name}"
                return True
            
        print(f"\n未找到服务器 '{server_name}'")
        return False

    async def plan_tasks(self, user_request: str) -> List[Dict[str, Any]]:
        """
        将用户请求拆分为多个按时间顺序执行的原子任务，并为每个任务标识最适合的工具类型
        """
        system_content = """你是一个专业的任务分解助手。你的工作是将用户的复杂请求拆解为可以按顺序执行的具体原子任务列表，并为每个任务推荐最适合的工具类型。
        请遵循以下规则：
        1. 将复杂请求分解为3-8个简单、明确的原子任务
        2. 每个任务必须具体、明确，便于后续处理
        3. 为每个任务标识最适合的工具类型，可能的类型包括：
           - bash: 适合文件操作、系统命令等
           - weather: 适合天气查询
           - calendar: 适合日历和时间管理操作
           - email: 适合发送和管理邮件
           - web: 适合网络搜索和浏览
           - database: 适合数据库操作
           - media: 适合媒体文件处理
           - document: 适合文档处理
           - general: 通用任务，无明确类别
        4. 每个步骤应该是可独立执行的
        5. 步骤之间应该有清晰的先后顺序关系
        6. 如果后续步骤依赖于前面步骤的结果，必须明确指出
        7. 以JSON格式返回，格式为：{"tasks": [{"description": "任务1描述", "tool_type": "工具类型1"}, {"description": "任务2描述", "tool_type": "工具类型2"}, ...]}
        8. 不要使用Markdown格式化，直接返回原始JSON
        """
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"请将以下请求拆解为具体的执行步骤：{user_request}"}
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        
        # 清理内容，去除可能的Markdown格式化
        cleaned_content = content
        # 移除可能存在的Markdown代码块标记
        if "```" in cleaned_content:
            code_blocks = re.findall(r'```(?:json)?(.*?)```', cleaned_content, re.DOTALL)
            if code_blocks:
                cleaned_content = code_blocks[0].strip()
            else:
                # 如果无法提取代码块，则移除所有```标记
                cleaned_content = re.sub(r'```(?:json)?', '', cleaned_content)
                cleaned_content = cleaned_content.replace('```', '').strip()
        
        try:
            tasks_data = json.loads(cleaned_content)
            return tasks_data.get("tasks", [])
        except json.JSONDecodeError as e:
            print(f"解析JSON失败: {content}")
            print(f"错误详情: {str(e)}")
            
            # 所有解析方法失败，将整个请求作为一个通用任务
            return [{"description": user_request, "tool_type": "general"}]

    async def connect_to_server(self) -> bool:
        """连接到所有启用的MCP服务器，并加载它们的所有工具"""
        try:
            # 获取所有启用的服务器列表
            enabled_servers = {}
            for server_name, server_info in self.server_config["servers"].items():
                if server_info.get("enabled", True):
                    # 检查路径是否存在
                    if os.path.exists(server_info["path"]):
                        enabled_servers[server_name] = server_info["path"]
                    # 如果路径不存在，尝试使用available_servers中的路径
                    elif server_name in self.available_servers:
                        enabled_servers[server_name] = self.available_servers[server_name]
            
            if not enabled_servers:
                print("\n未找到任何启用的服务器，将尝试发现可用服务器")
                # 重新扫描可用服务器
                self.update_server_paths()
                for server_name, server_path in self.available_servers.items():
                    enabled_servers[server_name] = server_path
                
                if not enabled_servers:
                    print("\n未找到任何可用服务器")
                    return False
            
            # 记录所有成功连接的服务器及其工具
            connected_servers = {}
            all_tools = []
            
            # 连接每个服务器并获取工具
            for server_name, server_path in enabled_servers.items():
                try:
                    print(f"\n正在连接服务器: {server_name} ({server_path})")
                    
                    # 初始化一个新的MCP客户端
                    client = MCPClient()
                    
                    # 连接到服务器
                    await client.connect_to_server(server_path)
                    
                    # 获取服务器工具列表
                    response = await client.session.list_tools()
                    server_tools = response.tools
                    
                    # 为每个工具添加服务器来源标记
                    for tool in server_tools:
                        tool.name = f"{server_name}.{tool.name}"
                    
                    # 记录服务器工具
                    connected_servers[server_name] = {
                        "client": client,
                        "path": server_path,
                        "tools": server_tools,
                        "description": self.server_config["servers"].get(server_name, {}).get("description", f"{server_name}服务器")
                    }
                    
                    # 添加到全局工具列表
                    all_tools.extend(server_tools)
                    
                    print(f"服务器 '{server_name}' 连接成功，提供 {len(server_tools)} 个工具")
                except Exception as e:
                    print(f"连接服务器 '{server_name}' 失败: {str(e)}")
            
            # 检查是否至少连接到了一个服务器
            if not connected_servers:
                print("\n未能成功连接到任何服务器")
                return False
            
            # 设置主客户端为第一个连接成功的服务器客户端
            first_server = next(iter(connected_servers.values()))
            self.mcp_client = first_server["client"]
            self.server_path = first_server["path"]
            
            # 保存所有连接的服务器信息
            self.connected_servers = connected_servers
            self.all_tools = all_tools
            
            # 输出所有可用工具
            tool_count = len(all_tools)
            print(f"\n成功连接 {len(connected_servers)} 个服务器，共有 {tool_count} 个可用工具")
            
            # 按服务器分组显示工具
            for server_name, server_info in connected_servers.items():
                print(f"\n{server_name} 服务器工具 ({len(server_info['tools'])}):")
                for tool in server_info["tools"]:
                    print(f"  - {tool.name}")
            
            return True
        except Exception as e:
            print(f"\n连接服务器过程中出现错误: {str(e)}")
            return False

    async def execute_task(self, task: Dict[str, Any]) -> str:
        """执行单个任务，根据任务类型选择最合适的工具"""
        try:
            # 如果没有连接服务器，尝试连接
            if not hasattr(self, 'connected_servers') or not self.connected_servers:
                connected = await self.connect_to_server()
                if not connected:
                    return "错误: 未连接到任何服务器"
            
            task_description = task["description"]
            tool_type = task["tool_type"]
            
            print(f"\n执行任务: {task_description}")
            print(f"推荐工具类型: {tool_type}")
            
            # 根据任务类型筛选合适的工具
            suitable_tools = []
            
            # 如果有特定的工具类型，优先考虑该类型的工具
            if tool_type != "general":
                for tool in self.all_tools:
                    # 检查工具名称是否与工具类型匹配
                    # 格式为 "server_name.tool_name"
                    server_name = tool.name.split('.')[0] if '.' in tool.name else ""
                    if server_name.lower() == tool_type.lower() or tool_type.lower() in tool.name.lower():
                        suitable_tools.append(tool)
            
            # 如果没有找到匹配的工具或者是通用任务，使用所有工具
            if not suitable_tools:
                suitable_tools = self.all_tools
                
            # 使用适当的服务器客户端处理查询
            result = await self.mcp_client.process_query(
                task_description, 
                suitable_tools, 
                self.connected_servers
            )
            return result
        except Exception as e:
            return f"执行任务失败: {str(e)}"

    async def execute_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, str]:
        """依次执行任务列表"""
        results = {}
        
        # 创建任务执行进度显示
        print(f"\n总计 {len(tasks)} 个任务待执行:\n")
        for i, task in enumerate(tasks, 1):
            print(f"{i}. [ ] {task['description']} (推荐工具: {task['tool_type']})")
        
        # 依次执行任务
        for i, task in enumerate(tasks, 1):
            print(f"\n正在执行任务 {i}/{len(tasks)}: {task['description']}")
            result = await self.execute_task(task)
            results[task['description']] = result
            
            # 更新任务状态
            print("\n任务执行状态:")
            for j, t in enumerate(tasks, 1):
                status = "✓" if j <= i else " "
                print(f"{j}. [{status}] {t['description']}")
        
        return results

    async def summarize_results(self, user_request: str, tasks: List[Dict[str, Any]], results: Dict[str, str]) -> str:
        """汇总任务执行结果"""
        task_summary = chr(10).join([f"{i+1}. {task['description']} (工具类型: {task['tool_type']})" for i, task in enumerate(tasks)])
        results_summary = chr(10).join([f"任务 {i+1}: {results[task['description']]}" for i, task in enumerate(tasks)])
        
        summary_prompt = f"""
用户原始请求: {user_request}

执行的任务:
{task_summary}

每个任务的结果:
{results_summary}

请为用户提供一个简洁、全面的总结，说明完成了什么任务、取得了什么成果，以及可能的后续步骤。请使用第一人称，就好像你就是执行任务的助手。
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的任务执行结果总结助手。请提供简洁、全面的总结，说明完成了什么任务、取得了什么成果。"},
            {"role": "user", "content": summary_prompt}
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages
        )
        
        return response.choices[0].message.content

    async def cleanup(self):
        """清理服务器连接和会话"""
        if not hasattr(self, 'connected_servers') or not self.connected_servers:
            return
        
        # 创建清理任务列表
        cleanup_tasks = []
        for server_name, server_info in list(self.connected_servers.items()):
            # 添加任务而不是立即执行
            cleanup_tasks.append(self._cleanup_client(server_name, server_info["client"]))
        
        if cleanup_tasks:
            try:
                # 并行执行所有清理任务，允许部分失败
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            except Exception as e:
                print(f"清理过程中出现错误: {e}")
        
        # 清空服务器客户端列表
        self.connected_servers = {}

    async def _cleanup_client(self, server_name, client):
        """清理单个客户端的资源，作为独立的异步任务"""
        try:
            if hasattr(client, 'process') and client.process:
                if client.process.returncode is None:
                    try:
                        # 发送终止信号
                        client.process.terminate()
                        # 等待进程终止，但设置超时
                        await asyncio.wait_for(
                            asyncio.create_subprocess_exec(
                                "wait", str(client.process.pid),
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL
                            ),
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        # 如果等待超时，强制终止
                        if client.process.returncode is None:
                            try:
                                client.process.kill()
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"终止服务器进程时出错: {e}")
            
            # 关闭WebSocket连接
            if hasattr(client, 'ws') and client.ws:
                try:
                    await client.ws.close()
                except Exception:
                    pass
            
            print(f"已清理服务器客户端: {server_name}")
        except asyncio.CancelledError:
            # 即使被取消也要尝试关闭资源
            try:
                if hasattr(client, 'process') and client.process and client.process.returncode is None:
                    client.process.kill()
                if hasattr(client, 'ws') and client.ws:
                    await client.ws.close()
            except Exception:
                pass
            print(f"服务器客户端 {server_name} 清理过程被取消")
            # 重新引发CancelledError以便调用者知道任务被取消
            raise
        except Exception as e:
            print(f"清理服务器客户端 {server_name} 时出错: {e}")

async def main():
    planner = TaskPlanner()
    
    try:
        print("\n欢迎使用任务规划执行系统")
        print("这个系统会将您的请求拆解为多个原子任务，并为每个任务自动选择最合适的工具执行")
        
        # 连接服务器
        connected = await planner.connect_to_server()
        if not connected:
            print("\n无法连接到服务器，程序退出")
            return
        
        # 主循环
        while True:
            user_request = input("\n请输入您的请求 (输入'quit'退出): ").strip()
            
            if user_request.lower() == 'quit':
                break
                
            if not user_request:
                continue
                
            # 1. 规划任务
            print("\n正在分析您的请求...")
            tasks = await planner.plan_tasks(user_request)
            
            if not tasks:
                print("\n未能从您的请求中提取出具体任务，请尝试更明确的描述")
                continue
                
            print(f"\n已将您的请求拆解为 {len(tasks)} 个任务:")
            for i, task in enumerate(tasks, 1):
                print(f"{i}. {task['description']} (推荐工具类型: {task['tool_type']})")
                
            # 确认是否执行
            confirm = input("\n是否执行这些任务? (y/n): ").strip().lower()
            if confirm != 'y':
                print("\n已取消任务执行")
                continue
                
            # 2. 执行任务
            results = await planner.execute_tasks(tasks)
            
            # 3. 生成总结
            print("\n所有任务已执行完毕，正在生成总结...")
            summary = await planner.summarize_results(user_request, tasks, results)
            
            print("\n执行总结:")
            print(summary)
            
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n出现错误: {str(e)}")
    finally:
        # 清理资源
        await planner.cleanup()
        print("\n程序已退出")

if __name__ == "__main__":
    asyncio.run(main()) 