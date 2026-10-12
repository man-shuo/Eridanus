# -*- coding: utf-8 -*-
"""
timezone_helper.py
????????????
- ?????????????????
- ??????????????????? UTC/GMT ???????
- ???????????? Castro Valley?Irvine?Waterloo ?????? Open-Meteo ???? API ????????????????
- ??????????????? Bot ?????????? Asia/Shanghai??????????
"""

import os
import re
import sqlite3
import datetime
from typing import Optional, Tuple, Dict, Any, List
from dateutil import tz

try:
    import requests
except ImportError:
    requests = None

DEFAULT_BOT_TZ_NAME = "Asia/Shanghai"
DEFAULT_BOT_OFFSET_HOURS = 8.0

CACHE_DB_PATH = os.path.join("data", "dataBase", "dynamic_schedules.db")

# ????/??? IANA ???????
CITY_TO_TZ_MAP: Dict[str, str] = {
    # ??????????????? UTC+8?
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "???": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "???": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "????": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "????": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Shanghai",
    "??": "Asia/Hong_Kong",
    "??": "Asia/Macau",
    "??": "Asia/Taipei",
    "??": "Asia/Taipei",

    # ???????
    "???": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "????": "Europe/Moscow",
    "saint petersburg": "Europe/Moscow",
    "???????": "Asia/Vladivostok",
    "???": "Asia/Vladivostok",
    "vladivostok": "Asia/Vladivostok",
    "?????": "Asia/Novosibirsk",
    "novosibirsk": "Asia/Novosibirsk",
    "?????": "Asia/Yekaterinburg",
    "?????": "Asia/Irkutsk",
    "irkutsk": "Asia/Irkutsk",
    "??????": "Europe/Moscow",
    "??": "Europe/Moscow",
    "??": "Europe/Moscow",

    # ??
    "??": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "??": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "??": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "???": "Asia/Tokyo",
    "??": "Asia/Tokyo",
    "??": "Asia/Tokyo",
    "??": "Asia/Tokyo",

    # ??
    "??": "Asia/Seoul",
    "seoul": "Asia/Seoul",
    "??": "Asia/Seoul",
    "??": "Asia/Seoul",

    # ?? & ??
    "??": "Europe/London",
    "london": "Europe/London",
    "??": "Europe/Paris",
    "paris": "Europe/Paris",
    "??": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "????": "Europe/Berlin",
    "??": "Europe/Rome",
    "rome": "Europe/Rome",
    "???": "Europe/Madrid",
    "?????": "Europe/Amsterdam",
    "???": "Europe/Vienna",
    "???": "Europe/Zurich",
    "???": "Europe/Zurich",
    "?????": "Europe/Stockholm",
    "??": "Europe/Warsaw",
    "??": "Europe/Kyiv",

    # ?????????????/?????
    "??": "America/New_York",
    "new york": "America/New_York",
    "???": "America/New_York",
    "washington": "America/New_York",
    "???": "America/New_York",
    "boston": "America/New_York",
    "???": "America/Chicago",
    "chicago": "America/Chicago",
    "???": "America/Chicago",
    "houston": "America/Chicago",
    "???": "America/Chicago",
    "dallas": "America/Chicago",
    "???": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "san jose": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "??": "America/Los_Angeles",
    "irvine": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "berkeley": "America/Los_Angeles",
    "????": "America/Los_Angeles",
    "palo alto": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "mountain view": "America/Los_Angeles",
    "????": "America/Los_Angeles",
    "cupertino": "America/Los_Angeles",
    "????": "America/Los_Angeles",
    "sunnyvale": "America/Los_Angeles",
    "????": "America/Los_Angeles",
    "fremont": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "oakland": "America/Los_Angeles",
    "?????": "America/Los_Angeles",
    "castro valley": "America/Los_Angeles",
    "???": "America/Los_Angeles",
    "hayward": "America/Los_Angeles",
    "????": "America/Los_Angeles",
    "san mateo": "America/Los_Angeles",
    "???": "America/Toronto",
    "toronto": "America/Toronto",
    "???": "America/Toronto",
    "???": "America/Vancouver",
    "vancouver": "America/Vancouver",

    # ??? & ??
    "???": "Asia/Singapore",
    "singapore": "Asia/Singapore",
    "???": "Asia/Kuala_Lumpur",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "??": "Asia/Bangkok",
    "bangkok": "Asia/Bangkok",
    "??": "Asia/Bangkok",
    "???": "Asia/Jakarta",
    "??": "Australia/Sydney",
    "sydney": "Australia/Sydney",
    "???": "Australia/Melbourne",
    "melbourne": "Australia/Melbourne",
    "????": "Australia/Brisbane",
    "??": "Australia/Perth",
    "auckland": "Pacific/Auckland",
}

