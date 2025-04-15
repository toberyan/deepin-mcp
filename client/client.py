import asyncio
import os
import json
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

class MCPClient:
    def __init__(self):
        """初始化MCP客户端"""
        self.exit_stack = AsyncExitStack()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL")
        
        if not self.openai_api_key:
            raise ValueError("\nOPENAI_API_KEY 未设置")
        
        self.client = OpenAI(
            api_key=self.openai_api_key,
            base_url=self.base_url
        )
        self.session: Optional[ClientSession] = None
        
        # 添加历史消息列表，用于存储对话历史
        self.history_messages = [
            {"role": "system", "content": "你是一个专注于执行工具调用的助手。如果工具调用成功，直接报告结果，不要发散讨论。如果工具调用失败，明确分析失败原因并提出精确的修复方案。保持回答简洁明了。"}
        ]
        # 添加命令历史，用于存储用户请求历史
        self.command_history = []
        # 设置历史记录最大长度
        self.max_history_length = 10
        
        # 从环境变量获取命令间隔时间(毫秒)，默认为10ms
        try:
            self.command_delay = float(os.getenv("COMMAND_DELAY_MS", "10")) / 1000.0
        except ValueError:
            print("\n警告: COMMAND_DELAY_MS 环境变量格式不正确，使用默认值100ms")
            self.command_delay = 0.1
        
    def _add_to_history(self, query: str, response: str):
        """添加一对对话到历史记录"""
        self.history_messages.append({"role": "user", "content": query})
        self.history_messages.append({"role": "assistant", "content": response})
        self._manage_history_size()
        
    def _manage_history_size(self):
        """管理历史记录大小，确保不会过大"""
        # 保持命令历史在合理范围内
        if len(self.command_history) > self.max_history_length:
            self.command_history = self.command_history[-self.max_history_length:]
            
        # 保持消息历史在合理范围内
        if len(self.history_messages) > (self.max_history_length * 2 + 1):
            # 保留系统消息
            system_messages = [msg for msg in self.history_messages if msg["role"] == "system"]
            # 保留最近的对话
            recent_messages = self.history_messages[-(self.max_history_length * 2):]
            # 合并
            self.history_messages = system_messages + recent_messages
        
    async def connect_to_server(self, server_script_path: str):
        """连接到服务器"""
        # 检查是否是shell命令（来自run_server.sh脚本）
        if server_script_path.endswith("run_server.sh") or " " in server_script_path:
            command_parts = server_script_path.split()
            command = command_parts[0] if len(command_parts) > 1 else server_script_path
            args = command_parts[1:] if len(command_parts) > 1 else []
                
            server_params = StdioServerParameters(command=command, args=args, env=None)
        else:
            # 正常的Python或JS文件处理
            is_python = server_script_path.endswith(".py") or server_script_path.endswith(".wrapper.py")
            is_js = server_script_path.endswith(".js")
            
            if not (is_python or is_js):
                raise ValueError("\n服务器脚本必须是Python或JavaScript文件")
            
            command = "python" if is_python else "node"
            server_params = StdioServerParameters(command=command, args=[server_script_path], env=None)
        
        # 创建stdio客户端
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        await self.session.initialize()
        
        # 获取工具列表
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已链接到服务器， 可用的工具：", [tool.name for tool in tools])
        
    async def process_query(self, query: str, all_tools=None, connected_servers=None) -> str:
        # 记录用户的原始查询
        self.command_history.append(query)
        
        # 如果有历史命令，创建历史上下文提示
        history_context = ""
        if len(self.command_history) > 1:
            history_context = "历史查询记录:\n"
            # 只使用最近的5条历史记录
            for i, cmd in enumerate(self.command_history[-6:-1], 1):
                history_context += f"{i}. {cmd}\n"
            history_context += "\n请参考上述历史查询，理解用户可能的意图。"
        
        # 首先检查可用的工具类型
        bash_tool_available = False
        available_tools = []
        
        try:
            # 获取可用工具列表
            if all_tools is not None:
                tool_list = all_tools
            else:
                response = await self.session.list_tools()
                tool_list = response.tools
            
            # 构建可用工具列表并检查是否有bash工具
            available_tools = [{"type": "function", 
                              "function": {
                                  "name": tool.name, 
                                  "description": tool.description, 
                                  "input_schema": tool.inputSchema
                                  }
                              } for tool in tool_list]
            
            # 检查是否存在run_bash工具
            for tool in available_tools:
                if tool["function"]["name"] == "run_bash":
                    bash_tool_available = True
                    break
        except Exception as e:
            print(f"获取工具列表时出错: {str(e)}")
            available_tools = []
            
        # 仅当存在bash工具时才进行命令翻译
        translated_content = ""
        is_bash_command = False
        
        if bash_tool_available:
            # 将用户查询翻译为bash命令
            trans_messages = [
                {"role": "system", "content": f"你是Linux命令行大师，将输入内容全部理解并翻译为 Linux bash 命令。如果涉及到打开文件操作，请使用xdg-open命令。请不要解释命令功能，只输出命令本身。格式为：CMD:实际命令。例如对于'显示当前目录'，只需返回'CMD:ls'。对于复杂命令，如果需要使用shell特性（如管道、重定向），应添加参数'use_shell:true'，例如：'CMD:ls -la | grep .txt;use_shell:true'。{history_context if history_context else ''}"},
                {"role": "user", "content": query}
            ]
            translation_response = self.client.chat.completions.create(
                model=self.model,
                messages=trans_messages
            )
            
            # 获取翻译后的命令
            translated_content = translation_response.choices[0].message.content
            print(f"\n原始查询: {query}")
            print(f"翻译结果: {translated_content}")
            
            # 检查是否返回了有效的命令格式
            if "CMD:" in translated_content:
                is_bash_command = True
                
        # 如果是bash命令并且有bash工具可用，则自动执行命令
        if is_bash_command and bash_tool_available and (all_tools is None or connected_servers is None):
            # 提取命令部分
            cmd_parts = translated_content.split("CMD:", 1)[1].strip()
            
            # 检查是否有use_shell参数
            use_shell = False
            if ";use_shell:true" in cmd_parts.lower():
                use_shell = True
                cmd_parts = cmd_parts.split(";use_shell:", 1)[0].strip()
            
            # 处理多条命令的情况（用分号分隔的多条命令）
            commands = [cmd.strip() for cmd in cmd_parts.split(";") if cmd.strip()] if ";" in cmd_parts and not use_shell else [cmd_parts]
            
            # 自动执行命令
            if len(commands) > 1:
                print(f"\n识别到多条命令，将依次执行，命令间隔{int(self.command_delay * 1000)}毫秒: {commands}")
            else:
                print(f"\n识别到命令，正在执行: {commands[0]}")
                
            try:
                # 查找run_bash工具
                bash_tool = None
                for tool in available_tools:
                    if tool["function"]["name"] == "run_bash":
                        bash_tool = tool
                        break
                
                if bash_tool:
                    all_results = []
                    
                    for i, command_str in enumerate(commands):
                        # 分解命令和参数
                        command = command_str.split(" ", 1)[0] if " " in command_str else command_str
                        args = command_str.split(" ", 1)[1] if " " in command_str else ""
                            
                        print(f"\n\n[Auto running bash command: {command} with args {args}, use_shell={use_shell}]\n\n")
                        
                        # 构建工具调用参数
                        tool_args = {"command": command, "args": args}
                        if use_shell:
                            tool_args["use_shell"] = True
                        
                        result = await self.session.call_tool("run_bash", tool_args)
                        tool_result = str(result.content[0].text)
                        all_results.append(tool_result)
                        
                        # 如果不是最后一条命令，等待命令间隔
                        if i < len(commands) - 1:
                            await asyncio.sleep(self.command_delay)
                    
                    # 合并所有结果
                    combined_result = "\n\n".join(all_results)
                    
                    # 更新历史消息
                    self._add_to_history(query, combined_result)
                    return combined_result
                else:
                    # 如果找不到run_bash工具，回退到常规工具调用处理
                    user_message = f"执行bash命令：{cmd_parts}"
            except Exception as e:
                print(f"自动执行命令失败: {str(e)}")
                # 命令执行失败，继续使用常规流程
                user_message = f"{history_context}\n\n当前查询: {translated_content}" if history_context else translated_content
        else:
            # 如果没有翻译成bash命令或者没有bash工具可用，使用原始查询
            user_message = query
        
        # 处理集成多服务器工具的情况
        if all_tools is not None and connected_servers is not None:
            try:
                # 使用模型选择最合适的工具
                content = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个专注于执行工具调用的助手。分析用户请求，选择最合适的工具进行调用。工具名称格式为'server_name.tool_name'，表示该工具由哪个服务器提供。针对文件操作使用file服务器工具，针对命令行操作使用bash服务器工具。"},
                        {"role": "user", "content": user_message}
                    ],
                    tools=available_tools,
                    tool_choice="auto"
                )
                
                # 检查模型是否决定调用工具
                if content.choices[0].finish_reason == "tool_calls":
                    # 获取工具调用信息
                    tool_call = content.choices[0].message.tool_calls[0]
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # 解析工具名称，获取服务器名称和实际工具名称
                    server_name, actual_tool_name = tool_name.split(".", 1)
                    
                    print(f"\n\n[调用服务器 '{server_name}' 的工具 '{actual_tool_name}' 参数: {tool_args}]\n\n")
                    
                    # 检查服务器是否存在
                    if server_name not in connected_servers:
                        return f"错误: 服务器 '{server_name}' 不存在或未连接"
                    
                    # 获取对应服务器的客户端
                    server_client = connected_servers[server_name]["client"]
                    
                    # 调用工具
                    result = await server_client.session.call_tool(actual_tool_name, tool_args)
                    tool_result = str(result.content[0].text)
                    
                    # 生成最终结果
                    current_messages = self.history_messages + [
                        {"role": "user", "content": user_message},
                        content.choices[0].message.model_dump(),
                        {"role": "tool", "content": tool_result, "tool_call_id": tool_call.id}
                    ]
                    
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=current_messages,
                        temperature=0.3
                    )
                    
                    # 更新历史消息
                    self._add_to_history(query, response.choices[0].message.content)
                    return response.choices[0].message.content
                else:
                    # 模型没有选择调用工具，返回普通回复
                    response_content = content.choices[0].message.content
                    
                    # 更新历史消息
                    self._add_to_history(query, response_content)
                    return response_content
            except Exception as e:
                error_message = f"工具调用出错: {str(e)}"
                print(f"\n[{error_message}]")
                return f"处理请求时出错: {str(e)}"
        
        # 使用常规流程处理查询
        try:
            content = self.client.chat.completions.create(
                model=self.model,
                messages=self.history_messages + [{"role": "user", "content": user_message}],
                tools=available_tools,
                tool_choice="auto"
            )
            
            # 检查模型是否决定调用工具
            if content.choices[0].finish_reason == "tool_calls":
                # 获取工具调用信息
                tool_call = content.choices[0].message.tool_calls[0]
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                print(f"\n\n[调用工具 {tool_name} 参数: {tool_args}]\n\n")
                
                # 调用工具
                result = await self.session.call_tool(tool_name, tool_args)
                tool_result = str(result.content[0].text)
                
                # 生成最终结果
                current_messages = self.history_messages + [
                    {"role": "user", "content": user_message},
                    content.choices[0].message.model_dump(),
                    {"role": "tool", "content": tool_result, "tool_call_id": tool_call.id}
                ]
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=current_messages,
                    temperature=0.3
                )
                
                # 更新历史消息
                self._add_to_history(query, response.choices[0].message.content)
                return response.choices[0].message.content
            else:
                # 模型没有选择调用工具，返回普通回复
                response_content = content.choices[0].message.content
                
                # 更新历史消息
                self._add_to_history(query, response_content)
                return response_content
        except Exception as e:
            error_message = f"工具调用出错: {str(e)}"
            print(f"\n[{error_message}]")
            return f"处理请求时出错: {str(e)}"

    async def cleanup(self):
        """清理资源"""
        if not hasattr(self, 'exit_stack'):
            return
        
        try:
            if hasattr(self, '_cleanup_pending_tasks'):
                try:
                    await self._cleanup_pending_tasks()
                except Exception as e:
                    print(f"取消待处理任务时出错: {str(e)}")
            
            try:
                await asyncio.wait_for(self._close_exit_stack(), timeout=3.0)
            except asyncio.TimeoutError:
                print("警告: exit_stack关闭超时")
            except asyncio.CancelledError:
                print("注意: 清理过程中发生取消操作")
                try:
                    self._force_close_resources()
                except Exception:
                    pass
            except Exception as e:
                print(f"关闭exit_stack时出错: {str(e)}")
        except Exception as e:
            print(f"清理资源时出错: {str(e)}")
        finally:
            # 确保资源引用被清除
            self.exit_stack = None
            if hasattr(self, 'ws'):
                self.ws = None 
            if hasattr(self, 'process'):
                self.process = None

    async def _close_exit_stack(self):
        """安全地关闭exit_stack"""
        if hasattr(self, 'exit_stack') and self.exit_stack:
            try:
                await self.exit_stack.aclose()
            finally:
                self.exit_stack = None

    def _force_close_resources(self):
        """强制关闭资源，用于紧急情况"""
        # 强制关闭进程
        if hasattr(self, 'process') and self.process and hasattr(self.process, 'returncode') and self.process.returncode is None:
            try:
                self.process.kill()
            except Exception:
                pass
            self.process = None
        
        # 强制关闭websocket
        if hasattr(self, 'ws') and self.ws:
            try:
                self.ws.close_connection()
            except Exception:
                pass
            self.ws = None

    async def _cleanup_pending_tasks(self):
        """取消所有待处理的任务"""
        if hasattr(self, '_task_group') and self._task_group:
            try:
                await self._task_group.cancel_scope.cancel()
            except Exception:
                pass
