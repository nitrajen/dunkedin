"""
Stage 3: Execute form filling using Computer Use Agent (CUA).

Simple batch approach:
- Start at top of form
- 2 CUA iterations per scroll level
- Scroll 40% of viewport
- Repeat until bottom reached
- 25% JPEG quality for lower tokens
"""

import time

from gemini_playwright.config import VIEWPORT_WIDTH, VIEWPORT_HEIGHT
from gemini_playwright.gemini_client import GeminiClient
from gemini_playwright.models import AnswerPlan, PlannedAnswer, Action
from gemini_playwright.logger import get_logger

log = get_logger(__name__)

# Config
SCROLL_PERCENT = 0.60  # 60% of viewport per scroll
ITERATIONS_PER_LEVEL = 2  # 2 turns per scroll level (except last level = 1)
MAX_TOTAL_ITERATIONS = 5  # 2 + 2 + 1 = 5 across 3 levels


def build_form_prompt(fields: list[PlannedAnswer], turn_id: int, max_turns: int) -> str:
    """Build prompt for CUA with clear instructions.

    Only includes text input fields (text, textarea, typeahead).
    Skips dropdowns, checkboxes, file uploads - they need multiple turns.
    """
    lines = []

    for a in fields:
        if a.action in [Action.FILL_TEXT, Action.FILL_TEXTAREA, Action.SELECT_TYPEAHEAD_CHOICE]:
            lines.append(f'"{a.label}" -> {a.proposed_text}')

    fields_str = "\n".join(lines)

    return f"""The browser is already open showing a job application form. The screenshot shows the current view.

Fill these text fields visible in the screenshot (Turn {turn_id}/{max_turns}):

{fields_str}

Instructions:
- Fill ALL visible text fields in ONE batch - you only have this turn before I scroll away
- Click on each text input field and type the value shown above
- Skip fields that are already filled
- ONLY fill text input boxes - skip dropdowns, checkboxes, file uploads
- Do NOT scroll - I will scroll for you after this turn
- Do NOT click submit button
- Do NOT open a new browser - the form is already visible"""


def execute_action(page, fc) -> tuple[str, dict, str]:
    """Execute a single CUA function call."""
    name = fc.name
    args = dict(fc.args) if fc.args else {}
    result = "success"

    try:
        if name == "click_at":
            x = int(args.get("x", 0) / 1000 * VIEWPORT_WIDTH)
            y = int(args.get("y", 0) / 1000 * VIEWPORT_HEIGHT)
            page.mouse.click(x, y)
            log.info(f"  click_at({x}, {y})")

        elif name == "type_text_at":
            x = int(args.get("x", 0) / 1000 * VIEWPORT_WIDTH)
            y = int(args.get("y", 0) / 1000 * VIEWPORT_HEIGHT)
            text = args.get("text", "")
            press_enter = args.get("press_enter", False)

            page.mouse.click(x, y)
            time.sleep(0.1)

            # Clear existing text
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")

            page.keyboard.type(text)
            if press_enter:
                page.keyboard.press("Enter")
            log.info(f"  type_text_at: '{text[:40]}...' at ({x}, {y})")

        elif name in ("scroll_document", "scroll_at"):
            log.info(f"  {name}: ignored (we control scrolling)")

        elif name == "navigate":
            log.info("  navigate: ignored")

        elif name == "open_web_browser":
            log.info("  open_web_browser: no-op")

        elif name == "key_combination":
            keys = args.get("keys", "")
            page.keyboard.press(keys)
            log.info(f"  key_combination: {keys}")

        elif name == "hover_at":
            x = int(args.get("x", 0) / 1000 * VIEWPORT_WIDTH)
            y = int(args.get("y", 0) / 1000 * VIEWPORT_HEIGHT)
            page.mouse.move(x, y)
            log.info(f"  hover_at({x}, {y})")

        elif name == "wait_5_seconds":
            log.info("  wait_5_seconds: ignored")

        else:
            log.warning(f"  Unknown action: {name}")
            result = "unknown"

        time.sleep(0.2)  # Let page react to action

    except Exception as e:
        log.error(f"  Error {name}: {e}")
        result = f"error: {e}"

    return name, args, result


