import asyncio
import base64
import json
import random
from concurrent.futures import ThreadPoolExecutor

import httpx
from developTools.event.events import GroupMessageEvent
from framework_common.database_util.llmDB import use_folder_chara
from run.mai_reply.service.simple_chat import simplified_chat
from run.character_detection.func_collection import operate_group_censor


def main(bot, config):
    sets = getattr(config.character_detection, "config", {}).get("抽象检测", {})

    # 1. 检查各子服务开关
    if_nailong = sets.get("奶龙检测", False)
    if_doro = sets.get("doro检测", False)
    if_nanniang = sets.get("男娘检测", False)
    if_deepseek = sets.get("deepseek检测", False)

    # 注册命令监听（加白名单/移出白名单）
    @bot.on(GroupMessageEvent)
    async def command_handler(event):
        text = (event.pure_text or "").strip()
        prefixes = [
            "/开启奶龙审核", "/关闭奶龙审核",
            "/开启doro审核", "/关闭doro审核",
            "/开启男娘审核", "/关闭男娘审核",
            "/开启deepseek审核", "/关闭deepseek审核"
        ]
        for p in prefixes:
            if text.startswith(p):
                parts = text.split(" ")
                if len(parts) > 1:
                    target_id = parts[1]
                    await operate_group_censor(bot, event, config, target_id, p[1:])
                return

    # 若所有检测均未开启，直接返回，绝不预加载torch等重型依赖
    if not (if_nailong or if_doro or if_nanniang or if_deepseek):
        bot.logger.info("Character Detection: 所有图片审核服务均未开启，不加载模型与重依赖。")
        return

    # 2. 如果开启了任意服务，通过 install_and_import 安全导入依赖
    from framework_common.utils.install_and_import import install_and_import
    install_and_import("torch")
    install_and_import("torchvision")
    install_and_import("PIL", "PIL")

    # 延迟导入服务模块
    service_funcs = {}
    if if_nailong:
        from run.character_detection.service.nailong11.nailong import main as nailong_main
        service_funcs["nailong"] = nailong_main
    if if_doro:
        from run.character_detection.service.doro.doro import main as doro_main
        service_funcs["doro"] = doro_main
    if if_nanniang:
        from run.character_detection.service.nanniang.nn import main as nn_main
        service_funcs["nanniang"] = nn_main
    if if_deepseek:
        from run.character_detection.service.deepseek.deepseek import main as deepseek_main
        service_funcs["deepseek"] = deepseek_main

    # 读取群白名单（安全处理各种类型）
    def get_whitelist(name):
        val = getattr(config.character_detection, name, None)
        if isinstance(val, dict):
            return val.get("whitelist", [])
        return []

    nailong_groups = get_whitelist("nailong")
    doro_groups = get_whitelist("doro")
    nanniang_groups = get_whitelist("nanniang")
    deepseek_groups = get_whitelist("deepseek")

    # 读取惩罚与回复配置
    action_config = {
        "nailong": {
            "recall": sets.get("奶龙撤回", True),
            "mute": sets.get("奶龙禁言", True),
            "attack": sets.get("骂奶龙", ["奶龙是你爹？这么喜欢发奶龙？"]),
            "tag": "奶龙",
            "prompt": "奶龙的图片,这是一张很唐的图，对其进行攻击"
        },
        "doro": {
            "recall": sets.get("doro撤回", True),
            "mute": sets.get("doro禁言", True),
            "attack": sets.get("骂doro", ["唐", "粉色奶龙"]),
            "tag": "doro",
            "prompt": "doro的图片,这是一张很唐(愚蠢引人不适)的图，对其进行攻击"
        },
        "nanniang": {
            "recall": sets.get("男娘撤回", True),
            "mute": sets.get("男娘禁言", True),
            "attack": sets.get("骂男娘", ["发男娘图给你超市"]),
            "tag": "男娘",
            "prompt": "男娘图，对其进行攻击"
        },
        "deepseek": {
            "recall": sets.get("deepseek撤回", True),
            "mute": sets.get("deepseek禁言", True),
            "attack": sets.get("骂deepseek", ["正在思考... 深度思考完毕：请勿发送鲸鱼娘！"]),
            "tag": "deepseek鲸鱼娘",
            "prompt": "deepseek拟人鲸鱼娘的图片，对其进行调侃和攻击"
        }
    }

    # 3. 异步任务队列与工作协程（限制CPU单并发/低并发）
    # 避免过去来一个图片开一个线程跑ResNet直接占满CPU
    task_queue = asyncio.Queue(maxsize=30)
    cpu_executor = ThreadPoolExecutor(max_workers=1)
    worker_started = False

    async def download_image_b64(url: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return base64.b64encode(res.content).decode("utf-8")
        except Exception as e:
            bot.logger.warning(f"Character Detection: 下载待审核图片失败: {e}")
        return None

    async def execute_penalty(target_type: str, event):
        cfg = action_config[target_type]
        # 1. 撤回
        if cfg["recall"]:
            try:
                msg_json = event.json()
                event_dict = json.loads(msg_json) if isinstance(msg_json, str) else msg_json
                source_id = event_dict.get("message_id")
                if source_id:
                    await bot.recall(source_id)
            except Exception as e:
                bot.logger.warning(f"Character Detection: 撤回消息失败: {e}")

        # 2. 回复/攻击
        try:
            # 使用新版 mai_reply 的简易对话接口；配置统一从 mai_reply 配置读取。
            mai_reply = getattr(config, "mai_reply", None)
            mai_cfg = getattr(mai_reply, "config", {}) if mai_reply else {}
            if not isinstance(mai_cfg, dict):
                mai_cfg = {}
            trigger_cfg = mai_cfg.get("trigger_llm", {}) or {}
            use_ai = bool(mai_cfg.get("enable", False) and trigger_cfg.get("enable", True))
            # trigger_llm 优先；未单独配置时回退到 mai_reply.llm.openai。
            llm_cfg = mai_cfg.get("llm", {}) or {}
            openai_cfg = llm_cfg.get("openai", {}) or {}
            keys = openai_cfg.get("api_keys", []) or []
            api_key = trigger_cfg.get("api_key") or (keys[0] if keys else "")
            base_url = trigger_cfg.get("base_url") or openai_cfg.get("base_url", "")
            model = trigger_cfg.get("model") or openai_cfg.get("model", "")
            if use_ai and base_url and model and api_key:
                data = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
                name = data.get("data", {}).get("nickname", "该用户")
                system_instruction = await use_folder_chara("喷子.txt")
                reply = await simplified_chat(
                    base_url=base_url,
                    prompt=f"系统提示：{name}刚刚发送了一张{cfg['prompt']}，你很不喜欢{cfg['prompt']}",
                    model=model,
                    api_key=api_key,
                    system_prompt=system_instruction or "",
                )
                await bot.send(event, reply, True)
            else:
                await bot.send(event, random.choice(cfg["attack"]), True)
        except Exception:
            await bot.send(event, random.choice(cfg["attack"]), True)

        # 3. 禁言
        if cfg["mute"]:
            try:
                await bot.mute(event.group_id, event.sender.user_id, 60)
            except Exception as e:
                bot.logger.warning(f"Character Detection: 禁言用户失败: {e}")

    async def detection_worker():
        loop = asyncio.get_running_loop()
        while True:
            item = await task_queue.get()
            try:
                event, img_url, enabled_types = item
                b64_img = await download_image_b64(img_url)
                if not b64_img:
                    continue

                for t in enabled_types:
                    func = service_funcs.get(t)
                    if not func:
                        continue
                    # 将CPU密集型ResNet推送到单worker线程池，避免卡死主异步事件循环
                    is_detected = await loop.run_in_executor(cpu_executor, func, b64_img)
                    if is_detected == 1:
                        bot.logger.info(f"Character Detection: 命中 {action_config[t]['tag']} (群: {event.group_id})")
                        await execute_penalty(t, event)
                        break
            except Exception as e:
                bot.logger.error(f"Character Detection worker 出错: {e}")
            finally:
                task_queue.task_done()

    def ensure_worker_started():
        nonlocal worker_started
        if not worker_started:
            try:
                asyncio.create_task(detection_worker())
                worker_started = True
            except RuntimeError:
                pass

    # 4. 消息监听器：仅收集并放入队列，毫秒级返回
    @bot.on(GroupMessageEvent)
    async def image_listener(event):
        ensure_worker_started()
        images = event.get("image")
        if not images:
            return

        gid = event.group_id
        # 判断当前群开启了哪些类型的审核
        enabled_types = []
        if if_nailong and gid in nailong_groups:
            enabled_types.append("nailong")
        if if_doro and gid in doro_groups:
            enabled_types.append("doro")
        if if_nanniang and (gid in nanniang_groups or event.user_id == 1270858640):
            enabled_types.append("nanniang")
        if if_deepseek and gid in deepseek_groups:
            enabled_types.append("deepseek")

        if not enabled_types:
            return

        # 获取首张图片URL投入队列
        img_url = images[0].get("url")
        if img_url:
            if task_queue.full():
                try:
                    task_queue.get_nowait()
                    task_queue.task_done()
                except Exception:
                    pass
            await task_queue.put((event, img_url, enabled_types))

    bot.logger.info("Character Detection: 图片审核服务及任务调度队列加载完成。")
