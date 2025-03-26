import json
import httpx
from typing import Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WeatherServer")

OPENWEATHER_API_BASE = "https://api.openweathermap.org/data/2.5/weather"
API_KEY = "00e7ce455e2967d191355f3c7321c943"
USER_AGENT = "weather-app/1.0"

async def fetch_weather(city: str) -> dict[str, Any] | None:
    """
    从OpenWeatherMap API获取指定城市的天气信息
    
    Args:
        city: 城市名称
    
    Returns:
        dict[str, Any] | None: 天气信息字典或None（如果请求失败）
    """
    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric",
        "lang": "zh_cn"
    }

    headers = {
        "User-Agent": USER_AGENT
    }
    
    print(f"Fetching weather for {city} with params: {params}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENWEATHER_API_BASE, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"HTTP请求错误: {e.response.status_code}")
        except Exception as e:
            print(f"其他错误: {str(e)}")
            return None
        
def format_weather(data: dict[str, Any] | str) -> str:
    """
    格式化天气信息
    
    Args:
        data: 天气数据字典或JSON字符串
        
    Returns:
        str: 格式化后的天气信息字符串
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            return f"无法解析天气数据: {str(e)}"
        except Exception as e:
            return f"处理天气数据时出错: {str(e)}"
    
    if not isinstance(data, dict):
        return "无效的天气数据格式"
        
    if "error" in data:
        return f"天气查询失败: {data['error']}"
    
    try:
        city = data.get("name", "未知城市")
        country = data.get("sys", {}).get("country", "未知国家")
        temp = data.get("main", {}).get("temp", "未知温度")
        humidity = data.get("main", {}).get("humidity", "未知湿度")
        wind_speed = data.get("wind", {}).get("speed", "未知风速")
        weather_list = data.get("weather", [{}])
        description = weather_list[0].get("description", "未知天气") if weather_list else "未知天气"

        return (f"城市: {city}, {country}\n"
                f"温度: {temp}°C\n"
                f"湿度: {humidity}%\n"
                f"风速: {wind_speed}m/s\n"
                f"天气: {description}")
    except Exception as e:
        return f"格式化天气数据时出错: {str(e)}"

@mcp.tool()
async def query_weather(city: str) -> str:
    """
    查询指定城市的天气信息
    """
    data = await fetch_weather(city)
    return format_weather(data)
    
if __name__ == "__main__":
    mcp.run(transport='stdio')
    
    
    
    