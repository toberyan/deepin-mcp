import os
import shutil
import subprocess
from typing import Any
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("FileServer")

@mcp.tool()
async def open_file(file_path: str) -> str:
    """
    使用系统默认程序打开文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 操作结果信息
    """
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return f"文件不存在: {file_path}"
            
        # 获取用户环境变量
        user_env = os.environ.copy()
        
        # 确保 DISPLAY 环境变量存在
        if 'DISPLAY' not in user_env:
            user_env['DISPLAY'] = ':0'
            
        # 使用用户环境启动 xdg-open
        process = subprocess.Popen(
            ['xdg-open', file_path],
            env=user_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 等待进程完成
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            return f"文件已成功打开: {file_path}"
        else:
            error_msg = stderr.decode('utf-8') if stderr else "未知错误"
            return f"打开文件失败: {error_msg}"
            
    except Exception as e:
        return f"打开文件失败: {str(e)}"

@mcp.tool()
async def copy_file(source_path: str, destination_path: str) -> str:
    """
    复制文件到指定位置
    
    Args:
        source_path: 源文件路径
        destination_path: 目标文件路径
        
    Returns:
        str: 操作结果信息
    """
    try:
        shutil.copy2(source_path, destination_path)
        return f"文件已成功复制到: {destination_path}"
    except Exception as e:
        return f"复制文件失败: {str(e)}"

@mcp.tool()
async def move_file(source_path: str, destination_path: str) -> str:
    """
    移动文件到指定位置（剪切粘贴）
    
    Args:
        source_path: 源文件路径
        destination_path: 目标文件路径
        
    Returns:
        str: 操作结果信息
    """
    try:
        shutil.move(source_path, destination_path)
        return f"文件已成功移动到: {destination_path}"
    except Exception as e:
        return f"移动文件失败: {str(e)}"

@mcp.tool()
async def rename_file(old_path: str, new_name: str) -> str:
    """
    重命名文件
    
    Args:
        old_path: 原文件路径
        new_name: 新文件名
        
    Returns:
        str: 操作结果信息
    """
    try:
        old_file = Path(old_path)
        new_path = old_file.parent / new_name
        old_file.rename(new_path)
        return f"文件已成功重命名为: {new_name}"
    except Exception as e:
        return f"重命名文件失败: {str(e)}"

@mcp.tool()
async def delete_file(file_path: str) -> str:
    """
    删除文件
    
    Args:
        file_path: 要删除的文件路径
        
    Returns:
        str: 操作结果信息
    """
    try:
        os.remove(file_path)
        return f"文件已成功删除: {file_path}"
    except Exception as e:
        return f"删除文件失败: {str(e)}"

@mcp.tool()
async def create_file(file_path: str, content: str = "") -> str:
    """
    创建新文件
    
    Args:
        file_path: 新文件路径
        content: 文件初始内容（可选）
        
    Returns:
        str: 操作结果信息
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"文件已成功创建: {file_path}"
    except Exception as e:
        return f"创建文件失败: {str(e)}"

@mcp.tool()
async def batch_rename(folder_path: str, new_name: str) -> str:
    """
    批量重命名文件夹下的所有文件
    
    Args:
        folder_path: 文件夹路径
        new_name: 新文件名模板（不包含扩展名）
        
    Returns:
        str: 操作结果信息
    """
    try:
        # 检查文件夹是否存在
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            return f"文件夹不存在或不是有效的文件夹: {folder_path}"
            
        # 获取文件夹中的所有文件
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        
        if not files:
            return f"文件夹为空: {folder_path}"
            
        renamed_count = 0
        errors = []
        
        for index, old_file in enumerate(files, 1):
            try:
                # 获取文件扩展名
                _, ext = os.path.splitext(old_file)
                
                # 构建新文件名
                if len(files) == 1:
                    # 如果只有一个文件，直接使用新名称
                    new_file = f"{new_name}{ext}"
                else:
                    # 如果有多个文件，添加数字后缀
                    new_file = f"{new_name}_{index}{ext}"
                
                # 构建完整的文件路径
                old_path = os.path.join(folder_path, old_file)
                new_path = os.path.join(folder_path, new_file)
                
                # 重命名文件
                os.rename(old_path, new_path)
                renamed_count += 1
                
            except Exception as e:
                errors.append(f"重命名文件 {old_file} 失败: {str(e)}")
        
        # 构建返回消息
        if errors:
            return f"批量重命名完成，成功重命名 {renamed_count} 个文件，失败 {len(errors)} 个文件。\n错误详情：\n" + "\n".join(errors)
        else:
            return f"批量重命名完成，成功重命名 {renamed_count} 个文件"
            
    except Exception as e:
        return f"批量重命名失败: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport='stdio') 