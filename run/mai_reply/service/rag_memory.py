"""Scoped conversation episodes, provider adapters and quota-conscious retrieval."""
import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np

from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.rag_archive import EpisodeArchive
from run.mai_reply.service.rag_retrieval import EpisodeRetrieval, RAG_PREFIX

logger = get_logger(__name__)

def trim_tokens(text, budget):
    """UTF-8 byte length upper-bounds tokens for the supported byte tokenizers."""
    return text.encode("utf-8")[:max(0, budget)].decode("utf-8", errors="ignore")

class RAGMemory(EpisodeArchive, EpisodeRetrieval):
    def __init__(self, config):
        self.cfg = dict(getattr(config.mai_reply, "rag", None) or {})
        self.enable = bool(self.cfg.get("enable", False))
        self._log_enabled = bool(self.cfg.get("logging", {}).get("enable", True))
        self._lock = threading.RLock()
        self._db = None
        self._worker = None
        self._client = None
        self._closed = False
        self._cooldown = 0.0
        self._generation = 0
        self._init_retrieval()
        self._init_archive(config)
        self._embedding_cfg = self.cfg.get("embedding", {})
        e = self._embedding_cfg
        self._provider = str(e.get("provider", "openai")).strip().lower()
        self._cloudflare_cfg = e.get("cloudflare", {})
        # Preserve OpenAI namespaces and isolate vectors from other providers.
        identity = [e.get("base_url"), e.get("endpoint", "embeddings"), e.get("model"), e.get("dimensions")]
        if self._provider != "openai":
            cf = self._cloudflare_cfg
            identity = [self._provider, cf.get("account_id"), cf.get("model", "@cf/baai/bge-m3")]
        self._namespace = hashlib.sha256(json.dumps(
            identity
        ).encode()).hexdigest()
        if self.enable:
            try:
                path = Path(self.cfg.get("db_path", "data/dataBase/mai_rag_memory.db"))
                path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("""CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, user_id TEXT NOT NULL,
                    source TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL,
                    vector BLOB, namespace TEXT, UNIQUE(scope, source))""")
                self._db.execute("CREATE INDEX IF NOT EXISTS rag_scope ON memories(scope, created)")
                self._db.commit()
                self._init_archive(config)
            except Exception as exc:
                logger.error("[MaiReply RAG] 数据库初始化失败 (%s)，本次启动关闭 RAG", type(exc).__name__)
                if self._db:
                    self._db.close()
                self._db = None
                self.enable = False
        if self.enable:
            group = self.cfg.get("group", {})
            group_policy = ("关闭" if not group.get("enable", True) else
                            f"白名单 {len(group.get('whitelist', []))} 个群" if group.get("whitelist_enabled", True) else "所有群")
            self._log("[MaiReply RAG] 已启用 provider=%s 私聊=%s 群聊=%s 旁观=%s；私聊每%s轮/群聊每%s条用户消息归档，空闲%s秒补归档",
                      self._provider, self.allowed(), group_policy, group.get("observe_untriggered", True),
                      self._archive_cfg['private_turns'], self._archive_cfg['group_messages'],
                      self._archive_cfg.get('idle_seconds', 600))
            if self._provider == "cloudflare":
                cf = self._cloudflare_cfg
                missing = []
                if not cf.get("account_id"):
                    missing.append("account_id")
                if not (os.environ.get(cf.get("api_token_env", "CLOUDFLARE_API_TOKEN")) or cf.get("api_token")):
                    missing.append("api_token/环境变量")
                if missing:
                    logger.warning("[MaiReply RAG] Cloudflare 配置不完整：缺少 %s；请补齐后重启 Bot", ", ".join(missing))
        else:
            self._log("[MaiReply RAG] 未启用 (enable=false)，沿用原有聊天和记忆流程")

    def _log(self, message, *args):
        if self._log_enabled:
            logger.info(message, *args)

    def _warn(self, message, exc):
        logger.warning("[MaiReply RAG] %s (%s)", message, type(exc).__name__)

    @staticmethod
    def scope_for(group_id, user_id):
        return f"group:{group_id}" if group_id is not None else f"private:{user_id}"

    @property
    def replaces_legacy(self):
        return self.enable and self.cfg.get("integration_mode", "replace") == "replace"

    def allowed(self, group_id=None):
        if not self.enable or self._closed:
            return False
        if group_id is None:
            return bool(self.cfg.get("private", {}).get("enable", True))
        cfg = self.cfg.get("group", {})
        return bool(cfg.get("enable", True)) and (
            not cfg.get("whitelist_enabled", True)
            or str(group_id) in {str(x) for x in cfg.get("whitelist", [])}
        )

    def _run_db(self, fn, *args):
        with self._lock:
            if self._db is None:
                return None
            with self._db:
                return fn(self._db, *args)

    async def _embed(self, texts, query=False):
        e = self._embedding_cfg
        if self._provider not in ("openai", "cloudflare"):
            raise ValueError("unsupported embedding provider")
        cf = self._cloudflare_cfg
        settings = cf if self._provider == "cloudflare" else e
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(trust_env=False, timeout=float(
                settings.get("timeout_seconds", e.get("timeout_seconds", 12))))
        values = texts
        # Qwen instructions must not leak into BGE-M3 requests.
        instruction = settings.get("query_instruction", "")
        if query and instruction:
            values = [f"Instruct: {instruction}\nQuery: {s}" for s in texts]
        if self._provider == "cloudflare":
            account_id = str(cf.get("account_id", "")).strip()
            model = str(cf.get("model", "@cf/baai/bge-m3")).strip()
            if not account_id or not model.startswith(("@cf/", "@hf/")):
                raise ValueError("cloudflare account_id/model not configured")
            key = os.environ.get(cf.get("api_token_env", "CLOUDFLARE_API_TOKEN")) or cf.get("api_token", "")
            if not key:
                raise ValueError("cloudflare api_token not configured")
            url = ("https://api.cloudflare.com/client/v4/accounts/" + quote(account_id, safe="")
                   + "/ai/run/" + quote(model, safe="@/"))
            payload = {"text": values}
        else:
            key = os.environ.get(e.get("api_key_env", "MAI_RAG_API_KEY")) or e.get("api_key", "")
            payload = {"model": e.get("model", "qwen3-embedding-4b"), "input": values, "encoding_format": "float"}
            if e.get("dimensions") not in (None, ""):
                payload["dimensions"] = int(e["dimensions"])
            url = e.get("base_url", "http://localhost:8099/v1").rstrip("/") + "/" + e.get("endpoint", "embeddings").lstrip("/")
        response = await self._client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
        # Never log response bodies, which can contain keys, names or message text.
        if response.status_code != 200:
            raise RuntimeError(f"embedding HTTP {response.status_code}")
        body = response.json()
        if self._provider == "cloudflare":
            if body.get("success") is not True or body.get("errors"):
                raise RuntimeError("cloudflare embedding request failed")
            result = body.get("result") or {}
            data = result.get("data", [])
            if not isinstance(data, list):
                raise ValueError("invalid cloudflare embedding data")
            rows = [{"index": i, "embedding": vector} for i, vector in enumerate(data)]
            shape = result.get("shape")
            if shape is not None and (len(shape) != 2 or shape[0] != len(texts)
                                      or any(not isinstance(v, list) or len(v) != shape[1] for v in data)):
                raise ValueError("cloudflare embedding shape mismatch")
        else:
            rows = body.get("data", [])
        if len(rows) != len(texts) or sorted(r["index"] for r in rows) != list(range(len(texts))):
            raise ValueError("embedding count/index mismatch")
        vectors = []
        for row in sorted(rows, key=lambda r: r["index"]):
            v = np.asarray(row["embedding"], dtype=np.float32)
            if v.ndim != 1 or not v.size or not np.isfinite(v).all() or np.linalg.norm(v) == 0:
                raise ValueError("invalid embedding vector")
            vectors.append(v / np.linalg.norm(v))
        if len({v.size for v in vectors}) != 1:
            raise ValueError("inconsistent embedding dimensions")
        return vectors

    async def aclose(self):
        self._closed = True
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        with self._lock:
            if self._db:
                self._db.close()
                self._db = None
