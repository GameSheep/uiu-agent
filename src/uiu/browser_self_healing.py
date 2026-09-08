"""Browser Visual Self-Healing & Macro Hot-Patching Interceptor.

Provides dynamic 3-tier resilient execution:
1. Tier 1 (DOM Fast-Path): Tries composite fingerprint selectors (TestID, Aria/Semantic, ID, Text, CSS) with 1.2s tight timeout.
2. Tier 2 (Visual OCR Fallback): When DOM selectors fail due to frontend UI revamps or class-name mangling,
   captures a viewport screenshot, runs local RapidOCR to re-locate the target by text and intent, executes the click,
   and queries `document.elementFromPoint()` to extract the updated selector.
3. Tier 3 (In-Place Hot-Patching): Automatically rewrites the stored Playwright macro script on disk,
   repairing the broken selector permanently so future runs immediately hit the sub-50ms fast path.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Locator, Page


def _extract_element_at_point(page: Page, cx: float, cy: float) -> dict[str, Any]:
    """Inspect and extract composite fingerprint from the element located at (cx, cy)."""
    js = """
    ([x, y]) => {
        const el = document.elementFromPoint(x, y);
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const idAttr = el.id && !el.id.match(/^[0-9]+$/) ? el.id : '';
        const nameAttr = el.getAttribute('name') || '';
        let text = (el.innerText || el.value || ariaLabel || '').trim().replace(/\\s+/g, ' ').slice(0, 80);

        let selector = '';
        if (testId) {
            selector = `[data-testid="${testId}"]`;
        } else if (idAttr) {
            selector = '#' + CSS.escape(idAttr);
        } else if (nameAttr) {
            selector = `${el.tagName.toLowerCase()}[name="${nameAttr}"]`;
        } else if (ariaLabel) {
            selector = `${el.tagName.toLowerCase()}[aria-label="${ariaLabel}"]`;
        } else if (text && text.length < 30) {
            selector = `${el.tagName.toLowerCase()}:has-text("${text}")`;
        } else {
            selector = el.tagName.toLowerCase();
        }

        return {
            tag: el.tagName.toLowerCase(),
            testId: testId,
            id: idAttr,
            ariaLabel: ariaLabel,
            name: nameAttr,
            text: text,
            selector: selector,
            bbox: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            }
        };
    }
    """
    try:
        res = page.evaluate(js, [cx, cy])
        return res if isinstance(res, dict) else {}
    except Exception:
        return {}


def _ocr_find_in_image(img: Image.Image, target_text: str) -> dict[str, Any] | None:
    """Run RapidOCR on a PIL image to find coordinates of target_text."""
    from .screen_tools import _get_rapidocr_engine
    import numpy as np

    engine = _get_rapidocr_engine()
    if engine is None:
        return None

    img_np = np.array(img.convert("RGB"))
    results, _ = engine(img_np)
    if not results:
        return None

    target_clean = target_text.strip().lower()
    best_match = None
    highest_score = 0.0

    for box, text, score in results:
        t_clean = text.strip().lower()
        if not t_clean:
            continue
        # Check exact or substring containment
        if target_clean == t_clean or target_clean in t_clean or t_clean in target_clean:
            x1, y1 = box[0]
            x2, y2 = box[2]
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            current_score = float(score)
            if target_clean == t_clean:
                current_score += 1.0  # boost exact match
            if current_score > highest_score:
                highest_score = current_score
                best_match = {
                    "text": text,
                    "cx": cx,
                    "cy": cy,
                    "box": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)],
                    "score": float(score),
                }

    return best_match


def patch_macro_file(
    macro_path: Path | str,
    old_selector: str,
    new_selector: str,
) -> bool:
    """Hot-patch a macro python file on disk by replacing broken selectors with updated ones."""
    p = Path(macro_path)
    if not p.is_file():
        return False

    try:
        content = p.read_text(encoding="utf-8")
        if old_selector and old_selector in content:
            updated = content.replace(old_selector, new_selector)
            p.write_text(updated, encoding="utf-8")
            return True
    except Exception:
        pass
    return False


def resilient_browser_action(
    page: Page,
    step_meta: dict[str, Any],
    macro_file_path: Path | str | None = None,
    dom_timeout_ms: float = 1200.0,
) -> dict[str, Any]:
    """Execute a browser action using multi-tier resilient self-healing:
    Tier 1: DOM selectors (TestID, Aria, ID, Text, CSS) with fast timeout.
    Tier 2: Visual OCR recovery if DOM changed.
    Tier 3: In-place macro hot-patching.
    """
    action = step_meta.get("action", "click").lower()
    value = step_meta.get("value", "")
    fingerprint = step_meta.get("fingerprint", {})
    target = step_meta.get("target", "")

    # Build prioritized candidate selectors
    candidates: list[str] = []

    if fingerprint.get("testId"):
        candidates.append(f'[data-testid="{fingerprint["testId"]}"]')
    if fingerprint.get("id"):
        candidates.append(f'#{fingerprint["id"]}')
    if fingerprint.get("ariaLabel"):
        candidates.append(f'[aria-label="{fingerprint["ariaLabel"]}"]')
    if fingerprint.get("semantic"):
        candidates.append(fingerprint["semantic"])
    if fingerprint.get("text"):
        t = fingerprint["text"]
        if len(t) <= 40:
            candidates.append(f'text="{t}"')
    if fingerprint.get("css"):
        candidates.append(fingerprint["css"])
    if isinstance(target, str) and target:
        if target not in candidates:
            candidates.append(target)

    # ---------- Tier 1: DOM Fast-Path ----------
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=dom_timeout_ms):
                loc.scroll_into_view_if_needed(timeout=dom_timeout_ms)
                if action in ("click", "click_element"):
                    loc.click(timeout=dom_timeout_ms)
                elif action in ("fill", "type", "input"):
                    loc.fill(value, timeout=dom_timeout_ms)
                elif action == "hover":
                    loc.hover(timeout=dom_timeout_ms)

                try:
                    page.wait_for_load_state("domcontentloaded", timeout=1500)
                except Exception:
                    pass

                return {
                    "success": True,
                    "tier": "dom",
                    "selector_used": sel,
                    "action": action,
                    "healed": False,
                }
        except Exception:
            continue

    # ---------- Tier 2: Visual OCR Fallback ----------
    search_text = (
        fingerprint.get("text")
        or fingerprint.get("ariaLabel")
        or (target if isinstance(target, str) and not target.startswith(("#", ".", "[", "xpath=")) else "")
    )

    if search_text:
        try:
            screenshot_bytes = page.screenshot()
            img = Image.open(io.BytesIO(screenshot_bytes))
            match = _ocr_find_in_image(img, search_text)

            if match:
                cx, cy = match["cx"], match["cy"]
                # Click via coordinates
                page.mouse.click(cx, cy)
                time.sleep(0.3)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=1500)
                except Exception:
                    pass

                # Inspect updated DOM element at point
                new_info = _extract_element_at_point(page, cx, cy)
                new_selector = new_info.get("selector") or f'text="{match["text"]}"'

                patched = False
                if macro_file_path and candidates and new_selector:
                    for old_cand in candidates:
                        alt_cand = old_cand.replace('"', "'") if '"' in old_cand else old_cand.replace("'", '"')
                        if patch_macro_file(macro_file_path, old_cand, new_selector):
                            patched = True
                            break
                        if patch_macro_file(macro_file_path, alt_cand, new_selector):
                            patched = True
                            break

                return {
                    "success": True,
                    "tier": "visual_healed",
                    "action": action,
                    "healed": True,
                    "matched_text": match["text"],
                    "coords": (cx, cy),
                    "new_selector": new_selector,
                    "patched": patched,
                    "note": f"DOM 选择器失效，已通过 OCR 视觉定位成功点击 ('{match['text']}' @ ({int(cx)}, {int(cy)}))",
                }
        except Exception as e:
            pass

    # ---------- Tier 3: Bounding Box Safe Click Fallback ----------
    bbox = fingerprint.get("bbox")
    if bbox and "cx" in bbox and "cy" in bbox:
        try:
            page.mouse.click(bbox["cx"], bbox["cy"])
            time.sleep(0.3)
            return {
                "success": True,
                "tier": "bbox_fallback",
                "action": action,
                "healed": True,
                "coords": (bbox["cx"], bbox["cy"]),
                "note": f"DOM 与 OCR 未完全匹配，采用历史几何坐标 ({bbox['cx']}, {bbox['cy']}) 兜底点击",
            }
        except Exception:
            pass

    return {
        "success": False,
        "tier": "failed",
        "action": action,
        "error": f"所有 DOM 选择器 ({len(candidates)} 个) 与视觉 OCR 兜底均未能命中目标 (意图: '{search_text}')",
        "candidates": candidates,
    }
