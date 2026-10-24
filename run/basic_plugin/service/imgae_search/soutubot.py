# -*- coding: utf-8 -*-
import os
import io
import time
import json
import urllib.parse
from typing import Optional, Dict, Any, List, Union
import requests
import asyncio
from PIL import Image as PILImage

API_URL = "https://soutubot.moe/api/search"
BASE_URL = "https://soutubot.moe"

try:
    from framework_common.ToolKits.util import Util
    tool = Util.get_instance()
    USER_AGENT = tool.network.random_headers().get("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
except Exception:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

IMAGE_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Referer": BASE_URL + "/",
}


def get_local_file_path(url: str) -> str:
    """解析本地 URI / 绝对路径 / 兼容反斜杠与 URL 解码"""
    if not url:
        return ""
    p = str(url).strip()
    if p.startswith("file:///"):
        p = p[8:]
    elif p.startswith("file://"):
        p = p[7:]
    try:
        p = urllib.parse.unquote(p)
    except Exception:
        pass
    if len(p) >= 3 and p[0] in ('/', '\\') and p[2] == ':' and p[1].isalpha():
        p = p[1:]
    return os.path.normpath(p)


def _prepare_image_data(image_data: bytes, max_bytes: int = 5 * 1024 * 1024, max_width: int = 2000) -> bytes:
    """如果图片超出大小限制或尺寸过大，按与前端相同的逻辑进行缩放和压缩"""
    if len(image_data) <= max_bytes:
        try:
            with PILImage.open(io.BytesIO(image_data)) as img:
                if img.width <= max_width and img.height <= max_width:
                    return image_data
        except Exception:
            return image_data

    try:
        with PILImage.open(io.BytesIO(image_data)) as img:
            rgb_img = img.convert("RGB")
            width, height = rgb_img.size
            scale = min(1.0, float(max_width) / max(width, 1))

            quality = 90
            for _ in range(10):
                new_w = max(1, int(round(width * scale)))
                new_h = max(1, int(round(height * scale)))
                resized = rgb_img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=quality)
                out_bytes = buf.getvalue()
                if len(out_bytes) <= max_bytes:
                    return out_bytes
                if quality > 66:
                    quality -= 8
                else:
                    scale *= 0.82
            return out_bytes
    except Exception:
        return image_data


def _parse_soutubot_response(payload: dict) -> List[Dict[str, Any]]:
    """
    将 soutubot.moe 新版 API (/api/search) 返回的 JSON 解析为统一格式。
    与 image_search.py 保持兼容：
    title, similarity, page, previewImageUrl, source, source_url, page_url 等。
    """
    items = []
    results = payload.get("results", [])
    if not isinstance(results, list):
        return items

    for hit in results:
        score = float(hit.get("score", 0.0) or 0.0)
        segments = hit.get("path_segments", [])
        if not segments:
            continue

        best_seg = segments[0]
        for seg in segments:
            meta = seg.get("metadata") or {}
            lang = str((meta.get("facts") or {}).get("language") or seg.get("language") or "").lower()
            if "chinese" in lang or "zh" in lang:
                best_seg = seg
                break
            if seg.get("metadata_status") == "found" and best_seg.get("metadata_status") != "found":
                best_seg = seg

        meta = best_seg.get("metadata") or {}
        src = meta.get("source") or {}
        title_obj = meta.get("title")
        title = ""
        if isinstance(title_obj, dict):
            title = title_obj.get("primary") or title_obj.get("japanese_or_alias") or title_obj.get("romanized") or ""
        elif isinstance(title_obj, str):
            title = title_obj

        source_name = src.get("name") or best_seg.get("source_key") or "未知"
        source_id = src.get("id") or best_seg.get("external_id") or ""

        if not title:
            source_key = str(best_seg.get("source_key") or "").lower()
            if source_key == "pixiv" or "pixiv" in str(source_name).lower():
                title = f"Pixiv ID: {source_id}" if source_id else "Pixiv 作品"
            elif source_id:
                title = f"{source_name} #{source_id}"
            else:
                title = "未知作品"

        page_no = best_seg.get("page_no") or (meta.get("facts") or {}).get("page") or 1
        links = best_seg.get("links") or {}
        thumb_url = best_seg.get("thumbnail_url") or links.get("thumbnail_url") or ""
        source_url = best_seg.get("source_url") or links.get("source_url") or src.get("url") or ""
        page_url = best_seg.get("page_url") or links.get("page_url") or ""

        items.append({
            "title": title,
            "similarity": f"{score:.2f}%",
            "score": round(score, 2),
            "page": page_no,
            "previewImageUrl": thumb_url,
            "source": source_name,
            "source_url": source_url,
            "page_url": page_url,
            "language": (meta.get("facts") or {}).get("language") or best_seg.get("language") or "",
        })

    return items


