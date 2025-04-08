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
        # 只有当全局planner未初始化时才进行初始化
        if planner is None:
            load_dotenv()
            planner = TaskPlanner()
            # 使用默认服务器路径或启用的服务器
            connected = await planner.connect_to_server()
            if not connected:
                print("\n无法连接到服务器，程序可能无法正常运行")
    except Exception as e:
        print(f"\n初始化过程中出现错误: {str(e)}")
    
    yield
    
    # 关闭时不清理资源，因为主程序会负责清理
    # 避免重复清理导致的问题
    pass

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

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Deepin MCP 任务规划系统')
    parser.add_argument('--port', type=int, help='API服务器端口号')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='API服务器主机地址')
    parser.add_argument('--cli', action='store_true', help='仅使用命令行界面，不启动API服务器')
    parser.add_argument('--query', type=str, help='CLI模式下直接执行的查询')
    parser.add_argument('--list-servers', action='store_true', help='列出所有可用的服务器')
    parser.add_argument('--server', type=str, help='指定要使用的服务器名称')
    parser.add_argument('--enable-server', type=str, help='启用指定的服务器')
    parser.add_argument('--disable-server', type=str, help='禁用指定的服务器')
    parser.add_argument('--set-default', type=str, help='设置默认服务器')
    parser.add_argument('--version', action='version', version=f'Deepin MCP {VERSION}')
    return parser.parse_args()

async def run_cli_mode(query=None):
    """运行CLI模式"""
    global planner
    
    if query:
        # 直接执行指定查询
        print(f"\n执行查询: {query}")
        try:
            # 规划任务
            tasks = await planner.plan_tasks(query)
            
            if not tasks:
                print("\n未能从请求中提取出具体任务，请尝试更明确的描述")
                return
                
            print(f"\n已将请求拆解为 {len(tasks)} 个任务:")
            for i, task in enumerate(tasks, 1):
                print(f"{i}. {task}")
                
            # 执行任务
            results = await planner.execute_tasks(tasks)
            
            # 生成总结
            print("\n所有任务已执行完毕，正在生成总结...")
            summary = await planner.summarize_results(query, tasks, results)
            
            print("\n执行总结:")
            print(summary)
        except Exception as e:
            print(f"\n执行过程中出现错误: {str(e)}")
            traceback_str = traceback.format_exc()
            print(traceback_str)
    else:
        # 进入交互式模式
        await interactive_mode(planner)

async def start_api_server(port: Optional[int], host: str):
    """启动OpenAI兼容的API服务器"""
    # 查找可用端口
    if port is None:
        port = int(os.getenv("MCP_API_PORT", "0"))
        if port == 0:
            # 查找随机可用端口
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                port = s.getsockname()[1]
    
    if not host:
        host = os.getenv("MCP_API_HOST", "127.0.0.1")
    
    print(f"\n====== Deepin MCP OpenAI兼容API服务器 ======")
    print(f"版本: {VERSION}")
    print(f"正在启动服务器...")
    print(f"已选择端口: {port}")
    print(f"服务器地址: http://{host}:{port}")
    print(f"OpenAI客户端连接URL: http://{host}:{port}/v1")
    print(f"环境变量: MCP_API_PORT={port}")
    print(f"======================================")
    
    # 更新环境变量
    os.environ["MCP_API_PORT"] = str(port)
    os.environ["MCP_API_HOST"] = host
    
    # 将端口和主机保存到.env文件
    try:
        # 读取现有.env文件内容
        env_content = []
        if os.path.exists(".env"):
            with open(".env", "r") as f:
                env_content = f.readlines()
        
        # 检查是否已存在配置项
        port_exists = False
        host_exists = False
        for i, line in enumerate(env_content):
            if line.startswith("MCP_API_PORT="):
                env_content[i] = f"MCP_API_PORT={port}\n"
                port_exists = True
            elif line.startswith("MCP_API_HOST="):
                env_content[i] = f"MCP_API_HOST={host}\n"
                host_exists = True
        
        # 如果不存在，则添加
        if not port_exists:
            env_content.append(f"MCP_API_PORT={port}\n")
        if not host_exists:
            env_content.append(f"MCP_API_HOST={host}\n")
        
        # 写回文件
        with open(".env", "w") as f:
            f.writelines(env_content)
            
        print(f"API服务器配置已保存到.env文件")
    except Exception as e:
        print(f"保存配置到.env文件时出错: {str(e)}")
        print(f"这不会影响程序运行，但下次启动时可能使用不同的端口")
    
    try:
        # 启动API服务器
        config = uvicorn.Config(
            app=app, 
            host=host, 
            port=port, 
            log_level="info",
            log_config=None,  # 禁用默认日志配置，避免formatter错误
            timeout_keep_alive=60  # 保持连接的超时时间（秒）
        )
        server = uvicorn.Server(config)
        
        # 注册自定义的信号处理程序
        import signal
        
        # 保存原来的信号处理程序
        original_handler = signal.getsignal(signal.SIGINT)
        
        def graceful_shutdown(sig, frame):
            print("\n正在优雅关闭服务器...")
            # 服务器将在下一次事件循环迭代时停止
            # 不在信号处理程序中执行任何异步操作
            
            # 恢复原来的信号处理程序，这样连续两次 Ctrl+C 将立即终止
            signal.signal(signal.SIGINT, original_handler)
        
        # 替换SIGINT信号处理程序
        signal.signal(signal.SIGINT, graceful_shutdown)
        
        # 使用任务包装器启动服务器
        await server.serve()
    except Exception as e:
        print(f"API服务器运行出错: {str(e)}")
    except KeyboardInterrupt:
        print("\n检测到键盘中断，正在关闭服务器...")
    finally:
        print("API服务器已停止")

