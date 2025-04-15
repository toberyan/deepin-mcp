import json
import urllib.parse
import asyncio
import requests
from typing import Dict, List, Any, Optional
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("BaiduSearchServer")

async def local_baidu_search(query: str, result_count: int = 10) -> List[Dict[str, str]]:
    """
    执行百度搜索查询并返回结果
    
    Args:
        query: 搜索查询字符串
        result_count: 返回结果数量
        
    Returns:
        List[Dict[str, str]]: 搜索结果列表，每个结果包含标题、链接和内容
    """
    try:
        # 设置请求超时
        timeout = 10
        
        # 构建百度搜索URL
        search_url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}&tn=json&rn={result_count}"
        
        # 发送请求
        response = requests.get(
            search_url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"}
        )
        
        if response.status_code == 200:
            json_res = response.json()
            data = json_res.get('feed', {}).get('entry', [])
        else:
            print(f"百度搜索请求失败，状态码: {response.status_code}")
            data = []
            
    except Exception as e:
        print(f"百度搜索过程中出错: {str(e)}")
        data = []
    
    # 处理搜索结果
    search_results = []
    for result in data:
        title = result.get('title', '')
        link = result.get('url', '')
        content = result.get('abs', '')
        if link:  # 过滤没有链接的结果
            search_results.append({'title': title, 'link': link, 'content': content})
    
    return search_results

async def process_website_content(url: str, query: str) -> Dict[str, Any]:
    """
    处理网站内容，提取与查询相关的信息
    
    Args:
        url: 网站URL
        query: 搜索查询
        
    Returns:
        Dict[str, Any]: 包含URL和相关内容的字典
    """
    try:
        # 设置请求超时
        timeout = 15
        
        # 发送请求获取网页内容
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"}
        )
        
        if response.status_code == 200:
            # 简单提取网页内容，实际应用中可能需要更复杂的HTML解析
            content = response.text
            
            # 截取部分内容，避免返回过大的数据
            max_content_length = 10000
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            
            return {
                "url": url,
                "content": content
            }
        else:
            return {
                "url": url,
                "content": f"无法获取网页内容，状态码: {response.status_code}"
            }
            
    except Exception as e:
        return {
            "url": url,
            "content": f"处理网站内容时出错: {str(e)}"
        }

def get_website_from_query(query: str) -> Dict[str, Any]:
    """
    从查询中提取网站URL
    
    Args:
        query: 搜索查询
        
    Returns:
        Dict[str, Any]: 包含查询和URL信息的字典
    """
    # 使用正则表达式匹配URL
    url_regex = r'https?://[^\s]+'
    import re
    
    # 查找所有URL
    urls = re.findall(url_regex, query)
    
    if not urls:
        return {
            "queryWithoutUrls": query,
            "url": "",
            "hasUrl": False
        }
    
    # 获取第一个URL
    url = urls[0]
    
    # 从查询中移除URL
    query_without_urls = query.replace(url, "").strip()
    
    return {
        "queryWithoutUrls": query_without_urls,
        "url": url,
        "hasUrl": True
    }

def format_search_results(data: Dict[str, Any], pretty_format: bool = False) -> str:
    """
    格式化搜索结果，可选择JSON或人类可读格式
    
    Args:
        data: 要格式化的搜索数据
        pretty_format: 是否使用人类可读格式，默认为False（使用JSON格式）
        
    Returns:
        str: 格式化后的结果字符串
    """
    if not pretty_format:
        # 返回JSON格式
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    # 返回人类可读格式
    result_str = ""
    
    if data.get("type") == "error":
        result_str = f"搜索错误: {data.get('error', '未知错误')}"
    
    elif data.get("type") == "specific_website":
        result_str = f"网站: {data.get('website')}\n"
        result_str += f"查询: {data.get('query')}\n"
        result_str += f"内容摘要:\n{data.get('content', '无内容')[:500]}...\n"
    
    elif data.get("type") == "search":
        result_str = f"查询: {data.get('query')}\n\n"
        
        if "error" in data:
            result_str += f"错误: {data.get('error')}\n"
        else:
            results = data.get("results", [])
            if not results:
                result_str += "未找到相关结果\n"
            else:
                result_str += f"找到 {len(results)} 个结果:\n\n"
                for i, result in enumerate(results, 1):
                    result_str += f"{i}. {result.get('title', '无标题')}\n"
                    result_str += f"   链接: {result.get('url', '无链接')}\n"
                    snippet = result.get('snippet', '无描述')
                    if len(snippet) > 100:
                        snippet = snippet[:100] + "..."
                    result_str += f"   描述: {snippet}\n\n"
    
    return result_str

