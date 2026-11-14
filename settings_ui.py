"""Modal Settings and Automatic Local LLM Setup dialog."""

import threading
import time
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from config import LMSTUDIO_DEFAULT_MODELS, OLLAMA_DEFAULT_MODELS
from llm_client import (
    find_lmstudio_paths,
    find_ollama_binary,
    get_installed_models,
    install_ollama_for_os,
    is_server_running,
    load_lmstudio_model,
    pull_ollama_model,
    start_lmstudio_server,
    start_ollama_server,
)

if TYPE_CHECKING:
    from main import TranslationTrainerApp


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent: "TranslationTrainerApp"):
        super().__init__(parent)
        self.parent = parent
        self._busy = False

        self.title("Settings & Local Backend Setup")
        self.geometry("540x520")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        # --- Section 1: Provider & Model ---
        cfg_frame = ctk.CTkFrame(self)
        cfg_frame.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="ew")
        cfg_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(cfg_frame, text="Local AI Provider:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=14, pady=(12, 4), sticky="w"
        )
        self.provider_var = ctk.StringVar(value=parent.config_data.get("provider", "Ollama"))
        self.provider_switch = ctk.CTkSegmentedButton(
            cfg_frame,
            values=["Ollama", "LM Studio"],
            variable=self.provider_var,
            command=self._on_provider_changed,
        )
        self.provider_switch.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(cfg_frame, text="Model:", font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, padx=14, pady=(2, 2), sticky="w"
        )
        initial_models = (
            OLLAMA_DEFAULT_MODELS if self.provider_var.get() == "Ollama" else LMSTUDIO_DEFAULT_MODELS
        )
        self.model_var = ctk.StringVar(value=parent.config_data.get("model", initial_models[0]))
        self.model_combo = ctk.CTkComboBox(
            cfg_frame,
            values=initial_models,
            variable=self.model_var,
            command=lambda _: self.refresh_diagnostics(),
        )
        self.model_combo.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="ew")

        self.hint_lbl = ctk.CTkLabel(cfg_frame, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.hint_lbl.grid(row=4, column=0, padx=14, pady=(0, 10), sticky="w")

        ctk.CTkLabel(cfg_frame, text="Local Server URL:", font=ctk.CTkFont(weight="bold")).grid(
            row=5, column=0, padx=14, pady=(2, 2), sticky="w"
        )
        self.host_entry = ctk.CTkEntry(cfg_frame)
        default_host = (
            parent.config_data.get("ollama_host", "http://localhost:11434")
            if self.provider_var.get() == "Ollama"
            else parent.config_data.get("lmstudio_host", "http://localhost:1234")
        )
        self.host_entry.insert(0, default_host)
        self.host_entry.grid(row=6, column=0, padx=14, pady=(0, 14), sticky="ew")

        # --- Section 2: Diagnostics & Auto-Setup ---
        setup_frame = ctk.CTkFrame(self)
        setup_frame.grid(row=1, column=0, padx=18, pady=6, sticky="ew")
        setup_frame.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(setup_frame, fg_color="transparent")
        header_row.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")

        ctk.CTkLabel(header_row, text="System Status & Auto-Setup", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.refresh_btn = ctk.CTkButton(
            header_row,
            text="Re-check",
            width=75,
            height=24,
            fg_color="gray35",
            hover_color="gray25",
            command=self.refresh_diagnostics,
        )
        self.refresh_btn.pack(side="right")

        self.cli_status_lbl = ctk.CTkLabel(setup_frame, text="• Application: Checking...", anchor="w")
        self.cli_status_lbl.grid(row=1, column=0, padx=16, pady=2, sticky="ew")

        self.srv_status_lbl = ctk.CTkLabel(setup_frame, text="• Local Server: Checking...", anchor="w")
        self.srv_status_lbl.grid(row=2, column=0, padx=16, pady=2, sticky="ew")

        self.mdl_status_lbl = ctk.CTkLabel(setup_frame, text="• Model Status: Checking...", anchor="w")
        self.mdl_status_lbl.grid(row=3, column=0, padx=16, pady=(2, 10), sticky="ew")

        self.auto_btn = ctk.CTkButton(
            setup_frame,
            text="Auto-Install & Configure Everything",
            command=self.start_auto_setup,
            fg_color="#2fa572",
            hover_color="#248259",
            height=36,
            font=ctk.CTkFont(weight="bold"),
        )
        self.auto_btn.grid(row=4, column=0, padx=14, pady=(2, 8), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(setup_frame)
        self.progress_bar.grid(row=5, column=0, padx=14, pady=(0, 4), sticky="ew")
        self.progress_bar.set(0)

        self.task_lbl = ctk.CTkLabel(
            setup_frame, text="Ready.", font=ctk.CTkFont(size=12), text_color="gray", anchor="w"
        )
        self.task_lbl.grid(row=6, column=0, padx=14, pady=(0, 12), sticky="ew")

        # --- Footer ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=18, pady=(8, 16), sticky="ew")

        self.save_btn = ctk.CTkButton(footer, text="Save & Close", command=self._save_and_close, width=130)
        self.save_btn.pack(side="right")
        ctk.CTkButton(
            footer, text="Cancel", command=self._on_close, fg_color="transparent", border_width=1, width=90
        ).pack(side="right", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_provider_hints()
        self.refresh_diagnostics()

    def _update_provider_hints(self) -> None:
        if self.provider_var.get() == "Ollama":
            self.hint_lbl.configure(
                text="gemma3:4b (~3.3 GB, 4 GB RAM)  |  qwen2.5:3b (~1.9 GB, 2.5 GB RAM)"
            )
        else:
            self.hint_lbl.configure(
                text="Uses LM Studio's OpenAI-compatible server (default port 1234). Load any GGUF/MLX model."
            )

    def _on_provider_changed(self, provider: str) -> None:
        self.host_entry.delete(0, "end")
        if provider == "Ollama":
            self.host_entry.insert(0, self.parent.config_data.get("ollama_host", "http://localhost:11434"))
            self.model_combo.configure(values=OLLAMA_DEFAULT_MODELS)
            self.model_var.set(OLLAMA_DEFAULT_MODELS[0])
        else:
            self.host_entry.insert(0, self.parent.config_data.get("lmstudio_host", "http://localhost:1234"))
            self.model_combo.configure(values=LMSTUDIO_DEFAULT_MODELS)
            self.model_var.set(LMSTUDIO_DEFAULT_MODELS[0])

        self._update_provider_hints()
        self.progress_bar.set(0)
        self.refresh_diagnostics()

    def _on_close(self) -> None:
        if self._busy:
            messagebox.showinfo("Setup in Progress", "Please wait until the automatic setup finishes.")
            return
        self.destroy()

    def refresh_diagnostics(self) -> None:
        provider = self.provider_var.get()
        default_url = "http://localhost:11434" if provider == "Ollama" else "http://localhost:1234"
        host = self.host_entry.get().strip().rstrip("/") or default_url
        target_model = self.model_var.get().strip()

        def worker():
            if provider == "Ollama":
                installed_app = bool(find_ollama_binary())
            else:
                lms_cli, gui_app = find_lmstudio_paths()
                installed_app = bool(lms_cli or gui_app)

            running = is_server_running(provider, host)
            installed_models = get_installed_models(provider, host) if running else []

            if provider == "Ollama":
                has_model = any(
                    m == target_model or (":" not in target_model and m.startswith(f"{target_model}:"))
                    for m in installed_models
                )
            else:
                has_model = len(installed_models) > 0 and (
                    target_model in installed_models or target_model in LMSTUDIO_DEFAULT_MODELS
                )

            self.after(
                0,
                lambda: self._apply_diagnostics(
                    provider, installed_app, running, installed_models, has_model, target_model
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_diagnostics(
        self,
        provider: str,
        installed_app: bool,
        running: bool,
        installed_models: list[str],
        has_model: bool,
        target_model: str,
    ) -> None:
        if installed_app or running:
            self.cli_status_lbl.configure(text=f"✓ {provider} App: Installed", text_color="#2fa572")
        else:
            self.cli_status_lbl.configure(text=f"✗ {provider} App: Not found", text_color="#e05252")

        if running:
            self.srv_status_lbl.configure(text="✓ Local Server: Running", text_color="#2fa572")
            defaults = OLLAMA_DEFAULT_MODELS if provider == "Ollama" else LMSTUDIO_DEFAULT_MODELS
            merged = list(dict.fromkeys(installed_models + defaults))
            self.model_combo.configure(values=merged)
            if provider == "LM Studio" and installed_models and target_model not in installed_models:
                self.model_var.set(installed_models[0])
                target_model = installed_models[0]
                has_model = True
        else:
            self.srv_status_lbl.configure(text="✗ Local Server: Stopped", text_color="#e0a83b")

        if provider == "Ollama":
            if has_model:
                self.mdl_status_lbl.configure(text=f"✓ Model ({target_model}): Ready", text_color="#2fa572")
            else:
                self.mdl_status_lbl.configure(text=f"✗ Model ({target_model}): Not downloaded", text_color="#e0a83b")
        else:
            if running and installed_models:
                self.mdl_status_lbl.configure(
                    text=f"✓ LM Studio Models Available: {len(installed_models)}", text_color="#2fa572"
                )
            elif running:
                self.mdl_status_lbl.configure(text="✗ No model loaded in LM Studio yet", text_color="#e0a83b")
            else:
                self.mdl_status_lbl.configure(text="• Start LM Studio server to detect models", text_color="gray")

        ready = (installed_app or running) and running and has_model
        if ready:
            self.auto_btn.configure(text="✓ Everything Ready (Re-run Check)", fg_color="#1f6aa5")
            if not self._busy:
                self.progress_bar.set(1.0)
                self.task_lbl.configure(text="All set! Click 'Save & Close' to start translating.")
        else:
            btn_label = (
                "Auto-Install & Configure Ollama" if provider == "Ollama" else "Start LM Studio Local Server"
            )
            self.auto_btn.configure(text=btn_label, fg_color="#2fa572")

    def start_auto_setup(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.auto_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.progress_bar.set(0.05)

        provider = self.provider_var.get()
        default_url = "http://localhost:11434" if provider == "Ollama" else "http://localhost:1234"
        host = self.host_entry.get().strip().rstrip("/") or default_url
        target_model = self.model_var.get().strip()

        target_fn = self._auto_setup_ollama if provider == "Ollama" else self._auto_setup_lmstudio
        threading.Thread(target=target_fn, args=(host, target_model), daemon=True).start()

    def _set_progress(self, fraction: float, text: str) -> None:
        self.after(0, lambda: (self.progress_bar.set(fraction), self.task_lbl.configure(text=text)))

    def _auto_setup_lmstudio(self, host: str, target_model: str) -> None:
        try:
            lms_cli, gui_app = find_lmstudio_paths()
            if not lms_cli and not gui_app and not is_server_running("LM Studio", host):
                raise RuntimeError(
                    "LM Studio was not found on this computer.\n\n"
                    "Install LM Studio from lmstudio.ai, or switch the provider above to 'Ollama' for 1-click auto-install."
                )

            if not is_server_running("LM Studio", host):
                self._set_progress(0.3, "Starting LM Studio local server...")
                start_lmstudio_server(lms_cli, gui_app)
                for _ in range(30):
                    if is_server_running("LM Studio", host):
                        break
                    time.sleep(0.5)

                if not is_server_running("LM Studio", host):
                    raise RuntimeError(
                        "LM Studio launched, but its Local Server isn't listening on port 1234 yet.\n"
                        "Open the 'Local Server' (Developer) tab inside LM Studio and click 'Start Server'."
                    )

            models = get_installed_models("LM Studio", host)
            if not models and lms_cli and target_model:
                self._set_progress(0.6, f"Loading {target_model} via LM Studio CLI...")
                load_lmstudio_model(lms_cli, target_model)
                models = get_installed_models("LM Studio", host)

            if not models:
                self._set_progress(
                    0.8, "Server running! Load a model inside LM Studio (e.g., Gemma 3 4B or Qwen 2.5 3B)."
                )
            else:
                self._set_progress(1.0, f"LM Studio connected! Ready with '{models[0]}'.")
        except Exception as exc:
            self._set_progress(0.0, f"Error: {exc}")
            self.after(0, lambda: messagebox.showerror("LM Studio Setup", str(exc)))
        finally:
            self._finish_setup()

    def _auto_setup_ollama(self, host: str, target_model: str) -> None:
        try:
            binary = find_ollama_binary()
            if not binary and not is_server_running("Ollama", host):
                install_ollama_for_os(self._set_progress)
                binary = find_ollama_binary()
                if not binary and not is_server_running("Ollama", host):
                    raise RuntimeError("Ollama installation finished, but the binary was not found.")

            if not is_server_running("Ollama", host):
                self._set_progress(0.25, "Starting Ollama background server...")
                start_ollama_server(binary)
                for _ in range(30):
                    if is_server_running("Ollama", host):
                        break
                    time.sleep(0.5)
                if not is_server_running("Ollama", host):
                    raise RuntimeError("Timed out waiting for Ollama server to start on localhost:11434.")

            installed = get_installed_models("Ollama", host)
            has_model = any(
                m == target_model or (":" not in target_model and m.startswith(f"{target_model}:"))
                for m in installed
            )
            if not has_model:
                pull_ollama_model(host, target_model, self._set_progress)

            self._set_progress(1.0, f"Setup complete! '{target_model}' is installed and ready.")
        except Exception as exc:
            self._set_progress(0.0, f"Error: {exc}")
            self.after(0, lambda: messagebox.showerror("Auto-Setup Failed", str(exc)))
        finally:
            self._finish_setup()

    def _finish_setup(self) -> None:
        self._busy = False
        self.after(
            0,
            lambda: (
                self.auto_btn.configure(state="normal"),
                self.refresh_btn.configure(state="normal"),
                self.save_btn.configure(state="normal"),
                self.refresh_diagnostics(),
            ),
        )

    def _save_and_close(self) -> None:
        if self._busy:
            return
        provider = self.provider_var.get()
        selected_model = self.model_var.get().strip() or (
            "gemma3:4b" if provider == "Ollama" else "google/gemma-3-4b"
        )
        host = self.host_entry.get().strip().rstrip("/") or (
            "http://localhost:11434" if provider == "Ollama" else "http://localhost:1234"
        )
        self.parent.apply_settings(provider, selected_model, host)
        self.destroy()
