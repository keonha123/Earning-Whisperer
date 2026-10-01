"""Bounded, frame-local registration choices with observable commit evidence.

This module does not submit forms. Provider-specific widgets without semantic
option ownership still need an adapter; arbitrary page text is never a choice.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from typing import Any, Sequence


@dataclass(frozen=True)
class FormControlResult:
    success: bool
    reason: str
    kind: str = "custom_choice"


_STATE = r"""element => {
    const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
    const widget = element.closest('[role="combobox"]') || element;
    const nodes = [...new Set([element, widget])];
    const refs = nodes.flatMap(node => [node.getAttribute('aria-controls'), node.getAttribute('aria-owns')])
        .filter(Boolean).flatMap(value => value.split(/\s+/)).filter(Boolean);
    const role = widget.getAttribute('role') || element.getAttribute('role') || '';
    const structured = role === 'combobox' || nodes.some(node =>
        ['listbox', 'true'].includes(node.getAttribute('aria-haspopup')) ||
        ['list', 'both', 'inline'].includes(node.getAttribute('aria-autocomplete'))) ||
        refs.some(id => element.ownerDocument.getElementById(id)?.getAttribute('role') === 'listbox');
    let scope = element.parentElement;
    // Collect only field-local proof, never an unrelated hidden form token.
    for (let i = 0; i < 2 && scope?.parentElement; i++) {
        if (scope.matches('form') || scope.parentElement.matches('form, body, html')) break;
        const peers = [...scope.parentElement.querySelectorAll('input:not([type="hidden"]), select, textarea')];
        if (peers.some(peer => peer !== element && !widget.contains(peer))) break;
        scope = scope.parentElement;
    }
    if (scope?.matches('form, body, html')) scope = widget;
    const hidden = scope ? [...scope.querySelectorAll('input[type="hidden"]')]
        .map(node => `${node.name || node.id}:${node.value}`).filter(value => !value.endsWith(':')) : [];
    const selected = scope ? [...scope.querySelectorAll('[data-selected-value], [class*="__single-value"]')]
        .map(node => norm(node.getAttribute('data-selected-value') || node.textContent)).filter(Boolean) : [];
    return {
        tag: element.tagName.toLowerCase(), structured, refs, ids: nodes.map(node => node.id).filter(Boolean),
        value: norm('value' in element ? element.value : ''),
        display: norm(element.getAttribute('aria-valuetext') ||
            (element.matches('button, [role="combobox"]:not(input)') ? element.textContent : '')),
        hidden, selected,
        invalid: nodes.some(node => node.getAttribute('aria-invalid') === 'true') ||
            ('validity' in element && !element.validity.valid),
        focused: nodes.some(node => node === element.ownerDocument.activeElement || node.contains(element.ownerDocument.activeElement)),
    };
}"""


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


async def is_structured_choice(control: Any) -> bool:
    """Whether a field requires choosing an object, rather than plain typing."""
    try:
        state = await control.evaluate(_STATE, timeout=300)
        return bool(state["structured"])
    except Exception:
        return False


async def select_custom_option(
    control: Any,
    value: str,
    *,
    fill: bool = False,
    timeout_ms: int = 1800,
    aliases: Sequence[str] = (),
) -> FormControlResult:
    """Select an exact owned option and verify a committed field state.

    ``fill=True`` also supports a regular text field, provided it does not
    expose choice semantics. For an autocomplete, typed search text alone is
    never proof of selection. All work, including actionability waits, shares
    one deadline. Native selects remain the caller's responsibility.
    """
    if not str(value or "").strip():
        return FormControlResult(False, "empty_requested_value")
    limit = max(100, min(int(timeout_ms), 5000)) / 1000
    try:
        return await asyncio.wait_for(
            _select(control, value, fill=fill, budget=limit, aliases=aliases),
            timeout=limit + 0.1,
        )
    except asyncio.TimeoutError:
        return FormControlResult(False, "choice_deadline")
    except Exception:
        return FormControlResult(False, "choice_control_unavailable")


async def _select(control: Any, value: str, *, fill: bool, budget: float,
                  aliases: Sequence[str]) -> FormControlResult:
    deadline = time.monotonic() + budget

    def remaining_ms():
        return max(1, min(450, int((deadline - time.monotonic()) * 1000)))

    initial = await control.evaluate(_STATE, timeout=remaining_ms())
    if initial["tag"] == "select":
        return FormControlResult(False, "native_select_requires_native_handler", "native_select")
    handle = await control.element_handle(timeout=remaining_ms())
    frame = await handle.owner_frame() if handle else None
    if frame is None:
        return FormControlResult(False, "choice_frame_unavailable")
    accepted = {_normal(value), *(_normal(alias) for alias in aliases)}

    async def visible_menus():
        menus = await frame.locator('[role="listbox"]').element_handles()
        return [menu for menu in menus[:20] if await menu.is_visible()]

    before_menus = await visible_menus()

    await control.click(timeout=remaining_ms())
    if fill:
        await control.fill(value, timeout=remaining_ms())
    state = await control.evaluate(_STATE, timeout=remaining_ms())
    if fill and not state["structured"] and not initial["structured"]:
        # Actual free text: blur triggers validation before reporting success.
        await control.press("Tab", timeout=remaining_ms())
        state = await control.evaluate(_STATE, timeout=remaining_ms())
        ok = _normal(state["value"]) == _normal(value) and not state["invalid"]
        return FormControlResult(ok, "plain_text_verified" if ok else "plain_text_invalid", "text")

    # Many autocompletes only open on an explicit key event after typing.
    if state["tag"] in {"input", "textarea"}:
        await control.press("ArrowDown", timeout=remaining_ms())
    saw_menu = False
    last_reason = "choice_menu_not_found"
    while time.monotonic() < deadline:
        state = await control.evaluate(_STATE, timeout=remaining_ms())
        menus = []
        for ref in state["refs"][:16]:
            candidates = await frame.locator(f'[id={json.dumps(ref)}]').element_handles()
            for candidate in candidates[:1]:
                if await candidate.is_visible():
                    menus.append(candidate)
        if not menus:
            for owner_id in state["ids"][:4]:
                candidates = await frame.locator(
                    f'[role="listbox"][aria-labelledby~={json.dumps(owner_id)}]'
                ).element_handles()
                menus.extend([candidate for candidate in candidates[:4] if await candidate.is_visible()])
        if not menus and not before_menus and state["focused"]:
            # Causal semantic fallback: this control opened the only visible
            # listbox in this document. Never adopt a pre-existing menu.
            candidates = await visible_menus()
            if len(candidates) == 1:
                menus = candidates
        if menus:
            saw_menu = True
            last_reason = "exact_owned_option_not_found"
        for menu in menus:
            options = await menu.query_selector_all('[role="option"]')
            for option in options[:100]:
                if not await option.is_visible():
                    continue
                info = await option.evaluate("""node => ({
                    label: node.getAttribute('aria-label') || node.textContent || '',
                    disabled: node.getAttribute('aria-disabled') === 'true' || !!node.disabled
                })""")
                if info["disabled"] or _normal(info["label"]) not in accepted:
                    continue
                before_click = await control.evaluate(_STATE, timeout=remaining_ms())
                await option.click(timeout=remaining_ms())
                # A clicked option can close while the provider rejects the
                # value. Require observable selection/value state, not a click.
                while time.monotonic() < deadline:
                    after = await control.evaluate(_STATE, timeout=remaining_ms())
                    selected = False
                    try:
                        selected = await option.get_attribute("aria-selected") == "true"
                    except Exception:
                        pass
                    changed_exact_value = (
                        _normal(after["value"]) in accepted and
                        after["value"] != before_click["value"]
                    )
                    changed_display = (
                        _normal(after["display"]) in accepted and
                        after["display"] != before_click["display"]
                    )
                    selected_display = any(
                        _normal(label) in accepted and label not in before_click["selected"]
                        for label in after["selected"]
                    )
                    hidden_changed = bool(set(after["hidden"]) - set(before_click["hidden"]))
                    if not after["invalid"] and (selected or changed_exact_value or changed_display or selected_display or hidden_changed):
                        return FormControlResult(True, "exact_option_committed")
                    await asyncio.sleep(0.05)
                return FormControlResult(False, "option_clicked_commit_unverified")
        await asyncio.sleep(0.05)
    return FormControlResult(False, last_reason if saw_menu else "choice_menu_not_found")
