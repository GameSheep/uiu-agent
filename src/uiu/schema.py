"""数据格式版本与迁移（审计 §3.3）。

问题：config.yaml / sessions/*.json / cron/jobs.json 都是「写下去就永远读回来」，
格式一旦演进，老用户的文件没有任何升级路径。

机制（最小但完整）：
- 每个存储带 schema 版本；读时自动迁移到 CURRENT
- 迁移是**纯函数**：旧 payload → 新 payload，不碰磁盘
- 迁移前备份由调用方负责（见 uiu.backup，daemon 起手会做每日备份）
- 未知/未来版本不猜测：保持原样交给容错读处理

注意：AppConfig.from_dict 里的字段级兼容（旧 model: 是字符串等）仍然保留，
那是「同版本内的字段规范化」；这里管的是**存储格式版本**。
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ["CURRENT", "STORES", "current", "detect", "needs_migration", "migrate", "stamp"]

CURRENT: dict[str, int] = {"config": 1, "session": 1, "jobs": 1}
STORES = tuple(CURRENT)


def current(store: str) -> int:
    return CURRENT[store]


def detect(store: str, payload: Any) -> int:
    """声明式版本优先；没有 schema 键的文件一律视为 0（引入版本之前的老格式）。"""
    if isinstance(payload, dict):
        raw = payload.get("schema")
        if isinstance(raw, bool):
            return 0
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
    return 0


def needs_migration(store: str, payload: Any) -> bool:
    return detect(store, payload) < CURRENT[store]


def stamp(store: str, payload: Any) -> Any:
    """给即将落盘的 payload 打上当前版本号。"""
    if isinstance(payload, dict):
        data = dict(payload)
        data["schema"] = CURRENT[store]
        return data
    return payload


# ---------- 迁移步骤（每个函数只管一个版本跨度） ----------


def _session_0_to_1(payload: Any) -> Any:
    """老会话：{id, updated, messages}（无 schema），更老的可能是裸消息列表。"""
    if isinstance(payload, list):
        return {"schema": 1, "id": "", "updated": 0.0, "messages": payload}
    data = dict(payload or {})
    if not isinstance(data.get("messages"), list):
        data["messages"] = []
    data["schema"] = 1
    return data


def _jobs_0_to_1(payload: Any) -> Any:
    """老 jobs.json 顶层是裸 list；v1 变成 {schema:1, jobs:[...]}。"""
    if isinstance(payload, list):
        return {"schema": 1, "jobs": payload}
    data = dict(payload or {})
    if not isinstance(data.get("jobs"), list):
        data["jobs"] = []
    data["schema"] = 1
    return data


def _config_0_to_1(payload: Any) -> Any:
    data = dict(payload or {})
    data["schema"] = 1
    return data


_STEPS: dict[tuple[str, int], Callable[[Any], Any]] = {
    ("session", 0): _session_0_to_1,
    ("jobs", 0): _jobs_0_to_1,
    ("config", 0): _config_0_to_1,
}


def migrate(store: str, payload: Any) -> tuple[Any, list[str]]:
    """把 payload 升到 CURRENT，返回 (新 payload, 已应用的步骤描述)。"""
    if store not in CURRENT:
        raise KeyError(f"未知存储: {store}")
    version = detect(store, payload)
    applied: list[str] = []
    while version < CURRENT[store]:
        step = _STEPS.get((store, version))
        if step is None:
            break            # 没有迁移路径：不猜，交由调用方的容错读处理
        payload = step(payload)
        version += 1
        applied.append(f"{store} {version - 1}->{version}")
    return payload, applied
