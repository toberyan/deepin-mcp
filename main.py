#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import argparse
import json
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from client.planning import TaskPlanner
from fastapi import FastAPI, Request, Response, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import uuid

# 版本信息
VERSION = "1.0.0"

# 标准输出重定向缓存
class OutputCapture:
    def __init__(self):
        self.captured_output = []
        self.subscribers = {}
    
    def write(self, text):
        self.captured_output.append(text)
        for callback in self.subscribers.values():
            callback(text)
        sys.__stdout__.write(text)
    
    def flush(self):
        sys.__stdout__.flush()
    
    def subscribe(self, callback):
        sub_id = str(uuid.uuid4())
        self.subscribers[sub_id] = callback
        return sub_id
    
    def unsubscribe(self, sub_id):
        if sub_id in self.subscribers:
            del self.subscribers[sub_id]

# 创建输出捕获器
output_capture = OutputCapture()
sys.stdout = output_capture

# 全局TaskPlanner实例
planner = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化TaskPlanner
    global planner
    try:
        load_dotenv()
        planner = TaskPlanner()
        # 使用默认服务器路径
        connected = await planner.connect_to_server()
        if not connected:
            print("\n无法连接到服务器，程序可能无法正常运行")
    except Exception as e:
        print(f"\n初始化过程中出现错误: {str(e)}")
    
    yield
    
    # 关闭时清理资源
    if planner:
        await planner.cleanup()

# 创建FastAPI应用
app = FastAPI(lifespan=lifespan)

# OpenAI API模型
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Dict[str, str]]
    stream: bool = False
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None

class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4()}")
    type: str = "function"
    function: Dict[str, Any]

class ChatChoice(BaseModel):
    index: int = 0
    message: Dict[str, Any]
    finish_reason: str = "stop"

class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4()}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(asyncio.get_event_loop().time()))
    model: str
    choices: List[ChatChoice]
    usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# 处理chat completions API
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, background_tasks: BackgroundTasks):
    global planner
    
    if not planner:
        raise HTTPException(status_code=500, detail="Task planner not initialized")
    
    # 提取用户查询
    user_request = ""
    for msg in request.messages:
        if msg["role"] == "user":
            user_request = msg["content"]
            break
    
    if not user_request:
        raise HTTPException(status_code=400, detail="No user message found")
    
    if request.stream:
        return StreamingResponse(
            stream_completion(user_request, request.model),
            media_type="text/event-stream"
        )
    else:
        try:
            # 1. 规划任务
            print("\n正在分析请求...")
            tasks = await planner.plan_tasks(user_request)
            
            if not tasks:
                content = "未能从请求中提取出具体任务，请尝试更明确的描述"
                return create_completion_response(request.model, content)
            
            print(f"\n已将请求拆解为 {len(tasks)} 个任务:")
            for i, task in enumerate(tasks, 1):
                print(f"{i}. {task}")
            
            # 2. 执行任务
            results = await planner.execute_tasks(tasks)
            
            # 3. 生成总结
            print("\n所有任务已执行完毕，正在生成总结...")
            summary = await planner.summarize_results(user_request, tasks, results)
            
            print("\n执行总结:")
            print(summary)
            
            return create_completion_response(request.model, summary)
        
        except Exception as e:
            traceback_str = traceback.format_exc()
            print(f"\n处理请求时出现错误: {str(e)}\n{traceback_str}")
            raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

def create_completion_response(model: str, content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        model=model,
        choices=[
            ChatChoice(
                message={
                    "role": "assistant",
                    "content": content
                }
            )
        ]
    )

async def stream_completion(user_request: str, model: str):
    global planner
    
    # 创建一个队列用于存储输出
    queue = asyncio.Queue()
    
    # 注册一个回调来接收控制台输出
    def output_callback(text):
        queue.put_nowait(text)
    
    # 订阅输出
    sub_id = output_capture.subscribe(output_callback)
    
    try:
        # 发送SSE事件头部
        yield f"data: {json.dumps({'id': f'chatcmpl-{uuid.uuid4()}', 'object': 'chat.completion.chunk', 'created': int(asyncio.get_event_loop().time()), 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        
        # 执行任务的异步函数
        async def execute():
            try:
                # 1. 规划任务
                print("\n正在分析请求...")
                tasks = await planner.plan_tasks(user_request)
                
                if not tasks:
                    # 发送最后一条消息
                    queue.put_nowait("\n未能从请求中提取出具体任务，请尝试更明确的描述")
                    return
                
                print(f"\n已将请求拆解为 {len(tasks)} 个任务:")
                for i, task in enumerate(tasks, 1):
                    print(f"{i}. {task}")
                
                # 2. 执行任务
                results = await planner.execute_tasks(tasks)
                
                # 3. 生成总结
                print("\n所有任务已执行完毕，正在生成总结...")
                summary = await planner.summarize_results(user_request, tasks, results)
                
                print("\n执行总结:")
                print(summary)
                
            except Exception as e:
                traceback_str = traceback.format_exc()
                queue.put_nowait(f"\n处理请求时出现错误: {str(e)}\n{traceback_str}")
        
        # 启动执行任务
        asyncio.create_task(execute())
        
        # 流式返回捕获的输出
        while True:
            try:
                output = await asyncio.wait_for(queue.get(), timeout=1.0)
                if output:
                    # 将输出分成小块发送，以保持流畅的流式响应
                    for chunk in output.split('\n'):
                        if chunk:
                            yield f"data: {json.dumps({'id': f'chatcmpl-{uuid.uuid4()}', 'object': 'chat.completion.chunk', 'created': int(asyncio.get_event_loop().time()), 'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk + '\n'}, 'finish_reason': None}]})}\n\n"
                            await asyncio.sleep(0.01)  # 短暂延迟以防止过快发送
            except asyncio.TimeoutError:
                # 检查执行任务是否完成
                if queue.empty():
                    # 发送完成信号
                    yield f"data: {json.dumps({'id': f'chatcmpl-{uuid.uuid4()}', 'object': 'chat.completion.chunk', 'created': int(asyncio.get_event_loop().time()), 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
    finally:
        # 取消订阅
        output_capture.unsubscribe(sub_id)

