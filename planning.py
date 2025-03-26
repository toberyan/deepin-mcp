import asyncio
import os
import sys
import json
from typing import List, Dict
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
        
        # 找到bash_server.py的路径
        self.server_paths = [
            "bash_server.py",
            "servers/bash_server.py",
            Path(__file__).parent / "bash_server.py",
            Path(__file__).parent / "servers" / "bash_server.py"
        ]
        self.server_path = None
        for path in self.server_paths:
            if Path(path).exists():
                self.server_path = str(Path(path).resolve())
                break
        
        if not self.server_path:
            raise FileNotFoundError("找不到bash_server.py文件")

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
                2. 每个步骤应该是一条完整的Linux命令或明确的操作指令
                3. 步骤之间应该有清晰的先后顺序关系
                4. 每个步骤应该是可独立执行的
                5. 不要包含解释或分析，只提供步骤列表
                6. 每个步骤必须明确指出操作的对象（文件、目录等）
                7. 如果后续步骤依赖于前面步骤的结果，必须明确指出
                8. 以JSON格式返回，格式为：{"tasks": ["任务1", "任务2", "任务3", ...]}
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
        try:
            tasks_data = json.loads(content)
            return tasks_data.get("tasks", [])
        except json.JSONDecodeError:
            print(f"解析JSON失败: {content}")
            # 尝试提取可能的任务
            import re
            # 使用更精确的正则表达式来匹配数组中的字符串
            tasks = re.findall(r'\[(.*?)\]', content)
            if tasks:
                # 提取数组中的字符串
                task_list = re.findall(r'"([^"]+)"', tasks[0])
                if task_list:
                    return task_list
            # 如果还是找不到任务，尝试直接匹配引号中的内容，但排除常见的JSON键名
            tasks = re.findall(r'"([^"]+)"', content)
            if tasks:
                # 过滤掉常见的JSON键名
                filtered_tasks = [task for task in tasks if task.lower() not in ['tasks', 'task', 'steps', 'step']]
                if filtered_tasks:
                    return filtered_tasks
            return [user_request]  # 如果解析失败，将整个请求作为一个任务

    async def connect_to_server(self):
        """连接到MCP服务器"""
        try:
            await self.mcp_client.connect_to_server(self.server_path)
            print(f"\n已成功连接到服务器: {self.server_path}")
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