def execute_form_filling(
    page,
    answer_plan: AnswerPlan,
    client: GeminiClient | None = None,
) -> dict:
    """
    Execute form filling in batches.

    For each scroll level:
    - Take screenshot
    - Call CUA (iteration 1)
    - Take screenshot
    - Call CUA (iteration 2)
    - Scroll down 40% of viewport
    - Repeat until bottom
    """
    if client is None:
        client = GeminiClient()

    fields_to_fill = [a for a in answer_plan.answers if a.action != Action.SKIP]
    skipped_fields = [a for a in answer_plan.answers if a.action == Action.SKIP]

    log.info(f"Fields to fill: {len(fields_to_fill)}, Skipped: {len(skipped_fields)}")

    # Get page dimensions
    page_height = page.evaluate("document.body.scrollHeight")
    scroll_amount = int(VIEWPORT_HEIGHT * SCROLL_PERCENT)
    max_scroll = page_height - VIEWPORT_HEIGHT

    log.info(f"Page height: {page_height}px, Viewport: {VIEWPORT_HEIGHT}px")
    log.info(f"Scroll amount: {scroll_amount}px (60% of viewport)")
    log.info(f"Max iterations: {MAX_TOTAL_ITERATIONS}")

    total_tokens = {"prompt": 0, "response": 0, "total": 0}
    all_actions = []
    turn = 0
    level = 0

    current_scroll = int(page.evaluate("window.scrollY"))

    while turn < MAX_TOTAL_ITERATIONS:
        level += 1
        log.info(f"=== Level {level} (scroll position: {current_scroll}px) ===")

        # 2 iterations per level, but only 1 on level 3
        iters_this_level = 1 if level >= 3 else ITERATIONS_PER_LEVEL
        for iteration in range(1, iters_this_level + 1):
            if turn >= MAX_TOTAL_ITERATIONS:
                break

            turn += 1
            log.info(f"  Turn {turn} (iteration {iteration}/{iters_this_level})")

            # Take screenshot (PNG for max quality)
            screenshot = page.screenshot(type="png")

            # Build prompt
            prompt = build_form_prompt(fields_to_fill, turn, MAX_TOTAL_ITERATIONS)

            # Call CUA
            function_calls, usage = client.execute_computer_use(screenshot, prompt)

            total_tokens["prompt"] += usage["prompt"]
            total_tokens["response"] += usage["response"]
            total_tokens["total"] += usage["total"]

            log.info(f"    Actions: {len(function_calls)}, Tokens: {usage['total']}")

            # Execute actions
            for fc in function_calls:
                result = execute_action(page, fc)
                all_actions.append(result)

            # Pause between iterations - let page settle
            time.sleep(0.5)

        if turn >= MAX_TOTAL_ITERATIONS:
            log.info(f"Reached max iterations ({MAX_TOTAL_ITERATIONS})")
            break

        # Scroll down
        next_scroll = current_scroll + scroll_amount

        if next_scroll >= max_scroll:
            # We've reached the bottom
            log.info(f"Reached bottom of page at level {level}")
            break

        page.evaluate(f"window.scrollTo(0, {next_scroll})")
        current_scroll = next_scroll
        time.sleep(0.5)  # Let new content render

    log.info(f"Completed: {turn} turns across {level} levels")

    return {
        "turns": turn,
        "levels": level,
        "total_actions": len(all_actions),
        "fields_to_fill": len(fields_to_fill),
        "fields_skipped": len(skipped_fields),
        "token_usage": total_tokens,
        "actions": [(n, str(a), r) for n, a, r in all_actions],
    }
