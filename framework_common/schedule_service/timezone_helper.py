# -*- coding: utf-8 -*-
"""
timezone_helper.py
时区与城市换算辅助模块：
- 支持城市名与主流中英文城市字典匹配
- 支持中文时区描述（东八区、西五区等）与 UTC/GMT 偏移量智能解析
- 自动将目标时区的指定时间换算为 Bot 所在服务器时区（默认 Asia/Shanghai，东八区）的执行时间
"""

import re
import datetime
from typing import Optional, Tuple, Dict, Any, List
from dateutil import tz

DEFAULT_BOT_TZ_NAME = "Asia/Shanghai"
DEFAULT_BOT_OFFSET_HOURS = 8.0

# 常见城市/地区到 IANA 时区名称映射表
CITY_TO_TZ_MAP: Dict[str, str] = {
    # 中国主要城市（统一中国标准时间 UTC+8）
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "广州": "Asia/Shanghai",
    "深圳": "Asia/Shanghai",
    "杭州": "Asia/Shanghai",
    "成都": "Asia/Shanghai",
    "重庆": "Asia/Shanghai",
    "武汉": "Asia/Shanghai",
    "西安": "Asia/Shanghai",
    "南京": "Asia/Shanghai",
    "天津": "Asia/Shanghai",
    "郑州": "Asia/Shanghai",
    "长沙": "Asia/Shanghai",
    "沈阳": "Asia/Shanghai",
    "青岛": "Asia/Shanghai",
    "济南": "Asia/Shanghai",
    "哈尔滨": "Asia/Shanghai",
    "大连": "Asia/Shanghai",
    "厦门": "Asia/Shanghai",
    "福州": "Asia/Shanghai",
    "通辽": "Asia/Shanghai",
    "苏州": "Asia/Shanghai",
    "合肥": "Asia/Shanghai",
    "东莞": "Asia/Shanghai",
    "佛山": "Asia/Shanghai",
    "无锡": "Asia/Shanghai",
    "昆明": "Asia/Shanghai",
    "长春": "Asia/Shanghai",
    "石家庄": "Asia/Shanghai",
    "南昌": "Asia/Shanghai",
    "贵阳": "Asia/Shanghai",
    "南宁": "Asia/Shanghai",
    "乌鲁木齐": "Asia/Shanghai",
    "兰州": "Asia/Shanghai",
    "呼和浩特": "Asia/Shanghai",
    "海口": "Asia/Shanghai",
    "三亚": "Asia/Shanghai",
    "银川": "Asia/Shanghai",
    "西宁": "Asia/Shanghai",
    "拉萨": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "澳门": "Asia/Macau",
    "台北": "Asia/Taipei",
    "台湾": "Asia/Taipei",

    # 俄罗斯主要城市
    "莫斯科": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "圣彼得堡": "Europe/Moscow",
    "saint petersburg": "Europe/Moscow",
    "符拉迪沃斯托克": "Asia/Vladivostok",
    "海参崴": "Asia/Vladivostok",
    "vladivostok": "Asia/Vladivostok",
    "新西伯利亚": "Asia/Novosibirsk",
    "novosibirsk": "Asia/Novosibirsk",
    "叶卡捷琳堡": "Asia/Yekaterinburg",
    "伊尔库茨克": "Asia/Irkutsk",
    "irkutsk": "Asia/Irkutsk",
    "下诺夫哥罗德": "Europe/Moscow",
    "喀山": "Europe/Moscow",
    "索契": "Europe/Moscow",

    # 日本
    "东京": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "大阪": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "京都": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "名古屋": "Asia/Tokyo",
    "横滨": "Asia/Tokyo",
    "福冈": "Asia/Tokyo",
    "札幌": "Asia/Tokyo",

    # 韩国
    "首尔": "Asia/Seoul",
    "seoul": "Asia/Seoul",
    "釜山": "Asia/Seoul",
    "仁川": "Asia/Seoul",

    # 英国 & 欧洲
    "伦敦": "Europe/London",
    "london": "Europe/London",
    "巴黎": "Europe/Paris",
    "paris": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "法兰克福": "Europe/Berlin",
    "罗马": "Europe/Rome",
    "rome": "Europe/Rome",
    "马德里": "Europe/Madrid",
    "阿姆斯特丹": "Europe/Amsterdam",
    "维也纳": "Europe/Vienna",
    "苏黎世": "Europe/Zurich",
    "日内瓦": "Europe/Zurich",
    "斯德哥尔摩": "Europe/Stockholm",
    "华沙": "Europe/Warsaw",
    "基辅": "Europe/Kyiv",

    # 北美
    "纽约": "America/New_York",
    "new york": "America/New_York",
    "华盛顿": "America/New_York",
    "washington": "America/New_York",
    "波士顿": "America/New_York",
    "芝加哥": "America/Chicago",
    "chicago": "America/Chicago",
    "休斯顿": "America/Chicago",
    "洛杉矶": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "西雅图": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "多伦多": "America/Toronto",
    "toronto": "America/Toronto",
    "温哥华": "America/Vancouver",
    "vancouver": "America/Vancouver",

    # 东南亚 & 澳洲
    "新加坡": "Asia/Singapore",
    "singapore": "Asia/Singapore",
    "吉隆坡": "Asia/Kuala_Lumpur",
    "曼谷": "Asia/Bangkok",
    "bangkok": "Asia/Bangkok",
    "清迈": "Asia/Bangkok",
    "雅加达": "Asia/Jakarta",
    "悉尼": "Australia/Sydney",
    "sydney": "Australia/Sydney",
    "墨尔本": "Australia/Melbourne",
    "melbourne": "Australia/Melbourne",
    "布里斯班": "Australia/Brisbane",
    "珀斯": "Australia/Perth",
    "奥克兰": "Pacific/Auckland",

    # 中东
    "迪拜": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "阿布扎比": "Asia/Dubai",
}

