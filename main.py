"""OpenClaw - Post Frame Building Designer

Launch the GUI or run headless from the command line.

Usage:
    python main.py              # Launch GUI
    python main.py --headless "Design a 30x40 shop"   # Headless mode
"""

import argparse
import logging
import os
import sys

# Load API keys from .env file before anything else imports them
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path, override=True)
except ImportError:
    # python-dotenv not installed — keys must come from environment / .bat file
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw - Post Frame Building Designer"
    )
    parser.add_argument(
        "--headless",
        type=str,
        default=None,
        help="Run in headless mode with the given prompt (no GUI).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-5-20250929",
        help="Model to use.",
    )
    args = parser.parse_args()

    if args.headless:
        _run_headless(args.headless, args.api_key, args.model)
    else:
        _run_gui()


def _run_headless(prompt: str, api_key: str | None, model: str):
    from agent.agent import AgentState, run_agent

    state = AgentState()

    def on_message(role, text):
        prefix = {
            "user": "[YOU]",
            "assistant": "[AGENT]",
            "tool": "[TOOL]",
            "tool_result": "[RESULT]",
            "system": "[SYS]",
            "error": "[ERROR]",
        }.get(role, "")
        print(f"{prefix} {text}")

    run_agent(
        user_prompt=prompt,
        state=state,
        on_message=on_message,
        api_key=api_key,
        model=model,
    )


def _run_gui():
    import tkinter as tk

    from gui.app import OpenClawGUI

    root = tk.Tk()
    OpenClawGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
