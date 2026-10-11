# -*- coding: utf-8 -*-
plugin_description = "qq空间"


async def plugin_cleanup():
    """供框架 unload_plugin 或热重载前调用的清理钩子"""
    import sys

    # 1. 优先调用 qzone 模块的清理函数
    qzone_mod = sys.modules.get("run.qq_zone.qzone")
    if qzone_mod and hasattr(qzone_mod, "plugin_cleanup"):
        try:
            await qzone_mod.plugin_cleanup()
        except Exception as e:
            print(f"[qq_zone.__init__] 调用 qzone.plugin_cleanup 异常: {e}")

    # 2. 清理 sys._qzone_runtime_state 活跃实例
    runtime_state = getattr(sys, "_qzone_runtime_state", None)
    if isinstance(runtime_state, dict):
        active_inst = runtime_state.get("active_instance")
        if active_inst and hasattr(active_inst, "stop"):
            try:
                await active_inst.stop()
            except Exception as e:
                print(f"[qq_zone.__init__] 停止旧 active_instance 异常: {e}")
        runtime_state["active_instance"] = None
        runtime_state["bg_started"] = False
        in_prog = runtime_state.get("in_progress_comments")
        if isinstance(in_prog, set):
            in_prog.clear()

    # 3. 兼容清理 sys._qzone_lifecycle_manager 历史对象
    mgr = getattr(sys, "_qzone_lifecycle_manager", None)
    if mgr and hasattr(mgr, "stop"):
        try:
            await mgr.stop()
        except Exception as e:
            print(f"[qq_zone.__init__] 停止旧 _qzone_lifecycle_manager 异常: {e}")
    sys._qzone_lifecycle_manager = None
