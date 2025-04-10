import asyncio
import json
import re
from typing import List, Dict, Any, Optional

from openai import OpenAI


class TaskManager:
    """任务管理器，负责规划、执行和总结任务"""
    def __init__(self, openai_client: OpenAI, model: str):
        """
        初始化任务管理器
        
        Args:
            openai_client: OpenAI客户端实例
            model: 使用的OpenAI模型名称
        """
        self.client = openai_client
        self.model = model
        self.connected_servers = {}
        self.all_tools = []
        self.mcp_client = None

    async def plan_tasks(self, user_request: str) -> List[Dict[str, Any]]:
        """
        将用户请求拆分为多个按时间顺序执行的原子任务，并为每个任务标识最适合的工具类型
        
        Args:
            user_request: 用户的请求文本
            
        Returns:
            List[Dict[str, Any]]: 任务列表，每个任务包含描述和工具类型
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

    async def execute_task(self, task: Dict[str, Any], mcp_client, connected_servers, all_tools) -> str:
        """
        执行单个任务，根据任务类型选择最合适的工具
        
        Args:
            task: 任务描述字典
            mcp_client: MCP客户端实例
            connected_servers: 连接的服务器信息
            all_tools: 所有可用工具列表
            
        Returns:
            str: 任务执行结果
        """
        try:
            # 设置必要的引用
            self.mcp_client = mcp_client
            self.connected_servers = connected_servers
            self.all_tools = all_tools
            
            # 检查是否有效连接
            if not self.mcp_client or not self.connected_servers:
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

    async def execute_tasks(self, tasks: List[Dict[str, Any]], mcp_client, connected_servers, all_tools) -> Dict[str, str]:
        """
        依次执行任务列表
        
        Args:
            tasks: 任务列表
            mcp_client: MCP客户端实例
            connected_servers: 连接的服务器信息
            all_tools: 所有可用工具列表
            
        Returns:
            Dict[str, str]: 任务描述到执行结果的映射
        """
        results = {}
        
        # 创建任务执行进度显示
        print(f"\n总计 {len(tasks)} 个任务待执行:\n")
        for i, task in enumerate(tasks, 1):
            print(f"{i}. [ ] {task['description']} (推荐工具: {task['tool_type']})")
        
        # 依次执行任务
        for i, task in enumerate(tasks, 1):
            print(f"\n正在执行任务 {i}/{len(tasks)}: {task['description']}")
            result = await self.execute_task(task, mcp_client, connected_servers, all_tools)
            results[task['description']] = result
            
            # 更新任务状态
            print("\n任务执行状态:")
            for j, t in enumerate(tasks, 1):
                status = "✓" if j <= i else " "
                print(f"{j}. [{status}] {t['description']}")
        
        return results

    async def summarize_results(self, user_request: str, tasks: List[Dict[str, Any]], results: Dict[str, str]) -> str:
        """
        汇总任务执行结果
        
        Args:
            user_request: 原始用户请求
            tasks: 任务列表
            results: 任务执行结果
            
        Returns:
            str: 执行结果总结
        """
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