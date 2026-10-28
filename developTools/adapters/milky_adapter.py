# developTools/adapters/milky_adapter.py
# Milky Protocol 1.3 Adapter for Eridanus
import asyncio
import json
import os
import sys
import time
import uuid
from typing import Type, Union, Dict, Optional, List, Any

import httpx
import websockets

from developTools.event.base import EventBase
from developTools.event.eventFactory import EventFactory
from developTools.event.events import (
    GroupMessageEvent,
    PrivateMessageEvent,
    LifecycleMetaEvent,
    NoticeEvent,
    GroupRecallNoticeEvent,
    FriendRecallNoticeEvent,
    PokeNotifyEvent,
    GroupIncreaseNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupBanNoticeEvent,
    GroupAdminNoticeEvent,
)
from developTools.message.message_chain import MessageChain
from developTools.message.message_components import MessageComponent, Text, Reply, Node, File, Image, Face, At
from developTools.utils.logger import get_logger
from framework_common.utils.utils import convert_list_to_type


class EventBus:
    def __init__(self, handler_timeout_warning: float = 10.0, enable_monitoring: bool = True) -> None:
        self.handlers: dict[Type[EventBase], set] = {}
        self.handler_timeout_warning = handler_timeout_warning
        self.enable_monitoring = enable_monitoring
        self.logger = get_logger() if enable_monitoring else None
        self._handler_info_cache: Dict[Any, str] = {}

    def subscribe(self, event: Type[EventBase], handler):
        if event not in self.handlers:
            self.handlers[event] = set()
        self.handlers[event].add(handler)

    def on(self, event: Type[EventBase]):
        def decorator(func):
            self.subscribe(event, func)
            return func
        return decorator

    def set_handler_timeout_warning(self, timeout: float):
        self.handler_timeout_warning = timeout
        if self.logger:
            self.logger.info_msg(f"Handler超时警告阈值已设置为: {timeout}秒")

    def toggle_monitoring(self, enabled: bool):
        self.enable_monitoring = enabled
        if enabled and self.logger is None:
            self.logger = get_logger()

    async def emit(self, event_instance: EventBase) -> None:
        event_type = type(event_instance)
        if handlers := self.handlers.get(event_type):
            for handler in handlers:
                task = asyncio.create_task(handler(event_instance))
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


