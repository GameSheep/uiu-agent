"""Memory + RAG — semantic memory with vector database.

Enhances MEMORY.md with semantic search using ChromaDB + Sentence Transformers.

Features:
- auto_embed(): index MEMORY.md into vector DB
- recall_semantic(query): semantic search across memories
- add_memory(text): add a new memory and index it
- memory_state(): check RAG status

Install:
    pip install chromadb sentence-transformers
"""

from __future__ import annotations

import os
import hashlib
from datetime import datetime
from pathlib import Path


# ---------- vector store ----------

class VectorMemory:
    """Vector-backed memory store using ChromaDB."""

    def __init__(self, persist_dir: str):
        self.persist_dir = persist_dir
        self._client = None
        self._collection = None

    def _ensure_initialized(self) -> bool:
        """Lazy-initialize ChromaDB. Returns True if ready."""
        if self._collection is not None:
            return True

        try:
            import chromadb
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        except ImportError:
            return False

        os.makedirs(self.persist_dir, exist_ok=True)

        self._client = chromadb.PersistentClient(path=self.persist_dir)

        # Use sentence-transformers for embedding (works offline)
        embed_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",  # 384-dim, fast, good quality
        )

        self._collection = self._client.get_or_create_collection(
            name="uiu_memory",
            embedding_function=embed_fn,
        )

        return True

    def add(self, text: str, metadata: dict | None = None) -> bool:
        """Add a memory entry to the vector store."""
        if not self._ensure_initialized():
            return False

        # Generate stable ID from content
        doc_id = hashlib.md5(text.encode()).hexdigest()[:16]

        meta = {
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        }

        try:
            self._collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[meta],
            )
            return True
        except Exception:
            return False

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Semantic search for memories."""
        if not self._ensure_initialized():
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
            )

            memories = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]

            for doc, meta, dist in zip(docs, metas, dists):
                memories.append({
                    "text": doc,
                    "metadata": meta,
                    "score": 1.0 - dist,  # convert distance to similarity
                })

            return memories
        except Exception:
            return []

    def count(self) -> int:
        """Get number of indexed memories."""
        if not self._ensure_initialized():
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self) -> bool:
        """Clear all memories."""
        if not self._ensure_initialized():
            return False
        try:
            self._client.delete_collection("uiu_memory")
            self._collection = None
            self._ensure_initialized()
            return True
        except Exception:
            return False


# ---------- global instance ----------

_vector_memory: VectorMemory | None = None


def get_vector_memory(persist_dir: str | None = None) -> VectorMemory:
    """Get or create the global VectorMemory instance."""
    global _vector_memory
    if _vector_memory is None:
        if persist_dir is None:
            persist_dir = str(Path.home() / ".uiu" / "memory_vectors")
        _vector_memory = VectorMemory(persist_dir)
    return _vector_memory


# ---------- public API ----------

def auto_embed(memory_text: str) -> str:
    """Index MEMORY.md content into vector store.

    Splits by sections (## or ### headers) and indexes each.
    """
    import re

    vm = get_vector_memory()

    # Split by headers (## or ###)
    sections = re.split(r"\n(?=#{2,3}\s)", memory_text.strip())

    added = 0
    for section in sections:
        section = section.strip()
        if not section or len(section) < 10:
            continue

        # Extract header as metadata
        header_match = re.match(r"#{2,3}\s+(.+)", section)
        title = header_match.group(1) if header_match else "untitled"

        if vm.add(section, metadata={"title": title, "source": "MEMORY.md"}):
            added += 1

    if added:
        return f"[ok] 已索引 {added} 条记忆到向量数据库"
    return "[ok] 无新记忆需要索引（或向量数据库未安装）"


def recall_semantic(query: str, n_results: int = 5) -> str:
    """Semantic search across all memories.

    query: what to search for
    n_results: number of results to return
    """
    vm = get_vector_memory()
    results = vm.search(query, n_results=n_results)

    if not results:
        return f"未找到与 '{query}' 相关的记忆"

    lines = [f"语义搜索 '{query}' 结果 ({len(results)} 条):"]
    for i, r in enumerate(results, 1):
        score = r["score"]
        text = r["text"][:150].replace("\n", " ")
        title = r["metadata"].get("title", "")
        lines.append(f"  {i}. [{score:.2f}] {title}: {text}...")

    return "\n".join(lines)


def add_memory(text: str, title: str = "") -> str:
    """Add a new memory and index it in the vector store.

    The plain-text entry is appended to the SAME MEMORY.md used by
    memory_add (learning), using the same `- [date]` line format, so the
    two memory tools never diverge. The vector index is an enhancement.
    """
    vm = get_vector_memory()

    # Locate workspace memory file consistently (env > cwd > home)
    memory_path = _workspace_memory_path()

    # Append to MEMORY.md using learning's line format: - [YYYY-MM-DD] text
    timestamp = datetime.now().strftime("%Y-%m-%d")
    entry = f"- [{timestamp}] {text.strip()}\n"

    try:
        from ._atomic import atomic_write_text, file_lock
        with file_lock(memory_path):        # 读-改-写必须互斥，否则并发追加会丢条目
            if memory_path.exists():
                existing = memory_path.read_text(encoding="utf-8")
                atomic_write_text(memory_path, existing + entry)
            else:
                memory_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(memory_path, f"# MEMORY\n{entry}")
    except Exception:
        return "[error] 写入 MEMORY.md 失败"

    # 通知运行期会话热刷新（与 learning.memory_add 同一钩子）
    try:
        from .learning import notify_memory_changed as _notify
        _notify()
    except Exception:
        pass

    # Index in vector store
    if vm.add(text.strip(), metadata={"title": title or "记忆", "source": "manual"}):
        return f"[ok] 已添加记忆: {title or text.strip()[:30]}"
    return "[ok] 已添加到 MEMORY.md（向量索引未安装，可 pip install uiu[rag]）"


def _workspace_memory_path() -> Path:
    """Locate the active workspace's MEMORY.md (same file as learning.memory_add)."""
    try:
        from .learning import _memory_path as _learning_memory_path
        return _learning_memory_path()
    except Exception:
        pass
    import os as _os
    env = _os.environ.get("UIU_WORKSPACE")
    candidates = []
    if env:
        candidates.append(Path(env).expanduser() / "MEMORY.md")
    candidates += [
        Path.cwd() / "workspace" / "MEMORY.md",
        Path.home() / "workspace" / "MEMORY.md",
        Path.home() / ".uiu" / "workspace" / "MEMORY.md",
    ]
    # Prefer existing file; else first candidate dir that exists
    for p in candidates:
        if p.exists():
            return p
    for p in candidates:
        if p.parent.is_dir():
            return p
    return candidates[0]


def memory_state() -> str:
    """Check RAG/memory system status."""
    lines = []

    # Check chromadb
    try:
        import chromadb
        lines.append("✅ chromadb (向量数据库)")
    except ImportError:
        lines.append("❌ chromadb (未安装: pip install chromadb)")

    # Check sentence-transformers
    try:
        import sentence_transformers
        lines.append("✅ sentence-transformers (嵌入模型)")
    except ImportError:
        lines.append("❌ sentence-transformers (未安装: pip install sentence-transformers)")

    # Vector count
    vm = get_vector_memory()
    count = vm.count()
    lines.append(f"\n已索引记忆: {count} 条")

    return "\n".join(lines)


# ---------- tool definitions ----------

AUTO_EMBED_DEF = {
    "type": "function",
    "function": {
        "name": "auto_embed",
        "description": "将 MEMORY.md 内容索引到向量数据库，支持语义搜索。首次使用或记忆更新时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_text": {"type": "string", "description": "MEMORY.md 的完整内容"},
            },
            "required": ["memory_text"],
        },
    },
}

