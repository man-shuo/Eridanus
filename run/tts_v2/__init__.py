plugin_description = "tts_v2"

dynamic_imports = {
    "run.tts_v2.service.tts": [
        "call_tts",
        "get_all_speakers",
    ]
}

function_declarations = [
    {
        "name": "call_tts",
        "description": "使用指定角色声线进行语音合成并发送。当你想用特定声线说话、用某位角色的口吻回复或用户要求发语音时调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要合成并播放的语音文本。"
                },
                "speaker": {
                    "type": "string",
                    "description": "说话人角色名称，例如：'natuki'(赛马娘默认), '米浴'(赛马娘), 'MoriCalliope'或'gura'(Hololive), 'JP_Mari'或'Mari'(蔚蓝档案), 'otto'或'电棍'(电棍活字印刷), '达妮娅'(GPT-SoVITS), '綾地寧々'(本地VITS)等。留空或未指定则自动采用默认声线。"
                },
                "lang_type": {
                    "type": "string",
                    "description": "目标语言类型，如 'JP'(日语，自动翻译中文)、'ZH'(中文) 等。默认为配置中的 'JP'。"
                },
                "mood": {
                    "type": "string",
                    "enum": ["生气_angry", "开心_happy", "中立_neutral", "难过_sad"],
                    "description": "语音情绪，根据语境判断，默认为中立_neutral。"
                }
            },
            "required": [
                "text"
            ]
        }
    },
    {
        "name": "get_all_speakers",
        "description": "获取所有可用的语音合成角色列表及对应音源引擎。"
    }
]
