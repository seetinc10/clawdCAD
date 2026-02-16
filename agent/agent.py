"""OpenClaw post-frame building agent.

Runs an agentic loop: user prompt -> LLM -> tool calls -> macro builder -> FreeCAD.
Supports pause/stop via threading events.
After FreeCAD renders the model it captures screenshots which the agent reviews
for errors, allowing a self-correction cycle.

Supports multiple LLM providers:
- Anthropic (Claude) — native SDK
- OpenAI (GPT)      — openai SDK
- DeepSeek           — openai SDK (OpenAI-compatible)
- xAI (Grok)         — openai SDK (OpenAI-compatible)
"""

import base64
import json
import logging
import mimetypes
import os
import subprocess
import threading
import time
from typing import Callable

import anthropic

try:
    import openai as openai_sdk
except ImportError:
    openai_sdk = None  # Will fail gracefully if OpenAI SDK not installed

from agent.prompts import SYSTEM_PROMPT, TOOL_DEFINITIONS, TOOL_DEFINITIONS_OPENAI
from agent.macro_generator import MacroBuilder

log = logging.getLogger(__name__)

FREECAD_EXE = r"C:\Program Files\FreeCAD 1.0\bin\freecad.exe"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshots")
MAX_REVIEW_ROUNDS = 2
SCREENSHOT_WAIT_SECS = 90
SCREENSHOT_POLL_SECS = 2

# ---------------------------------------------------------------------------
# Provider / model registry
# ---------------------------------------------------------------------------

# Maps display name -> (provider, api_model_id, base_url_or_None)
MODEL_REGISTRY: dict[str, tuple[str, str, str | None]] = {
    # Anthropic
    "claude-sonnet-4-5-20250929": ("anthropic", "claude-sonnet-4-5-20250929", None),
    "claude-haiku-4-5-20251001":  ("anthropic", "claude-haiku-4-5-20251001", None),
    "claude-opus-4-6":            ("anthropic", "claude-opus-4-6", None),
    # DeepSeek  (OpenAI-compatible)
    "deepseek-chat":              ("deepseek", "deepseek-chat", "https://api.deepseek.com"),
    "deepseek-reasoner":          ("deepseek", "deepseek-reasoner", "https://api.deepseek.com"),
    # OpenAI
    "gpt-4.1-nano":               ("openai", "gpt-4.1-nano", None),
    "gpt-4.1-mini":               ("openai", "gpt-4.1-mini", None),
    "gpt-4.1":                    ("openai", "gpt-4.1", None),
    "gpt-4o-mini":                ("openai", "gpt-4o-mini", None),
    "gpt-4o":                     ("openai", "gpt-4o", None),
    # xAI / Grok  (OpenAI-compatible)
    "grok-4-1-fast":              ("grok", "grok-4-1-fast-non-reasoning", "https://api.x.ai/v1"),
    "grok-3-mini":                ("grok", "grok-3-mini", "https://api.x.ai/v1"),
    "grok-3":                     ("grok", "grok-3", "https://api.x.ai/v1"),
}

# For the GUI dropdown — ordered cheapest-first per provider
MODEL_CHOICES = [
    # --- Anthropic ---
    "claude-haiku-4-5-20251001",     # $1.00 / $5.00  per M tokens
    "claude-sonnet-4-5-20250929",    # $3.00 / $15.00
    "claude-opus-4-6",               # $15.00 / $75.00
    # --- DeepSeek ---
    "deepseek-chat",                 # $0.28 / $0.42   (cheapest overall)
    "deepseek-reasoner",             # $0.28 / $0.42   (reasoning mode)
    # --- OpenAI ---
    "gpt-4.1-nano",                  # $0.10 / $0.40   (cheapest OpenAI)
    "gpt-4o-mini",                   # $0.15 / $0.60
    "gpt-4.1-mini",                  # $0.40 / $1.60
    "gpt-4.1",                       # $2.00 / $8.00
    "gpt-4o",                        # $2.50 / $10.00
    # --- xAI / Grok ---
    "grok-4-1-fast",                 # $0.20 / $0.50   (cheapest Grok)
    "grok-3-mini",                   # $0.30 / $0.50
    "grok-3",                        # $3.00 / $15.00
]

# Maps provider name -> env var name for API key
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek":  "DEEPSEEK_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "grok":      "GROK_API_KEY",
}


def _get_provider(model: str) -> tuple[str, str, str | None]:
    """Return (provider, api_model_id, base_url) for *model*."""
    if model in MODEL_REGISTRY:
        return MODEL_REGISTRY[model]
    # Fallback: assume Anthropic for unknown models
    return ("anthropic", model, None)