class MilkyAdapter:
    def __init__(
        self,
        api_url: str = "http://127.0.0.1:3001",
        event_ws_url: str = "ws://127.0.0.1:3001/event",
        access_token: str = "",
        config = None,
        blocked_loggers = None,
        enable_monitoring: bool = True,
        handler_timeout_warning: float = 10.0,
        **kwargs
    ):
        self.api_url = api_url.rstrip("/")
        self.event_ws_url = event_ws_url
        self.access_token = access_token or ""
        self.config = config
        self.id = 1000000
        self.is_secondary = False

        self.logger = get_logger(blocked_loggers=blocked_loggers)
        self.event_bus = EventBus(handler_timeout_warning=handler_timeout_warning, enable_monitoring=enable_monitoring)

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._message_queue = asyncio.Queue()
        self.receive_task: Optional[asyncio.Task] = None
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False

        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        # 显式关闭环境变量代理，直连本机 localhost/127.0.0.1
        self._http_client = httpx.AsyncClient(headers=headers, timeout=30.0, trust_env=False)

    def on(self, event: Type[EventBase]):
        return self.event_bus.on(event)

    async def _call_api(self, action: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        endpoint = action
        if action == "send_group_msg":
            endpoint = "send_group_message"
            if "group_id" in params:
                params["group_id"] = int(params["group_id"])
        elif action == "send_private_msg":
            endpoint = "send_private_message"
            if "user_id" in params:
                params["user_id"] = int(params["user_id"])
        elif action == "delete_msg":
            if "group_id" in params:
                endpoint = "recall_group_message"
            elif "user_id" in params:
                endpoint = "recall_private_message"
            else:
                endpoint = "recall_group_message"
            if "message_id" in params and "message_seq" not in params:
                params["message_seq"] = int(params["message_id"])

        url = f"{self.api_url}/api/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            resp = await self._http_client.post(url, json=params)
            if resp.status_code == 200:
                data = resp.json()
                return data
            else:
                self.logger.error(f"Milky API [{endpoint}] HTTP 状态码: {resp.status_code}, 内容: {resp.text}")
                return {"status": "failed", "retcode": resp.status_code, "data": None, "msg": resp.text}
        except Exception as e:
            self.logger.error(f"Milky API [{endpoint}] 调用失败: {e}")
            return {"status": "failed", "retcode": -1, "data": None, "msg": str(e)}

    @staticmethod
    def onebot_to_milky_segments(onebot_segments: list) -> list:
        milky_segs = []
        for seg in onebot_segments:
            if isinstance(seg, dict):
                stype = seg.get("type", "text")
                sdata = seg.get("data", {})
            elif hasattr(seg, "comp_type"):
                stype = seg.comp_type
                sdata = {}
                for k, v in seg:
                    if k not in ["comp_type"]:
                        sdata[k] = v
            else:
                stype = "text"
                sdata = {"text": str(seg)}

            if stype == "text":
                milky_segs.append({"type": "text", "data": {"text": str(sdata.get("text", ""))}})
            elif stype in ["mention", "at"]:
                qq = str(sdata.get("qq", sdata.get("user_id", "")))
                if qq == "all":
                    milky_segs.append({"type": "mention_all", "data": {}})
                else:
                    milky_segs.append({"type": "mention", "data": {"user_id": int(qq)}})
            elif stype == "face":
                face_id = sdata.get("id", 0)
                milky_segs.append({"type": "face", "data": {"face_id": str(face_id)}})
            elif stype in ["image", "mface"]:
                uri = sdata.get("url") or sdata.get("file") or ""
                milky_segs.append({"type": "image", "data": {"uri": uri}})
            elif stype == "record":
                uri = sdata.get("url") or sdata.get("file") or ""
                milky_segs.append({"type": "record", "data": {"uri": uri}})
            elif stype == "reply":
                seq = sdata.get("id", 0)
                milky_segs.append({"type": "reply", "data": {"message_seq": int(seq)}})
            else:
                milky_segs.append({"type": stype, "data": sdata})
        return milky_segs

    @staticmethod
    def milky_to_onebot_segments(milky_segments: list) -> list:
        ob_segs = []
        for seg in milky_segments:
            stype = seg.get("type", "text")
            sdata = seg.get("data", {})
            if stype == "text":
                ob_segs.append({"type": "text", "data": {"text": sdata.get("text", "")}})
            elif stype == "mention":
                ob_segs.append({"type": "at", "data": {"qq": str(sdata.get("user_id", ""))}})
            elif stype == "mention_all":
                ob_segs.append({"type": "at", "data": {"qq": "all"}})
            elif stype == "face":
                ob_segs.append({"type": "face", "data": {"id": str(sdata.get("face_id", ""))}})
            elif stype == "image":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({
                    "type": "image",
                    "data": {
                        "file": uri,
                        "url": uri,
                        "summary": sdata.get("summary", ""),
                        "sub_type": sdata.get("sub_type", "normal")
                    }
                })
            elif stype == "record":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({"type": "record", "data": {"file": uri, "url": uri}})
            elif stype == "video":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({"type": "video", "data": {"file": uri, "url": uri}})
            elif stype == "reply":
                ob_segs.append({"type": "reply", "data": {"id": sdata.get("message_seq", 0)}})
            elif stype == "market_face":
                ob_segs.append({
                    "type": "mface",
                    "data": {
                        "summary": sdata.get("face_name", ""),
                        "url": "",
                        "emoji_id": str(sdata.get("face_id", "")),
                        "emoji_package_id": str(sdata.get("package_id", ""))
                    }
                })
            else:
                ob_segs.append({"type": stype, "data": sdata})
        return ob_segs

    async def _dispatch_milky_event(self, data: dict):
        event_type = data.get("event_type", "")
        event_data = data.get("data", {})
        event_time = data.get("time", int(time.time()))

        ob_event_dict = None

        if event_type == "message_receive":
            sender_info = event_data.get("sender", {})
            milky_segments = event_data.get("segments", [])
            ob_message = self.milky_to_onebot_segments(milky_segments)

            raw_msg = "".join([
                s.get("data", {}).get("text", "") if s.get("type") == "text"
                else f"[CQ:{s.get('type')}]" for s in ob_message
            ])

            user_id = int(sender_info.get("user_id", 0))
            message_seq = int(event_data.get("message_seq", 0))

            sender_dict = {
                "user_id": user_id,
                "nickname": sender_info.get("nickname", ""),
                "card": sender_info.get("card", ""),
                "role": sender_info.get("role", "member"),
                "title": sender_info.get("title", ""),
            }

            if "group_id" in event_data:
                group_id = int(event_data.get("group_id"))
                ob_event_dict = {
                    "post_type": "message",
                    "message_type": "group",
                    "sub_type": "normal",
                    "message_id": message_seq,
                    "group_id": group_id,
                    "user_id": user_id,
                    "message": ob_message,
                    "raw_message": raw_msg,
                    "font": 0,
                    "sender": sender_dict,
                    "time": event_time,
                    "adapter_source": "milky",
                }
            else:
                ob_event_dict = {
                    "post_type": "message",
                    "message_type": "private",
                    "sub_type": "friend",
                    "message_id": message_seq,
                    "user_id": user_id,
                    "message": ob_message,
                    "raw_message": raw_msg,
                    "font": 0,
                    "sender": sender_dict,
                    "time": event_time,
                    "adapter_source": "milky",
                }

        elif event_type == "group_message_recall":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_recall",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("author_id", 0)),
                "operator_id": int(event_data.get("operator_id", 0)),
                "message_id": int(event_data.get("message_seq", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "friend_message_recall":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": int(event_data.get("user_id", 0)),
                "message_id": int(event_data.get("message_seq", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type in ["group_nudge", "friend_nudge"]:
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "sender_id": int(event_data.get("sender_id", 0)),
                "user_id": int(event_data.get("sender_id", 0)),
                "target_id": int(event_data.get("target_id", 0)),
                "group_id": int(event_data.get("group_id", 0)) if "group_id" in event_data else None,
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "group_member_increase":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_increase",
                "sub_type": "approve",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("user_id", 0)),
                "operator_id": int(event_data.get("operator_id", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "group_member_decrease":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_decrease",
                "sub_type": "leave",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("user_id", 0)),
                "operator_id": int(event_data.get("operator_id", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        if not ob_event_dict:
            self.logger.debug(f"Milky 未处理事件类型: {event_type}")
            return

        event_obj = EventFactory.create_event(ob_event_dict)
        if not event_obj:
            self.logger.warning(f"无法解析事件类型: {ob_event_dict}")
            return

        if self.config and hasattr(self.config, "common_config"):
            cfg = self.config.common_config
            basic = cfg.basic_config
            if hasattr(event_obj, "group_id") and event_obj.group_id is not None:
                grp_logic = basic.get("group_handle_logic", "blacklist")
                censor_grp = cfg.censor_group.get(grp_logic, [])
                if grp_logic == "blacklist" and event_obj.group_id in censor_grp:
                    self.logger.info(f"群 {event_obj.group_id} 在黑名单中，跳过处理。")
                    return
                elif grp_logic == "whitelist" and event_obj.group_id not in censor_grp:
                    self.logger.info(f"群 {event_obj.group_id} 不在白名单中，跳过处理。")
                    return

            if hasattr(event_obj, "user_id") and event_obj.user_id is not None:
                usr_logic = basic.get("user_handle_logic", "blacklist")
                censor_usr = convert_list_to_type(cfg.censor_user.get(usr_logic, []))
                if usr_logic == "blacklist" and event_obj.user_id in censor_usr:
                    self.logger.info(f"用户 {event_obj.user_id} 在黑名单中，跳过处理。")
                    return
                elif usr_logic == "whitelist" and event_obj.user_id not in censor_usr:
                    self.logger.info(f"用户 {event_obj.user_id} 不在白名单中，跳过处理。")
                    return

        asyncio.create_task(self.event_bus.emit(event_obj))

    async def _receive(self):
        try:
            async for raw in self.websocket:
                await self._message_queue.put(raw)
        except websockets.exceptions.ConnectionClosedError as e:
            self.logger.warning(f"Milky Event WebSocket 连接关闭: {e}")
            if self._running:
                self.logger.warning("5秒后重试连接 Milky Event WS...")
                await asyncio.sleep(5)
                await self._connect_and_run()
        except Exception as e:
            self.logger.error(f"Milky Event WS 接收异常: {e}", exc_info=True)

    async def _process_messages(self):
        while self._running:
            try:
                raw = await self._message_queue.get()
                data = json.loads(raw)
                await self._dispatch_milky_event(data)
                self._message_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"处理 Milky 事件发生异常: {e}", exc_info=True)

    async def _connect(self):
        try:
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            import inspect
            sig = inspect.signature(websockets.connect)
            conn_kwargs = {"max_size": None}
            if "additional_headers" in sig.parameters:
                if headers:
                    conn_kwargs["additional_headers"] = headers
            else:
                if headers:
                    conn_kwargs["extra_headers"] = list(headers.items())
            self.websocket = await websockets.connect(
                self.event_ws_url,
                **conn_kwargs
            )
            self.logger.info_msg("Milky Event WebSocket 连接已建立")
        except Exception as e:
            self.logger.error(f"Milky Event WebSocket 连接错误: {e}")
            if self._running:
                self.logger.warning("5秒后重试连接...")
                await asyncio.sleep(5)
                await self._connect_and_run()

    async def _connect_and_run(self):
        self._running = True

        try:
            info = await self._call_api("get_login_info")
            if info.get("status") == "ok" and "data" in info:
                self.id = int(info["data"].get("uin", self.id))
                self.logger.info(f"Milky 连接成功，当前登录 UIN: {self.id}, 昵称: {info['data'].get('nickname', '')}")
                meta_event = LifecycleMetaEvent(
                    time=int(time.time()),
                    sender=self.id,
                    post_type="meta_event",
                    meta_event_type="lifecycle",
                    sub_type="connect"
                )
                asyncio.create_task(self.event_bus.emit(meta_event))
        except Exception as e:
            self.logger.warning(f"获取 Milky 登录信息失败: {e}")

        await self._connect()
        if self.websocket:
            self.receive_task = asyncio.create_task(self._receive())
            self._processing_task = asyncio.create_task(self._process_messages())
            try:
                await self.receive_task
            except Exception as e:
                self.logger.error(f"Milky 接收任务退出: {e}")
            finally:
                if self._processing_task and not self._processing_task.done():
                    self._processing_task.cancel()

    async def send(self, event: EventBase, components: Union[str, list], Quote: bool = False):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if Quote and hasattr(event, "message_id"):
            components.insert(0, Reply(id=event.message_id))

        if hasattr(event, "group_id") and event.group_id:
            return await self.send_group_message(event.group_id, components)
        elif hasattr(event, "user_id") and event.user_id:
            return await self.send_friend_message(event.user_id, components)
        else:
            self.logger.error(f"无法推断目标发送目标: {event}")

    async def send_group_message(self, group_id: int, components: Union[str, list]):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if components and isinstance(components[0], Node):
            return await self.send_group_forward_msg(group_id, components)

        milky_segs = self.onebot_to_milky_segments(components)
        params = {
            "group_id": int(group_id),
            "message": milky_segs
        }
        res = await self._call_api("send_group_message", params)
        if res.get("status") == "ok" and "data" in res:
            res["data"] = {"message_id": res["data"].get("message_seq", 0)}
        return res

    async def send_friend_message(self, user_id: int, components: Union[str, list]):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if components and isinstance(components[0], Node):
            return await self.send_private_forward_msg(user_id, components)

        milky_segs = self.onebot_to_milky_segments(components)
        params = {
            "user_id": int(user_id),
            "message": milky_segs
        }
        res = await self._call_api("send_private_message", params)
        if res.get("status") == "ok" and "data" in res:
            res["data"] = {"message_id": res["data"].get("message_seq", 0)}
        return res

    async def send_to_server(self, event: EventBase, message: Union[MessageChain, dict]):
        if isinstance(message, MessageChain):
            comps = list(message)
        elif isinstance(message, list):
            comps = message
        else:
            comps = [message]

        if hasattr(event, "group_id") and event.group_id:
            return await self.send_group_message(event.group_id, comps)
        elif hasattr(event, "user_id") and event.user_id:
            return await self.send_friend_message(event.user_id, comps)

    async def recall(self, message_id: int, group_id: Optional[int] = None, user_id: Optional[int] = None):
        params = {"message_seq": int(message_id)}
        if group_id:
            params["group_id"] = int(group_id)
            return await self._call_api("recall_group_message", params)
        elif user_id:
            params["user_id"] = int(user_id)
            return await self._call_api("recall_private_message", params)
        else:
            return await self._call_api("recall_group_message", params)

    async def get_login_info(self):
        return await self._call_api("get_login_info")

    async def get_status(self):
        info = await self.get_login_info()
        is_ok = info.get("status") == "ok"
        return {
            "status": "ok",
            "retcode": 0,
            "data": {
                "online": is_ok,
                "good": is_ok,
                "user_id": self.id
            }
        }

    async def get_friend_list(self):
        res = await self._call_api("get_friend_list")
        if res.get("status") == "ok" and "data" in res:
            friends = res["data"].get("friends", [])
            return {"status": "ok", "retcode": 0, "data": friends}
        return res

    async def get_group_list(self):
        res = await self._call_api("get_group_list")
        if res.get("status") == "ok" and "data" in res:
            groups = res["data"].get("groups", [])
            return {"status": "ok", "retcode": 0, "data": groups}
        return res

    async def get_group_info(self, group_id: int, no_cache: bool = False):
        res = await self._call_api("get_group_info", {"group_id": int(group_id)})
        if res.get("status") == "ok" and "data" in res and "group" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["group"]}
        return res

    async def get_group_member_list(self, group_id: int):
        res = await self._call_api("get_group_member_list", {"group_id": int(group_id)})
        if res.get("status") == "ok" and "data" in res and "members" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["members"]}
        return res

    async def get_group_member_info(self, group_id: int, user_id: int, no_cache: bool = False):
        res = await self._call_api("get_group_member_info", {"group_id": int(group_id), "user_id": int(user_id)})
        if res.get("status") == "ok" and "data" in res and "member" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["member"]}
        return res

    async def mute(self, group_id: int, user_id: int, duration: int = 1800):
        return await self._call_api("set_group_member_mute", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "duration": int(duration)
        })

    async def set_group_whole_ban(self, group_id: int, enable: bool = True):
        return await self._call_api("set_group_mute", {
            "group_id": int(group_id),
            "mute": enable
        })

    async def set_group_card(self, group_id: int, user_id: int, card: str = ""):
        return await self._call_api("set_group_member_card", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "card": card
        })

    async def set_group_name(self, group_id: int, group_name: str):
        return await self._call_api("set_group_name", {
            "group_id": int(group_id),
            "name": group_name
        })

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False):
        return await self._call_api("kick_group_member", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "reject_add_request": reject_add_request
        })

    async def quit(self, group_id: int):
        return await self._call_api("leave_group", {"group_id": int(group_id)})

    async def group_poke(self, group_id: int, user_id: int):
        return await self._call_api("send_group_nudge", {
            "group_id": int(group_id),
            "user_id": int(user_id)
        })

    async def friend_poke(self, user_id: int):
        return await self._call_api("send_friend_nudge", {"user_id": int(user_id)})

    async def send_group_forward_msg(self, group_id: int, components: Union[str, list]):
        self.logger.warning("Milky 暂不直接支持合并转发，降级处理")
        return await self.send_group_message(group_id, components)

    async def send_private_forward_msg(self, user_id: int, components: Union[str, list]):
        self.logger.warning("Milky 暂不直接支持私聊合并转发，降级处理")
        return await self.send_friend_message(user_id, components)

    async def get_msg(self, message_id: int):
        return None

    async def close(self):
        self._running = False
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
        if hasattr(self, '_http_client') and self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass

    async def aclose(self):
        await self.close()
