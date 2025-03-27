import asyncio
import os
import sys
import json
import glob
import subprocess
from typing import List, Dict, Optional
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
            raise ValueError(f"\nOPENAI_API_KEY 未设置")
        
        self.client = OpenAI(
            api_key=self.openai_api_key,
            base_url=self.base_url
        )
        
        # 初始化MCP客户端
        self.mcp_client = MCPClient()
        
        # 查找可用的服务器脚本
        self.available_servers = self.find_available_servers()
        self.server_path = self.get_default_server_path()
        
        if not self.server_path:
            raise FileNotFoundError("找不到任何可用的服务器脚本")

    def find_available_servers(self) -> Dict[str, str]:
        """
        查找所有可用的服务器脚本
        
        Returns:
            Dict[str, str]: 服务器名称到路径的映射
        """
        server_paths = {}
        
        # 检查是否在打包环境中运行
        is_packaged = getattr(sys, 'frozen', False)
        
        # 获取可能的搜索路径
        search_paths = []
        
        # 1. 当前工作目录及其servers子目录
        search_paths.extend([
            "*.py",
            "servers/*.py"
        ])
        
        # 2. 脚本所在目录及其servers子目录
        script_dir = Path(sys.argv[0]).resolve().parent
        search_paths.extend([
            str(script_dir / "*.py"),
            str(script_dir / "servers" / "*.py")
        ])
        
        # 3. 可执行文件所在目录（针对PyInstaller打包的应用）
        if is_packaged:
            executable_dir = Path(sys.executable).resolve().parent
            search_paths.extend([
                str(executable_dir / "*.py"),
                str(executable_dir / "servers" / "*.py")
            ])
            
            # 在打包环境中添加对包装器脚本的搜索
            search_paths.extend([
                str(executable_dir / "servers" / "*.wrapper.py")
            ])
        
        # 搜索所有路径
        for pattern in search_paths:
            for server_path in glob.glob(pattern):
                server_file = Path(server_path)
                
                # 跳过主程序文件、客户端文件等
                if server_file.name in ['main.py', 'client.py', '__init__.py', '__main__.py']:
                    continue
                
                # 获取服务器名称
                if server_file.name.endswith('.wrapper.py'):
                    # 对于包装器脚本，去除.wrapper.py后缀
                    orig_name = server_file.name[:-11]  # 移除".wrapper.py"
                    server_name = orig_name
                    if server_name.endswith('_server'):
                        server_name = server_name[:-7]  # 移除"_server"
                else:
                    # 对于常规脚本，检查文件名是否包含"server"
                    if "server" in server_file.name.lower():
                        server_name = server_file.stem
                        if server_name.endswith('_server'):
                            server_name = server_name[:-7]  # 移除"_server"
                    else:
                        continue  # 不是服务器脚本
                
                # 将路径添加到可用服务器列表
                server_paths[server_name] = str(server_file.resolve())
        
        # 如果在打包环境中运行，优先使用包装器脚本
        if is_packaged:
            run_server_script = None
            for root in [Path(sys.executable).resolve().parent, Path.cwd()]:
                script_path = root / "run_server.sh"
                if script_path.exists():
                    run_server_script = str(script_path)
                    break
            
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

    def get_default_server_path(self) -> Optional[str]:
        """
        获取默认服务器路径，优先使用bash_server
        
        Returns:
            Optional[str]: 默认服务器路径
        """
        # 优先使用bash_server
        if 'bash' in self.available_servers:
            return self.available_servers['bash']
        
        # 如果没有bash_server，使用第一个可用的服务器
        if self.available_servers:
            return next(iter(self.available_servers.values()))
        
        return None

    def list_available_servers(self) -> List[str]:
        """
        列出所有可用的服务器
        
        Returns:
            List[str]: 可用服务器名称列表
        """
        return list(self.available_servers.keys())

    def set_server(self, server_name: str) -> bool:
        """
        设置要使用的服务器
        
        Args:
            server_name: 服务器名称或路径
            
        Returns:
            bool: 是否成功设置
        """
        # 检查是否是已知的服务器名称
        if server_name in self.available_servers:
            self.server_path = self.available_servers[server_name]
            return True
        
        # 检查是否是路径而非名称
        if os.path.exists(server_name):
            self.server_path = str(Path(server_name).resolve())
            return True
        
        # 检查是否在打包环境中运行
        if getattr(sys, 'frozen', False):
            # 尝试查找run_server.sh脚本
            run_server_script = None
            for root in [Path(sys.executable).resolve().parent, Path.cwd()]:
                script_path = root / "run_server.sh"
                if script_path.exists():
                    run_server_script = str(script_path)
                    break
            
            if run_server_script:
                # 尝试使用服务器名称构造run_server.sh命令
                self.server_path = f"{run_server_script} {server_name}"
                return True
            
        return False

    async def plan_tasks(self, user_request: str) -> List[str]:
        """
        将用户请求拆分为多个按时间顺序执行的任务
        
        Args:
            user_request: 用户输入的请求
            
        Returns:
            List[str]: 任务列表
        """
        messages = [
            {
                "role": "system", 
                "content": """你是一个专业的任务分解助手。你的工作是将用户的复杂请求拆解为可以按顺序执行的具体任务列表。
                请遵循以下规则：
                1. 将复杂请求分解为3-8个简单、明确的步骤
                2. 将输入内容全部理解并翻译为 Linux bash 命令。如果涉及到打开文件操作，请使用xdg-open命令。请不要解释命令功能，只输出命令本身。格式为：CMD:实际命令。例如对于'显示当前目录'，只需返回'CMD:ls'。对于复杂命令，如果需要使用shell特性（如管道、重定向），应添加参数'use_shell:true'，例如：'CMD:ls -la | grep .txt;use_shell:true
                3. 步骤之间应该有清晰的先后顺序关系
                4. 每个步骤应该是可独立执行的
                5. 不要包含解释或分析，只提供步骤列表
                6. 每个步骤必须明确指出操作的对象（文件、目录等）
                7. 如果后续步骤依赖于前面步骤的结果，必须明确指出
                8. 以JSON格式返回，格式为：{"tasks": ["任务1", "任务2", "任务3", ...]}
                9. 不要使用Markdown格式化，直接返回原始JSON
                """
            },
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
            # 提取```和```之间的内容
            import re
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
            
            # 尝试更强大的解析方法
            try:
                # 1. 尝试使用正则表达式直接提取tasks数组
                import re
                tasks_match = re.search(r'"tasks"\s*:\s*\[(.*?)\]', cleaned_content, re.DOTALL)
                if tasks_match:
                    tasks_str = tasks_match.group(1)
                    # 提取数组中的字符串
                    task_list = re.findall(r'"([^"]*?)"', tasks_str)
                    if task_list:
                        return task_list
                
                # 2. 如果第一种方法失败，尝试找到所有命令格式的字符串
                cmd_list = re.findall(r'CMD:(.*?)(?:;|"|$)', cleaned_content)
                if cmd_list:
                    return [f"CMD:{cmd.strip()}" for cmd in cmd_list]
                
                # 3. 尝试提取任何看起来像任务的字符串
                tasks = re.findall(r'\[(.*?)\]', cleaned_content)
                if tasks:
                    # 提取数组中的字符串
                    task_list = re.findall(r'"([^"]+)"', tasks[0])
                    if task_list:
                        return task_list
                
                # 4. 最后尝试，直接匹配引号中的内容，排除常见的JSON键名
                tasks = re.findall(r'"([^"]+)"', cleaned_content)
                if tasks:
                    # 过滤掉常见的JSON键名
                    filtered_tasks = [task for task in tasks if task.lower() not in ['tasks', 'task', 'steps', 'step']]
                    if filtered_tasks:
                        return filtered_tasks
            except Exception as parse_error:
                print(f"额外解析尝试失败: {str(parse_error)}")
            
            # 所有方法都失败，将整个请求作为一个任务
            return [user_request]

    async def connect_to_server(self) -> bool:
        """
        连接到MCP服务器
        
        Returns:
            bool: 连接是否成功
        """
        try:
            await self.mcp_client.connect_to_server(self.server_path)
            return True
        except Exception as e:
            print(f"\n连接服务器失败: {str(e)}")
            return False

    async def execute_task(self, task: str) -> str:
        """
        执行单个任务
        
        Args:
            task: 要执行的任务
            
        Returns:
            str: 任务执行结果
        """
        try:
            result = await self.mcp_client.process_query(task)
            return result
        except Exception as e:
            return f"执行任务失败: {str(e)}"

    async def execute_tasks(self, tasks: List[str]) -> Dict[str, str]:
        """
        依次执行任务列表
        
        Args:
            tasks: 任务列表
            
        Returns:
            Dict[str, str]: 任务执行结果字典
        """
        results = {}
        
        # 创建任务执行进度显示
        print(f"\n总计 {len(tasks)} 个任务待执行:\n")
        for i, task in enumerate(tasks, 1):
            print(f"{i}. [ ] {task}")
        
        # 依次执行任务
        for i, task in enumerate(tasks, 1):
            print(f"\n正在执行任务 {i}/{len(tasks)}: {task}")
            result = await self.execute_task(task)
            results[task] = result
            
            # 更新任务状态
            print("\n任务执行状态:")
            for j, t in enumerate(tasks, 1):
                status = "✓" if j <= i else " "
                print(f"{j}. [{status}] {t}")
        
        return results

    async def summarize_results(self, user_request: str, tasks: List[str], results: Dict[str, str]) -> str:
        """
        汇总任务执行结果
        
        Args:
            user_request: 原始用户请求
            tasks: 任务列表
            results: 任务执行结果
            
        Returns:
            str: 任务执行总结
        """
        summary_prompt = f"""
用户原始请求: {user_request}

执行的任务:
{chr(10).join([f"{i+1}. {task}" for i, task in enumerate(tasks)])}

每个任务的结果:
{chr(10).join([f"任务 {i+1}: {results[task]}" for i, task in enumerate(tasks)])}

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
        """清理资源"""
        if self.mcp_client:
            await self.mcp_client.cleanup()

async def main():
    planner = TaskPlanner()
    
    try:
        print("\n欢迎使用任务规划执行系统")
        print("这个系统会将您的请求拆解为多个任务，并依次执行")
        
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
                print(f"{i}. {task}")
                
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