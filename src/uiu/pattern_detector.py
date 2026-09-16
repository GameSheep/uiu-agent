"""Action sequence pattern detector — discover repetitive loop bodies in user actions.

Finds repeating subsequence patterns from a continuous stream of recorded GUI steps,
automatically stripping initial setup and final teardown actions to extract the
minimal repeating loop unit.
"""

from __future__ import annotations

import json
from typing import Any


def _step_to_token(step: dict[str, Any], coord_bin: int = 15) -> str:
    """Convert a step dict into a canonical token string for pattern matching.

    coord_bin: spatial tolerance grid in pixels to absorb minor manual mouse jitter.
    """
    t = step.get("t", step.get("action", "")).lower().strip()
    if t in ("click", "click_at"):
        x = int(step.get("x", 0)) // coord_bin
        y = int(step.get("y", 0)) // coord_bin
        btn = step.get("button", "left")
        return f"click:{btn}:{x}:{y}"
    elif t == "key":
        return f"key:{step.get('key', '')}"
    elif t == "hotkey":
        keys = "+".join(sorted(str(k) for k in step.get("keys", [])))
        return f"hotkey:{keys}"
    elif t in ("type", "type_text"):
        txt = step.get("text", "")
        # Use length or token to distinguish text inputs without being overly brittle
        return f"type:{len(txt)}"
    elif t == "scroll":
        clicks = int(step.get("clicks", 0))
        direction = "up" if clicks > 0 else "down"
        return f"scroll:{direction}"
    elif t == "wait":
        return "wait"
    return f"other:{t}"


def detect_repeating_loop(steps: list[dict[str, Any]],
                          min_repetitions: int = 2,
                          min_loop_length: int = 1,
                          coord_bin: int = 15) -> dict[str, Any]:
    """Detect the most significant repeating subsequence in a list of steps.

    Returns:
    {
        "found": bool,
        "period": int,              # Steps in single loop
        "repetitions": int,         # How many cycles were observed
        "start_index": int,         # Start of repeating region in input steps
        "end_index": int,           # End of repeating region (exclusive)
        "loop_steps": list[dict],   # The isolated single loop body
        "summary": str,             # Human readable explanation
    }
    """
    if not steps or len(steps) < (min_loop_length * min_repetitions):
        return {
            "found": False,
            "period": 0,
            "repetitions": 0,
            "start_index": 0,
            "end_index": 0,
            "loop_steps": [],
            "summary": "步骤数量过少，不足以检测重复规律",
        }

    tokens = [_step_to_token(s, coord_bin=coord_bin) for s in steps]
    n = len(tokens)

    best_pattern = None
    best_score = 0  # score = length * repetitions

    # Try every candidate start position (stripping prefix noise)
    for start in range(n - (min_loop_length * min_repetitions) + 1):
        # Try every candidate loop length
        max_len = (n - start) // min_repetitions
        for length in range(min_loop_length, max_len + 1):
            pattern = tokens[start:start + length]
            reps = 1
            idx = start + length

            # Count consecutive matches of this pattern
            while idx + length <= n:
                candidate = tokens[idx:idx + length]
                if candidate == pattern:
                    reps += 1
                    idx += length
                else:
                    break

            if reps >= min_repetitions:
                score = length * reps
                if score > best_score:
                    best_score = score
                    best_pattern = {
                        "start": start,
                        "length": length,
                        "reps": reps,
                        "end": idx,
                    }

    if not best_pattern:
        return {
            "found": False,
            "period": 0,
            "repetitions": 0,
            "start_index": 0,
            "end_index": 0,
            "loop_steps": [],
            "summary": f"未检测到连续重复 ≥{min_repetitions} 次的操作模式",
        }

    s_idx = best_pattern["start"]
    period = best_pattern["length"]
    reps = best_pattern["reps"]
    e_idx = best_pattern["end"]

    # Extract the representative loop body (we pick the second repetition if available,
    # as it's typically cleaner than the first where user was still finding their rhythm)
    chosen_start = s_idx + period if reps >= 2 else s_idx
    loop_steps = steps[chosen_start:chosen_start + period]

    summary = f"成功检测到重复操作规律：每周期 {period} 步，连续重复了 {reps} 轮（已切片提取为标准循环宏）"

    return {
        "found": True,
        "period": period,
        "repetitions": reps,
        "start_index": s_idx,
        "end_index": e_idx,
        "loop_steps": loop_steps,
        "summary": summary,
    }
