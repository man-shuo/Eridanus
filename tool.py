import asyncio
from time import sleep

from ruamel.yaml import YAML

from developTools.utils.logger import get_logger

logger=get_logger()
async def main():
    logger.info("""请输入要执行的指令：
        1 youtube登录
        2 更新bot代码""")
    sleep(1)
    user_input=input("请输入指令序号：")
    print(user_input)
    if user_input=="1":
        logger.info("youtube登录")
        logger.warning(
            """
            \n
            youtube登录需要手动操作，请按照以下步骤进行：
            0.等待链接出现
            1.打开链接
            2.输入input code 后面的代码
            3.继续使用你的google账号登录
            4.完成后，在这个页面按回车(等待结束后自动退出)
            """
        )
        #获取必要参数
        yaml = YAML(typ='safe')
        with open('config/api.yaml', 'r', encoding='utf-8') as f:
            local_config = yaml.load(f)
        proxy = local_config.get("proxy").get("http_proxy")
        pyproxies = {  # pytubefix代理
            "http": proxy,
            "https": proxy
        }

        from pytubefix import YouTube
        from pytubefix.helpers import reset_cache
        reset_cache()

        yt = YouTube(url="https://www.youtube.com/watch?v=PZnXXFrjSjg", client='IOS', proxies=pyproxies, use_oauth=True, allow_oauth_cache=True)
        ys = yt.streams.get_audio_only()
        #ys.download(output_path="data/voice/cache/", filename="PZnXXFrjSjg")



asyncio.run(main())