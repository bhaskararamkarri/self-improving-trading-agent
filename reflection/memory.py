"""Vector memory store for trading lessons using ChromaDB."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import CHROMA_PERSIST_DIR, logger

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    logger.warning("ChromaDB is not installed. Vector memory will run in JSON file fallback mode.")


class LessonMemory:
    """Manages long-term vector memory for self-improving trading lessons."""

    COLLECTION_NAME = "trading_lessons"
    MAX_ACTIVE_LESSONS = 10

    def __init__(self, persist_directory: Path = CHROMA_PERSIST_DIR):
        self.persist_dir = Path(persist_directory)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.fallback_file = self.persist_dir / "lessons_fallback.json"
        self.client = None
        self.collection = None

        if HAS_CHROMADB:
            try:
                self.client = chromadb.PersistentClient(path=str(self.persist_dir))
                self.collection = self.client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"description": "Trading lessons learned from trade history and daily reflection."},
                )
                logger.info(f"Initialized ChromaDB collection '{self.COLLECTION_NAME}' at {self.persist_dir}")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB PersistentClient: {e}. Using JSON fallback.")
                self.collection = None

    def add_lesson(self, lesson_text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Stores an actionable trading lesson in vector memory, maintaining max 10 active lessons (FIFO)."""
        lesson_id = str(uuid.uuid4())
        meta = metadata or {}
        meta["timestamp"] = meta.get("timestamp", datetime.utcnow().isoformat())
        meta["date"] = meta.get("date", datetime.utcnow().strftime("%Y-%m-%d"))

        # Convert list tags to comma-separated string for ChromaDB compatibility
        if "tags" in meta and isinstance(meta["tags"], list):
            meta["tags"] = ", ".join(meta["tags"])

        if self.collection is not None:
            try:
                # Enforce max 10 active lessons limit (prune oldest if at capacity)
                count = self.collection.count()
                if count >= self.MAX_ACTIVE_LESSONS:
                    existing = self.collection.get()
                    existing_ids = existing.get("ids", [])
                    existing_metas = existing.get("metadatas", [])

                    # Sort by timestamp ascending to identify oldest
                    items = list(zip(existing_ids, existing_metas))
                    items.sort(key=lambda x: (x[1] or {}).get("timestamp", ""))
                    num_to_delete = count - self.MAX_ACTIVE_LESSONS + 1
                    ids_to_delete = [item[0] for item in items[:num_to_delete]]

                    if ids_to_delete:
                        self.collection.delete(ids=ids_to_delete)
                        logger.info(f"Pruned {len(ids_to_delete)} oldest lesson(s) to maintain max {self.MAX_ACTIVE_LESSONS} limit.")

                self.collection.add(
                    documents=[lesson_text],
                    metadatas=[meta],
                    ids=[lesson_id],
                )
                logger.info(f"Added lesson to ChromaDB: '{lesson_text[:80]}...' [ID: {lesson_id[:8]}]")
                return lesson_id
            except Exception as e:
                logger.error(f"Error adding lesson to ChromaDB: {e}. Saving to fallback.")

        # Fallback JSON persistence with max 10 FIFO limit
        lessons = self._read_fallback_lessons()
        while len(lessons) >= self.MAX_ACTIVE_LESSONS:
            lessons.pop(0)  # Remove oldest

        lessons.append({
            "id": lesson_id,
            "text": lesson_text,
            "metadata": meta,
        })
        self._write_fallback_lessons(lessons)
        logger.info(f"Saved lesson to fallback storage: '{lesson_text[:80]}...'")
        return lesson_id

    def retrieve_lessons(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Retrieves top N relevant past trading lessons for a given market query."""
        if not query or not query.strip():
            query = "market trend indicators RSI MACD risk management"

        if self.collection is not None:
            try:
                count = self.collection.count()
                if count == 0:
                    return self._get_default_lessons()

                actual_n = min(n_results, count)
                results = self.collection.query(
                    query_texts=[query],
                    n_results=actual_n,
                )
                documents = results.get("documents", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                ids = results.get("ids", [[]])[0]
                if documents:
                    logger.debug(f"Retrieved {len(documents)} lessons from ChromaDB for query: '{query[:50]}...'")
                    return [{"id": ids[i], "text": documents[i], "metadata": metadatas[i] if metadatas else {}} for i in range(len(documents))]
            except Exception as e:
                logger.error(f"ChromaDB retrieval error: {e}. Using fallback.")

        # Fallback keyword matching / recency
        fallback_lessons = self._read_fallback_lessons()
        if not fallback_lessons:
            return self._get_default_lessons()

        return fallback_lessons[-n_results:]

    def get_all_lessons(self) -> List[Dict[str, Any]]:
        """Retrieves all stored lessons with metadata."""
        if self.collection is not None:
            try:
                results = self.collection.get()
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])
                ids = results.get("ids", [])
                return [
                    {"id": i, "text": doc, "metadata": m}
                    for i, doc, m in zip(ids, docs, metas)
                ]
            except Exception as e:
                logger.error(f"Error fetching all ChromaDB lessons: {e}")

        return self._read_fallback_lessons()

    def clear_lessons(self) -> None:
        """Clears all stored trading lessons in ChromaDB and the JSON fallback file."""
        if self.collection is not None and self.client is not None:
            try:
                self.client.delete_collection(name=self.COLLECTION_NAME)
                self.collection = self.client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"description": "Trading lessons learned from trade history and daily reflection."},
                )
                logger.info(f"Cleared ChromaDB collection '{self.COLLECTION_NAME}'.")
            except Exception as e:
                logger.error(f"Error clearing ChromaDB collection: {e}")

        if self.fallback_file.exists():
            try:
                self.fallback_file.unlink()
                logger.info("Cleared fallback lessons JSON file.")
            except Exception as e:
                logger.error(f"Error removing fallback lessons file: {e}")

    def _read_fallback_lessons(self) -> List[Dict[str, Any]]:
        if not self.fallback_file.exists():
            return []
        try:
            with open(self.fallback_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_fallback_lessons(self, lessons: List[Dict[str, Any]]) -> None:
        try:
            with open(self.fallback_file, "w", encoding="utf-8") as f:
                json.dump(lessons, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing fallback lessons: {e}")

    @staticmethod
    def _get_default_lessons() -> List[Dict[str, Any]]:
        """Provides foundational trading heuristics before any reflection cycles occur."""
        lessons = [
            "Never buy when RSI is above 75 (extreme overbought) without exceptional volume confirmation.",
            "Respect the 2% stop-loss strictly; cutting losers early preserves capital for winning setups.",
            "Avoid taking buy signals when price is below both 50 EMA and 200 EMA during strong downtrends.",
            "Look for MACD bullish crossovers that coincide with RSI rising above 50 for higher conviction entries.",
            "Take profit at 4% target or trail stops when Bollinger Band upper resistance is reached.",
        ]
        return [{"id": f"default_{i}", "text": text, "metadata": {"min_sample_size": 5, "loss_rate": 0.65}} for i, text in enumerate(lessons)]
