"""Durable conversational buffering and threshold/idle-based episode indexing."""
import asyncio
import json
import time
import uuid
from datetime import datetime

from run.mai_reply.service.rag_query import topic_labels


class EpisodeArchive:
    def start(self):
        """Resume durable indexing/tail timers once the bot event loop is running."""
        self._kick()

    def _init_archive(self, config):
        main = getattr(config.mai_reply, "config", {}) or {}
        context = main.get("context", {})
        self._archive_cfg = dict(self.cfg.get("archive", {}))
        self._archive_cfg.setdefault("private_turns", context.get("user_trigger_turns", 3))
        self._archive_cfg.setdefault("group_messages", context.get("group_trigger_messages", 10))
        self._wake = asyncio.Event()
        if self._db is None:
            return
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(memories)")}
        for column, definition in (("ended", "REAL"), ("participants", "TEXT NOT NULL DEFAULT '[]'")):
            if column not in columns:
                self._db.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS rag_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                user_id TEXT NOT NULL, speaker TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, created REAL NOT NULL, received REAL NOT NULL,
                turn_end INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS rag_events_scope ON rag_events(scope,id);
            CREATE TABLE IF NOT EXISTS rag_receipts (
                scope TEXT NOT NULL, source TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(scope,source)
            );
            CREATE TABLE IF NOT EXISTS rag_episode_tail (
                scope TEXT PRIMARY KEY, events TEXT NOT NULL
            );
        """)
        self._db.commit()

    async def remember(self, group_id, user_id, user_name, text, reply="", message_id=None,
                       bot_name="Bot", timestamp=None):
        """Compatibility entry: a supplied reply is one completed user/Bot turn."""
        if reply:
            return await self.record_turn(group_id, user_id, user_name, text, reply,
                                          message_id=message_id, bot_name=bot_name, timestamp=timestamp)
        return await self.observe(group_id, user_id, user_name, text,
                                  message_id=message_id, timestamp=timestamp)

    async def observe(self, group_id, user_id, user_name, text, message_id=None,
                      timestamp=None, role="user"):
        return await self._record(group_id, user_id, [
            (role, user_name, text, False),
        ], message_id, timestamp)

    async def record_turn(self, group_id, user_id, user_name, text, reply,
                          message_id=None, bot_name="Bot", timestamp=None):
        # Both halves enter SQLite in one transaction, after a reply was sent.
        return await self._record(group_id, user_id, [
            ("user", user_name, text, False), ("assistant", bot_name, reply, True),
        ], message_id, timestamp)

    async def _record(self, group_id, user_id, items, message_id, timestamp):
        if not self.allowed(group_id):
            return
        now = time.time()
        created = now if timestamp is None else float(timestamp)
        scope = self.scope_for(group_id, user_id)
        source = str(message_id) if message_id is not None else uuid.uuid4().hex
        limit = max(100, int(self.cfg.get("index", {}).get("max_message_chars", 16000)))
        events = []
        for role, speaker, text, turn_end in items:
            if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip():
                continue
            text = text.strip()
            if role == "user" and text.startswith(("/", "#")):
                continue
            events.append((role, str(speaker)[:40], text[:limit], int(turn_end)))
        if not events or (len(items) == 2 and events[0][0] != "user"):
            return
        generation = self._generation

        def insert(db):
            if generation != self._generation:
                return 0, 0, 0
            inserted = 0
            for role, speaker, content, turn_end in events:
                receipt = f"{role}:{user_id}:{source}"
                if db.execute("INSERT OR IGNORE INTO rag_receipts VALUES(?,?,?)", (scope, receipt, now)).rowcount:
                    db.execute("""INSERT INTO rag_events(scope,user_id,speaker,role,content,created,received,turn_end)
                                  VALUES(?,?,?,?,?,?,?,?)""",
                               (scope, str(user_id), speaker, role, content, created, now, turn_end))
                    inserted += 1
            # Bound raw buffering too, including scopes that only receive Bot
            # messages. Expired receipts are removed along with old raw events.
            cutoff = now - max(1, int(self.cfg.get('retention', {}).get('days', 365))) * 86400
            db.execute('DELETE FROM rag_events WHERE received<?', (cutoff,))
            db.execute('DELETE FROM rag_receipts WHERE created<?', (cutoff,))
            raw_limit = max(20, int(self._archive_cfg.get('max_buffer_messages', 200)))
            db.execute('''DELETE FROM rag_events WHERE scope=? AND id NOT IN
                          (SELECT id FROM rag_events WHERE scope=? ORDER BY id DESC LIMIT ?)''',
                       (scope, scope, raw_limit))
            count, turns = db.execute("SELECT COUNT(*),COALESCE(SUM(turn_end),0) FROM rag_events WHERE scope=?",
                                      (scope,)).fetchone()
            return inserted, count, turns
        try:
            inserted, count, turns = await asyncio.to_thread(self._run_db, insert)
            #if inserted:
                #self._log("[MaiReply RAG] 缓冲 scope=%s 新增=%d 消息 待归档=%d 完成轮数=%d（未逐条调用embedding）",scope, inserted, count, turns)
            self._kick()
        except Exception as exc:
            self._warn("消息缓冲失败", exc)

    @staticmethod
    def _event(row):
        return {"user_id": row[1], "speaker": row[2], "role": row[3],
                "content": row[4], "created": row[5]}

    def _scope_allowed(self, scope):
        if scope.startswith("group:"):
            return self.allowed(scope.split(":", 1)[1])
        return self.allowed(None)

    def _archive_due(self, db, force=False):
        now = time.time()
        scopes = db.execute("""SELECT scope,COUNT(*),COALESCE(SUM(turn_end),0),
                              SUM(CASE WHEN role='user' THEN 1 ELSE 0 END),SUM(LENGTH(content)),MAX(received)
                              FROM rag_events GROUP BY scope""").fetchall()
        written = 0
        for scope, count, turns, humans, chars, last in scopes:
            if not self._scope_allowed(scope):
                continue
            group = scope.startswith("group:")
            threshold = max(1, int(self._archive_cfg.get("group_messages" if group else "private_turns", 10 if group else 3)))
            idle = float(self._archive_cfg.get("idle_seconds", 600))
            size_limit = max(100, int(self._archive_cfg.get("max_buffer_chars", 6000)))
            if not (force or (humans if group else turns) >= threshold or chars >= size_limit
                    or (idle > 0 and now - last >= idle)):
                continue
            rows = db.execute("SELECT id,user_id,speaker,role,content,created FROM rag_events WHERE scope=? ORDER BY id",
                              (scope,)).fetchall()
            events = [self._event(row) for row in rows]
            # Bot-only proactive messages are kept for context until a human joins.
            if not any(event["role"] == "user" for event in events):
                continue
            tail_row = db.execute("SELECT events FROM rag_episode_tail WHERE scope=?", (scope,)).fetchone()
            tail = json.loads(tail_row[0]) if tail_row else []
            overlap = max(0, min(4, int(self._archive_cfg.get("overlap_messages", 2))))
            # Do not attach a months-old tail to a new conversation.
            gap = float(self._archive_cfg.get("context_gap_seconds", 1800))
            if tail and abs(events[0]["created"] - tail[-1]["created"]) > gap:
                tail = []
            combined = tail[-overlap:] + events if overlap else events
            episode_id = uuid.uuid4().hex
            chunks = self._episode_chunks(combined)
            for index, messages in enumerate(chunks):
                start, end = min(e["created"] for e in messages), max(e["created"] for e in messages)
                participants = sorted({e["user_id"] for e in messages if e["role"] == "user"})
                human_text = "\n".join(e["content"] for e in messages if e["role"] == "user")
                document = {"version": 2, "episode": episode_id, "start": start, "end": end,
                            "topics": topic_labels(human_text), "messages": messages}
                owner = scope.split(":", 1)[1] if not group else "*"
                db.execute("""INSERT INTO memories(scope,user_id,source,text,created,ended,participants)
                              VALUES(?,?,?,?,?,?,?)""", (scope, owner, f"episode:{episode_id}:{index}",
                              json.dumps(document, ensure_ascii=False), start, end, json.dumps(participants)))
                written += 1
            # Raw buffer and episode creation commit together; no data is lost on restart.
            db.execute("DELETE FROM rag_events WHERE scope=? AND id<=?", (scope, rows[-1][0]))
            db.execute("INSERT OR REPLACE INTO rag_episode_tail VALUES(?,?)",
                       (scope, json.dumps(events[-overlap:] if overlap else [], ensure_ascii=False)))
            self._prune(db, scope, now)
            self._log("[MaiReply RAG] 对话归档 scope=%s 消息=%d 用户消息=%d 完成轮数=%d 向量片段=%d",
                      scope, count, humans, turns, len(chunks))
        return written

    def _episode_chunks(self, events):
        limit = max(300, int(self._archive_cfg.get("chunk_chars", 1800)))
        result, chunk = [], []
        # Keep each short human/Bot exchange together whenever it fits.
        for event in events:
            for offset in range(0, len(event["content"]), max(100, limit - 250)):
                piece = {**event, "content": event["content"][offset:offset + max(100, limit - 250)]}
                if chunk and len(json.dumps(chunk + [piece], ensure_ascii=False)) > limit:
                    result.append(chunk)
                    # Carry one preceding message to ground short answers in the next chunk.
                    chunk = chunk[-1:] if len(json.dumps(chunk[-1:], ensure_ascii=False)) < limit // 3 else []
                chunk.append(piece)
        if chunk:
            result.append(chunk)
        return result

    def _prune(self, db, scope, now):
        cfg = self.cfg.get("retention", {})
        cutoff = now - max(1, int(cfg.get("days", 365))) * 86400
        db.execute("DELETE FROM memories WHERE COALESCE(ended,created)<?", (cutoff,))
        db.execute("DELETE FROM rag_receipts WHERE created<?", (cutoff,))
        maximum = max(1, int(cfg.get("max_per_scope", 4000)))
        db.execute("""DELETE FROM memories WHERE scope=? AND id NOT IN
                      (SELECT id FROM memories WHERE scope=? ORDER BY COALESCE(ended,created) DESC,id DESC LIMIT ?)""",
                   (scope, scope, maximum))
        pending = max(1, int(self.cfg.get("index", {}).get("max_pending", 10000)))
        db.execute("""DELETE FROM memories WHERE (vector IS NULL OR namespace != ?) AND id NOT IN
                      (SELECT id FROM memories WHERE vector IS NULL OR namespace != ? ORDER BY id DESC LIMIT ?)""",
                   (self._namespace, self._namespace, pending))

    def _kick(self):
        if self.enable and not self._closed:
            self._wake.set()
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._index_loop(), name="mai-rag-episodes")

    def _pending(self, db, limit=None):
        rows = db.execute("SELECT id,text,scope FROM memories WHERE vector IS NULL OR namespace != ? ORDER BY id",
                          (self._namespace,)).fetchall()
        rows = [row for row in rows if self._scope_allowed(row[2])]
        return rows if limit is None else rows[:limit]

    @staticmethod
    def _embedding_text(raw):
        document = json.loads(raw)
        if document.get("version") != 2:
            return raw
        # Keep rich metadata in SQLite; avoid repeating JSON keys/timestamps in
        # every embedding input. All actual human/Bot utterances are retained.
        stamp = lambda value: datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M")
        lines = [f"对话时间 {stamp(document['start'])} 至 {stamp(document['end'])}"]
        if document.get("topics"):
            lines.append("相关话题 " + "; ".join(document["topics"]))
        for event in document["messages"]:
            label = (f"{event['speaker']}[user;ID:{event['user_id']}]" if event["role"] == "user" else
                     f"Bot[assistant;回复ID:{event['user_id']}]")
            lines.append(label + ": " + event["content"])
        return "\n".join(lines)

    async def _index_loop(self):
        batch = max(1, min(100, int(self.cfg.get("index", {}).get("batch_size", 16))))
        retry = max(1, float(self.cfg.get("index", {}).get("retry_seconds", 60)))
        while not self._closed:
            self._wake.clear()
            try:
                await asyncio.to_thread(self._run_db, self._archive_due)
                rows = await asyncio.to_thread(self._run_db, self._pending, batch)
                if rows and time.monotonic() >= self._cooldown:
                    started = time.monotonic()
                    self._log("[MaiReply RAG] 索引开始 provider=%s 本批=%d 对话片段", self._provider, len(rows))
                    vectors = await self._embed([self._embedding_text(row[1]) for row in rows])
                    def save(db):
                        return db.executemany("UPDATE memories SET vector=?,namespace=? WHERE id=? AND text=?",
                                              [(v.tobytes(), self._namespace, row[0], row[1]) for row, v in zip(rows, vectors)]).rowcount
                    saved = await asyncio.to_thread(self._run_db, save)
                    self._log("[MaiReply RAG] 索引完成 写入=%d 维度=%d 耗时=%.2fs",
                              saved or 0, vectors[0].size, time.monotonic() - started)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._cooldown = time.monotonic() + retry
                self._warn("归档或索引失败，持久化队列等待重试", exc)
            idle = float(self._archive_cfg.get("idle_seconds", 600))
            delay = min(30, idle) if idle > 0 else 30
            if time.monotonic() < self._cooldown:
                delay = min(delay, self._cooldown - time.monotonic())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.02, delay))
            except asyncio.TimeoutError:
                pass

    async def flush(self, force=False):
        """Explicit flushing is useful for maintenance/tests; normal traffic uses thresholds."""
        if not self.enable or self._closed:
            return 0
        count = await asyncio.to_thread(self._run_db, self._archive_due, force)
        self._kick()
        return count

    async def wait_idle(self, timeout=10):
        """Wait for currently eligible episodes, without forcing a partial conversation."""
        if not self.enable or self._closed:
            return
        await self.flush()
        async def wait():
            while await asyncio.to_thread(self._run_db, self._pending):
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait(), timeout)

    def _recent_events(self, db, scope, limit=12):
        rows = db.execute("""SELECT id,user_id,speaker,role,content,created FROM rag_events
                              WHERE scope=? ORDER BY id DESC LIMIT ?""", (scope, limit)).fetchall()
        return [self._event(row) for row in reversed(rows)]
