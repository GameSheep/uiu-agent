"""Browser Exploratory Step Engine & Composite Fingerprint Capturer.

Implements the interactive ReAct exploration loop for web automation:
1. Capture Page State (A11y/DOM interactive elements + viewport metadata).
2. Atomic Playwright step execution with multi-strategy resolution.
3. Composite Fingerprint extraction (Semantic Role, Stable Attributes, Text, CSS, Bounding Box).
4. Step effect verification (URL changes, DOM mutations, network settle).
5. Continuous trajectory recording for self-learning compilation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Locator, Page


JS_GET_INTERACTIVE_ELEMENTS = """
(() => {
    const results = [];
    const elements = document.querySelectorAll(
        'button, a[href], input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="tab"], [onclick], [tabindex]:not([tabindex="-1"])'
    );

    let idCounter = 1;
    for (const el of elements) {
        // Skip hidden or invisible elements
        const rect = el.getBoundingClientRect();
        if (rect.width <= 2 || rect.height <= 2) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

        // Extract stable identifiers
        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const nameAttr = el.getAttribute('name') || '';
        const idAttr = el.id && !el.id.match(/^[0-9]+$/) && !el.id.includes('random') ? el.id : '';
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        
        // Extract visible text (truncated)
        let text = (el.innerText || el.value || ariaLabel || placeholder || '').trim();
        text = text.replace(/\\s+/g, ' ').slice(0, 80);

        // Build compact CSS selector
        let css = '';
        if (idAttr) {
            css = '#' + CSS.escape(idAttr);
        } else if (testId) {
            css = `[data-testid="${testId}"]`;
        } else if (nameAttr) {
            css = `${el.tagName.toLowerCase()}[name="${nameAttr}"]`;
        } else {
            let path = el.tagName.toLowerCase();
            if (el.className && typeof el.className === 'string') {
                const classes = el.className.split(/\\s+/).filter(c => c && !c.includes(':') && c.length < 30).slice(0, 2);
                if (classes.length > 0) path += '.' + classes.join('.');
            }
            css = path;
        }

        results.push({
            ref: idCounter++,
            tag: el.tagName.toLowerCase(),
            role: role,
            text: text,
            testId: testId,
            ariaLabel: ariaLabel,
            placeholder: placeholder,
            id: idAttr,
            name: nameAttr,
            css: css,
            bbox: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            }
        });
        if (results.length >= 60) break;
    }
    return results;
})()
"""

JS_EXTRACT_ELEMENT_FINGERPRINT = """
(el) => {
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const nameAttr = el.getAttribute('name') || '';
    const idAttr = el.id && !el.id.match(/^[0-9]+$/) ? el.id : '';
    const role = el.getAttribute('role') || el.tagName.toLowerCase();
    let text = (el.innerText || el.value || ariaLabel || placeholder || '').trim();
    text = text.replace(/\\s+/g, ' ').slice(0, 100);

    // Build specific selectors
    let semantic = '';
    if (ariaLabel) {
        semantic = `${el.tagName.toLowerCase()}[aria-label="${ariaLabel}"]`;
    } else if (text && text.length <= 40) {
        semantic = `${el.tagName.toLowerCase()}:has-text("${text}")`;
    }

    let css = '';
    if (idAttr) {
        css = '#' + CSS.escape(idAttr);
    } else if (testId) {
        css = `[data-testid="${testId}"]`;
    } else if (nameAttr) {
        css = `${el.tagName.toLowerCase()}[name="${nameAttr}"]`;
    } else {
        css = el.tagName.toLowerCase();
    }

    return {
        tag: el.tagName.toLowerCase(),
        role: role,
        text: text,
        testId: testId,
        ariaLabel: ariaLabel,
        placeholder: placeholder,
        id: idAttr,
        name: nameAttr,
        semantic: semantic,
        css: css,
        bbox: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            cx: Math.round(rect.x + rect.width / 2),
            cy: Math.round(rect.y + rect.height / 2),
        }
    };
}
"""


def capture_page_state(page: Page, max_elements: int = 50) -> dict[str, Any]:
    """Capture current page state: URL, title, and interactive element list."""
    try:
        url = page.url
        title = page.title()
    except Exception as e:
        return {"error": f"Failed to get page state: {e}", "elements": []}

    try:
        elements = page.evaluate(JS_GET_INTERACTIVE_ELEMENTS)
        if not isinstance(elements, list):
            elements = []
        elements = elements[:max_elements]
    except Exception as e:
        elements = []

    return {
        "url": url,
        "title": title,
        "element_count": len(elements),
        "elements": elements,
    }


def format_page_state_for_agent(state: dict[str, Any]) -> str:
    """Format the captured page state into a clean, LLM-friendly view."""
    if "error" in state:
        return f"[error] {state['error']}"

    lines = [
        f"**页面标题:** {state.get('title', '')}",
        f"**当前 URL:** {state.get('url', '')}",
        f"**可交互元素 (前 {state.get('element_count', 0)} 个):**",
    ]
    for el in state.get("elements", []):
        ref = el.get("ref")
        tag = el.get("tag")
        role = el.get("role")
        text = el.get("text")
        testid = el.get("testId")
        aria = el.get("ariaLabel")
        desc = text or aria or testid or el.get("placeholder") or el.get("css")
        meta = []
        if testid:
            meta.append(f'testid="{testid}"')
        if el.get("id"):
            meta.append(f'id="#{el.get("id")}"')
        meta_str = f" ({', '.join(meta)})" if meta else ""
        lines.append(f"  [{ref}] <{tag}:{role}> \"{desc}\"{meta_str}")

    return "\n".join(lines)


def resolve_element_locator(
    page: Page,
    target: str | int | dict[str, Any],
    cached_elements: list[dict[str, Any]] | None = None,
) -> tuple[Locator | None, dict[str, Any] | None]:
    """Resolve a target reference (ref int, selector string, or fingerprint dict) to a Playwright Locator."""
    # 1. Numeric reference matching cached elements
    if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
        ref_idx = int(target)
        if not cached_elements:
            cached_elements = page.evaluate(JS_GET_INTERACTIVE_ELEMENTS) or []
        for el in cached_elements:
            if el.get("ref") == ref_idx:
                # Prioritize stable attrs
                if el.get("testId"):
                    loc = page.locator(f'[data-testid="{el["testId"]}"]').first
                elif el.get("id"):
                    loc = page.locator(f'#{el["id"]}').first
                elif el.get("text"):
                    loc = page.get_by_text(el["text"], exact=False).first
                elif el.get("css"):
                    loc = page.locator(el["css"]).first
                else:
                    loc = page.locator(f"xpath=//*[text()='{el.get('text', '')}']").first
                return loc, el
        return None, None

    # 2. Dictionary with composite fingerprint
    if isinstance(target, dict):
        fp = target
        # Try in order: testid -> semantic/text -> id -> css
        if fp.get("testId"):
            loc = page.locator(f'[data-testid="{fp["testId"]}"]').first
            if loc.count() > 0:
                return loc, fp
        if fp.get("id"):
            loc = page.locator(f'#{fp["id"]}').first
            if loc.count() > 0:
                return loc, fp
        if fp.get("text"):
            loc = page.get_by_text(fp["text"], exact=False).first
            if loc.count() > 0:
                return loc, fp
        if fp.get("semantic"):
            loc = page.locator(fp["semantic"]).first
            if loc.count() > 0:
                return loc, fp
        if fp.get("css"):
            loc = page.locator(fp["css"]).first
            return loc, fp
        return None, fp

    # 3. String: could be selector, text, or xpath
    target_str = str(target).strip()
    # Check if target is a known selector syntax
    if target_str.startswith(("#", ".", "[", "xpath=", "//")) or " > " in target_str:
        loc = page.locator(target_str).first
        return loc, {"css": target_str}

    # Try exact / substring text match
    try:
        loc_text = page.get_by_text(target_str, exact=False).first
        if loc_text.count() > 0:
            return loc_text, {"text": target_str}
    except Exception:
        pass

    # Fallback to general locator
    return page.locator(target_str).first, {"css": target_str}


def extract_composite_fingerprint(locator: Locator, page: Page) -> dict[str, Any]:
    """Extract full composite fingerprint for a resolved locator."""
    try:
        element_handle = locator.element_handle()
        if element_handle:
            fp = page.evaluate(JS_EXTRACT_ELEMENT_FINGERPRINT, element_handle)
            if isinstance(fp, dict):
                return fp
    except Exception:
        pass
    return {"css": str(locator), "text": ""}


def execute_step(
    page: Page,
    action: str,
    target: str | int | dict[str, Any] = "",
    value: str = "",
    clear_before: bool = True,
    timeout_ms: float = 8000.0,
) -> dict[str, Any]:
    """Execute an atomic browser action and capture composite fingerprint + verification."""
    action = action.lower().strip()
    url_before = page.url
    t_start = time.perf_counter()

    # Locate element if target is provided
    locator: Locator | None = None
    fingerprint: dict[str, Any] = {}

    if target != "":
        locator, pre_fp = resolve_element_locator(page, target)
        if not locator:
            return {
                "success": False,
                "error": f"无法定位元素目标: {target}",
                "action": action,
                "target": target,
            }
        try:
            fingerprint = extract_composite_fingerprint(locator, page)
        except Exception:
            fingerprint = pre_fp or {}

    try:
        if action in ("click", "click_element"):
            if not locator:
                return {"success": False, "error": "Click requires target"}
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
            locator.click(timeout=timeout_ms)

        elif action in ("fill", "type", "input"):
            if not locator:
                return {"success": False, "error": "Fill requires target"}
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
            if clear_before:
                locator.fill(value, timeout=timeout_ms)
            else:
                locator.press_sequentially(value, timeout=timeout_ms)

        elif action == "press":
            key = value or str(target)
            page.keyboard.press(key)

        elif action == "hover":
            if not locator:
                return {"success": False, "error": "Hover requires target"}
            locator.hover(timeout=timeout_ms)

        elif action == "scroll":
            delta_y = int(value) if value else 400
            page.mouse.wheel(0, delta_y)

        elif action == "navigate":
            dest_url = value or str(target)
            page.goto(dest_url, timeout=timeout_ms)

        elif action == "wait":
            wait_s = float(value or 1.0)
            page.wait_for_timeout(wait_s * 1000)

        else:
            return {"success": False, "error": f"未知网页动作: {action}"}

        # Settle wait
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass

        url_after = page.url
        navigated = url_before != url_after
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        return {
            "success": True,
            "action": action,
            "target": target,
            "value": value,
            "fingerprint": fingerprint,
            "navigated": navigated,
            "url_before": url_before,
            "url_after": url_after,
            "elapsed_ms": round(elapsed_ms, 1),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"执行 {action} 失败: {type(e).__name__}: {e}",
            "action": action,
            "target": target,
            "fingerprint": fingerprint,
        }


@dataclass
class BrowserTrajectory:
    """Represents a recorded sequence of successful browser steps."""
    name: str
    description: str = ""
    start_url: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)


class TrajectoryRecorder:
    """Manages recording of verified browser interaction steps during exploration."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.start_url = ""
        self.steps: list[dict[str, Any]] = []

    def record_step(self, step_result: dict[str, Any]) -> None:
        """Add a verified step into the trajectory."""
        if not step_result.get("success"):
            return
        if not self.start_url and step_result.get("url_before"):
            self.start_url = step_result["url_before"]

        self.steps.append({
            "action": step_result.get("action"),
            "target": step_result.get("target"),
            "value": step_result.get("value", ""),
            "fingerprint": step_result.get("fingerprint", {}),
            "navigated": step_result.get("navigated", False),
            "url_after": step_result.get("url_after", ""),
        })

    def export_trajectory(self, parameters: list[str] | None = None) -> BrowserTrajectory:
        return BrowserTrajectory(
            name=self.name,
            description=self.description,
            start_url=self.start_url,
            steps=self.steps,
            parameters=parameters or [],
        )
