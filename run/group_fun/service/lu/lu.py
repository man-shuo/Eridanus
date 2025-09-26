from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase
from run.anime_game_service.service.skland.core import *
import json
import time
import asyncio
from io import BytesIO
from datetime import datetime, timedelta
from PIL import Image as PImage
import base64
import pprint
from developTools.message.message_components import Text, Image, At
from framework_common.manshuo_draw import *
from run.group_fun.service.lu.core import *
from framework_common.manshuo_draw import *
db=asyncio.run(AsyncSQLiteDatabase.get_instance())



async def today_lu(userid,times,bot=None,event=None):
    day_info = await date_get()
    user_info =await data_init(userid,day_info)
    update_json = {'type':'lu_done','times':times}
    await data_update(user_info,update_json,day_info)
    if bot and event:target_name = (await bot.get_group_member_info(event.group_id, userid))['data']['nickname']
    else:target_name = '您'
    content = [f"{target_name} 的{day_info['today'].strftime('%Y年%m月')}的开🦌计划",
               f"今天🦌了 {user_info['lu_done']['data'][day_info['day']]} 次，牛牛可开心了，",
               f"今天牛牛一共变长了 {user_info['length']['data'][day_info['day']]} cm",
               f"您一共🦌了 {user_info['collect']['lu_done']} 次，现在牛牛一共 {user_info['collect']['length']} cm!!!"]
    img_path = await lu_img_maker(user_info,content,day_info)
    await db.write_user(userid, {'lu': user_info})
    if bot and event:
        recall_id = await bot.send(event, [At(qq=userid)," 今天🦌了！",Image(file=img_path)])
        return recall_id
    else:
        pprint.pprint('今天🦌了！')

async def supple_lu(userid,bot=None,event=None):
    day_info = await date_get()
    user_info =await data_init(userid,day_info)

    times_record = user_info['lu_supple']['record']
    times_record_check = int(times_record) // 3
    if times_record_check == 0:
        await bot.send(event, [At(qq=userid),
                               f' 您的补🦌次数好像不够呢喵~~（已连续{times_record}天）(3天1次)'])
    update_json = {'type':'supple_lu'}
    await data_update(user_info,update_json,day_info)
    if bot and event:target_name = (await bot.get_group_member_info(event.group_id, userid))['data']['nickname']
    else:target_name = '您'
    content = [f"{target_name} 的{day_info['today'].strftime('%Y年%m月')}的开🦌计划",
               f"已成功补🦌! ",
               f"您一共🦌了 {user_info['collect']['lu_done']} 次，现在牛牛一共 {user_info['collect']['length']} cm!!!"]
    img_path = await lu_img_maker(user_info,content,day_info)
    await db.write_user(userid, {'lu': user_info})
    if bot and event:
        recall_id = await bot.send(event, [At(qq=userid)," 已成功补🦌了！",Image(file=img_path)])
        return recall_id
    else:
        pprint.pprint('已成功补🦌了！')

async def check_lu(userid,bot=None,event=None):
    day_info = await date_get()
    user_info =await data_init(userid,day_info)
    if bot and event:target_name = (await bot.get_group_member_info(event.group_id, userid))['data']['nickname']
    else:target_name = '您'
    content = [f"{target_name} 的{day_info['today'].strftime('%Y年%m月')}的开🦌计划",
               f"今天🦌了 {user_info['lu_done']['data'][day_info['day']]} 次，牛牛可开心了，",
               f"今天牛牛一共变长了 {user_info['length']['data'][day_info['day']]} cm",
               f"您一共🦌了 {user_info['collect']['lu_done']} 次，现在牛牛一共 {user_info['collect']['length']} cm!!!"]
    img_path = await lu_img_maker(user_info,content,day_info)
    await db.write_user(userid, {'lu': user_info})
    if bot and event:
        recall_id = await bot.send(event, [At(qq=userid)," 这是您的开🦌记录！",Image(file=img_path)])
        return recall_id
    else:
        pprint.pprint('今天🦌了！')

async def rank_lu(userid_list,type_check='month',bot=None,event=None):
    day_info = await date_get()
    user_list = await user_list_get(userid_list,day_info,type_check)
    #pprint.pprint(user_list)
    if type_check == 'month':send_str = '本月'
    elif type_check == 'year': send_str = '年度'
    elif type_check == 'total':send_str = '总共'
    if event:
        self_id = event.self_id
        self_name = (await bot.get_group_member_info(event.group_id, self_id))['data']['nickname']
    else:
        self_id,self_name = '2319804644','枫与岚'
    draw_list = [
        {'type': 'avatar', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={self_id}&s=640"],
         'upshift_extra': 15,'content': [f"[name]{self_name} 一直在看着你哦～[/name]\n[time]看看群友都有多勤奋的🦌！[/time]"]},
        f"[title]这是本群{send_str}的开🦌排行！[/title]",
        {'type': 'math', 'subtype': 'bar_chart', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={item['userid']}&s=640" for item in user_list],
         'number_per_row': 1, 'chart_height': 75,'max':user_list[0]['times'],'upshift_label':-5,
         'is_stroke_label':True,'font_label_size':29,'font_label_color':(255, 255, 255),'label_color':(194, 228, 255, 255),
         'content': [item['times'] for item in user_list],'label': [f"{item['times']}次" for item in user_list]},
    ]
    img_path = await manshuo_draw(draw_list)
    if bot and event:
        recall_id = await bot.send(event, [f"{self_name} 一直在看着你哦～",Image(file=img_path)])
        return recall_id
    else:
        pprint.pprint('今天🦌了！')



if __name__ == '__main__':
    start_time = time.time()
    target_id = 1270858640
    asyncio.run(rank_lu([1270858640,2191331427,1270858640,2191331427,1270858640,2191331427,1270858640,2191331427,1270858640,2191331427,]))
    end_time = time.time()  # 记录结束时间
    duration = end_time - start_time  # 计算持续时间，单位为秒

    print(f"程序运行了 {duration:.2f} 秒")