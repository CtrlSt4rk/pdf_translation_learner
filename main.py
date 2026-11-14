#!/usr/bin/env python3
"""Main entry point and translation workspace UI."""

import threading
import time
import urllib.error
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import load_config, load_progress, save_config, save_progress
from llm_client import (
    find_lmstudio_paths,
    find_ollama_binary,
    get_installed_models,
    grade_sentence,
    is_server_running,
    start_lmstudio_server,
    start_ollama_server,
    warm_up_ollama_model,
)
from pdf_parser import extract_sentences_from_pdf
from settings_ui import SettingsWindow


class TranslationTrainerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("PDF Translation Trainer")
        self.geometry("860x720")
        self.minsize(720, 600)

        self.pdf_path: Path | None = None
        self.progress_path: Path | None = None
        self.state: dict = {"current_index": 0, "sentences": [], "history": {}}
        self.config_data = load_config()

        self._build_ui()
        self._restore_last_session()
        self._ensure_ready_and_warmup()

    def _persist_config(self) -> None:
        self.config_data["src"] = self.src_entry.get().strip()
        self.config_data["tgt"] = self.tgt_entry.get().strip()
        if self.pdf_path:
            self.config_data["last_pdf"] = str(self.pdf_path)
        save_config(self.config_data)

    def apply_settings(self, provider: str, model: str, host: str) -> None:
        self.config_data["provider"] = provider
        self.config_data["model"] = model
        if provider == "Ollama":
            self.config_data["ollama_host"] = host
        else:
            self.config_data["lmstudio_host"] = host
        self.active_model_label.configure(text=f"{provider}: {model}")
        self._persist_config()
        self._ensure_ready_and_warmup()

    def _active_host(self) -> str:
        provider = self.config_data.get("provider", "Ollama")
        if provider == "Ollama":
            return self.config_data.get("ollama_host", "http://localhost:11434").rstrip("/")
        return self.config_data.get("lmstudio_host", "http://localhost:1234").rstrip("/")

    def _ensure_ready_and_warmup(self) -> None:
        provider = self.config_data.get("provider", "Ollama")
        model = self.config_data.get("model", "gemma3:4b")
        host = self._active_host()

        def worker():
            # Auto-detect LM Studio if Ollama isn't installed/running
            if provider == "Ollama" and not is_server_running("Ollama", host) and not find_ollama_binary():
                lms_host = self.config_data.get("lmstudio_host", "http://localhost:1234").rstrip("/")
                if is_server_running("LM Studio", lms_host):
                    models = get_installed_models("LM Studio", lms_host)
                    chosen = models[0] if models else "local-model"
                    self.after(0, lambda: self.apply_settings("LM Studio", chosen, lms_host))
                    return

            if provider == "Ollama":
                if not is_server_running("Ollama", host):
                    binary = find_ollama_binary()
                    if not binary:
                        self.after(300, lambda: SettingsWindow(self))
                        return
                    start_ollama_server(binary)
                    for _ in range(20):
                        if is_server_running("Ollama", host):
                            break
                        time.sleep(0.5)
                warm_up_ollama_model(host, model)
            else:
                if not is_server_running("LM Studio", host):
                    lms_cli, _ = find_lmstudio_paths()
                    if lms_cli:
                        start_lmstudio_server(lms_cli, None)
                    else:
                        self.after(300, lambda: SettingsWindow(self))

        threading.Thread(target=worker, daemon=True).start()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Top Bar ---
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        self.open_btn = ctk.CTkButton(top_frame, text="Open PDF Book", command=self.open_pdf, width=130)
        self.open_btn.grid(row=0, column=0, padx=10, pady=10)

        self.file_label = ctk.CTkLabel(top_frame, text="No PDF loaded", anchor="w", text_color="gray")
        self.file_label.grid(row=0, column=1, padx=6, pady=10, sticky="ew")

        provider = self.config_data.get("provider", "Ollama")
        current_model = self.config_data.get("model", "gemma3:4b")
        self.active_model_label = ctk.CTkLabel(
            top_frame, text=f"{provider}: {current_model}", text_color="gray", font=ctk.CTkFont(size=12)
        )
        self.active_model_label.grid(row=0, column=2, padx=(8, 10), pady=10)

        self.settings_btn = ctk.CTkButton(
            top_frame,
            text="⚙ Settings",
            command=lambda: SettingsWindow(self),
            width=100,
            fg_color="gray35",
            hover_color="gray25",
        )
        self.settings_btn.grid(row=0, column=3, padx=(0, 10), pady=10)

        # --- Language & Navigation Bar ---
        nav_frame = ctk.CTkFrame(self)
        nav_frame.grid(row=1, column=0, padx=16, pady=4, sticky="ew")

        ctk.CTkLabel(nav_frame, text="From:").pack(side="left", padx=(12, 4), pady=8)
        self.src_entry = ctk.CTkEntry(nav_frame, width=110)
        self.src_entry.insert(0, self.config_data.get("src", "English"))
        self.src_entry.pack(side="left", padx=4, pady=8)

        ctk.CTkLabel(nav_frame, text="To:").pack(side="left", padx=(10, 4), pady=8)
        self.tgt_entry = ctk.CTkEntry(nav_frame, width=110)
        self.tgt_entry.insert(0, self.config_data.get("tgt", "Portuguese"))
        self.tgt_entry.pack(side="left", padx=4, pady=8)

        self.progress_label = ctk.CTkLabel(nav_frame, text="Sentence 0 / 0", font=ctk.CTkFont(weight="bold"))
        self.progress_label.pack(side="right", padx=12, pady=8)

        self.jump_btn = ctk.CTkButton(nav_frame, text="Go", width=45, command=self.jump_to_sentence)
        self.jump_btn.pack(side="right", padx=(2, 10), pady=8)

        self.jump_entry = ctk.CTkEntry(nav_frame, width=60, placeholder_text="#")
        self.jump_entry.pack(side="right", padx=2, pady=8)

        # --- Main Workspace ---
        work_frame = ctk.CTkFrame(self)
        work_frame.grid(row=2, column=0, padx=16, pady=8, sticky="nsew")
        work_frame.grid_columnconfigure(0, weight=1)
        work_frame.grid_rowconfigure(1, weight=1)
        work_frame.grid_rowconfigure(3, weight=1)
        work_frame.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(work_frame, text="Original Sentence:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(10, 2), sticky="w"
        )
        self.source_box = ctk.CTkTextbox(work_frame, height=100, font=ctk.CTkFont(size=15), wrap="word")
        self.source_box.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.source_box.configure(state="disabled")

        ctk.CTkLabel(work_frame, text="Your Translation (Ctrl+Enter to submit):", font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, padx=12, pady=(4, 2), sticky="w"
        )
        self.attempt_box = ctk.CTkTextbox(work_frame, height=100, font=ctk.CTkFont(size=15), wrap="word")
        self.attempt_box.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.attempt_box.bind("<Control-Return>", lambda e: self.submit_translation())
        self.attempt_box.bind("<Command-Return>", lambda e: self.submit_translation())

        btn_row = ctk.CTkFrame(work_frame, fg_color="transparent")
        btn_row.grid(row=4, column=0, padx=12, pady=4, sticky="ew")

        self.check_btn = ctk.CTkButton(
            btn_row, text="Check Translation", command=self.submit_translation, fg_color="#1f6aa5"
        )
        self.check_btn.pack(side="left", padx=(0, 8))

        self.skip_btn = ctk.CTkButton(
            btn_row, text="Skip Sentence", command=self.next_sentence, fg_color="gray40", hover_color="gray30"
        )
        self.skip_btn.pack(side="left", padx=4)

        self.next_btn = ctk.CTkButton(
            btn_row, text="Next Sentence ->", command=self.next_sentence, fg_color="#2fa572", hover_color="#248259"
        )
        self.next_btn.pack(side="right")

        self.feedback_box = ctk.CTkTextbox(work_frame, height=140, font=ctk.CTkFont(size=14), wrap="word")
        self.feedback_box.grid(row=5, column=0, padx=12, pady=(8, 12), sticky="nsew")
        self.feedback_box.configure(state="disabled")

    def _restore_last_session(self) -> None:
        last_pdf = self.config_data.get("last_pdf")
        if last_pdf and Path(last_pdf).exists():
            self._load_pdf(Path(last_pdf))

    def open_pdf(self) -> None:
        file_str = filedialog.askopenfilename(filetypes=[("PDF Documents", "*.pdf")])
        if file_str:
            self._load_pdf(Path(file_str))

    def _load_pdf(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path
        self.progress_path = pdf_path.with_suffix(".progress.json")
        self.file_label.configure(text=pdf_path.name, text_color=("black", "white"))

        existing = load_progress(self.progress_path)
        if existing:
            self.state = existing
        else:
            sentences = extract_sentences_from_pdf(pdf_path)
            if not sentences:
                messagebox.showerror("Empty PDF", "No selectable text was found in this PDF.")
                return
            self.state = {"pdf_file": pdf_path.name, "current_index": 0, "sentences": sentences, "history": {}}
            save_progress(self.progress_path, self.state)

        self._persist_config()
        self._render_current_sentence()

    def _render_current_sentence(self) -> None:
        sentences = self.state.get("sentences", [])
        total = len(sentences)
        idx = self.state.get("current_index", 0)

        self.attempt_box.delete("1.0", "end")
        self._set_feedback("")

        if total == 0:
            return
        if idx >= total:
            self.progress_label.configure(text=f"Completed ({total} / {total})")
            self._set_source("Congratulations! You have finished every sentence in this book.")
            return

        self.progress_label.configure(text=f"Sentence {idx + 1} / {total}")
        self._set_source(sentences[idx])

    def _set_source(self, text: str) -> None:
        self.source_box.configure(state="normal")
        self.source_box.delete("1.0", "end")
        self.source_box.insert("1.0", text)
        self.source_box.configure(state="disabled")

    def _set_feedback(self, text: str) -> None:
        self.feedback_box.configure(state="normal")
        self.feedback_box.delete("1.0", "end")
        self.feedback_box.insert("1.0", text)
        self.feedback_box.configure(state="disabled")

    def jump_to_sentence(self) -> None:
        total = len(self.state.get("sentences", []))
        if not total:
            return
        try:
            target = int(self.jump_entry.get().strip())
            if 1 <= target <= total:
                self.state["current_index"] = target - 1
                if self.progress_path:
                    save_progress(self.progress_path, self.state)
                self._render_current_sentence()
            else:
                messagebox.showwarning("Out of Range", f"Enter a number between 1 and {total}.")
        except ValueError:
            pass

    def next_sentence(self) -> None:
        total = len(self.state.get("sentences", []))
        if total and self.state["current_index"] < total:
            self.state["current_index"] += 1
            if self.progress_path:
                save_progress(self.progress_path, self.state)
            self._render_current_sentence()

    def submit_translation(self) -> None:
        sentences = self.state.get("sentences", [])
        idx = self.state.get("current_index", 0)
        if not sentences or idx >= len(sentences):
            return

        attempt = self.attempt_box.get("1.0", "end").strip()
        if not attempt:
            return

        self._persist_config()
        source_sentence = sentences[idx]
        src_lang = self.src_entry.get().strip() or "English"
        tgt_lang = self.tgt_entry.get().strip() or "Portuguese"
        provider = self.config_data.get("provider", "Ollama")
        model = self.config_data.get("model", "gemma3:4b")
        host = self._active_host()

        self.check_btn.configure(state="disabled", text="Grading...")
        self._set_feedback(f"Evaluating via {provider} ({model})...")

        def worker():
            try:
                result = grade_sentence(provider, host, model, source_sentence, attempt, src_lang, tgt_lang)
                self.after(0, lambda: self._on_grade_success(idx, source_sentence, attempt, result))
            except urllib.error.URLError:
                msg = (
                    f"{provider} server is not reachable at {host}.\n\n"
                    f"Click '⚙ Settings' in the top-right corner to start {provider} or switch providers."
                )
                self.after(0, lambda: self._on_grade_error(msg))
            except Exception as exc:
                self.after(0, lambda: self._on_grade_error(f"Grading error ({provider}):\n{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_grade_success(self, idx: int, source_sentence: str, attempt: str, result: dict) -> None:
        self.check_btn.configure(state="normal", text="Check Translation")
        score = result.get("score", "?")
        verdict = result.get("verdict", "Reviewed")
        feedback = result.get("feedback", "")
        natural = result.get("natural_translation", "")

        report = (
            f"Score: {score}/10  —  {verdict}\n\n"
            f"Feedback:\n{feedback}\n\n"
            f"Reference Translation:\n{natural}"
        )
        self._set_feedback(report)
        self.state["history"][str(idx)] = {
            "source": source_sentence,
            "attempt": attempt,
            "score": score,
            "verdict": verdict,
        }
        if self.progress_path:
            save_progress(self.progress_path, self.state)

    def _on_grade_error(self, error_msg: str) -> None:
        self.check_btn.configure(state="normal", text="Check Translation")
        self._set_feedback(error_msg)


if __name__ == "__main__":
    app = TranslationTrainerApp()
    app.mainloop()
