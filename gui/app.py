"""Tkinter GUI for the OpenClaw post-frame building agent."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from agent.agent import AgentState, run_agent, MODEL_CHOICES, MODEL_REGISTRY, PROVIDER_KEY_ENV


class OpenClawGUI:
    """Main application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OpenClaw - Post Frame Building Designer")
        self.root.geometry("950x750")
        self.root.minsize(700, 500)

        self.state = AgentState()
        self.agent_thread: threading.Thread | None = None
        self.image_paths: list[str] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Top frame: model selector
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value="claude-sonnet-4-5-20250929")
        model_combo = ttk.Combobox(
            top,
            textvariable=self.model_var,
            values=MODEL_CHOICES,
            state="readonly",
            width=35,
        )
        model_combo.pack(side=tk.LEFT, padx=5)
        model_combo.bind("<<ComboboxSelected>>", self._on_model_changed)

        # Provider label (shows which provider is selected)
        self.provider_label = ttk.Label(top, text="(Anthropic)", foreground="#6b7280")
        self.provider_label.pack(side=tk.LEFT, padx=3)

        # Prompt input
        prompt_frame = ttk.LabelFrame(self.root, text="Building Request", padding=5)
        prompt_frame.pack(fill=tk.X, padx=5, pady=5)

        self.prompt_text = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.X)
        self.prompt_text.insert(
            "1.0",
            "Design a 30' x 40' post-frame barndominium with 10' eave height, "
            "charcoal roof and tan wall panels. "
            "One 10'x10' overhead door on the front wall centered, "
            "a walk door on the right side, and windows on each wall. "
            "Include a 3 bed / 2 bath interior with open great room and kitchen.",
        )

        # Image attach row
        img_frame = ttk.Frame(prompt_frame)
        img_frame.pack(fill=tk.X, pady=(3, 0))

        self.attach_btn = ttk.Button(
            img_frame, text="Attach Image", command=self._on_attach_image, width=14
        )
        self.attach_btn.pack(side=tk.LEFT)

        self.clear_img_btn = ttk.Button(
            img_frame, text="Clear", command=self._on_clear_images, width=6
        )
        self.clear_img_btn.pack(side=tk.LEFT, padx=3)

        self.image_label = ttk.Label(img_frame, text="No images attached", foreground="#6b7280")
        self.image_label.pack(side=tk.LEFT, padx=5)

        # Control buttons
        btn_frame = ttk.Frame(self.root, padding=5)
        btn_frame.pack(fill=tk.X, padx=5)

        self.start_btn = ttk.Button(
            btn_frame, text="Start", command=self._on_start, width=12
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = ttk.Button(
            btn_frame, text="Pause", command=self._on_pause, state=tk.DISABLED, width=12
        )
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            btn_frame, text="Stop", command=self._on_stop, state=tk.DISABLED, width=12
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = ttk.Button(
            btn_frame, text="Reset", command=self._on_reset, width=12
        )
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        # Status label
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(btn_frame, textvariable=self.status_var)
        status_label.pack(side=tk.RIGHT, padx=10)

        # Output / conversation log
        log_frame = ttk.LabelFrame(self.root, text="Agent Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for coloring
        self.log_text.tag_configure("user", foreground="#2563eb")
        self.log_text.tag_configure("assistant", foreground="#16a34a")
        self.log_text.tag_configure("tool", foreground="#9333ea")
        self.log_text.tag_configure("tool_result", foreground="#7c3aed")
        self.log_text.tag_configure("system", foreground="#6b7280")
        self.log_text.tag_configure("error", foreground="#dc2626")

        # Macro info panel
        info_frame = ttk.LabelFrame(self.root, text="Output", padding=5)
        info_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.info_text = scrolledtext.ScrolledText(
            info_frame,
            wrap=tk.WORD,
            height=3,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.info_text.pack(fill=tk.X)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _append_log(self, role: str, text: str):
        """Thread-safe log append. Called from the agent thread."""
        self.root.after(0, self._do_append_log, role, text)

    def _do_append_log(self, role: str, text: str):
        self.log_text.configure(state=tk.NORMAL)
        prefix = {
            "user": "[YOU] ",
            "assistant": "[AGENT] ",
            "tool": "[TOOL] ",
            "tool_result": "[RESULT] ",
            "system": "[SYS] ",
            "error": "[ERROR] ",
        }.get(role, "")
        self.log_text.insert(tk.END, f"{prefix}{text}\n\n", role)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

        # Update info panel on key events
        if "Macro written" in text or "FreeCAD launched" in text or "Design complete" in text:
            self._update_info(text)

    def _update_info(self, text: str):
        self.info_text.configure(state=tk.NORMAL)
        self.info_text.insert(tk.END, text + "\n")
        self.info_text.see(tk.END)
        self.info_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _set_running_state(self, running: bool):
        if running:
            self.start_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.NORMAL)
            self.prompt_text.configure(state=tk.DISABLED)
            self.status_var.set("Running...")
        else:
            self.start_btn.configure(state=tk.NORMAL)
            self.pause_btn.configure(state=tk.DISABLED, text="Pause")
            self.stop_btn.configure(state=tk.DISABLED)
            self.prompt_text.configure(state=tk.NORMAL)
            self.status_var.set("Ready")

    def _on_attach_image(self):
        paths = filedialog.askopenfilenames(
            title="Select floor plan or reference images",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self.image_paths.extend(paths)
            names = [os.path.basename(p) for p in self.image_paths]
            self.image_label.configure(
                text=f"{len(self.image_paths)} image(s): {', '.join(names)}",
                foreground="#2563eb",
            )

    def _on_clear_images(self):
        self.image_paths.clear()
        self.image_label.configure(text="No images attached", foreground="#6b7280")

    def _on_model_changed(self, event=None):
        """Update the provider label when the model changes."""
        model = self.model_var.get()
        if model in MODEL_REGISTRY:
            provider = MODEL_REGISTRY[model][0]
            labels = {
                "anthropic": "(Anthropic)",
                "deepseek": "(DeepSeek)",
                "openai": "(OpenAI)",
                "grok": "(xAI / Grok)",
            }
            self.provider_label.configure(text=labels.get(provider, f"({provider})"))

    def _on_start(self):
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            self._append_log("error", "Please enter a building request.")
            return

        model = self.model_var.get()

        # Look up the correct API key for the selected provider
        if model in MODEL_REGISTRY:
            provider = MODEL_REGISTRY[model][0]
            env_var = PROVIDER_KEY_ENV.get(provider, "")
            api_key = os.environ.get(env_var, "") or None
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "") or None

        images = list(self.image_paths)  # snapshot

        self.state.reset()
        self._set_running_state(True)

        # Clear log
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

        # Clear info
        self.info_text.configure(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.configure(state=tk.DISABLED)

        def _run():
            try:
                run_agent(
                    user_prompt=prompt,
                    state=self.state,
                    on_message=self._append_log,
                    api_key=api_key,
                    model=model,
                    image_paths=images if images else None,
                )
            finally:
                self.root.after(0, self._set_running_state, False)

        self.agent_thread = threading.Thread(target=_run, daemon=True)
        self.agent_thread.start()

    def _on_pause(self):
        if self.state.is_paused:
            self.state.resume()
            self.pause_btn.configure(text="Pause")
            self.status_var.set("Running...")
        else:
            self.state.pause()
            self.pause_btn.configure(text="Resume")
            self.status_var.set("Paused")

    def _on_stop(self):
        self.state.stop()
        self.status_var.set("Stopping...")

    def _on_reset(self):
        self.state.reset()
        self._set_running_state(False)
        # Clear log
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        # Clear info
        self.info_text.configure(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.configure(state=tk.DISABLED)
        self.status_var.set("Reset - Ready")