# 中文数字转数字映射（如“东八区” -> 8，“西五区” -> -5）
CHINESE_ZONE_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "十一": 11, "十二": 12,
}


class TimezoneHelper:
    """时区解析与时间换算辅助类"""

    @staticmethod
    def get_bot_timezone() -> datetime.tzinfo:
        """获取 Bot 默认所在时区对象（默认 Asia/Shanghai，UTC+8）"""
        zone = tz.gettz(DEFAULT_BOT_TZ_NAME)
        if zone is not None:
            return zone
        return datetime.timezone(datetime.timedelta(hours=8))

    @classmethod
    def resolve_timezone(cls, city_or_tz: Optional[str]) -> Tuple[datetime.tzinfo, str, float]:
        """
        解析城市名称或时区标识为具体的 datetime.tzinfo。
        返回元组: (tzinfo 对象, 时区名称, UTC 偏移小时数)
        """
        bot_tz = cls.get_bot_timezone()
        if not city_or_tz or not isinstance(city_or_tz, str):
            return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

        raw = city_or_tz.strip().lower()

        # 1. 城市名字典匹配
        for k, tz_name in CITY_TO_TZ_MAP.items():
            if k.lower() in raw or raw in k.lower():
                zone = tz.gettz(tz_name)
                if zone is not None:
                    now = datetime.datetime.now(zone)
                    offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
                    return zone, tz_name, offset

        # 2. 中文时区表达（例如“东八区”、“西五区”、“东9区”）
        m_cn = re.search(r"([东西])([0-9零一二三四五六七八九十]+)区?", raw)
        if m_cn:
            direction, num_str = m_cn.groups()
            num = int(num_str) if num_str.isdigit() else CHINESE_ZONE_MAP.get(num_str, 8)
            offset = num if direction == "东" else -num
            zone = datetime.timezone(datetime.timedelta(hours=offset))
            sign = "+" if offset >= 0 else ""
            return zone, f"UTC{sign}{int(offset)}", float(offset)

        # 3. 常见 UTC / GMT 偏移字符串（如 UTC+8, UTC+03:00, GMT-5, +8, -3）
        m_utc = re.search(r"(?:utc|gmt)?\s*([+-]\d{1,2})(?::?(\d{2}))?", raw)
        if m_utc:
            hours = int(m_utc.group(1))
            mins = int(m_utc.group(2)) if m_utc.group(2) else 0
            total_offset = hours + (mins / 60.0 if hours >= 0 else -mins / 60.0)
            zone = datetime.timezone(datetime.timedelta(hours=hours, minutes=mins))
            sign = "+" if hours >= 0 else ""
            return zone, f"UTC{sign}{hours}:{mins:02d}" if mins else f"UTC{sign}{hours}", total_offset

        # 4. 直接尝试 tz.gettz 解析（如 "Europe/Moscow", "America/New_York"）
        direct_zone = tz.gettz(city_or_tz.strip())
        if direct_zone is not None:
            now = datetime.datetime.now(direct_zone)
            offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
            return direct_zone, city_or_tz.strip(), offset

        # 兜底返回 Bot 默认时区
        return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

    @classmethod
    def get_user_local_time(
        cls,
        city_or_tz: Optional[str],
        base_time: Optional[datetime.datetime] = None,
    ) -> datetime.datetime:
        """获取用户当地时间（若 base_time 为空则取当前时刻）"""
        zone, _, _ = cls.resolve_timezone(city_or_tz)
        if base_time is None:
            return datetime.datetime.now(zone)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=cls.get_bot_timezone())
        return base_time.astimezone(zone)

    @classmethod
    def is_user_current_time(
        cls,
        city_or_tz: Optional[str],
        target_hour: int,
        target_minute: int,
        tolerance_minutes: int = 1,
        now_dt: Optional[datetime.datetime] = None,
    ) -> bool:
        """
        判断用户当地时间是否正处于 target_hour:target_minute 附近。
        tolerance_minutes: 允许的时间误差范围（分钟）
        """
        user_now = cls.get_user_local_time(city_or_tz, base_time=now_dt)
        current_minute_of_day = user_now.hour * 60 + user_now.minute
        target_minute_of_day = target_hour * 60 + target_minute
        return abs(current_minute_of_day - target_minute_of_day) <= tolerance_minutes

    @classmethod
    def compute_next_bot_run_time(
        cls,
        target_hour: int,
        target_minute: int,
        city_or_tz: Optional[str],
        weekdays: Optional[List[int]] = None,
        from_bot_dt: Optional[datetime.datetime] = None,
    ) -> datetime.datetime:
        """
        计算目标城市当地时间到达 target_hour:target_minute 时，对应的 Bot 时区（datetime 对象）。
        weekdays: 指定星期几（0=周一, 6=周日），若为 None 则表示每天。
        """
        bot_tz = cls.get_bot_timezone()
        user_tz, _, _ = cls.resolve_timezone(city_or_tz)

        if from_bot_dt is None:
            from_bot_dt = datetime.datetime.now(bot_tz)
        elif from_bot_dt.tzinfo is None:
            from_bot_dt = from_bot_dt.replace(tzinfo=bot_tz)

        user_now = from_bot_dt.astimezone(user_tz)

        # 向上搜寻接下来 14 天中最快满足条件的时间
        for day_offset in range(14):
            candidate_date = (user_now + datetime.timedelta(days=day_offset)).date()
            if weekdays is not None and candidate_date.weekday() not in weekdays:
                continue

            candidate_user_dt = datetime.datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                target_hour,
                target_minute,
                0,
                tzinfo=user_tz,
            )

            # 必须严格在当前时间之后
            if candidate_user_dt > user_now:
                return candidate_user_dt.astimezone(bot_tz)

        # 兜底返回明天
        fallback = user_now + datetime.timedelta(days=1)
        fallback_dt = datetime.datetime(
            fallback.year, fallback.month, fallback.day,
            target_hour, target_minute, 0, tzinfo=user_tz
        )
        return fallback_dt.astimezone(bot_tz)