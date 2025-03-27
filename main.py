#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import argparse
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from client.planning import TaskPlanner

# 版本信息
VERSION = "1.0.0"

async def main():
    """
    主入口函数，初始化并运行任务规划系统
    """
    parser = argparse.ArgumentParser(description="Deepin MCP 任务规划系统")
    parser.add_argument("--server", "-s", type=str, help="指定MCP服务器脚本路径或名称", default=None)
    parser.add_argument("--list-servers", "-l", action="store_true", help="列出所有可用的服务器")
    parser.add_argument("--version", "-v", action="store_true", help="显示版本信息")
    args = parser.parse_args()

    # 显示版本信息并退出
    if args.version:
        print(f"Deepin MCP 任务规划系统 v{VERSION}")
        return

    # 加载环境变量
    load_dotenv()

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