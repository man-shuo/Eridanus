import os
import shutil
import urllib.parse
import base64
import random
import re
import string
from io import BytesIO
from typing import Optional

import httpx
import requests
from PIL import Image

from .base import BaseTool



def _get_local_file_path(url: str) -> str:
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


class NetworkProcessor(BaseTool):

    _UA_SERVICES = [
        "https://httpbin.org/user-agent",
        "http://httpbin.org/user-agent",
    ]

    def __init__(self):
        super().__init__()
        #self.user_agent = self._fetch_ua_sync()
        self._client = httpx.AsyncClient(
            headers={},
            timeout=60,
        )

    def _fetch_ua_sync(self) -> Optional[str]:
        self.logger.info("Fetching User-Agent...")
        """获取当前的 User-Agent,其实没啥用，返回的是httpx的默认UA"""
        for service in self._UA_SERVICES:
            try:
                resp = requests.get(service, timeout=10)
                if resp.status_code == 200:
                    ua = resp.json().get("user-agent", "").strip()
                    if ua:
                        return ua
            except Exception as e:
                print(f"从 {service} 获取 UA 失败: {e}")
                continue
        return None

    def random_headers(self)->dict:
        user_agent_list = [
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/22.0.1207.1 Safari/537.1",
            "Mozilla/5.0 (X11; CrOS i686 2268.111.0) AppleWebKit/536.11 (KHTML, like Gecko) Chrome/20.0.1132.57 Safari/536.11",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.6 (KHTML, like Gecko) Chrome/20.0.1092.0 Safari/536.6",
            "Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.6 (KHTML, like Gecko) Chrome/20.0.1090.0 Safari/536.6",
            "Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/19.77.34.5 Safari/537.1",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/536.5 (KHTML, like Gecko) Chrome/19.0.1084.9 Safari/536.5",
            "Mozilla/5.0 (Windows NT 6.0) AppleWebKit/536.5 (KHTML, like Gecko) Chrome/19.0.1084.36 Safari/536.5",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1063.0 Safari/536.3",
            "Mozilla/5.0 (Windows NT 5.1) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1063.0 Safari/536.3",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1063.0 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1062.0 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1062.0 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1061.1 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1061.1 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1061.1 Safari/536.3",
            "Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1061.0 Safari/536.3",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/535.24 (KHTML, like Gecko) Chrome/19.0.1055.1 Safari/535.24",
            "Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/535.24 (KHTML, like Gecko) Chrome/19.0.1055.1 Safari/535.24"]

        userAgent = random.choice(user_agent_list)
        headers = {'User-Agent': userAgent}
        return headers

    """这几个函数除了network类，各自类别中也都有。那为什么要再写一份呢，因为有铸币"""
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
        if url.startswith("file://") or (not url.startswith(("http://", "https://")) and os.path.isfile(_get_local_file_path(url))):
            local_src = _get_local_file_path(url)
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

        async with httpx.AsyncClient(proxies=proxies, headers=headers) as client:
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
    async def download_file(self,url,path,proxy=None)->str:
        if proxy is not None and proxy != '':
            proxies = {"http://": proxy, "https://": proxy}
        else:
            proxies = None
        async with httpx.AsyncClient(proxies=proxies, timeout=None) as client:
            response = await client.get(url)
            with open(path, 'wb') as f:
                f.write(response.content)
            return path
    """
    给笨蛋用的
    """
    async def get(self, url, *, params=None, headers=None, cookies=None):
        return await self._client.get(url, params=params, headers=headers, cookies=cookies)

    async def post(self, url, *, data=None, files=None, headers=None, cookies=None):
        return await self._client.post(url, data=data, files=files, headers=headers, cookies=cookies)

    async def post_json(self, url, *, json=None, headers=None, cookies=None):
        return await self._client.post(url, json=json, headers=headers, cookies=cookies)