def _do_search(session: requests.Session, image_data: bytes,
               factor: float = 1.2, proxy: Optional[str] = None) -> Dict[str, Any]:
    """
    发送图片二进制给 soutubot.moe 新版 API 并返回统一格式结果。
    新版前端不再需要 window.GLOBAL.m 也不再需要 x-api-key。
    """
    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json",
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }

    prepared_data = _prepare_image_data(image_data)
    files = {"file": ("image.png", prepared_data, "image/png")}
    data = {"factor": str(factor), "metadata_mode": "display", "top_k": "25"}
    proxies = {"http": proxy, "https": proxy} if proxy else None

    resp = session.post(API_URL, headers=headers, files=files, data=data, proxies=proxies, timeout=30)
    resp.raise_for_status()

    raw_json = resp.json()
    parsed_items = _parse_soutubot_response(raw_json)
    return {
        "data": parsed_items,
        "raw": raw_json,
        "results": raw_json.get("results", [])
    }


def search_by_image(image_path: str, factor: float = 1.2, proxy: Optional[str] = None) -> Dict[str, Any]:
    """以本地图片路径搜索。"""
    target_path = get_local_file_path(image_path)
    with open(target_path, "rb") as f:
        image_data = f.read()

    session = requests.Session()
    return _do_search(session, image_data, factor=factor, proxy=proxy)


def search_by_url(image_url: str, factor: float = 1.2, proxy: Optional[str] = None) -> Dict[str, Any]:
    """先下载远程图片，再调用搜索。"""
    session = requests.Session()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    print(f"[*] 下载图片: {image_url}")
    img_resp = session.get(image_url, headers=IMAGE_HEADERS, proxies=proxies, timeout=20)
    img_resp.raise_for_status()

    return _do_search(session, img_resp.content, factor=factor, proxy=proxy)


def search_img_by_path_or_url(target: str, factor: float = 1.2, proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    综合入口：支持本地路径与远程 URL，返回解析好的结果列表（用于 image_search.py）。
    """
    try:
        if target.startswith("http://") or target.startswith("https://"):
            print(f"[*] 远程图片搜索: {target}")
            result = search_by_url(target, factor, proxy=proxy)
        else:
            print(f"[*] 本地图片搜索: {target}")
            target = get_local_file_path(target)
            result = search_by_image(target, factor, proxy=proxy)

        return result.get("data", [])
    except Exception as e:
        import traceback
        print(f"[x] 搜索失败: {e}")
        traceback.print_exc()
        return []


async def async_search_by_image(image_path: str, factor: float = 1.2, proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    异步包装：本地图片搜索
    """
    result = await asyncio.to_thread(search_img_by_path_or_url, image_path, factor, proxy)
    return result


def print_results(result: Union[Dict[str, Any], List[Dict[str, Any]]]):
    items = result.get("data", []) if isinstance(result, dict) else result
    if items:
        print(f"\n[*] 共 {len(items)} 条结果:")
        for i, item in enumerate(items, 1):
            title = item.get("title") or "无标题"
            sim = item.get("similarity", "未知")
            source = item.get("source", "未知源")
            page = item.get("page", 1)
            print(f"  {i}. [{source}] {title} (相似度: {sim}, 页码: {page})")
    else:
        print("[-] 未找到相关结果。")