CHINESE_ZONE_MAP = {
    "?": 0, "?": 1, "?": 2, "?": 3, "?": 4, "?": 5, "?": 6,
    "?": 7, "?": 8, "?": 9, "?": 10, "??": 11, "??": 12,
}


class TimezoneHelper:
    """????????????"""

    _mem_cache: Dict[str, str] = {}
    _failed_queries: set = set()
    _db_initialized: bool = False

    @classmethod
    def _ensure_cache_db(cls) -> None:
        if cls._db_initialized:
            return
        try:
            os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
            with sqlite3.connect(CACHE_DB_PATH, timeout=5.0) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS city_timezone_cache (
                        city_key TEXT PRIMARY KEY,
                        tz_name TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            cls._db_initialized = True
        except Exception:
            pass

    @classmethod
    def _get_cached_tz(cls, raw_key: str) -> Optional[str]:
        if raw_key in cls._mem_cache:
            return cls._mem_cache[raw_key]
        cls._ensure_cache_db()
        try:
            with sqlite3.connect(CACHE_DB_PATH, timeout=3.0) as conn:
                cur = conn.execute(
                    "SELECT tz_name FROM city_timezone_cache WHERE city_key = ?",
                    (raw_key,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    cls._mem_cache[raw_key] = row[0]
                    return row[0]
        except Exception:
            pass
        return None

    @classmethod
    def _save_cached_tz(cls, raw_key: str, tz_name: str) -> None:
        cls._mem_cache[raw_key] = tz_name
        cls._ensure_cache_db()
        try:
            now_str = datetime.datetime.now().isoformat()
            with sqlite3.connect(CACHE_DB_PATH, timeout=3.0) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO city_timezone_cache (city_key, tz_name, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (raw_key, tz_name, now_str),
                )
                conn.commit()
        except Exception:
            pass

    @classmethod
    def _query_remote_geocoding_tz(cls, city_query: str) -> Optional[str]:
        """?? Open-Meteo ????????????????? IANA ????"""
        raw_key = city_query.strip().lower()
        if not raw_key or raw_key in cls._failed_queries or requests is None:
            return None

        url = "https://geocoding-api.open-meteo.com/v1/search"
        for lang in ("zh", "en"):
            try:
                resp = requests.get(
                    url,
                    params={"name": city_query.strip(), "count": 1, "language": lang, "format": "json"},
                    timeout=3.5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results")
                    if results and isinstance(results, list):
                        tz_name = results[0].get("timezone")
                        if tz_name and tz.gettz(tz_name) is not None:
                            cls._save_cached_tz(raw_key, tz_name)
                            return tz_name
            except Exception:
                continue

        cls._failed_queries.add(raw_key)
        return None

    @staticmethod
    def get_bot_timezone() -> datetime.tzinfo:
        """?? Bot ??????????? Asia/Shanghai?UTC+8?"""
        zone = tz.gettz(DEFAULT_BOT_TZ_NAME)
        if zone is not None:
            return zone
        return datetime.timezone(datetime.timedelta(hours=8))

    @classmethod
    def resolve_timezone(cls, city_or_tz: Optional[str]) -> Tuple[datetime.tzinfo, str, float]:
        """
        ??????????????? datetime.tzinfo?
        ????: (tzinfo ??, ????, UTC ?????)
        """
        bot_tz = cls.get_bot_timezone()
        if not city_or_tz or not isinstance(city_or_tz, str):
            return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

        raw = city_or_tz.strip().lower()
        if not raw:
            return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

        # 1. ??????????????????????
        if raw in CITY_TO_TZ_MAP:
            tz_name = CITY_TO_TZ_MAP[raw]
            zone = tz.gettz(tz_name)
            if zone is not None:
                now = datetime.datetime.now(zone)
                offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
                return zone, tz_name, offset

        for k, tz_name in CITY_TO_TZ_MAP.items():
            k_low = k.lower()
            if len(k_low) >= 2 and (k_low in raw or raw in k_low):
                zone = tz.gettz(tz_name)
                if zone is not None:
                    now = datetime.datetime.now(zone)
                    offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
                    return zone, tz_name, offset

        # 2. ???????????????????????9???
        m_cn = re.search(r"([??])([0-9???????????]+)??", raw)
        if m_cn:
            direction, num_str = m_cn.groups()
            num = int(num_str) if num_str.isdigit() else CHINESE_ZONE_MAP.get(num_str, 8)
            offset = num if direction == "?" else -num
            zone = datetime.timezone(datetime.timedelta(hours=offset))
            sign = "+" if offset >= 0 else ""
            return zone, f"UTC{sign}{int(offset)}", float(offset)

        # 3. ?? UTC / GMT ??????? UTC+8, UTC+03:00, GMT-5, +8, -3?
        m_utc = re.search(r"^(?:utc|gmt)?\s*([+-]\d{1,2})(?::?(\d{2}))?$", raw)
        if m_utc:
            hours = int(m_utc.group(1))
            mins = int(m_utc.group(2)) if m_utc.group(2) else 0
            total_offset = hours + (mins / 60.0 if hours >= 0 else -mins / 60.0)
            zone = datetime.timezone(datetime.timedelta(hours=hours, minutes=mins))
            sign = "+" if hours >= 0 else ""
            return zone, f"UTC{sign}{hours}:{mins:02d}" if mins else f"UTC{sign}{hours}", total_offset

        # 4. ???? tz.gettz ???? "Europe/Moscow", "America/New_York"?
        direct_zone = tz.gettz(city_or_tz.strip())
        if direct_zone is not None:
            now = datetime.datetime.now(direct_zone)
            offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
            return direct_zone, city_or_tz.strip(), offset

        # 5. ????????????
        cached_tz_name = cls._get_cached_tz(raw)
        if cached_tz_name:
            cached_zone = tz.gettz(cached_tz_name)
            if cached_zone is not None:
                now = datetime.datetime.now(cached_zone)
                offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
                return cached_zone, cached_tz_name, offset

        # 6. ????????????????????/???? Castro Valley ???????
        remote_tz_name = cls._query_remote_geocoding_tz(city_or_tz.strip())
        if remote_tz_name:
            remote_zone = tz.gettz(remote_tz_name)
            if remote_zone is not None:
                now = datetime.datetime.now(remote_zone)
                offset = (now.utcoffset() or datetime.timedelta(hours=8)).total_seconds() / 3600.0
                return remote_zone, remote_tz_name, offset

        # ???? Bot ????
        return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

    @classmethod
    def get_user_local_time(
        cls,
        city_or_tz: Optional[str],
        base_time: Optional[datetime.datetime] = None,
    ) -> datetime.datetime:
        """?????????? base_time ?????????"""
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
        ????????????? target_hour:target_minute ???
        tolerance_minutes: ?????????????
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
        ???????????? target_hour:target_minute ????? Bot ???datetime ????
        weekdays: ??????0=??, 6=?????? None ??????
        """
        bot_tz = cls.get_bot_timezone()
        user_tz, _, _ = cls.resolve_timezone(city_or_tz)

        if from_bot_dt is None:
            from_bot_dt = datetime.datetime.now(bot_tz)
        elif from_bot_dt.tzinfo is None:
            from_bot_dt = from_bot_dt.replace(tzinfo=bot_tz)

        user_now = from_bot_dt.astimezone(user_tz)

        # ??????? 14 ???????????
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

            # ???????????
            if candidate_user_dt > user_now:
                return candidate_user_dt.astimezone(bot_tz)

        # ??????
        fallback = user_now + datetime.timedelta(days=1)
        fallback_dt = datetime.datetime(
            fallback.year, fallback.month, fallback.day,
            target_hour, target_minute, 0, tzinfo=user_tz
        )
        return fallback_dt.astimezone(bot_tz)
