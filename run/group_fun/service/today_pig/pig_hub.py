import asyncio
import os
import json
import re
import pprint
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import httpx
import shutil
import random
from framework_common.manshuo_draw import *
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase
db=asyncio.run(AsyncSQLiteDatabase.get_instance())

current_file = Path(__file__).resolve()
# 获取当前脚本文件所在的目录
plugin_dir = current_file.parent
resource_dir = plugin_dir / 'resource'
img_dir = resource_dir / 'img'
pig_data = resource_dir / 'pig_data.json'
pig_hub_data = resource_dir / 'pig_hub_data.json'
pig_hub_data_cache, pig_data_cache = {}, {}
if not resource_dir.exists():
    resource_dir.mkdir(parents=True, exist_ok=True)
if not img_dir.exists():
    img_dir.mkdir(parents=True, exist_ok=True)
if not pig_data.exists():
    with open(pig_data, 'w', encoding='utf-8') as f:
        json.dump({}, f, ensure_ascii=False, indent=4)
else:
    with open(pig_data, 'r', encoding='utf-8') as f:
        pig_data_cache = json.load(f)
if not pig_hub_data.exists():
    with open(pig_hub_data, 'w', encoding='utf-8') as f:
        json.dump({}, f, ensure_ascii=False, indent=4)
else:
    with open(pig_hub_data, 'r', encoding='utf-8') as f:
        pig_hub_data_cache = json.load(f)

#从pig_hub_api更新数据
async def pig_hub_update():
    global pig_hub_data_cache
    async with httpx.AsyncClient() as client:
        url = 'https://pighub.top/api/all-images'
        response = await client.get(url)
        pig_hub_data_cache = response.json()
        with open(pig_hub_data, 'w', encoding='utf-8') as f:
            json.dump(pig_hub_data_cache, f, ensure_ascii=False, indent=4)

#获取pig_hub的图片并保存在本地
async def pig_hub_img_get(img_name, img_url=None,proxy=None):
    img_path = img_dir / img_name

    def is_image_content(content, content_type=''):
        """判断响应/缓存内容是否为常见图片格式，避免把网页保存成图片。"""
        content_type = content_type.lower().split(';', 1)[0].strip()
        if content_type.startswith('image/'):
            return True
        return (
            content.startswith(b'\x89PNG\r\n\x1a\n')
            or content.startswith((b'GIF87a', b'GIF89a'))
            or content.startswith(b'\xff\xd8\xff')
            or (content.startswith(b'RIFF') and content[8:12] == b'WEBP')
            or content.startswith(b'BM')
            or content.startswith((b'II*\x00', b'MM\x00*'))
            or content.lstrip().startswith(b'<svg')
        )

    # 旧版本可能已经把 GitHub 的 HTML 页面缓存成了 .jpg/.png；只有确认是图片时才复用缓存。
    if img_path.exists():
        try:
            cached_content = img_path.read_bytes()
        except OSError:
            cached_content = b''
        if is_image_content(cached_content):
            return str(img_path)
    if img_url is None:
        return None

    # GitHub 的 /blob/ 地址返回的是 HTML 文件展示页，不是图片本体。
    # 将 https://github.com/owner/repo/blob/ref/path 转换为 raw 地址。
    parsed_url = urlsplit(img_url)
    path_parts = [part for part in parsed_url.path.split('/') if part]
    if parsed_url.hostname in {'github.com', 'www.github.com'} and 'blob' in path_parts:
        blob_index = path_parts.index('blob')
        if blob_index >= 2 and blob_index + 1 < len(path_parts):
            raw_path = '/' + '/'.join(
                path_parts[:blob_index] + path_parts[blob_index + 1:]
            )
            img_url = urlunsplit(
                (parsed_url.scheme, 'raw.githubusercontent.com', raw_path,
                 parsed_url.query, parsed_url.fragment)
            )

    #print(img_url)
    try:
        async with httpx.AsyncClient(
            proxy=proxy,
            follow_redirects=True,
        ) as client:
            response = await client.get(img_url)
            response.raise_for_status()
    except httpx.HTTPError:
        return None

    if not is_image_content(
        response.content,
        response.headers.get('content-type', ''),
    ):
        return None

    # 覆盖可能由旧版本留下的 HTML 缓存。
    try:
        img_path.write_bytes(response.content)
    except OSError:
        return None
    return str(img_path)

