import base64
import random
import re
import string
import shutil
import urllib.parse
from io import BytesIO
import os

import httpx

from PIL import Image
from .base import BaseTool



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


class ImageProcessor(BaseTool):
    def __init__(self):
        super().__init__(__class__.__name__)
    async def Image2Base64(self, url: str) -> str:
        """
        将图片转为base64，支持网络URL、本地文件路径、data:image base64字符串
        """
        if url.startswith("data:image"):
            match = re.match(r"data:image/(.*?);base64,(.+)", url)
            if not match:
                raise ValueError("Invalid Data URI format")
            _, base64_data = match.groups()
            return base64_data
        if url.startswith("file://") or (not url.startswith(("http://", "https://"))):
            actual_path = get_local_file_path(url)
            if not os.path.isfile(actual_path):
                raise FileNotFoundError(f"本地图片不存在：{actual_path}")
            with open(actual_path, "rb") as f:
                image_bytes = f.read()
        else:
            async with httpx.AsyncClient(timeout=9000) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    raise Exception(f"图片下载失败，状态码：{response.status_code}")
                image_bytes = response.content
        return base64.b64encode(image_bytes).decode("utf-8")
    async def download_img(self,url, path=None, gray_layer=False, proxy=None, headers=None)->str:
        """下载一张图片"""
        if path is None:
            characters = string.ascii_letters + string.digits
            random_string = ''.join(random.choice(characters) for _ in range(10))
            path = f'data/pictures/cache/{random_string}.jpg'

        dir_name = os.path.dirname(os.path.abspath(path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        if url.startswith("data:image"):
            match = re.match(r"data:image/(.*?);base64,(.+)", url)
            if not match:
                raise ValueError("Invalid Data URI format")
            img_type, base64_data = match.groups()
            img_data = base64.b64decode(base64_data)
            try:
                with open(path, "wb") as f:
                    f.write(img_data)
            finally:
                del img_data
            return path

        # 处理本地 file:// 协议与绝对路径
        if url.startswith("file://") or (not url.startswith(("http://", "https://")) and os.path.isfile(get_local_file_path(url))):
            local_src = get_local_file_path(url)
            if not os.path.isfile(local_src):
                raise FileNotFoundError(f"本地图片不存在：{local_src}")
            if gray_layer:
                with Image.open(local_src) as img:
                    image_raw = img
                    image_black_white = image_raw.convert('1')
                    image_black_white.save(path)
            else:
                shutil.copyfile(local_src, path)
            return path

        if proxy is not None and proxy != '':
            proxies = {"http://": proxy, "https://": proxy}
        else:
            proxies = None

        async with httpx.AsyncClient(proxies=proxies, headers=headers,timeout=60) as client:
            response = await client.get(url)

            if gray_layer:
                img = None
                try:
                    img = Image.open(BytesIO(response.content))  # 从二进制数据创建图片对象
                    image_raw = img
                    image_black_white = image_raw.convert('1')
                    image_black_white.save(path)
                finally:
                    if img is not None:
                        img.close()
                    del response
            else:
                try:
                    with open(path, 'wb') as f:
                        f.write(response.content)
                finally:
                    del response

            return path
