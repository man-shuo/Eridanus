import httpx
from xpinyin import Pinyin

p = Pinyin()


def format_free_weather(data: dict, default_city: str) -> str:
    """将 uapis 天气响应 dict 格式化为可读天气文本"""
    city_name = data.get("city") or default_city
    weather = data.get("weather")
    temp = data.get("temperature")
    wind_dir = data.get("wind_direction")
    wind_power = data.get("wind_power")
    humidity = data.get("humidity")

    parts = [str(city_name)]
    if weather:
        parts.append(str(weather))
    if temp is not None:
        parts.append(f"{temp}℃")
    wind_parts = []
    if wind_dir:
        wind_parts.append(str(wind_dir))
    if wind_power:
        wind_parts.append(str(wind_power))
    if wind_parts:
        parts.append("".join(wind_parts))
    if humidity is not None:
        parts.append(f"湿度{humidity}%")

    alerts = data.get("alerts")
    if alerts and isinstance(alerts, list):
        alert_titles = []
        for alert in alerts:
            if isinstance(alert, dict) and alert.get("title"):
                alert_titles.append(str(alert.get("title")))
            elif isinstance(alert, str):
                alert_titles.append(alert)
        if alert_titles:
            parts.append(f"预警: {'; '.join(alert_titles)}")

    if len(parts) > 1:
        return " ".join(parts)
    return f"{city_name} 天气信息暂不可用"


async def weather_query(proxy, api_key, location):
    if not api_key:
        return await free_weather_query(location)
    location_cleaned = (location or "").replace('市', '')
    location_pinyin = p.get_pinyin(location_cleaned, '')

    if proxy:
        proxies = {"http://": proxy, "https://": proxy}
    else:
        proxies = None
    async with httpx.AsyncClient(proxies=proxies, timeout=10.0) as client:
        r = await client.get(
            f"https://api.seniverse.com/v3/weather/daily.json?key={api_key}&location={location_pinyin}&language=zh-Hans&unit=c&start=0&days=5"
        )
        data = r.json()
        return data["results"]


async def free_weather_query(city):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
            r = await client.get(f"https://uapis.cn/api/v1/misc/weather?city={city}")
            if r.status_code != 200:
                return f"{city} 天气查询失败：{r.text}"
            data = r.json()
            if not isinstance(data, dict):
                return f"{city} 天气数据格式异常"
            return format_free_weather(data, city)
    except Exception as e:
        return f"{city} 天气查询异常：{e}"


if __name__ == '__main__':
    import asyncio
    result = asyncio.run(free_weather_query("清远市"))
    print(result)