#获取日期数据
async def date_get():
    current_date = datetime.now()
    timestamp = int(current_date.timestamp())
    current_year = current_date.year
    current_month = current_date.month
    current_day = current_date.day
    day = f'{current_year}_{current_month}_{current_day}'
    month = f'{current_year}_{current_month}'
    year = f'{current_year}'
    return_json = {'day':day, 'month':month, 'year':year,'today':current_date,'time':timestamp}
    return return_json
#初始化用户数据
async def data_init(userid,day_info=None):
    user_info = await db.read_user(userid)
    if day_info is None:day_info = await date_get()
    user_info.setdefault('pig_hub', {})
    user_info['pig_hub'].setdefault('day', [])
    for key in ['info', 'img_info']:
        user_info['pig_hub'].setdefault(key, {})
    return user_info['pig_hub']

async def pig_hub_random(userid, day_info=None, is_save=True):
    global pig_data_cache
    return_info = {'status':True, 'img_info':{}}
    if not pig_data_cache:
        return_info = {'status': False, 'msg':'猪圈空荡荡...'}
        return return_info
    if day_info is None: day_info = await date_get()
    user_info = await data_init(userid,day_info)
    #pprint.pprint(user_info)
    if day_info['day'] in user_info['img_info']:
        return_info['img_info'] = user_info['img_info'][day_info['day']]
        return return_info
    pig_hub_info = random.choice(pig_data_cache)
    img_path = await pig_hub_img_get(pig_hub_info['filename'])
    if img_path is None:
        img_path = await pig_hub_img_get(f"{pig_hub_info['id']}.png",
                                         f"https://github.com/BadFish-HSrui/PigHub-DB/blob/master/data/{pig_hub_info['filename']}",)
    if img_path is None:
        return_info = {'status': False, 'msg': '猪猪获取失败了喵'}
        return return_info
    user_info['img_info'][day_info['day']] = pig_hub_info
    if is_save:
        await db.write_user(userid, {f'pig_hub': user_info})
    return_info['img_info'] = pig_hub_info
    #pprint.pprint(pig_hub_info)
    return return_info

async def pig_random(proxy=None):
    global pig_hub_data_cache
    if not pig_hub_data_cache or 'images' not in pig_hub_data_cache:
        await pig_hub_update()
        if not pig_hub_data_cache or 'images' not in pig_hub_data_cache:
            return_info = {'status': False, 'msg':'猪圈空荡荡...'}
            return return_info
    #pprint.pprint(pig_hub_data_cache)
    pig_hub_info = random.choice(pig_hub_data_cache['images'])
    #pprint.pprint(pig_hub_info)
    img_path = await pig_hub_img_get(pig_hub_info['filename'], f"https://github.com/BadFish-HSrui/PigHub-DB/blob/master{pig_hub_info['thumbnail']}",proxy)
    #img_path = await pig_hub_img_get(pig_hub_info['filename'], f"https://pighub.top{pig_hub_info['thumbnail']}")
    if img_path is None:
        return_info = {'status': False, 'msg': '猪猪获取失败了喵'}
        return return_info
    manshuo_draw_list = []
    return_info = {'status': True, 'img_path': img_path, 'manshuo_draw_list':manshuo_draw_list}
    return return_info

async def pig_hub_random_img(userid, day_info=None, is_save=True):
    if day_info is None: day_info = await date_get()
    pig_info = await pig_hub_random(userid,day_info,is_save)
    if pig_info['status'] is True:
        pig_img_path = str(img_dir / f"{pig_info['img_info']['filename']}")
        manshuo_draw_list = [
        {'type': 'basic_set', 'img_width': 900, 'img_name_save': f"today_{pig_info['img_info']['id']}.png"},
        {'type': 'img', 'subtype': 'common_with_des_right','img': [pig_img_path],
         'content': [f"[title]{pig_info['img_info']['name']}[/title]\n{pig_info['img_info']['description']}\n{pig_info['img_info']['analysis']}"]},
        ]
        img_path = await manshuo_draw(manshuo_draw_list)
        #print(img_path)
        pig_info['img_path'] = img_path
    return pig_info

async def test():
    id = 1270858643
    info = await pig_hub_random_img(id,is_save=False)
    #info = await pig_random("http://127.0.0.1:20172")
    pprint.pprint(info)

if __name__ == '__main__':
    asyncio.run(test())
