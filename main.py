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
            # 加载所有启用的服务器接口
            try:
                connected = await planner.connect_to_server()
                if not connected:
                    print("\n无法连接到任何启用的服务器，程序可能无法正常运行")
            except KeyboardInterrupt:
                print("\n检测到Ctrl+C，初始化过程已中断")
                # 重新引发KeyboardInterrupt，将异常传递给调用者
                raise
    except KeyboardInterrupt:
        print("\n检测到Ctrl+C，初始化过程已中断")
        raise  # 重新引发异常，让FastAPI框架处理
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

# 添加一个新的共用函数来执行任务
async def execute_tasks_and_summarize(user_request: str) -> str:
    """执行任务并生成总结的共用函数"""
    global planner
    
    # 1. 规划任务
    print("\n正在分析请求...")
    tasks = await planner.plan_tasks(user_request)
    
    if not tasks:
        return "未能从请求中提取出具体任务，请尝试更明确的描述"
    
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
    
    return summary

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
            # 使用共用函数执行任务并生成总结
            summary = await execute_tasks_and_summarize(user_request)
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

async def ensure_tasks_cancelled(tasks=None):
    """确保所有任务被取消"""
    try:
        if tasks is None:
            # 获取所有任务
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        
        for task in tasks:
            if not (task.done() or task.cancelled()):
                task.cancel()
                
        # 允许任务有机会处理取消
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        print(f"取消任务时出错: {str(e)}")
    except KeyboardInterrupt:
        pass  # 忽略取消过程中的键盘中断

async def stream_completion(user_request: str, model: str):
    global planner
    
    # 创建一个队列用于存储输出
    queue = asyncio.Queue()
    
    # 创建SSE响应帮助函数
    def create_sse_message(content=None, finish_reason=None):
        data = {
            'id': f'chatcmpl-{uuid.uuid4()}', 
            'object': 'chat.completion.chunk', 
            'created': int(asyncio.get_event_loop().time()), 
            'model': model, 
            'choices': [{
                'index': 0, 
                'delta': {} if content is None else {'content': content},
                'finish_reason': finish_reason
            }]
        }
        return f"data: {json.dumps(data)}\n\n"
    
    # 发送结束消息
    def send_end_message():
        return [
            create_sse_message(finish_reason='stop'),
            "data: [DONE]\n\n"
        ]
    
    # 注册一个回调来接收控制台输出
    def output_callback(text):
        queue.put_nowait(text)
    
    # 订阅输出
    sub_id = output_capture.subscribe(output_callback)
    
    try:
        # 发送SSE事件头部
        yield create_sse_message({'role': 'assistant'})
        
        # 执行任务的异步函数
        async def execute():
            try:
                # 使用共用函数执行任务
                await execute_tasks_and_summarize(user_request)
            except KeyboardInterrupt:
                queue.put_nowait("\n检测到Ctrl+C，任务执行被中断")
            except Exception as e:
                traceback_str = traceback.format_exc()
                queue.put_nowait(f"\n处理请求时出现错误: {str(e)}\n{traceback_str}")
        
        # 启动执行任务
        execute_task = asyncio.create_task(execute())
        
        # 流式返回捕获的输出
        while True:
            try:
                output = await asyncio.wait_for(queue.get(), timeout=1.0)
                if output:
                    # 将输出分成小块发送，以保持流畅的流式响应
                    for chunk in output.split('\n'):
                        if chunk:
                            yield create_sse_message(chunk + '\n')
                            await asyncio.sleep(0.01)  # 短暂延迟以防止过快发送
            except asyncio.TimeoutError:
                # 检查执行任务是否完成
                if queue.empty() and (execute_task.done() or execute_task.cancelled()):
                    # 发送完成信号
                    for message in send_end_message():
                        yield message
                    break
            except KeyboardInterrupt:
                # 处理流式传输过程中的Ctrl+C
                execute_task.cancel()
                yield create_sse_message('\n检测到Ctrl+C，流式传输已中断\n')
                for message in send_end_message():
                    yield message
                break
    except KeyboardInterrupt:
        # 处理整体流程中的Ctrl+C
        yield create_sse_message('\n检测到Ctrl+C，流式传输已中断\n')
        for message in send_end_message():
            yield message
    finally:
        # 取消订阅
        output_capture.unsubscribe(sub_id)
        # 确保任务被取消
        if 'execute_task' in locals():
            await ensure_tasks_cancelled([execute_task])

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
        try:
            # 直接执行指定查询
            print(f"\n执行查询: {query}")
            try:
                # 使用共用函数执行任务
                await execute_tasks_and_summarize(query)
            except Exception as e:
                print(f"\n执行过程中出现错误: {str(e)}")
                traceback_str = traceback.format_exc()
                print(traceback_str)
        except KeyboardInterrupt:
            print("\n检测到Ctrl+C，正在退出程序...")
            print("\n感谢使用，再见！")
            return
    else:
        # 进入交互式模式
        await interactive_mode(planner)

