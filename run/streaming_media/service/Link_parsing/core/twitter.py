import copy
import re

import httpx
from bs4 import BeautifulSoup
from httpx import AsyncClient

from .common import COMMON_HEADER, filepath_init, json_init, no_draw_type
from developTools.utils.logger import get_logger
from framework_common.manshuo_draw.manshuo_draw import manshuo_draw


logger = get_logger()


def _twitter_quality_value(label):
    match = re.search(r"(\d+)\s*p", str(label or ""), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _twitter_media_options(html_text):
    """Extract the post title, preview image, and available video variants."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    title_node = soup.find("h3")
    title = title_node.get_text(" ", strip=True) if title_node else ""

    image_node = soup.find("img", src=True)
    image_url = image_node.get("src", "").strip() if image_node else ""

    video_options = []
    seen = set()
    for link in soup.select("a[href]"):
        href = link.get("href", "").strip()
        label = link.get_text(" ", strip=True)
        if not href.startswith(("http://", "https://")) or "mp4" not in label.lower():
            continue
        quality_match = re.search(r"\(([^)]+)\)", label)
        quality = quality_match.group(1).strip() if quality_match else label
        if href in seen:
            continue
        seen.add(href)
        video_options.append({
            "url": href,
            "label": label,
            "quality": quality,
        })

    video_options.sort(
        key=lambda item: _twitter_quality_value(item["quality"]),
        reverse=True,
    )
    return title, image_url, video_options


async def twitter(url, filepath=None, proxy=None, type_check=None):
    """Parse an X post through xdown.app and optionally render its preview."""
    json_check = copy.deepcopy(json_init)
    json_check["soft_type"] = "x"
    json_check["status"] = True
    json_check["video_url"] = False
    if filepath is None:
        filepath = filepath_init

    x_match = re.search(
        r"https?://x\.com/([0-9a-zA-Z_]{1,20})/status/(\d+)",
        str(url),
    )
    if not x_match:
        json_check["status"] = False
        json_check["reason"] = "未找到有效的 X 帖子链接"
        return json_check

    x_url = x_match[0]
    json_check["url"] = x_url
    json_check["user_name"] = f"@{x_match.group(1)}"

    async def x_req(post_url):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://xdown.app",
            "Referer": "https://xdown.app/",
            "User-Agent": COMMON_HEADER.get("User-Agent", ""),
        }
        client_options = {
            "headers": headers,
            "timeout": httpx.Timeout(30.0, connect=15.0),
            "follow_redirects": True,
        }
        # The project currently pins httpx<0.28, whose proxy option is
        # named ``proxies``.
        if proxy:
            client_options["proxies"] = proxy
        async with AsyncClient(**client_options) as client:
            response = await client.post(
                "https://xdown.app/api/ajaxSearch",
                data={"q": post_url, "lang": "zh-cn"},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

    rsq_data = await x_req(x_url)
    response_html = rsq_data.get("data") or ""
    title, img_url, video_options = _twitter_media_options(response_html)

    if title:
        json_check["title"] = title
        json_check["content"] = {"text": title, "type": "post"}
    if img_url:
        json_check["pic_url_list"] = [img_url]
    if video_options:
        json_check["video_options"] = video_options
        json_check["video_url"] = [item["url"] for item in video_options]

    if type_check not in no_draw_type:
        draw_proxy = proxy or "http://127.0.0.1:20172"
        draw_json = [
            {"type": "basic_set", "proxy": draw_proxy},
            {"type": "backdrop", "subtype": "one_color"},
        ]
        if img_url:
            draw_json.append({
                "type": "avatar",
                "subtype": "common",
                "img": [img_url],
                "upshift_extra": 20,
                "content": [
                    f"[name]{json_check.get('user_name', '')}[/name]\n"
                    f"[time]{json_check['url']}[/time]"
                ],
            })
        if json_check["pic_url_list"]:
            draw_json.append(json_check["pic_url_list"])
        draw_json.append([json_check.get("title") or "X 帖子"])
        json_check["pic_path"] = await manshuo_draw(draw_json)

    return json_check