async def main():
    """
    主入口函数，初始化并运行任务规划系统
    """
    parser = argparse.ArgumentParser(description="Deepin MCP 任务规划系统")
    parser.add_argument("--server", "-s", type=str, help="指定MCP服务器脚本路径或名称", default=None)
    parser.add_argument("--list-servers", "-l", action="store_true", help="列出所有可用的服务器")
    parser.add_argument("--version", "-v", action="store_true", help="显示版本信息")
    parser.add_argument("--api-server", "-a", action="store_true", help="启动OpenAI兼容的API服务器")
    parser.add_argument("--cli", "-c", action="store_true", help="以CLI模式启动（不启动API服务器）")
    parser.add_argument("--port", "-p", type=int, default=0, help="API服务器端口号，0表示自动选择随机端口")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API服务器主机地址")
    args = parser.parse_args()

    # 显示版本信息并退出
    if args.version:
        print(f"Deepin MCP 任务规划系统 v{VERSION}")
        return

    # 加载环境变量
    load_dotenv()
    
    # 在启动时自动启动API服务器（除非明确要求CLI模式或列出服务器或版本信息）
    if not args.cli and not args.list_servers and not args.version:
        args.api_server = True

    # 如果启动API服务器
    if args.api_server:
        # 加载环境变量中的端口和主机配置（如果存在）
        env_port = os.getenv('MCP_API_PORT')
        env_host = os.getenv('MCP_API_HOST')
        
        print(f"\n====== Deepin MCP OpenAI兼容API服务器 ======")
        print(f"版本: {VERSION}")
        print(f"正在启动服务器...")
        
        # 优先使用命令行参数指定的端口
        if args.port > 0:
            port = args.port
            print(f"使用命令行指定的端口: {port}")
        # 其次使用环境变量中的端口
        elif env_port and env_port.isdigit() and int(env_port) > 0:
            port = int(env_port)
            print(f"使用.env文件中的端口配置: {port}")
        # 最后才使用随机端口
        else:
            port = 0
            print("未指定端口，将自动选择随机端口")
        
        # 优先使用命令行参数指定的主机
        if args.host != "127.0.0.1":
            host = args.host
            print(f"使用命令行指定的主机地址: {host}")
        elif env_host:
            host = env_host
            print(f"使用.env文件中的主机配置: {host}")
        else:
            host = "127.0.0.1"
            print(f"使用默认主机地址: {host}")
        
        # 创建一个socket来找到可用端口（如果指定了随机端口）
        if port == 0:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('', 0))
            port = sock.getsockname()[1]
            sock.close()
        
        # 将端口保存到环境变量中
        os.environ['MCP_API_PORT'] = str(port)
        os.environ['MCP_API_HOST'] = host
        
        # 将端口写入.env文件
        try:
            env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            if os.path.exists(env_file):
                # 读取现有内容
                with open(env_file, 'r') as f:
                    env_content = f.readlines()
                
                # 更新或添加端口设置
                found_port = False
                found_host = False
                for i, line in enumerate(env_content):
                    if line.startswith('MCP_API_PORT='):
                        env_content[i] = f'MCP_API_PORT={port}\n'
                        found_port = True
                    elif line.startswith('MCP_API_HOST='):
                        env_content[i] = f'MCP_API_HOST={host}\n'
                        found_host = True
                
                if not found_port:
                    env_content.append(f'MCP_API_PORT={port}\n')
                if not found_host:
                    env_content.append(f'MCP_API_HOST={host}\n')
                
                # 写回文件
                with open(env_file, 'w') as f:
                    f.writelines(env_content)
            else:
                # 创建新文件
                with open(env_file, 'a') as f:
                    f.write(f'MCP_API_PORT={port}\n')
                    f.write(f'MCP_API_HOST={host}\n')
            
            print(f"API服务器配置已保存到 {env_file}")
        except Exception as e:
            print(f"无法写入配置到.env文件: {str(e)}")
        
        print(f"已选择端口: {port}")
        print(f"服务器地址: http://{host}:{port}")
        print(f"OpenAI客户端连接URL: http://{host}:{port}/v1")
        print(f"环境变量: MCP_API_PORT={port}")
        print(f"=======================================")
        
        # 启动API服务器
        config = uvicorn.Config(
            app="main:app", 
            host=host, 
            port=port, 
            log_level="info",
            log_config=None  # 禁用默认日志配置，避免formatter错误
        )
        server = uvicorn.Server(config)
        await server.serve()
        return

    # 初始化任务规划器
    try:
        planner = TaskPlanner()
        
        # 如果请求列出所有服务器
        if args.list_servers:
            servers = planner.list_available_servers()
            if servers:
                print("\n可用的服务器:")
                for i, server in enumerate(servers, 1):
                    print(f"{i}. {server} ({planner.available_servers[server]})")
                print(f"\n默认服务器: {Path(planner.server_path).stem}")
            else:
                print("\n未找到可用的服务器")
            return
        
        # 连接服务器，优先使用命令行参数指定的服务器
        if args.server:
            if not planner.set_server(args.server):
                print(f"\n指定的服务器 '{args.server}' 不存在")
                
                # 列出可用的服务器
                servers = planner.list_available_servers()
                if servers:
                    print("\n可用的服务器:")
                    for i, server in enumerate(servers, 1):
                        print(f"{i}. {server}")
                    
                    # 提示用户选择一个服务器
                    server_choice = input("\n请选择要使用的服务器 (输入编号): ").strip()
                    try:
                        choice_index = int(server_choice) - 1
                        if 0 <= choice_index < len(servers):
                            selected_server = servers[choice_index]
                            planner.set_server(selected_server)
                            print(f"\n已选择服务器: {selected_server}")
                        else:
                            print("\n无效的选择，使用默认服务器")
                    except ValueError:
                        print("\n无效的输入，使用默认服务器")
                else:
                    print("\n未找到可用的服务器，程序退出")
                    return
            
        
        # 列出可用的服务器
        servers = planner.list_available_servers()
        if len(servers) > 1:
            print(f"\n可用的服务器 ({len(servers)}):")
            for i, server in enumerate(servers, 1):
                is_current = " (当前使用)" if planner.available_servers[server] == planner.server_path else ""
                print(f"{i}. {server}{is_current}")
            
            server_choice = input("\n要切换服务器吗? (输入编号或直接回车继续): ").strip()
            if server_choice:
                try:
                    choice_index = int(server_choice) - 1
                    if 0 <= choice_index < len(servers):
                        selected_server = servers[choice_index]
                        planner.set_server(selected_server)
                        print(f"\n已切换到服务器: {selected_server}")
                    else:
                        print("\n无效的选择，保持当前服务器")
                except ValueError:
                    print("\n无效的输入，保持当前服务器")
        
        connected = await planner.connect_to_server()
        if not connected:
            print("\n无法连接到服务器，程序退出")
            return
        
        # 主循环
        while True:
            try:
                user_request = input("\n请输入您的请求 (输入'quit'退出, 'switch'切换服务器): ").strip()
                
                if user_request.lower() == 'quit':
                    break
                
                if user_request.lower() == 'switch':
                    servers = planner.list_available_servers()
                    if servers:
                        print("\n可用的服务器:")
                        for i, server in enumerate(servers, 1):
                            is_current = " (当前使用)" if planner.available_servers[server] == planner.server_path else ""
                            print(f"{i}. {server}{is_current}")
                        
                        server_choice = input("\n请选择要使用的服务器 (输入编号): ").strip()
                        try:
                            choice_index = int(server_choice) - 1
                            if 0 <= choice_index < len(servers):
                                selected_server = servers[choice_index]
                                
                                # 清理当前连接
                                await planner.cleanup()
                                
                                # 设置新服务器
                                planner.set_server(selected_server)
                                print(f"\n已切换到服务器: {selected_server}")
                                
                                # 连接到新服务器
                                connected = await planner.connect_to_server()
                                if not connected:
                                    print("\n无法连接到新服务器，请尝试其他服务器")
                            else:
                                print("\n无效的选择，保持当前服务器")
                        except ValueError:
                            print("\n无效的输入，保持当前服务器")
                    else:
                        print("\n未找到可用的服务器")
                    continue
                    
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
                print("\n程序已被用户中断")
                break
            except Exception as e:
                print(f"\n出现错误: {str(e)}")
                
    except KeyboardInterrupt:
        print("\n程序已被用户中断")
    except Exception as e:
        print(f"\n初始化过程中出现错误: {str(e)}")
    finally:
        # 清理资源
        if 'planner' in locals():
            await planner.cleanup()
        print("\n程序已退出")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已被用户中断")
    except Exception as e:
        print(f"\n运行时发生错误: {str(e)}") 