def update_env_file(key, value):
    """更新.env文件中的设置"""
    try:
        # 读取现有.env文件内容
        env_content = []
        if os.path.exists(".env"):
            with open(".env", "r") as f:
                env_content = f.readlines()
        
        # 检查是否已存在配置项
        setting_exists = False
        for i, line in enumerate(env_content):
            if line.startswith(f"{key}="):
                env_content[i] = f"{key}={value}\n"
                setting_exists = True
                break
        
        # 如果不存在，则添加
        if not setting_exists:
            env_content.append(f"{key}={value}\n")
        
        # 写回文件
        with open(".env", "w") as f:
            f.writelines(env_content)
            
        return True
    except Exception as e:
        print(f"保存配置到.env文件时出错: {str(e)}")
        return False

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
    port_updated = update_env_file("MCP_API_PORT", port)
    host_updated = update_env_file("MCP_API_HOST", host)
    
    if port_updated and host_updated:
        print(f"API服务器配置已保存到.env文件")
    else:
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

async def handle_server_management(args):
    """处理服务器管理相关命令"""
    if args.list_servers or args.enable_server or args.disable_server or args.set_default:
        # 创建TaskPlanner实例用于服务器管理
        temp_planner = TaskPlanner()
        
        if args.list_servers:
            await list_servers(temp_planner)
            return True
            
        if args.enable_server:
            temp_planner.enable_server(args.enable_server)
            print(f"\n已启用服务器: {args.enable_server}")
            return True
            
        if args.disable_server:
            temp_planner.disable_server(args.disable_server)
            print(f"\n已禁用服务器: {args.disable_server}")
            return True
            
        if args.set_default:
            temp_planner.set_default_server(args.set_default)
            print(f"\n已将 {args.set_default} 设置为默认服务器")
            return True
    
    return False

async def main_async():
    """异步主函数"""
    args = parse_arguments()
    global planner
    
    try:
        # 初始化环境变量
        load_dotenv()
        
        # 处理服务器管理命令
        if await handle_server_management(args):
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
            # 连接所有启用的服务器
            print("正在加载所有启用的服务器接口...")
            connected = await planner.connect_to_server()
            if not connected:
                print("无法连接到任何启用的服务器")
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
        print("\n检测到Ctrl+C，程序即将退出...")
        print("\n感谢使用，再见！")
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
        print("\n正在清理资源...")
    except Exception as e:
        print(f"\n程序运行出错: {str(e)}")
        traceback.print_exc()
    finally:
        # 关闭事件循环前确保所有待处理的任务都已完成
        try:
            # 获取所有任务前首先检查循环是否已关闭
            if not loop.is_closed():
                # 取消所有任务
                loop.run_until_complete(ensure_tasks_cancelled())
                
                # 最后关闭事件循环
                loop.close()
        except Exception as e:
            print(f"关闭事件循环时出错: {str(e)}")
            # 尝试强制关闭循环
            try:
                if not loop.is_closed():
                    loop.close()
            except:
                pass

async def handle_server_action(planner, server_name, action):
    """处理服务器操作"""
    if action == 'enable':
        planner.enable_server(server_name)
        print(f"\n已启用服务器: {server_name}")
    elif action == 'disable':
        planner.disable_server(server_name)
        print(f"\n已禁用服务器: {server_name}")
    elif action == 'default':
        planner.set_default_server(server_name)
        print(f"\n已将 {server_name} 设置为默认服务器")
    else:
        print("\n无效的操作")

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
                    
                    # 使用统一的处理函数
                    action = 'enable' if choice == 'E' else ('disable' if choice == 'D' else 'default')
                    await handle_server_action(planner, selected_server, action)
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
                    action = 'disable' if server_info["enabled"] else 'enable'
                    await handle_server_action(planner, selected_server, action)
                elif sub_choice == '2':
                    if not server_info.get("default", False):
                        await handle_server_action(planner, selected_server, 'default')
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
    print("使用 'quit' 退出，'servers' 管理服务器")
    
    while True:
        try:
            user_request = input("\n请输入您的请求: ").strip()
            
            if user_request.lower() == 'quit':
                print("\n感谢使用，再见！")
                break
                
            if user_request.lower() == 'servers':
                await list_servers(planner)
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
            
            # 2. 执行任务并生成总结
            try:
                # 使用execute_tasks_and_summarize函数的部分功能
                results = await planner.execute_tasks(tasks)
                
                # 生成总结
                print("\n所有任务已执行完毕，正在生成总结...")
                summary = await planner.summarize_results(user_request, tasks, results)
                
                print("\n执行总结:")
                print(summary)
            except Exception as e:
                print(f"\n执行过程中出现错误: {str(e)}")
                traceback_str = traceback.format_exc()
                print(traceback_str)
            
        except KeyboardInterrupt:
            print("\n检测到Ctrl+C，正在退出程序...")
            print("\n感谢使用，再见！")
            return  # 直接返回以退出函数
        except Exception as e:
            print(f"\n执行过程中出现错误: {str(e)}")
            traceback_str = traceback.format_exc()
            print(traceback_str)

if __name__ == "__main__":
    main() 