async def main_async():
    """异步主函数"""
    args = parse_arguments()
    global planner
    
    try:
        # 初始化环境变量
        load_dotenv()
        
        # 处理服务器管理命令
        if args.list_servers or args.enable_server or args.disable_server or args.set_default:
            # 创建TaskPlanner实例用于服务器管理
            temp_planner = TaskPlanner()
            
            if args.list_servers:
                await list_servers(temp_planner)
                return
                
            if args.enable_server:
                temp_planner.enable_server(args.enable_server)
                print(f"\n已启用服务器: {args.enable_server}")
                return
                
            if args.disable_server:
                temp_planner.disable_server(args.disable_server)
                print(f"\n已禁用服务器: {args.disable_server}")
                return
                
            if args.set_default:
                temp_planner.set_default_server(args.set_default)
                print(f"\n已将 {args.set_default} 设置为默认服务器")
                return
        
        # 创建TaskPlanner实例
        planner = TaskPlanner()
        
        # 连接服务器
        if args.server:
            # 连接指定的服务器
            connected = await planner.connect_to_server(args.server)
            if not connected:
                print(f"无法连接到指定的服务器: {args.server}")
                return
        else:
            # 连接默认服务器
            connected = await planner.connect_to_server()
            if not connected:
                print("无法连接到默认服务器")
                return
        
        # 使用CLI模式
        if args.cli:
            await run_cli_mode(args.query)
            return
        
        # API模式
        await start_api_server(args.port, args.host)
    except Exception as e:
        print(f"\n初始化过程中出现错误: {str(e)}")
        traceback_str = traceback.format_exc()
        print(traceback_str)
    except KeyboardInterrupt:
        print("\n检测到键盘中断，程序即将退出...")
    finally:
        # 在异步环境中清理资源
        if planner:
            try:
                await planner.cleanup()
            except Exception as e:
                print(f"清理资源时出错: {str(e)}")
            except asyncio.CancelledError:
                print("清理过程被取消")
            print("\n程序已退出")

def main():
    """主函数入口点"""
    # 设置事件循环
    try:
        # 检查是否已有事件循环
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            # 如果循环已关闭，创建新的循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        # 如果没有事件循环，创建新的循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        # 运行异步主函数
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n程序运行出错: {str(e)}")
        traceback.print_exc()
    finally:
        # 关闭事件循环前确保所有待处理的任务都已完成
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
            
        # 允许任务有机会处理取消
        if pending:
            try:
                # 等待所有任务处理它们的取消
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                print(f"关闭待处理任务时出错: {str(e)}")
        
        # 最后关闭事件循环
        loop.close()

