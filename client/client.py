import asyncio
import os
import sys
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
            raise ValueError(f"\nOPENAI_API_KEY 未设置")
        
        self.client = OpenAI(
            api_key=self.openai_api_key,
            base_url=self.base_url
        )
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
        # 添加历史消息列表，用于存储对话历史
        self.history_messages = [
            {"role": "system", "content": "你是一个专注于执行工具调用的助手。如果工具调用成功，直接报告结果，不要发散讨论。如果工具调用失败，明确分析失败原因并提出精确的修复方案。保持回答简洁明了。"}
        ]
        # 添加命令历史，用于存储用户请求历史
        self.command_history = []
        # 设置历史记录最大长度
        self.max_history_length = 10
        
    def _add_to_history(self, query: str, response: str):
        """
        添加一对对话到历史记录
        
        Args:
            query: 用户查询
            response: 助手响应
        """
        self.history_messages.append({"role": "user", "content": query})
        self.history_messages.append({"role": "assistant", "content": response})
        self._manage_history_size()
        
    def _manage_history_size(self):
        """管理历史记录大小，确保不会过大"""
        # 保持命令历史在合理范围内
        if len(self.command_history) > self.max_history_length:
            self.command_history = self.command_history[-self.max_history_length:]
            
        # 保持消息历史在合理范围内
        # 保留系统消息和最近的对话
        if len(self.history_messages) > (self.max_history_length * 2 + 1):  # 系统消息 + (用户+助手) * max_length
            # 保留系统消息
            system_messages = [msg for msg in self.history_messages if msg["role"] == "system"]
            # 保留最近的对话
            recent_messages = self.history_messages[-(self.max_history_length * 2):]
            # 合并
            self.history_messages = system_messages + recent_messages
        
    async def connect_to_server(self, server_script_path: str):
        """连接到服务器"""
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        
        if not (is_python or is_js):
            raise ValueError(f"\n服务器脚本必须是Python或JavaScript文件")
        
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )
        
        # 创建stdio客户端
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        await self.session.initialize()
        
        # 获取服务器信息
        print(f"\n成功连接到服务器")
        
        # 获取工具列表
        response = await self.session.list_tools()
        tools = response.tools
        print(f"\n已链接到服务器， 可用的工具：", [tool.name for tool in tools])
        
    async def process_query(self, query: str) -> str:
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
        
        # 记录重试次数
        retry_count = 0
        max_retries = 3
        
        trans_messages = [
            {"role": "system", "content": f"你是Linux命令行大师，将输入内容全部理解并翻译为 Linux bash 命令。如果涉及到打开文件操作，请使用xdg-open命令。请不要解释命令功能，只输出命令本身。格式为：CMD:实际命令。例如对于'显示当前目录'，只需返回'CMD:ls'。对于复杂命令，如果需要使用shell特性（如管道、重定向），应添加参数'use_shell:true'，例如：'CMD:ls -la | grep .txt;use_shell:true'。{history_context if history_context else ''}"},
            {"role": "user", "content": query}]
        # 先将用户查询翻译为bash命令
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
            # 提取命令部分
            cmd_parts = translated_content.split("CMD:", 1)[1].strip()
            
            # 检查是否有use_shell参数
            use_shell = False
            if ";use_shell:true" in cmd_parts.lower():
                use_shell = True
                cmd_parts = cmd_parts.split(";use_shell:", 1)[0].strip()
            
            # 分解命令和参数
            if " " in cmd_parts:
                command = cmd_parts.split(" ", 1)[0]
                args = cmd_parts.split(" ", 1)[1]
            else:
                command = cmd_parts
                args = ""
            
            # 自动执行命令
            print(f"\n识别到命令，正在执行: {command} {args}")
            try:
                print(f"\n\n[Auto running bash command: {command} with args {args}, use_shell={use_shell}]\n\n")
                response = await self.session.list_tools()
                
                # 构建可用工具列表
                available_tools = [{"type": "function", 
                                   "function": {
                                       "name": tool.name, 
                                       "description": tool.description, 
                                       "input_schema": tool.inputSchema
                                       }
                                   } for tool in response.tools]
                
                # 查找run_bash工具
                bash_tool = None
                for tool in available_tools:
                    if tool["function"]["name"] == "run_bash":
                        bash_tool = tool
                        break
                
                if bash_tool:
                    # 构建工具调用参数
                    tool_args = {
                        "command": command,
                        "args": args
                    }
                    
                    if use_shell:
                        tool_args["use_shell"] = True
                    
                    result = await self.session.call_tool("run_bash", tool_args)
                    tool_result = str(result.content[0].text)
                    
                    # 更新历史消息
                    self._add_to_history(query, tool_result)
                    
                    return tool_result
                else:
                    # 如果找不到run_bash工具，回退到常规工具调用处理
                    user_message = f"执行bash命令：{cmd_parts}"
            except Exception as e:
                print(f"自动执行命令失败: {str(e)}")
                # 命令执行失败，继续使用常规流程
                if history_context:
                    user_message = f"{history_context}\n\n当前查询: {translated_content}"
                else:
                    user_message = translated_content
        else:
            # 创建包含历史上下文的用户消息
            if history_context:
                user_message = f"{history_context}\n\n当前查询: {translated_content}"
            else:
                user_message = translated_content

        # 复制历史消息列表用于本次查询
        current_messages = self.history_messages.copy()
        current_messages.append({"role": "user", "content": user_message})
        
        response = await self.session.list_tools()
        
        # 构建可用工具列表
        available_tools = [{"type": "function", 
                            "function": {
                                "name": tool.name, 
                                "description": tool.description, 
                                "input_schema": tool.inputSchema
                                }
                            } for tool in response.tools]
        
        response = self.client.chat.completions.create(
            model = self.model,
            messages = current_messages,
            tools = available_tools,
            temperature = 0.7  # 初始调用保持适当的创造性
        )
        
        print(f"\n{response}")
        
        content = response.choices[0]
        if content.finish_reason == "tool_calls":
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            # 执行工具调用
            try:
                print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")
                result = await self.session.call_tool(tool_name, tool_args)
                
                # 检查工具调用结果是否成功
                # 这里我们假设如果有错误，result.content[0].text中会包含错误信息
                tool_result = str(result.content[0].text)
                
                # 判断是否是工具调用失败
                english_indicators = ["error", "exception", "failed"]
                chinese_indicators = ["失败", "不存在", "无法", "错误", "未找到", "无效", "请检查", "请确认", "不正确"]
                
                # 检查工具结果是否包含任何错误指示器
                is_english_failed = any(indicator in tool_result.lower() for indicator in english_indicators)
                is_chinese_failed = any(indicator in tool_result for indicator in chinese_indicators)
                
                # 如果结果中包含任何一个错误指示器，则认为调用失败
                if is_english_failed or is_chinese_failed:
                    print(f"\n[Tool call failed: {tool_result}]")
                    
                    # 分析错误原因和可能的解决方案
                    error_analysis_messages = [
                        {"role": "system", "content": "你是一个专注于分析工具调用错误的专家。请提供简明扼要的错误分析和具体可执行的解决方案。不要发散讨论。"},
                        {"role": "user", "content": f"工具'{tool_name}'调用失败，错误信息：{tool_result}。原始调用参数：{json.dumps(tool_args)}。可用工具：{[t['function']['name'] for t in available_tools]}。请分析错误原因并提供具体解决方案。"}
                    ]
                    
                    error_analysis = self.client.chat.completions.create(
                        model = self.model,
                        messages = error_analysis_messages
                    )
                    
                    analysis_result = error_analysis.choices[0].message.content
                    print(f"\n[Error analysis: {analysis_result}]")
                    
                    # 生成新的消息进行重试
                    retry_messages = current_messages.copy()
                    retry_messages.append(content.message.model_dump())
                    retry_messages.append({
                        "role": "tool",
                        "content": tool_result,
                        "tool_call_id": tool_call.id
                    })
                    retry_messages.append({
                        "role": "system", 
                        "content": "工具调用失败。请分析失败原因，并立即使用正确的参数重新调用工具。你必须使用工具，不要只给出分析。"
                    })
                    retry_messages.append({
                        "role": "user", 
                        "content": f"刚才的工具调用失败了，错误信息是：{tool_result}。请分析原因并立即使用修正后的参数重新调用工具。"
                    })
                    
                    # 重新调用模型进行修正
                    retry_response = self.client.chat.completions.create(
                        model = self.model,
                        messages = retry_messages,
                        temperature = 0.2,  # 降低温度，使回复更加可控和专注
                        tools = available_tools,  # 提供工具列表
                        tool_choice = "auto"  # 强制模型选择使用工具
                    )
                    
                    # 检查重试结果
                    retry_content = retry_response.choices[0]
                    if retry_content.finish_reason == "tool_calls":
                        # 处理重试的工具调用
                        retry_tool_call = retry_content.message.tool_calls[0]
                        retry_tool_name = retry_tool_call.function.name
                        retry_tool_args = json.loads(retry_tool_call.function.arguments)
                        
                        print(f"\n\n[Retrying tool {retry_tool_name} with args {retry_tool_args}]\n\n")
                        
                        try:
                            retry_result = await self.session.call_tool(retry_tool_name, retry_tool_args)
                            retry_tool_result = str(retry_result.content[0].text)
                            
                            # 检查重试结果是否成功
                            english_indicators = ["error", "exception", "failed"]
                            chinese_indicators = ["失败", "不存在", "无法", "错误", "未找到", "无效", "请检查", "请确认", "不正确"]
                            
                            is_english_failed = any(indicator in retry_tool_result.lower() for indicator in english_indicators)
                            is_chinese_failed = any(indicator in retry_tool_result for indicator in chinese_indicators)
                            
                            if is_english_failed or is_chinese_failed:
                                print(f"\n[Retry tool call failed: {retry_tool_result}]")
                                raise Exception(f"重试工具调用依然失败: {retry_tool_result}")
                                
                            # 更新消息
                            retry_messages.append(retry_content.message.model_dump())
                            retry_messages.append({
                                "role": "tool",
                                "content": retry_tool_result,
                                "tool_call_id": retry_tool_call.id
                            })
                            
                            # 最终响应
                            final_response = self.client.chat.completions.create(
                                model = self.model,
                                messages = retry_messages
                            )
                            
                            # 更新历史消息
                            self._add_to_history(query, final_response.choices[0].message.content)
                            
                            return final_response.choices[0].message.content
                        except Exception as e:
                            # 如果重试仍然失败，返回错误信息
                            error_message = f"工具调用重试失败: {str(e)}"
                            print(f"\n[{error_message}]")
                            
                            retry_messages.append({
                                "role": "system",
                                "content": f"{error_message}。请再尝试一次，修正参数后必须重新调用工具。"
                            })
                            retry_messages.append({
                                "role": "user",
                                "content": "请仔细检查参数并再次尝试，必须使用正确的工具和参数。"
                            })
                            
                            final_retry_response = self.client.chat.completions.create(
                                model = self.model,
                                messages = retry_messages,
                                temperature = 0.2,  # 降低温度，使回复更加可控和专注
                                tools = available_tools,  # 提供工具列表
                                tool_choice = "auto"  # 强制模型选择使用工具
                            )
                            
                            final_retry_content = final_retry_response.choices[0]
                            if final_retry_content.finish_reason == "tool_calls":
                                # 处理最终重试的工具调用
                                final_tool_call = final_retry_content.message.tool_calls[0]
                                final_tool_name = final_tool_call.function.name
                                final_tool_args = json.loads(final_tool_call.function.arguments)
                                
                                print(f"\n\n[Final retry tool {final_tool_name} with args {final_tool_args}]\n\n")
                                
                                try:
                                    final_result = await self.session.call_tool(final_tool_name, final_tool_args)
                                    final_tool_result = str(final_result.content[0].text)
                                    
                                    # 检查最终重试结果是否成功
                                    english_indicators = ["error", "exception", "failed"]
                                    chinese_indicators = ["失败", "不存在", "无法", "错误", "未找到", "无效", "请检查", "请确认", "不正确"]
                                    
                                    is_english_failed = any(indicator in final_tool_result.lower() for indicator in english_indicators)
                                    is_chinese_failed = any(indicator in final_tool_result for indicator in chinese_indicators)
                                    
                                    if is_english_failed or is_chinese_failed:
                                        print(f"\n[Final retry tool call failed: {final_tool_result}]")
                                        
                                        # 更新历史消息
                                        self._add_to_history(query, f"工具调用多次失败。最终错误：{final_tool_result}")
                                        
                                        return f"工具调用多次失败。最终错误：{final_tool_result}"
                                    
                                    # 更新消息
                                    retry_messages.append(final_retry_content.message.model_dump())
                                    retry_messages.append({
                                        "role": "tool",
                                        "content": final_tool_result,
                                        "tool_call_id": final_tool_call.id
                                    })
                                    
                                    # 最终响应
                                    final_response = self.client.chat.completions.create(
                                        model = self.model,
                                        messages = retry_messages,
                                        temperature = 0.3
                                    )
                                    
                                    # 更新历史消息
                                    self._add_to_history(query, final_response.choices[0].message.content)
                                    
                                    return final_response.choices[0].message.content
                                except Exception as last_error:
                                    error_result = f"工具调用多次失败。最终错误：{str(last_error)}。请检查参数并手动重试。"
                                    
                                    # 更新历史消息
                                    self._add_to_history(query, error_result)
                                    
                                    return error_result
                            
                            error_response = self.client.chat.completions.create(
                                model = self.model,
                                messages = retry_messages,
                                temperature = 0.2  # 降低温度，使回复更加可控和专注
                            )
                            
                            # 更新历史消息
                            self._add_to_history(query, error_response.choices[0].message.content)
                            
                            return error_response.choices[0].message.content
                    else:
                        # 重试没有进行工具调用
                        
                        # 更新历史消息
                        self._add_to_history(query, retry_content.message.content)
                        
                        return retry_content.message.content
                else:
                    # 工具调用成功，继续正常处理
                    # 更新消息，确保所有内容都是字符串类型
                    current_messages.append(content.message.model_dump())
                    current_messages.append({
                        "role": "tool",
                        "content": tool_result,
                        "tool_call_id": tool_call.id
                    })
                    
                    # 添加系统提示，限制模型只输出工具调用的结果
                    current_messages.append({
                        "role": "system",
                        "content": "只专注于回答用户问题，不要发散讨论。直接提供工具调用结果的简明总结。不需要解释工具是如何被调用的，直接给出最终答案。"
                    })
                    
                    response = self.client.chat.completions.create(
                        model = self.model,
                        messages = current_messages,
                        temperature = 0.3  # 使输出更加可控
                    )
                    
                    # 更新历史消息
                    self._add_to_history(query, response.choices[0].message.content)
                    
                    return response.choices[0].message.content
            except Exception as e:
                # 捕获工具调用中的异常
                error_message = f"工具调用出错: {str(e)}"
                print(f"\n[{error_message}]")
                
                # 分析错误原因
                error_analysis_messages = [
                    {"role": "system", "content": "你是一个专注于分析工具调用异常的专家。请提供简明扼要的错误分析和具体可执行的解决方案。不要发散讨论。"},
                    {"role": "user", "content": f"工具'{tool_name}'调用抛出异常：{str(e)}。原始调用参数：{json.dumps(tool_args)}。可用工具：{[t['function']['name'] for t in available_tools]}。请分析错误原因并提供具体解决方案。"}
                ]
                
                error_analysis = self.client.chat.completions.create(
                    model = self.model,
                    messages = error_analysis_messages
                )
                
                analysis_result = error_analysis.choices[0].message.content
                print(f"\n[Error analysis: {analysis_result}]")
                
                # 生成新的消息进行重试
                exception_messages = current_messages.copy()
                exception_messages.append(content.message.model_dump())
                exception_messages.append({
                    "role": "system",
                    "content": f"工具调用失败，出现异常：{str(e)}。请分析失败原因，并立即使用正确的参数重新调用工具。你必须使用工具，不要只给出分析。"
                })
                exception_messages.append({
                    "role": "user", 
                    "content": f"刚才的工具调用因异常失败了：{str(e)}。请分析原因并立即使用修正后的参数重新调用工具。"
                })
                
                # 重新调用模型进行修正
                exception_response = self.client.chat.completions.create(
                    model = self.model,
                    messages = exception_messages,
                    temperature = 0.2,  # 降低温度，使回复更加可控和专注
                    tools = available_tools,  # 提供工具列表
                    tool_choice = "auto"  # 强制模型选择使用工具
                )
                
                exception_content = exception_response.choices[0]
                if exception_content.finish_reason == "tool_calls":
                    # 处理重试的工具调用
                    retry_tool_call = exception_content.message.tool_calls[0]
                    retry_tool_name = retry_tool_call.function.name
                    retry_tool_args = json.loads(retry_tool_call.function.arguments)
                    
                    print(f"\n\n[Retrying tool {retry_tool_name} with args {retry_tool_args}]\n\n")
                    
                    try:
                        retry_result = await self.session.call_tool(retry_tool_name, retry_tool_args)
                        retry_tool_result = str(retry_result.content[0].text)
                        
                        # 检查重试结果是否成功
                        english_indicators = ["error", "exception", "failed"]
                        chinese_indicators = ["失败", "不存在", "无法", "错误", "未找到", "无效", "请检查", "请确认", "不正确"]
                        
                        is_english_failed = any(indicator in retry_tool_result.lower() for indicator in english_indicators)
                        is_chinese_failed = any(indicator in retry_tool_result for indicator in chinese_indicators)
                        
                        if is_english_failed or is_chinese_failed:
                            print(f"\n[Retry tool call failed: {retry_tool_result}]")
                            raise Exception(f"重试工具调用依然失败: {retry_tool_result}")
                            
                        # 更新消息
                        exception_messages.append(exception_content.message.model_dump())
                        exception_messages.append({
                            "role": "tool",
                            "content": retry_tool_result,
                            "tool_call_id": retry_tool_call.id
                        })
                        
                        # 最终响应
                        final_response = self.client.chat.completions.create(
                            model = self.model,
                            messages = exception_messages
                        )
                        
                        # 更新历史消息
                        self._add_to_history(query, final_response.choices[0].message.content)
                        
                        return final_response.choices[0].message.content
                    except Exception as retry_error:
                        # 如果重试仍然失败，返回错误信息
                        final_error_message = f"工具调用重试失败: {str(retry_error)}"
                        print(f"\n[{final_error_message}]")
                        
                        exception_messages.append({
                            "role": "system",
                            "content": f"{final_error_message}。请再尝试一次，修正参数后必须重新调用工具。"
                        })
                        exception_messages.append({
                            "role": "user",
                            "content": "请仔细检查参数并再次尝试，必须使用正确的工具和参数。"
                        })
                        
                        final_retry_response = self.client.chat.completions.create(
                            model = self.model,
                            messages = exception_messages,
                            temperature = 0.2,  # 降低温度，使回复更加可控和专注
                            tools = available_tools,  # 提供工具列表
                            tool_choice = "auto"  # 强制模型选择使用工具
                        )
                        
                        final_retry_content = final_retry_response.choices[0]
                        if final_retry_content.finish_reason == "tool_calls":
                            # 处理最终重试的工具调用
                            final_tool_call = final_retry_content.message.tool_calls[0]
                            final_tool_name = final_tool_call.function.name
                            final_tool_args = json.loads(final_tool_call.function.arguments)
                            
                            print(f"\n\n[Final retry tool {final_tool_name} with args {final_tool_args}]\n\n")
                            
                            try:
                                final_result = await self.session.call_tool(final_tool_name, final_tool_args)
                                final_tool_result = str(final_result.content[0].text)
                                
                                # 检查最终重试结果是否成功
                                english_indicators = ["error", "exception", "failed"]
                                chinese_indicators = ["失败", "不存在", "无法", "错误", "未找到", "无效", "请检查", "请确认", "不正确"]
                                
                                is_english_failed = any(indicator in final_tool_result.lower() for indicator in english_indicators)
                                is_chinese_failed = any(indicator in final_tool_result for indicator in chinese_indicators)
                                
                                if is_english_failed or is_chinese_failed:
                                    print(f"\n[Final retry tool call failed: {final_tool_result}]")
                                    
                                    # 更新历史消息
                                    self._add_to_history(query, f"工具调用多次失败。最终错误：{final_tool_result}")
                                    
                                    return f"工具调用多次失败。最终错误：{final_tool_result}"
                                
                                # 更新消息
                                exception_messages.append(final_retry_content.message.model_dump())
                                exception_messages.append({
                                    "role": "tool",
                                    "content": final_tool_result,
                                    "tool_call_id": final_tool_call.id
                                })
                                
                                # 最终响应
                                final_response = self.client.chat.completions.create(
                                    model = self.model,
                                    messages = exception_messages,
                                    temperature = 0.3
                                )
                                
                                # 更新历史消息
                                self._add_to_history(query, final_response.choices[0].message.content)
                                
                                return final_response.choices[0].message.content
                            except Exception as last_error:
                                error_result = f"工具调用多次失败。最终错误：{str(last_error)}。请检查参数并手动重试。"
                                
                                # 更新历史消息
                                self._add_to_history(query, error_result)
                                
                                return error_result
                        
                        error_response = self.client.chat.completions.create(
                            model = self.model,
                            messages = exception_messages,
                            temperature = 0.2  # 降低温度，使回复更加可控和专注
                        )
                        
                        # 更新历史消息
                        self._add_to_history(query, error_response.choices[0].message.content)
                        
                        return error_response.choices[0].message.content
                else:
                    # 重试没有进行工具调用
                    
                    # 更新历史消息
                    self._add_to_history(query, exception_content.message.content)
                    
                    return exception_content.message.content
        
        # 更新历史消息
        self._add_to_history(query, content.message.content)
        
        return content.message.content

    async def chat_loop(self):
        """聊天循环"""
        print("\n MCP 客户端已启动，输入'quit'退出")
        print(" 支持上下文记忆功能，会记住您之前的命令")
        
        while True:
            try:
                # 显示当前会话状态（有多少历史记录）
                history_count = len(self.command_history)
                if history_count > 0:
                    print(f"\n[当前会话已记录 {history_count} 条命令历史]")
                
                query = input("\nQuery: ").strip()
                if query.lower() == 'quit':
                    break
                elif query.lower() == 'history':
                    # 显示历史命令
                    print("\n历史命令记录:")
                    for i, cmd in enumerate(self.command_history, 1):
                        print(f"{i}. {cmd}")
                    continue
                elif query.lower() == 'clear history':
                    # 清除历史命令
                    self.command_history = []
                    self.history_messages = [
                        {"role": "system", "content": "你是一个专注于执行工具调用的助手。如果工具调用成功，直接报告结果，不要发散讨论。如果工具调用失败，明确分析失败原因并提出精确的修复方案。保持回答简洁明了。"}
                    ]
                    print("\n已清除所有历史记录")
                    continue
                
                print(f"\n [Mock Response] Your request： {query}")
                
                # 获取响应
                response = await self.process_query(query)
                if response is None:
                    continue
                
                print("\n [Mock Response] Assistant: ", end="", flush=True)
                print(response)
                
            except Exception as e:
                print(f"\n Error： {str(e)}")
    
    async def cleanup(self):
        """清理资源"""
        if self.exit_stack:
            await self.exit_stack.aclose()
            
async def main():
    if len(sys.argv) < 2:
        print("\nUsage: python client.py <server_script_path>")
        sys.exit(1)
    
    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()
        
if __name__ == "__main__":
    asyncio.run(main())