RECALL_SEMANTIC_DEF = {
    "type": "function",
    "function": {
        "name": "recall_semantic",
        "description": "语义搜索记忆。比关键词匹配更智能，能理解含义相近的查询。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的内容"},
                "n_results": {"type": "integer", "description": "返回结果数量（默认 5）"},
            },
            "required": ["query"],
        },
    },
}

ADD_MEMORY_DEF = {
    "type": "function",
    "function": {
        "name": "add_memory",
        "description": "添加一条新记忆到 MEMORY.md 并索引到向量数据库。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "记忆内容"},
                "title": {"type": "string", "description": "记忆标题/分类（可选）"},
            },
            "required": ["text"],
        },
    },
}

MEMORY_STATE_DEF = {
    "type": "function",
    "function": {
        "name": "memory_state",
        "description": "检查记忆系统状态（向量数据库、嵌入模型是否可用）",
        "parameters": {"type": "object", "properties": {}},
    },
}


MEMORY_TOOLS: dict[str, dict] = {
    "auto_embed": {"def": AUTO_EMBED_DEF, "fn": auto_embed},
    "recall_semantic": {"def": RECALL_SEMANTIC_DEF, "fn": recall_semantic},
    "add_memory": {"def": ADD_MEMORY_DEF, "fn": add_memory},
    "memory_state": {"def": MEMORY_STATE_DEF, "fn": memory_state},
}


def memory_tool_defs() -> list[dict]:
    return [t["def"] for t in MEMORY_TOOLS.values()]


def call_memory_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in MEMORY_TOOLS:
        return f"[error] unknown memory tool: {name}"
    fn = MEMORY_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