async def manage_servers_interactive(planner: TaskPlanner):
    """服务器管理交互界面"""
    while True:
        servers = planner.get_server_status()
        print("\n=== 服务器管理 ===")
        print("可用的服务器:")
        for i, (server_name, server_info) in enumerate(servers.items(), 1):
            enabled_status = "✓" if server_info["enabled"] else "✗"
            default_status = "默认" if server_info.get("default", False) else ""
            print(f"{i}. [{enabled_status}] {server_name} - {server_info['description']} {default_status}")
        
        print("\n操作选项:")
        print("E - 启用服务器")
        print("D - 禁用服务器")
        print("S - 设置默认服务器")
        print("R - 刷新服务器列表")
        print("Q - 返回主菜单")
        
        choice = input("\n请选择操作 (输入编号或选项): ").strip().upper()
        
        if choice == 'Q':
            break
        
        if choice == 'R':
            # 刷新服务器列表
            planner.update_server_paths()
            print("\n已刷新服务器列表")
            continue
        
        if choice == 'E' or choice == 'D' or choice == 'S':
            server_choice = input("请选择服务器 (输入编号): ").strip()
            try:
                choice_index = int(server_choice) - 1
                server_names = list(servers.keys())
                if 0 <= choice_index < len(server_names):
                    selected_server = server_names[choice_index]
                    
                    if choice == 'E':
                        # 启用服务器
                        planner.enable_server(selected_server)
                        print(f"\n已启用服务器: {selected_server}")
                    elif choice == 'D':
                        # 禁用服务器
                        planner.disable_server(selected_server)
                        print(f"\n已禁用服务器: {selected_server}")
                    elif choice == 'S':
                        # 设置默认服务器
                        planner.set_default_server(selected_server)
                        print(f"\n已将 {selected_server} 设置为默认服务器")
                else:
                    print("\n无效的选择")
            except ValueError:
                print("\n无效的输入")
            continue
        
        try:
            choice_index = int(choice) - 1
            server_names = list(servers.keys())
            if 0 <= choice_index < len(server_names):
                selected_server = server_names[choice_index]
                
                # 显示服务器详情
                server_info = servers[selected_server]
                print(f"\n=== {selected_server} 服务器详情 ===")
                print(f"描述: {server_info['description']}")
                print(f"路径: {server_info['path']}")
                print(f"状态: {'启用' if server_info['enabled'] else '禁用'}")
                print(f"默认: {'是' if server_info.get('default', False) else '否'}")
                
                # 操作选项
                print("\n操作选项:")
                print("1 - " + ("禁用" if server_info["enabled"] else "启用"))
                print("2 - " + ("取消默认" if server_info.get("default", False) else "设为默认"))
                print("Q - 返回")
                
                sub_choice = input("\n请选择操作: ").strip()
                
                if sub_choice == '1':
                    if server_info["enabled"]:
                        planner.disable_server(selected_server)
                        print(f"\n已禁用服务器: {selected_server}")
                    else:
                        planner.enable_server(selected_server)
                        print(f"\n已启用服务器: {selected_server}")
                elif sub_choice == '2':
                    if not server_info.get("default", False):
                        planner.set_default_server(selected_server)
                        print(f"\n已将 {selected_server} 设置为默认服务器")
            else:
                print("\n无效的选择")
        except ValueError:
            print("\n无效的输入")

async def list_servers(planner: TaskPlanner):
    """列出所有可用的服务器"""
    server_status = planner.get_server_status()
    if not server_status:
        print("\n未找到任何可用的服务器")
        return
        
    print("\n可用的服务器列表:")
    for i, (server_name, server_info) in enumerate(server_status.items(), 1):
        enabled_status = "✓" if server_info.get("enabled", True) else "✗"
        default_status = "默认" if server_name == planner.server_config["config"]["default_server"] else ""
        print(f"{i}. [{enabled_status}] {server_name} - {server_info['description']} {default_status}")
        print(f"   路径: {server_info['path']}")
        
    print(f"\n默认服务器: {planner.server_config['config']['default_server']}")
    print(f"服务器配置文件: {planner.config_file}")

async def interactive_mode(planner: TaskPlanner):
    """交互式命令行模式"""
    print("\n欢迎使用Deepin MCP 任务规划系统")
    print("使用 'quit' 退出，'servers' 管理服务器，'switch' 切换服务器")
    
    while True:
        try:
            user_request = input("\n请输入您的请求: ").strip()
            
            if user_request.lower() == 'quit':
                print("\n感谢使用，再见！")
                break
                
            if user_request.lower() == 'servers':
                await list_servers(planner)
                continue
                
            if user_request.lower() == 'switch':
                await switch_server_interactive(planner)
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
            print("\n操作已取消")
        except Exception as e:
            print(f"\n执行过程中出现错误: {str(e)}")
            traceback_str = traceback.format_exc()
            print(traceback_str)

async def switch_server_interactive(planner: TaskPlanner):
    """交互式切换服务器"""
    server_status = planner.get_server_status()
    enabled_servers = {name: info for name, info in server_status.items() if info.get("enabled", True)}
    
    if not enabled_servers:
        print("\n未找到任何启用的服务器")
        return
        
    print("\n可选的服务器:")
    server_names = list(enabled_servers.keys())
    for i, server_name in enumerate(server_names, 1):
        server_info = enabled_servers[server_name]
        current_indicator = " (当前使用)" if server_info["path"] == planner.server_path else ""
        default_indicator = " (默认)" if server_name == planner.server_config["config"]["default_server"] else ""
        print(f"{i}. {server_name}{current_indicator}{default_indicator} - {server_info['description']}")
    
    server_choice = input("\n请选择要切换的服务器 (输入编号): ").strip()
    try:
        choice_index = int(server_choice) - 1
        if 0 <= choice_index < len(server_names):
            selected_server = server_names[choice_index]
            
            # 切换服务器
            result = await planner.switch_server(selected_server)
            if result:
                print(f"\n已成功切换到服务器: {selected_server}")
            else:
                print(f"\n切换服务器失败")
        else:
            print("\n无效的选择，未进行切换")
    except ValueError:
        print("\n无效的输入，未进行切换")

if __name__ == "__main__":
    main() 