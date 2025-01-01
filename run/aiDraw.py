import asyncio
import base64
from io import BytesIO

import httpx
from bs4 import BeautifulSoup

from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Image, Node, Text
from plugins.aiDraw.setu_moderate import pic_audit_standalone
from plugins.utils.random_str import random_str
from plugins.aiDraw.aiDraw import  n4, n3, SdDraw0, SdreDraw, getloras, getcheckpoints, ckpt2
from plugins.utils.utils import download_img, url_to_base64, parse_arguments

turn = 0
UserGet = {}
tag_user = {}
sd_user_args = {}
sd_re_args = {}
UserGet1 = {}
def main(bot,config):
    @bot.on(GroupMessageEvent)
    async def naiDraw4(event):
        if str(event.raw_message).startswith("n4 ") and config.controller["ai绘画"]["novel_ai画图"]:
            tag = str(event.raw_message).replace("n4 ", "")
            path = f"data/pictures/cache/{random_str()}.png"
            bot.logger.info(f"发起nai4绘画请求，path:{path}|prompt:{tag}")
            await bot.send(event, '正在进行nai4画图', True)

            async def attempt_draw(retries_left=50):  # 这里是递归请求的次数
                try:
                    p = await n4(tag, path, event.group_id, config)
                    if p == False:
                        bot.logger.info("色图已屏蔽")
                        await bot.send(event, "杂鱼，色图不给你喵~", True)
                    else:
                        print(p)
                        await bot.send(event, [Image(file=p)], True)
                except Exception as e:
                    bot.logger.error(e)
                    if retries_left > 0:
                        bot.logger.error(f"尝试重新请求nai4，剩余尝试次数：{retries_left - 1}")
                        await asyncio.sleep(0.1)  # 等待0.5秒
                        await attempt_draw(retries_left - 1)
                    else:
                        await bot.send(event, "nai只因了，联系master喵~")

            await attempt_draw()

    @bot.on(GroupMessageEvent)
    async def naiDraw3(event):
        if str(event.raw_message).startswith("n3 ") and config.controller["ai绘画"]["novel_ai画图"]:
            tag = str(event.raw_message).replace("n3 ", "")
            path = f"data/pictures/cache/{random_str()}.png"
            bot.logger.info(f"发起nai3绘画请求，path:{path}|prompt:{tag}")
            await bot.send(event, '正在进行nai3画图', True)

            async def attempt_draw(retries_left=10):  # 这里是递归请求的次数
                try:
                    p = await n3(tag, path, event.group_id, config)
                    if p == False:
                        bot.logger.info("色图已屏蔽")
                        await bot.send(event, "杂鱼，色图不给你喵~", True)
                    else:
                        await bot.send(event, [Image(file=p)], True)
                except Exception as e:
                    bot.logger.error(e)
                    if retries_left > 0:
                        bot.logger.error(f"尝试重新请求nai3，剩余尝试次数：{retries_left - 1}")
                        await asyncio.sleep(0.5)  # 等待0.5秒
                        await attempt_draw(retries_left - 1)
                    else:
                        await bot.send(event, "nai只因了，联系master喵~")

            await attempt_draw()

    @bot.on(GroupMessageEvent)
    async def db(event):
        if str(event.raw_message).startswith("dan "):
            tag = str(event.raw_message).replace("dan ", "")
            bot.logger.info(f"收到来自群{event.group_id}的请求，prompt:{tag}")
            limit = 3
            if config.api["proxy"]["http_proxy"] is not None:
                proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
            else:
                proxies = None

            db_base_url = "https://kagamihara.donmai.us"  # 这是反代，原来的是https://danbooru.donmai.us
            # 把danbooru换成sonohara、kagamihara、hijiribe这三个任意一个试试，后面的不用改

            build_msg = [Node(content=[Text(f"{tag}的搜索结果:")])]

            msg = tag
            try:
                async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
                    resp = await client.get(
                        f"{db_base_url}/autocomplete?search%5Bquery%5D={msg}&search%5Btype%5D=tag_query&version=1&limit={limit}",
                        follow_redirects=True,
                    )
                    resp.raise_for_status()  # 检查请求是否成功
                    bot.logger.info(f"Autocomplete request successful for tag: {tag}")
            except Exception as e:
                bot.logger.error(f"Failed to get autocomplete data for tag: {tag}. Error: {e}")
                return

            soup = BeautifulSoup(resp.text, 'html.parser')
            tags = soup.find_all('li', class_='ui-menu-item')

            data_values = []
            raw_data_values = []
            for tag in tags:
                data_value = tag['data-autocomplete-value']
                raw_data_values.append(data_value)
                data_value_space = data_value.replace('_', ' ')
                data_values.append(data_value_space)
                bot.logger.info(f"Found autocomplete tag: {data_value_space}")

            for tag in raw_data_values:
                tag1 = tag.replace('_', ' ')
                b1 = Node(content=[Text(f"({tag1}:1)")])
                build_msg.append(b1)
                formatted_tag = tag.replace(' ', '_').replace('(', '%28').replace(')', '%29')

                try:
                    async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
                        image_resp = await client.get(
                            f"{db_base_url}/posts?tags={formatted_tag}",
                            follow_redirects=True
                        )
                        image_resp.raise_for_status()  # 检查请求是否成功
                        bot.logger.info(f"Posts request successful for tag: {formatted_tag}")
                except Exception as e:
                    bot.logger.error(f"Failed to get posts for tag: {formatted_tag}. Error: {e}")
                    continue  # 继续处理下一个标签

                soup = BeautifulSoup(image_resp.text, 'html.parser')
                img_urls = [img['src'] for img in soup.find_all('img') if img['src'].startswith('http')][:2]
                bot.logger.info(f"Found {len(img_urls)} images for tag: {formatted_tag}")

                async def download_img1(image_url: str) -> (str, bytes):
                    try:
                        async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
                            response = await client.get(image_url)
                            response.raise_for_status()
                            content_type = response.headers.get('content-type', '').lower()
                            if not content_type.startswith('image/'):
                                raise ValueError(f"URL {image_url} does not point to an image.")
                            bytes_image = response.content

                            buffered = BytesIO(bytes_image)
                            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

                            bot.logger.info(f"Downloaded image from URL: {image_url}")
                            return base64_image, bytes_image

                    except httpx.RequestError as e:
                        bot.logger.error(f"Failed to download image from {image_url}: {e}")
                        raise
                    except Exception as e:
                        bot.logger.error(f"An error occurred while processing the image from {image_url}: {e}")
                        raise

                async def process_image(image_url):
                    try:
                        base64_image, bytes_image = await download_img1(image_url)
                        if event.group_id in config.controller["ai绘画"]["no_nsfw_groups"]:
                            audit_result = await pic_audit_standalone(base64_image, return_none=True,
                                                                      url=config.api["ai绘画"]["sd审核和反推api"])
                            if audit_result:
                                bot.logger.info(f"Image at URL {image_url} was flagged by audit: {audit_result}")
                                return Text("太涩了")
                        bot.logger.info(f"Image at URL {image_url} passed the audit")
                        path = f"data/pictures/cache/{random_str()}.png"
                        p = await download_img(image_url, path)
                        return Image(file=p)
                    except Exception as e:
                        bot.logger.error(f"Failed to process image at {image_url}: {e}")
                        return None

                async def process_images(img_urls):
                    tasks = [process_image(url) for url in img_urls]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # 过滤掉异常和 None 结果
                    filtered_results = [result for result in results if
                                        not isinstance(result, Exception) and result is not None]

                    # 创建 ForwardMessageNode 列表
                    forward_messages = [
                        Node(
                            content=[result]
                        )
                        for result in filtered_results
                    ]

                    bot.logger.info(f"Processed {len(filtered_results)} images for tag: {formatted_tag}")
                    return forward_messages

                results = await process_images(img_urls)
                build_msg.extend(results)

            try:
                await bot.send(event, build_msg)
                bot.logger.info("Successfully sent the compiled message to the group.")
            except Exception as e:
                bot.logger.error(f"Failed to send the compiled message to the group. Error: {e}")

    @bot.on(GroupMessageEvent)
    async def tagger(event):
        global tag_user

        if event.get('image') == None and (
                str(event.raw_message) == ("tag") or str(event.raw_message).startswith("tag ")):
            tag_user[event.sender.user_id] = []
            await bot.send(event, "请发送要识别的图片")

        # 处理图片和重绘命令
        if (str(event.raw_message).startswith("tag") or event.sender.user_id in tag_user) and event.get('image'):
            if (str(event.raw_message).startswith("tag")) and event.get('image'):
                tag_user[event.sender.user_id] = []

            # 日志记录
            bot.logger.info(f"接收来自群：{event.group_id} 用户：{event.sender.user_id} 的tag反推指令")

            # 获取图片路径
            path = f"data/pictures/cache/{random_str()}.png"
            img_url = event.get("image")[0]["url"]
            bot.logger.info(f"发起反推tag请求，path:{path}")
            tag_user.pop(event.sender.user_id)

            try:
                b64_in = await url_to_base64(img_url)
                await bot.send(event, "tag反推中", True)
                message, tags, tags_str = await pic_audit_standalone(b64_in, is_return_tags=True,
                                                                     url=config.api["ai绘画"]["sd审核和反推api"])
                tags_str = tags_str.replace("_", " ")
                await bot.send(event, Text(tags_str), True)
            except Exception as e:
                bot.logger.error(f"反推失败: {e}")
                await bot.send(event, "反推失败了喵~", True)

    @bot.on(GroupMessageEvent)
    async def sdsettings(event):
        if str(event.raw_message).startswith("setsd "):
            global sd_user_args
            command = str(event.raw_message).replace("setsd ", "")
            cmd_dict = parse_arguments(command)  # 不需要 await
            sd_user_args[event.sender.user_id] = cmd_dict
            await bot.send(event, f"当前绘画参数设置: {sd_user_args[event.sender.user_id]}", True)

    @bot.on(GroupMessageEvent)
    async def sdresettings(event):
        if str(event.raw_message).startswith("setre "):
            global sd_re_args
            command = str(event.raw_message).replace("setre ", "")
            cmd_dict = parse_arguments(command)  # 不需要 await
            sd_re_args[event.sender.user_id] = cmd_dict
            await bot.send(event, f"当前重绘参数设置: {sd_re_args[event.sender.user_id]}", True)

    @bot.on(GroupMessageEvent)
    async def sdreDrawRun(event):
        global UserGet
        global turn

        if event.get('image') == None and (
                str(event.raw_message) == ("重绘") or str(event.raw_message).startswith("重绘 ")):
            prompt = str(event.raw_message).replace("重绘", "").strip()
            UserGet[event.sender.user_id] = [prompt]
            await bot.send(event, "请发送要重绘的图片")

        # 处理图片和重绘命令
        if (str(event.raw_message).startswith("重绘") or event.sender.user_id in UserGet) and event.get('image'):
            if (str(event.raw_message).startswith("重绘")) and event.raw_message.count(Image):
                prompt = str(event.raw_message).replace("重绘", "").strip()
                UserGet[event.sender.user_id] = [prompt]

            # 日志记录
            prompts = ', '.join(UserGet[event.sender.user_id])
            bot.logger.info(f"接收来自群：{event.group_id} 用户：{event.sender.user_id} 的重绘指令 prompt: {prompts}")

            # 获取图片路径
            path = f"data/pictures/cache/{random_str()}.png"
            img_url = event.get("image")[0]["url"]
            bot.logger.info(f"发起SDai重绘请求，path:{path}|prompt:{prompts}")
            prompts_str = ' '.join(UserGet[event.sender.user_id]) + ' '
            UserGet.pop(event.sender.user_id)

            try:
                args = sd_re_args.get(event.sender.user_id, {})
                b64_in = await url_to_base64(img_url)

                await bot.send(event, f"开始重绘啦~sd前面排队{turn}人，请耐心等待喵~", True)
                turn += 1
                # 将 UserGet[event.sender.user_id] 列表中的内容和 positive_prompt 合并成一个字符串
                p = await SdreDraw(prompts_str, path, config, event.group_id, b64_in, args)
                if p == False:
                    turn -= 1
                    bot.logger.info("色图已屏蔽")
                    await bot.send(event, "杂鱼，色图不给你喵~", True)
                else:
                    turn -= 1
                    await bot.send(event, [Image(file=p)], True)
            except Exception as e:
                bot.logger.error(f"重绘失败: {e}")
                await bot.send(event, "重绘失败了喵~", True)

    @bot.on(GroupMessageEvent)
    async def AiSdDraw(event):
        global turn  # 画 中空格的意义在于防止误触发，但fluxDrawer无所谓了，其他倒是可以做一做限制。
        global sd_user_args
        if str(event.raw_message).startswith("画 ") and config.controller["ai绘画"]["sd画图"] and config.api["ai绘画"][
            "sdUrl"] != "":
            tag = str(event.raw_message).replace("画 ", "")
            path = f"data/pictures/cache/{random_str()}.png"
            bot.logger.info(f"发起SDai绘画请求，path:{path}|prompt:{tag}")
            try:
                await bot.send(event, f'sd前面排队{turn}人，请耐心等待喵~', True)
                turn += 1
                # 没啥好审的，controller直接自个写了。
                args = sd_user_args.get(event.sender.user_id, {})
                p = await SdDraw0(tag, path, config, event.group_id, args)
                # logger.error(str(p))
                if p == False:
                    turn -= 1
                    bot.logger.info("色图已屏蔽")
                    await bot.send(event, "杂鱼，色图不给你喵~", True)
                else:
                    turn -= 1
                    await bot.send(event, [Image(file=p)], True)
                    # logger.info("success")
                    # await bot.send(event, "防出色图加上rating_safe，如果色图请自行撤回喵~")
            except Exception as e:
                bot.logger.error(e)
                turn -= 1
                await bot.send(event, "sd只因了，联系master喵~")

        if str(event.raw_message) == "lora" and config.controller["ai绘画"]["sd画图"]:  # 获取lora列表
            bot.logger.info('查询loras中...')
            try:
                p = await getloras(config)
                bot.logger.info(str(p))
                await bot.send(event, p, True)
                # logger.info("success")
            except Exception as e:
                bot.logger.error(e)

        if str(event.raw_message) == "ckpt" and config.controller["ai绘画"]["sd画图"]:  # 获取lora列表
            bot.logger.info('查询checkpoints中...')
            try:
                p = await getcheckpoints(config)
                bot.logger.info(str(p))
                await bot.send(event, p, True)
                # logger.info("success")
            except Exception as e:
                bot.logger.error(e)

        if str(event.raw_message).startswith("ckpt2 ") and config.controller["ai绘画"]["sd画图"]:
            tag = str(event.raw_message).replace("ckpt2 ", "")
            bot.logger.info('切换ckpt中')
            try:
                await ckpt2(tag)
                await bot.send(event, "切换成功喵~第一次会慢一点~", True)
                # logger.info("success")
            except Exception as e:
                bot.logger.error(e)
                await bot.send(event, "ckpt切换失败", True)