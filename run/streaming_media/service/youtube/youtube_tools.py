# -*- coding: utf-8 -*-
import os
import re
import shutil
import asyncio
import httpx
from framework_common.utils.install_and_import import install_and_import

yt_dlp = install_and_import("yt-dlp", "yt_dlp")

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import get_headers
from developTools.utils.logger import get_logger

logger = get_logger()

def get_proxy():
    # 1. 尝试从 YAML 配置文件中读取
    try:
        yamlmanager = YAMLManager.get_instance()
        basic_cfg = yamlmanager.common_config.basic_config
        if isinstance(basic_cfg.get("proxy"), dict):
            p = basic_cfg.get("proxy", {}).get("http_proxy")
            if p:
                return p
            p = basic_cfg.get("proxy", {}).get("socks_proxy")
            if p:
                return p
        elif isinstance(basic_cfg.get("proxy"), str) and basic_cfg.get("proxy"):
            return basic_cfg.get("proxy")

        tg_p = basic_cfg.get("telegram", {}).get("proxy")
        if tg_p:
            return tg_p

        bs_p = basic_cfg.get("basic_setting", {}).get("proxy")
        if bs_p:
            return bs_p
    except Exception:
        pass

    # 2. 尝试从环境变量读取
    for env_key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        val = os.environ.get(env_key)
        if val:
            return val

    # 3. 尝试从 Windows 系统代理注册表读取
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if server:
                    if not server.startswith("http://") and not server.startswith("https://"):
                        server = "http://" + server
                    return server
    except Exception:
        pass

    return None

def get_ydl_base_opts():
    proxy = get_proxy()
    opts = {
        "quiet": False,
        "no_warnings": False,
    }
    if proxy:
        opts["proxy"] = proxy

    # 自动探测 Node.js 环境以解决 YouTube 提取签名运行时的需求
    node_path = shutil.which("node")
    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}

    return opts

def audio_download(video_id, output_dir="data/voice/cache"):
    global yt_dlp
    if yt_dlp is None:
        yt_dlp = install_and_import("yt-dlp", "yt_dlp")
        if yt_dlp is None:
            raise ImportError("无法加载或安装 yt-dlp 模块")

    os.makedirs(output_dir, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    target_file = os.path.join(output_dir, f"{video_id}.mp3")

    if os.path.exists(target_file) and os.path.getsize(target_file) > 1024:
        logger.info(f"YouTube audio cache hit: {target_file}")
        return target_file

    ydl_opts = get_ydl_base_opts()
    outtmpl = os.path.join(output_dir, f"{video_id}.%(ext)s")
    ydl_opts.update({
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "overwrites": True,
    })

    logger.info(f"Downloading YouTube audio: {url} -> {target_file}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not os.path.exists(target_file):
        for f in os.listdir(output_dir):
            if f.startswith(video_id):
                return os.path.join(output_dir, f)
        raise FileNotFoundError(f"Failed to find downloaded audio for {video_id}")

    return target_file

def video_download(video_id, output_dir="data/video/cache"):
    global yt_dlp
    if yt_dlp is None:
        yt_dlp = install_and_import("yt-dlp", "yt_dlp")
        if yt_dlp is None:
            raise ImportError("无法加载或安装 yt-dlp 模块")

    os.makedirs(output_dir, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    target_file = os.path.join(output_dir, f"{video_id}.mp4")

    if os.path.exists(target_file) and os.path.getsize(target_file) > 1024:
        logger.info(f"YouTube video cache hit: {target_file}")
        return target_file

    ydl_opts = get_ydl_base_opts()
    outtmpl = os.path.join(output_dir, f"{video_id}.%(ext)s")
    ydl_opts.update({
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "overwrites": True,
    })

    logger.info(f"Downloading YouTube video: {url} -> {target_file}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not os.path.exists(target_file):
        for f in os.listdir(output_dir):
            if f.startswith(video_id):
                return os.path.join(output_dir, f)
        raise FileNotFoundError(f"Failed to find downloaded video for {video_id}")

    return target_file

async def get_img(video_id, output_dir="data/pictures/cache"):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{video_id}.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 512:
        return path

    proxy = get_proxy()
    proxies = {"http://": proxy, "https://": proxy} if proxy else None

    thumb_urls = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hq720.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    ]

    async with httpx.AsyncClient(headers=get_headers(), proxies=proxies, timeout=30) as client:
        for url in thumb_urls:
            try:
                response = await client.get(url)
                if response.status_code == 200 and len(response.content) > 1000:
                    with open(path, "wb") as f:
                        f.write(response.content)
                    return path
            except Exception as e:
                logger.warning(f"Failed to download thumbnail from {url}: {e}")

    return path

def get_info(video_id):
    global yt_dlp
    if yt_dlp is None:
        yt_dlp = install_and_import("yt-dlp", "yt_dlp")
        if yt_dlp is None:
            raise ImportError("无法加载或安装 yt-dlp 模块")

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = get_ydl_base_opts()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    print(f"标题: {info.get('title')}")
    print(f"作者: {info.get('uploader')}")
    print(f"时长(秒): {info.get('duration')}")
    print(f"观看次数: {info.get('view_count')}")
    desc = info.get("description") or ""
    print(f"描述: {desc[:200]}...")
    return info

if __name__ == "__main__":
    url = "https://youtu.be/QhUvJLOI6_E?si=nARo0Y6GtfKlhPp0"
    regex = r"(?:youtu\.be\/|youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/))([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    if match:
        v_id = match.group(1)
        print("Video ID:", v_id)
        get_info(v_id)
        print("Audio:", audio_download(v_id))
        print("Video:", video_download(v_id))