@mcp.tool()
async def web_search(query: str, result_count: int = 5, pretty_print: bool = True) -> str:
    """
    执行网络搜索，返回结果
    
    Args:
        query: 搜索查询
        result_count: 返回结果数量（默认为5）
        pretty_print: 是否使用友好格式打印结果（默认为True，使用人类可读格式）
        
    Returns:
        str: 格式化的搜索结果
    """
    try:
        # 检查查询是否包含特定网站URL
        website_info = get_website_from_query(query)
        
        if website_info["hasUrl"]:
            # 如果查询包含URL，直接处理该网站
            url = website_info["url"]
            search_query = website_info["queryWithoutUrls"]
            
            # 处理特定网站
            result = await process_website_content(url, search_query)
            
            # 构建结果数据
            result_data = {
                "type": "specific_website",
                "query": search_query,
                "website": url,
                "content": result["content"][:1000]  # 限制内容长度
            }
            
            # 格式化并返回结果
            return format_search_results(result_data, pretty_print)
            
        else:
            # 执行普通百度搜索
            search_results = await local_baidu_search(query, result_count)
            
            if not search_results:
                result_data = {
                    "type": "search",
                    "query": query,
                    "error": "未找到相关搜索结果"
                }
            else:
                # 格式化搜索结果
                formatted_results = []
                for result in search_results:
                    formatted_results.append({
                        "title": result["title"],
                        "url": result["link"],
                        "snippet": result["content"]
                    })
                
                result_data = {
                    "type": "search",
                    "query": query,
                    "results": formatted_results
                }
            
            # 格式化并返回结果
            return format_search_results(result_data, pretty_print)
            
    except Exception as e:
        result_data = {
            "type": "error",
            "query": query,
            "error": f"执行搜索时出错: {str(e)}"
        }
        return format_search_results(result_data, pretty_print)

@mcp.tool()
async def get_webpage_content(url: str, pretty_print: bool = True) -> str:
    """
    获取指定网页的内容
    
    Args:
        url: 网页URL
        pretty_print: 是否使用友好格式打印结果（默认为True，使用人类可读格式）
        
    Returns:
        str: 网页内容
    """
    try:
        # 获取网页内容
        result = await process_website_content(url, "")
        
        # 构建结果数据
        result_data = {
            "url": url,
            "content": result["content"][:5000]  # 限制内容长度
        }
        
        # 如果需要友好打印
        if pretty_print:
            return f"网页: {url}\n\n内容摘要:\n{result_data['content'][:1000]}...\n"
        else:
            # 返回JSON格式
            return json.dumps(result_data, ensure_ascii=False, indent=2)
        
    except Exception as e:
        result_data = {
            "url": url,
            "error": f"获取网页内容时出错: {str(e)}"
        }
        
        if pretty_print:
            return f"获取网页内容时出错: {str(e)}"
        else:
            return json.dumps(result_data, ensure_ascii=False, indent=2)

# 移除MCP装饰器，使其成为内部函数
async def print_search_results(json_data: str) -> str:
    """
    格式化并打印搜索结果，将JSON数据转换为可读性更好的格式
    
    Args:
        json_data: JSON格式的搜索结果数据
        
    Returns:
        str: 格式化后的可读性结果
    """
    try:
        # 将JSON字符串解析为Python对象
        data = json.loads(json_data)
        
        # 使用格式化函数处理数据
        return format_search_results(data, True)
        
    except json.JSONDecodeError:
        return f"错误: 无法解析JSON数据: {json_data[:100]}..."
    except Exception as e:
        return f"格式化搜索结果时出错: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport='stdio') 