from typing import Optional
"""Hololive Style Bert-VITS2 Gradio adapter."""

import asyncio
import json
import random
import string
from pathlib import Path

import aiohttp

BASE_URL = "https://kit-lemonfoot-hololive-style-bert-vits2.hf.space"
HEADERS = {"origin": BASE_URL, "referer": f"{BASE_URL}/?__theme=system"}

# 这些是服务端公开且稳定的 speaker；用户可在 tts_v2/config.yaml 中选择/扩展。
SPEAKERS = {
    "MoriCalliope": {"fn_index": 0, "model_name": "SBV2_HoloLow", "model_path": "model_assets/SBV2_HoloLow/SBV2_HoloLow.safetensors"},
    "TakanashiKiara": {"fn_index": 1, "model_name": "SBV2_TakanashiKiara", "model_path": "model_assets/SBV2_TakanashiKiara/SBV2_TakanashiKiara.safetensors"},
    "NinomaeInanis": {"fn_index": 2, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "GawrGura": {"fn_index": 3, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "AmeliaWatson": {"fn_index": 4, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "IRyS": {"fn_index": 5, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "TsukumoSana": {"fn_index": 6, "model_name": "SBV2_HoloAus", "model_path": "model_assets/SBV2_HoloAus/SBV2_HoloAus.safetensors"},
    "CeresFauna": {"fn_index": 7, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "OuroKronii": {"fn_index": 8, "model_name": "SBV2_HoloLow", "model_path": "model_assets/SBV2_HoloLow/SBV2_HoloLow.safetensors"},
    "NanashiMumei": {"fn_index": 9, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "HakosBaelz": {"fn_index": 10, "model_name": "SBV2_HoloAus", "model_path": "model_assets/SBV2_HoloAus/SBV2_HoloAus.safetensors"},
    "ShioriNovella": {"fn_index": 11, "model_name": "SBV2_HoloHi", "model_path": "model_assets/SBV2_HoloHi/SBV2_HoloHi.safetensors"},
    "KosekiBijou": {"fn_index": 12, "model_name": "SBV2_KosekiBijou", "model_path": "model_assets/SBV2_KosekiBijou/SBV2_KosekiBijou.safetensors"},
    "NerissaRavencroft": {"fn_index": 13, "model_name": "SBV2_HoloLow", "model_path": "model_assets/SBV2_HoloLow/SBV2_HoloLow.safetensors"},
    "AyundaRisu": {"fn_index": 14, "model_name": "SBV2_HoloESL", "model_path": "model_assets/SBV2_HoloESL/SBV2_HoloESL.safetensors"},
    "MoonaHoshinova": {"fn_index": 15, "model_name": "SBV2_HoloESL", "model_path": "model_assets/SBV2_HoloESL/SBV2_HoloESL.safetensors"},
    "AiraniIofifteen": {"fn_index": 16, "model_name": "SBV2_HoloESL", "model_path": "model_assets/SBV2_HoloESL/SBV2_HoloESL.safetensors"},
    "KureijiOllie": {"fn_index": 17, "model_name": "SBV2_HoloIDFlu", "model_path": "model_assets/SBV2_HoloIDFlu/SBV2_HoloIDFlu.safetensors"},
    "AnyaMelfissa": {"fn_index": 18, "model_name": "SBV2_HoloESL", "model_path": "model_assets/SBV2_HoloESL/SBV2_HoloESL.safetensors"},
    "VestiaZeta": {"fn_index": 19, "model_name": "SBV2_HoloIDFlu", "model_path": "model_assets/SBV2_HoloIDFlu/SBV2_HoloIDFlu.safetensors"},
    "TokinoSora": {"fn_index": 20, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "SakuraMiko": {"fn_index": 21, "model_name": "SBV2_HoloJPBaby", "model_path": "model_assets/SBV2_HoloJPBaby/SBV2_HoloJPBaby.safetensors"},
    "HoshimachiSuisei": {"fn_index": 22, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "AZKi": {"fn_index": 23, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "YozoraMel": {"fn_index": 24, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "ShirakamiFubuki": {"fn_index": 25, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "NatsuiroMatsuri": {"fn_index": 26, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "AkiRosenthal": {"fn_index": 27, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "AkaiHaato": {"fn_index": 28, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "MinatoAqua": {"fn_index": 29, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "NakiriAyame": {"fn_index": 30, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "OozoraSubaru": {"fn_index": 31, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "NekomataOkayu": {"fn_index": 32, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "UsadaPekora": {"fn_index": 33, "model_name": "SBV2_UsadaPekora", "model_path": "model_assets/SBV2_UsadaPekora/SBV2_UsadaPekora.safetensors"},
    "UruhaRushia": {"fn_index": 34, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "ShiranuiFlare": {"fn_index": 35, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "ShiroganeNoel": {"fn_index": 36, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "HoushouMarine": {"fn_index": 37, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "AmaneKanata": {"fn_index": 38, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "TsunomakiWatame": {"fn_index": 39, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "TokoyamiTowa": {"fn_index": 40, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "HimemoriLuna": {"fn_index": 41, "model_name": "SBV2_HoloJPBaby", "model_path": "model_assets/SBV2_HoloJPBaby/SBV2_HoloJPBaby.safetensors"},
    "YukihanaLamy": {"fn_index": 42, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "MomosuzuNene": {"fn_index": 43, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "OmaruPolka": {"fn_index": 44, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
    "LaplusDarknesss": {"fn_index": 45, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "TakaneLui": {"fn_index": 46, "model_name": "SBV2_HoloJPTest2.5", "model_path": "model_assets/SBV2_HoloJPTest2.5/SBV2_HoloJPTest2.5.safetensors"},
    "HakuiKoyori": {"fn_index": 47, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "SakamataChloe": {"fn_index": 48, "model_name": "SBV2_HoloJPTest2", "model_path": "model_assets/SBV2_HoloJPTest2/SBV2_HoloJPTest2.safetensors"},
    "IchijouRirika": {"fn_index": 49, "model_name": "SBV2_HoloJPTest", "model_path": "model_assets/SBV2_HoloJPTest/SBV2_HoloJPTest.safetensors"},
    "JuufuuteiRaden": {"fn_index": 50, "model_name": "SBV2_HoloJPTest3", "model_path": "model_assets/SBV2_HoloJPTest3/SBV2_HoloJPTest3.safetensors"},
}


class HoliveTTS:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._session = None
        return cls._instance

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def open(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @staticmethod
    def speakers():
        return list(SPEAKERS)

    @staticmethod
    def _hash():
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    async def _submit(self, session_hash, speaker, text, language):
        cfg = SPEAKERS[speaker]
        data = [cfg["model_name"], cfg["model_path"], text, language, None, 0.2, 0.6, 0.8, 1.2, True, 0.5, "", 0.7, False, "Neutral", 3, "", False, speaker]
        async with self._session.post(f"{BASE_URL}/queue/join", json={"data": data, "event_data": None, "fn_index": cfg["fn_index"], "session_hash": session_hash}, headers={**HEADERS, "content-type": "application/json"}) as response:
            response.raise_for_status()

    async def _poll(self, session_hash):
        async with self._session.get(f"{BASE_URL}/queue/data?session_hash={session_hash}", headers=HEADERS) as response:
            response.raise_for_status()
            async for raw in response.content:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                if event.get("msg") == "process_completed":
                    if not event.get("success"):
                        raise RuntimeError(f"Holive TTS failed: {event}")
                    output = event.get("output", {}).get("data", [])
                    if len(output) < 2 or not output[1]:
                        raise RuntimeError(output[0] if output else f"Holive TTS returned no audio: {event}")
                    audio = output[1]
                    return audio.get("url") or f"{BASE_URL}/file={audio['path']}"
        raise RuntimeError("Holive TTS queue ended without audio")

    async def synthesize(self, text, speaker="MoriCalliope", language="JP"):
        if speaker not in SPEAKERS:
            raise ValueError(f"未知角色: {speaker}，可选: {self.speakers()}")
        if self._session is None or self._session.closed:
            await self.open()
        session_hash = self._hash()
        await self._submit(session_hash, speaker, text, language)
        audio_url = await self._poll(session_hash)
        async with self._session.get(audio_url, headers=HEADERS) as response:
            response.raise_for_status()
            return await response.read()

    async def synthesize_to_file(self, text, save_as, speaker="MoriCalliope", language="JP"):
        data = await self.synthesize(text, speaker, language)
        Path(save_as).parent.mkdir(parents=True, exist_ok=True)
        Path(save_as).write_bytes(data)
        return save_as


HOLIVE_ALIASES = {
    "gura": "GawrGura",
    "gawrgura": "GawrGura",
    "calli": "MoriCalliope",
    "moricalliope": "MoriCalliope",
    "ina": "NinomaeInanis",
    "kiara": "TakanashiKiara",
    "watson": "AmeliaWatson",
    "amelia": "AmeliaWatson",
    "kronii": "OuroKronii",
    "mumei": "NanashiMumei",
    "baelz": "HakosBaelz",
    "fauna": "CeresFauna",
    "suisei": "HoshimachiSuisei",
    "miko": "SakuraMiko",
    "marine": "HoushouMarine",
    "fubuki": "ShirakamiFubuki",
    "pekora": "UsadaPekora",
    "aqua": "MinatoAqua",
    "ayame": "NakiriAyame",
    "subaru": "OozoraSubaru",
    "korone": "InugamiKorone",
    "okayu": "NekomataOkayu",
}

def resolve_holive_speaker(speaker: str) -> Optional[str]:
    if not speaker:
        return None
    spk_clean = speaker.strip()
    spk_lower = spk_clean.lower()
    for h in SPEAKERS:
        if h.lower() == spk_lower:
            return h
    if spk_lower in HOLIVE_ALIASES:
        return HOLIVE_ALIASES[spk_lower]
    return None