class AgentState:
    """Thread-safe state for the agent loop."""

    def __init__(self):
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.pause_event.set()  # Start un-paused
        self.messages: list[dict] = []
        self.is_running = False
        self.macro: MacroBuilder | None = None
        self.building_length_ft = 0.0
        self.building_width_ft = 0.0

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()  # Unblock if paused

    def reset(self):
        self.pause_event.set()
        self.stop_event.clear()
        self.messages.clear()
        self.is_running = False
        self.macro = None
        self.building_length_ft = 0.0
        self.building_width_ft = 0.0

    @property
    def is_paused(self) -> bool:
        return not self.pause_event.is_set()


def _execute_tool(name: str, input_args: dict, state: AgentState) -> str:
    """Execute a tool by adding to the macro builder. Returns a result string."""
    macro = state.macro

    try:
        if name == "create_concrete_slab":
            result = macro.create_concrete_slab(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_post_layout":
            # Track building dimensions for door/window placement
            state.building_length_ft = input_args.get("building_length_ft", 0)
            state.building_width_ft = input_args.get("building_width_ft", 0)
            result = macro.create_post_layout(**input_args)
            return json.dumps({"status": "ok", "created": "post_layout"})

        elif name == "create_wall_girts":
            result = macro.create_wall_girts(**input_args)
            return json.dumps({"status": "ok", "created": "wall_girts"})

        elif name == "create_wainscot":
            result = macro.create_wainscot(**input_args)
            return json.dumps({"status": "ok", "created": "wainscot"})

        elif name == "create_roof_trusses":
            result = macro.create_roof_trusses(**input_args)
            return json.dumps({"status": "ok", "created": "roof_trusses"})

        elif name == "create_purlins":
            result = macro.create_purlins(**input_args)
            return json.dumps({"status": "ok", "created": "purlins"})

        elif name == "create_ridge_cap":
            result = macro.create_ridge_cap(**input_args)
            return json.dumps({"status": "ok", "created": "ridge_cap"})

        elif name == "create_overhead_door":
            input_args["building_length_ft"] = state.building_length_ft
            input_args["building_width_ft"] = state.building_width_ft
            result = macro.create_overhead_door(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_walk_door":
            input_args["building_length_ft"] = state.building_length_ft
            input_args["building_width_ft"] = state.building_width_ft
            result = macro.create_walk_door(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_window":
            input_args["building_length_ft"] = state.building_length_ft
            input_args["building_width_ft"] = state.building_width_ft
            result = macro.create_window(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_interior_wall":
            result = macro.create_interior_wall(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_roof_panels":
            result = macro.create_roof_panels(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_wall_panels":
            result = macro.create_wall_panels(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_room":
            # Validate room is within building footprint
            warnings = []
            rx = input_args.get("x_ft", 0)
            ry = input_args.get("y_ft", 0)
            rw = input_args.get("width_ft", 0)
            rd = input_args.get("depth_ft", 0)
            blen = state.building_length_ft
            bwid = state.building_width_ft
            if blen > 0 and bwid > 0:
                if rx < 0 or ry < 0:
                    warnings.append(f"Room origin ({rx},{ry}) is negative - outside building!")
                if rx + rw > blen:
                    warnings.append(
                        f"Room exceeds building length: x({rx})+w({rw})={rx+rw} > {blen}"
                    )
                if ry + rd > bwid:
                    warnings.append(
                        f"Room exceeds building width: y({ry})+d({rd})={ry+rd} > {bwid}"
                    )
            result = macro.create_room(**input_args)
            resp = {"status": "ok", "created": result}
            if warnings:
                resp["warnings"] = warnings
                resp["building_footprint"] = f"{blen}'x{bwid}' (length x width)"
                resp["hint"] = "Room must fit within 0,0 to building_length,building_width"
            return json.dumps(resp)

        elif name == "create_kitchen_fixtures":
            result = macro.create_kitchen_fixtures(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "create_bathroom_fixtures":
            result = macro.create_bathroom_fixtures(**input_args)
            return json.dumps({"status": "ok", "created": result})

        elif name == "save_document":
            return json.dumps({"status": "ok", "note": "Will save when macro executes"})

        elif name == "export_step":
            return json.dumps({"status": "ok", "note": "STEP export will be available from FreeCAD"})

        elif name == "get_building_summary":
            return json.dumps({"status": "ok", "macro_lines": len(macro.lines)})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        log.exception(f"Tool {name} failed")
        return json.dumps({"error": str(e)})


def _launch_freecad(macro_path: str, on_message=None):
    """Launch FreeCAD with the generated macro."""
    if not os.path.isfile(FREECAD_EXE):
        if on_message:
            on_message("error", f"FreeCAD not found at {FREECAD_EXE}")
        return False

    if on_message:
        on_message("system", f"Launching FreeCAD with macro: {macro_path}")

    try:
        subprocess.Popen(
            [FREECAD_EXE, macro_path],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        if on_message:
            on_message("system", "FreeCAD launched! The building model will appear shortly.")
        return True
    except Exception as e:
        if on_message:
            on_message("error", f"Failed to launch FreeCAD: {e}")
        return False


def _encode_image(path: str, provider: str = "anthropic") -> dict:
    """Read an image file and return a provider-appropriate image content block."""
    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("ascii")

    if provider == "anthropic":
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": data,
            },
        }
    else:
        # OpenAI-compatible format (works for OpenAI, DeepSeek, Grok)
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{data}",
            },
        }


def _wait_for_screenshots(state: AgentState, on_message=None) -> bool:
    """Wait for FreeCAD to finish rendering and capture screenshots.

    Returns True if screenshots are ready, False on timeout or stop.
    """
    signal_file = os.path.join(SCREENSHOT_DIR, "done.signal")

    # Clean up old signal file before waiting
    if os.path.exists(signal_file):
        os.remove(signal_file)

    if on_message:
        on_message("system", "Waiting for FreeCAD to render and capture screenshots...")

    elapsed = 0
    while elapsed < SCREENSHOT_WAIT_SECS:
        if state.stop_event.is_set():
            return False

        if os.path.exists(signal_file):
            # Give FreeCAD a moment to finish writing files
            time.sleep(1)
            if on_message:
                on_message("system", "Screenshots captured! Reviewing model...")
            return True

        time.sleep(SCREENSHOT_POLL_SECS)
        elapsed += SCREENSHOT_POLL_SECS

    if on_message:
        on_message("system", "Timed out waiting for screenshots. Skipping review.")
    return False


def _collect_screenshots() -> list[str]:
    """Return paths to available screenshot images."""
    names = ["view_isometric.png", "view_top.png", "view_front.png"]
    paths = []
    for name in names:
        p = os.path.join(SCREENSHOT_DIR, name)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            paths.append(p)
    return paths


def _clean_screenshots():
    """Remove old screenshots and signal file before a new build."""
    if os.path.isdir(SCREENSHOT_DIR):
        for f in os.listdir(SCREENSHOT_DIR):
            fp = os.path.join(SCREENSHOT_DIR, f)
            try:
                os.remove(fp)
            except OSError:
                pass


def _run_design_loop_anthropic(
    client: anthropic.Anthropic,
    state: AgentState,
    on_message,
    model: str,
    max_turns: int,
) -> bool:
    """Run the Anthropic tool-calling loop. Returns True if design completed normally."""
    turn = 0
    while turn < max_turns:
        # Check stop
        if state.stop_event.is_set():
            if on_message:
                on_message("system", "Agent stopped by user.")
            return False

        # Wait if paused
        state.pause_event.wait()
        if state.stop_event.is_set():
            return False

        # Call LLM
        if on_message:
            on_message("system", f"Thinking... (turn {turn + 1})")

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=state.messages,
        )

        turn += 1

        # Process response content
        assistant_content = response.content
        state.messages.append({"role": "assistant", "content": assistant_content})

        # Extract text blocks for display
        for block in assistant_content:
            if hasattr(block, "text"):
                if on_message:
                    on_message("assistant", block.text)

        # If no tool use, we're done with this design pass
        if response.stop_reason == "end_turn":
            return True

        # Handle tool calls
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                if state.stop_event.is_set():
                    break

                state.pause_event.wait()
                if state.stop_event.is_set():
                    break

                tool_name = block.name
                tool_input = block.input

                if on_message:
                    on_message(
                        "tool",
                        f"Calling {tool_name}({json.dumps(tool_input, indent=2)})",
                    )

                result = _execute_tool(tool_name, tool_input, state)

                if on_message:
                    on_message("tool_result", f"{tool_name} -> {result}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        if state.stop_event.is_set():
            return False

        if tool_results:
            state.messages.append({"role": "user", "content": tool_results})

    if on_message:
        on_message("system", "Max turns reached for this pass.")
    return True


def _run_design_loop_openai(
    client,  # openai.OpenAI
    state: AgentState,
    on_message,
    model: str,
    max_turns: int,
) -> bool:
    """Run the OpenAI-compatible tool-calling loop (OpenAI / DeepSeek / Grok).

    Returns True if design completed normally.
    """
    turn = 0

    # Build OpenAI-format messages from state.messages
    # We keep a separate openai_messages list because OpenAI uses a different
    # format for tool calls/results than Anthropic.
    oai_messages = _convert_messages_for_openai(state.messages)

    while turn < max_turns:
        if state.stop_event.is_set():
            if on_message:
                on_message("system", "Agent stopped by user.")
            return False

        state.pause_event.wait()
        if state.stop_event.is_set():
            return False

        if on_message:
            on_message("system", f"Thinking... (turn {turn + 1})")

        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + oai_messages,
            tools=TOOL_DEFINITIONS_OPENAI,
            tool_choice="auto",
        )

        turn += 1

        choice = response.choices[0]
        assistant_msg = choice.message

        # Store the raw assistant message for the conversation
        oai_assistant = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            oai_assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        oai_messages.append(oai_assistant)

        # Also store in state.messages for macro rebuild detection
        state.messages.append({"role": "assistant", "content": assistant_msg.content or ""})

        # Display text
        if assistant_msg.content and on_message:
            on_message("assistant", assistant_msg.content)

        # No tool calls = done
        if not assistant_msg.tool_calls:
            return True

        # Process tool calls
        for tc in assistant_msg.tool_calls:
            if state.stop_event.is_set():
                break

            state.pause_event.wait()
            if state.stop_event.is_set():
                break

            tool_name = tc.function.name
            try:
                tool_input = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_input = {}

            if on_message:
                on_message(
                    "tool",
                    f"Calling {tool_name}({json.dumps(tool_input, indent=2)})",
                )

            result = _execute_tool(tool_name, tool_input, state)

            if on_message:
                on_message("tool_result", f"{tool_name} -> {result}")

            # OpenAI expects tool results as role=tool messages
            oai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        if state.stop_event.is_set():
            return False

    if on_message:
        on_message("system", "Max turns reached for this pass.")
    return True


def _convert_messages_for_openai(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-format messages to OpenAI-format for the initial prompt.

    Only handles the user prompt (first message). Subsequent messages in the
    OpenAI loop are built natively in OpenAI format.
    """
    oai = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user":
            if isinstance(content, str):
                oai.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Could be multimodal (image + text) or tool_results from Anthropic
                # Check if it's tool results
                if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                    # Skip Anthropic tool results — not applicable in OpenAI loop
                    continue
                # Otherwise it's multimodal content — already in OpenAI format
                # if images were encoded with provider != "anthropic"
                oai.append({"role": "user", "content": content})
        elif role == "assistant":
            if isinstance(content, str):
                oai.append({"role": "assistant", "content": content})
            # Skip Anthropic content block objects
    return oai


def _create_client(model: str, api_key: str | None = None):
    """Create the appropriate API client for *model*.

    Returns (client, provider, api_model_id).
    """
    provider, api_model_id, base_url = _get_provider(model)

    if provider == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        return client, provider, api_model_id

    # OpenAI-compatible providers
    if openai_sdk is None:
        raise RuntimeError(
            "The 'openai' Python package is required for non-Anthropic models. "
            "Install it with: pip install openai"
        )

    env_var = PROVIDER_KEY_ENV.get(provider, "")
    key = api_key or os.environ.get(env_var, "")
    if not key:
        raise RuntimeError(
            f"No API key found for {provider}. Set {env_var} environment variable."
        )

    kwargs = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url

    client = openai_sdk.OpenAI(**kwargs)
    return client, provider, api_model_id


def run_agent(
    user_prompt: str,
    state: AgentState,
    on_message: Callable[[str, str], None] | None = None,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-5-20250929",
    max_turns: int = 25,
    image_paths: list[str] | None = None,
):
    """Run the agent loop with optional self-review cycle.

    Flow:
    1. Agent designs the building via tool calls -> macro is generated
    2. FreeCAD executes macro, captures screenshots (isometric, top, front)
    3. Screenshots are sent back to agent for review
    4. If agent finds errors, it issues correction tool calls -> new macro
    5. Repeat up to MAX_REVIEW_ROUNDS times

    Args:
        user_prompt: The user's building request.
        state: AgentState for pause/stop control.
        on_message: Callback(role, text) for streaming updates to the GUI.
        api_key: API key override (otherwise uses env var for the provider).
        model: Model display name from MODEL_CHOICES.
        max_turns: Maximum number of LLM round-trips per design pass.
        image_paths: Optional list of image file paths to include with the prompt.
    """
    state.is_running = True
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    save_path = os.path.join(OUTPUT_DIR, "building.FCStd")
    macro_path = os.path.join(OUTPUT_DIR, "building_macro.py")

    state.macro = MacroBuilder(save_path=save_path)

    # Create provider-specific client
    client, provider, api_model_id = _create_client(model, api_key)

    if on_message:
        on_message("system", f"Using model: {model} (provider: {provider})")

    is_anthropic = provider == "anthropic"

    # Choose the right design-loop function
    _run_loop = _run_design_loop_anthropic if is_anthropic else _run_design_loop_openai

    # Build user message - text only or multimodal with images
    if image_paths:
        content_blocks = []
        for img_path in image_paths:
            if os.path.isfile(img_path):
                content_blocks.append(_encode_image(img_path, provider))
                if on_message:
                    on_message("system", f"Attached image: {os.path.basename(img_path)}")
        content_blocks.append({"type": "text", "text": user_prompt})
        state.messages.append({"role": "user", "content": content_blocks})
    else:
        state.messages.append({"role": "user", "content": user_prompt})

    if on_message:
        on_message("user", user_prompt)

    try:
        # === PASS 1: Initial design ===
        _clean_screenshots()

        design_ok = _run_loop(client, state, on_message, api_model_id, max_turns)

        if not design_ok or state.stop_event.is_set():
            return

        # Write macro and launch FreeCAD
        if on_message:
            on_message("system", "Design complete. Generating macro...")

        state.macro.write_macro(macro_path)
        if on_message:
            on_message("system", f"Macro written to {macro_path}")

        launched = _launch_freecad(macro_path, on_message)
        if not launched:
            return

        # === REVIEW LOOP ===
        for review_round in range(MAX_REVIEW_ROUNDS):
            if state.stop_event.is_set():
                break

            # Wait for FreeCAD to produce screenshots
            screenshots_ready = _wait_for_screenshots(state, on_message)
            if not screenshots_ready:
                break  # Timeout or stopped - skip review

            screenshot_paths = _collect_screenshots()
            if not screenshot_paths:
                if on_message:
                    on_message("system", "No screenshots found. Skipping review.")
                break

            # Send screenshots to agent for review
            review_content = []
            for sp in screenshot_paths:
                review_content.append(_encode_image(sp, provider))
                view_name = os.path.basename(sp).replace("view_", "").replace(".png", "")
                if on_message:
                    on_message("system", f"Sending {view_name} view to agent for review...")

            review_prompt = (
                "Here are screenshots of the FreeCAD model you just created. "
                "Review these views carefully:\n"
                "1. ISOMETRIC VIEW - Check overall proportions, roof shape, wall panels\n"
                "2. TOP VIEW (plan view) - Check room layout, wall positions, overlaps\n"
                "3. FRONT VIEW (elevation) - Check door/window placement, eave height\n\n"
                "If everything looks correct, say 'REVIEW PASSED' and summarize what was built.\n"
                "If you see errors (overlapping rooms, missing walls, wrong proportions, "
                "misplaced doors/windows, etc.), describe the issues and call the tools "
                "to fix them. The macro will be regenerated and FreeCAD relaunched."
            )
            review_content.append({"type": "text", "text": review_prompt})

            state.messages.append({"role": "user", "content": review_content})

            if on_message:
                on_message("system", f"Review round {review_round + 1}/{MAX_REVIEW_ROUNDS}...")

            # Run LLM again - it will either say "looks good" or issue fix tool calls
            review_ok = _run_loop(client, state, on_message, api_model_id, max_turns=10)

            if not review_ok or state.stop_event.is_set():
                break

            # Check if agent made any corrections (new tool calls added lines to macro)
            current_macro = state.macro.build_macro()
            with open(macro_path, "r") as f:
                previous_macro = f.read()

            if current_macro != previous_macro:
                # Agent made corrections - rebuild and relaunch
                if on_message:
                    on_message("system", "Corrections detected. Rebuilding macro...")

                _clean_screenshots()
                state.macro.write_macro(macro_path)

                if on_message:
                    on_message("system", f"Updated macro written to {macro_path}")

                _launch_freecad(macro_path, on_message)
                # Continue to next review round
            else:
                # Agent said it looks good - we're done
                if on_message:
                    on_message("system", "Review passed! Model is complete.")
                break

    except anthropic.APIError as e:
        if on_message:
            on_message("error", f"Anthropic API error: {e}")
        log.exception("Anthropic API error")
    except Exception as e:
        err_msg = str(e)
        if on_message:
            on_message("error", f"Error: {err_msg}")
        log.exception("Agent error")
    finally:
        state.is_running = False
        if on_message:
            on_message("system", "Agent finished.")
