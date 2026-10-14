import asyncio
import threading
from typing import Union, Optional, Iterable, Dict
from pydantic import BaseModel
from framework_common.manshuo_draw import *
from ..api import BaseGameSign
from ..api import BaseMission, get_missions_state
from ..api.common import genshin_note, get_game_record, starrail_note, zzz_note
from ..model import (MissionStatus, PluginDataManager, plugin_config, UserData, CommandUsage, GenshinNoteNotice,
                     StarRailNoteNotice)
import pprint
from developTools.utils.logger import get_logger
logger=get_logger('MiHoYo')
from developTools.message.message_components import Text, Image, At
import traceback
from .config import game_name_list, game_all_list

#米游币签到
async def mys_note_check(user_id,bot=None,event=None,target='星铁'):
    #pprint.pprint(PluginDataManager.plugin_data.users)
    user = PluginDataManager.plugin_data.users.get(str(user_id))
    if not user or not user.accounts:
        msg = '此用户还未绑定，请发送 ‘米游社帮助’ 查看菜单'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return
    #开始进行米游币签到
    for item in game_name_list:
        if target in game_name_list[item]:
            target = item
            break
    if target not in ['原神', '崩坏：星穹铁道', '绝区零']:
        msg = '当前便签仅支持原神、崩铁与绝区零查看哦'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return
    try:
        if target == '原神':
            await genshin_note_check(user, user_id, bot=bot, event=event)
        elif target == '崩坏：星穹铁道':
            await starrail_note_check(user, user_id, bot=bot, event=event)
        elif target == '绝区零':
            await zzz_note_check(user, user_id, bot=bot, event=event)

    except Exception as e:
        print(e)
        traceback.print_exc()
        msg = '便签查看失败，请稍后重试喵'
        if bot: await bot.send(event, msg)
        else:print(msg)



async def genshin_note_check(user, user_id, bot = None,event = None):
    """
    查看原神实时便笺函数，并发送给用户任务执行消息。

    :param user: 用户对象
    :param user_ids: 发送通知的所有用户ID
    :param matcher: 事件响应器
    """
    for account in user.accounts.values():
        if account.enable_resin and 'GenshinImpact' in account.game_sign_games:
            genshin_board_status, note = await genshin_note(account)
            print(genshin_board_status, note)
            if not genshin_board_status:
                if bot:
                    if genshin_board_status.login_expired:
                        msg = f' 登录失效，请重新登录'
                    elif genshin_board_status.no_genshin_account:
                        msg = f' 没有绑定任何原神账户，请绑定后再重试'
                    elif genshin_board_status.need_verify:
                        msg = f' 获取实时便笺时被人机验证阻拦'
                    if bot:
                        await bot.send(event, msg)
                    else:
                        print(msg)
                continue

            msg = "  \n❖原神·实时便笺❖" \
                   f"\n🆔账户 {account.display_name}" \
                   f"\n⏳树脂数量：{note.current_resin} / 200" \
                   f"\n⏱️树脂{note.resin_recovery_text}" \
                   f"\n🕰️探索派遣：{note.current_expedition_num} / {note.max_expedition_num}" \
                   f"\n📅每日委托：{4 - note.finished_task_num} 个任务未完成" \
                   f"\n💰洞天财瓮：{note.current_home_coin} / {note.max_home_coin}" \
                   f"\n🎰参量质变仪：{note.transformer_text if note.transformer else 'N/A'}"
            if bot:
                await bot.send(event, [At(qq=user_id), msg])
            else:
                print(msg)


async def starrail_note_check(user, user_id, bot = None,event = None):
    """
    查看星铁实时便笺函数，并发送给用户任务执行消息。

    :param user: 用户对象
    :param user_ids: 发送通知的所有用户ID
    :param matcher: 事件响应器
    """
    for account in user.accounts.values():
        if account.enable_resin and 'StarRail' in account.game_sign_games:
            starrail_board_status, note = await starrail_note(account)
            if not starrail_board_status:
                if bot:
                    if starrail_board_status.login_expired:
                        msg = f' 登录失效，请重新登录'
                    elif starrail_board_status.no_genshin_account:
                        msg = f' 没有绑定任何星铁账户，请绑定后再重试'
                    elif starrail_board_status.need_verify:
                        msg = f' 获取实时便笺时被人机验证阻拦'
                    if bot:
                        await bot.send(event, msg)
                    else:
                        print(msg)
                continue

            msg = "  \n❖星穹铁道·实时便笺❖" \
                   f"\n🆔账户 {account.display_name}" \
                   f"\n⏳开拓力数量：{note.current_stamina} / {note.max_stamina}" \
                   f"\n⏱开拓力{note.stamina_recover_text}" \
                   f"\n📒每日实训：{note.current_train_score} / {note.max_train_score}" \
                   f"\n📅每日委托：{note.accepted_expedition_num} / 4" \
                   f"\n🌌模拟宇宙：{note.current_rogue_score} / {note.max_rogue_score}"

            if bot:
                await bot.send(event, [At(qq=user_id), msg])
            else:
                print(msg)


async def zzz_note_check(user, user_id, bot=None, event=None):
    """查看绝区零实时便签并按现有便签格式发送。"""
    for account in user.accounts.values():
        if account.enable_resin and 'ZenlessZoneZero' in account.game_sign_games:
            zzz_board_status, note = await zzz_note(account)
            if not zzz_board_status:
                if zzz_board_status.login_expired:
                    msg = ' 登录失效，请重新登录'
                elif zzz_board_status.no_zzz_account:
                    msg = ' 没有绑定任何绝区零账户，请绑定后再重试'
                elif zzz_board_status.need_verify:
                    msg = ' 获取实时便签时被人机验证阻拦'
                else:
                    msg = ' 获取实时便签请求失败，请稍后重试'
                if bot: await bot.send(event, msg)
                else: print(msg)
                continue

            msg = "  \n❖绝区零·实时便签❖" \
                  f"\n🆔账户 {account.display_name}" \
                  f"\n⏳电量数量：{note.current_energy} / {note.max_energy}" \
                  f"\n⏱电量{note.energy_recover_text}" \
                  f"\n📒今日活跃度：{note.current_vitality} / {note.max_vitality}" \
                  f"\n🎰刮刮卡：{note.card_sign_text}" \
                  f"\n🏪录像店经营：{note.vhs_sale_text}" \
                  f"\n🎯悬赏委托：{note.bounty_num} / {note.bounty_total}" \
                  f"\n📅丽都周纪：{note.weekly_num} / {note.weekly_total}"
            if bot:
                await bot.send(event, [At(qq=user_id), msg])
            else:
                print(msg)
