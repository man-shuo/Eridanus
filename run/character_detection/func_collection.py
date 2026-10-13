from framework_common.database_util.User import get_user

async def operate_group_censor(bot, event, config, target_id, operation):
    target_id = int(target_id)
    mapping = {
        "开启奶龙审核": ("nailong", "奶龙审核", True),
        "关闭奶龙审核": ("nailong", "奶龙审核", False),
        "开启doro审核": ("doro", "doro审核", True),
        "关闭doro审核": ("doro", "doro审核", False),
        "开启男娘审核": ("nanniang", "男娘审核", True),
        "关闭男娘审核": ("nanniang", "男娘审核", False),
        "开启deepseek审核": ("deepseek", "deepseek审核", True),
        "关闭deepseek审核": ("deepseek", "deepseek审核", False),
    }

    if operation not in mapping:
        return

    cfg_key, display_name, status = mapping[operation]
    await _handle_whitelist_toggle(bot, event, config, cfg_key, display_name, target_id, status)

async def _handle_whitelist_toggle(bot, event, config, cfg_key, display_name, target_id, status):
    user_info = await get_user(event.user_id, event.sender.nickname)
    required_level = config.common_config.basic_config.get("user_handle_logic_operate_level", 1)
    if user_info.permission < required_level:
        await bot.send(event, "你没有足够权限执行此操作")
        return

    sub_cfg = getattr(config.character_detection, cfg_key, None)
    if sub_cfg is None or "whitelist" not in sub_cfg:
        await bot.send(event, f"配置项 {cfg_key} 未正确初始化")
        return

    whitelist = sub_cfg["whitelist"]
    if status:
        if target_id not in whitelist:
            whitelist.append(target_id)
            config.save_yaml(cfg_key, plugin_name="character_detection")
        await bot.send(event, f"已将 {target_id} 加入{display_name}目标")
    else:
        if target_id in whitelist:
            whitelist.remove(target_id)
            config.save_yaml(cfg_key, plugin_name="character_detection")
            await bot.send(event, f"已将 {target_id} 移出{display_name}目标")
        else:
            await bot.send(event, f"{target_id} 不在{display_name}目标中")
