#!/usr/bin/env python3
"""
PDF Sentence-by-Sentence Translation Trainer (Desktop GUI)
Packages cleanly into Windows .exe and macOS .app via PyInstaller.
"""

import json
import os
import re
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

CONFIG_PATH = Path.home() / ".translation_trainer_config.json"


# --- Structured Output Schema ---
class GradeResult(BaseModel):
    score: int = Field(description="Score from 1 to 10 based on accuracy and naturalness.")
    verdict: str = Field(description="Short status: 'Accurate', 'Minor Nuance Missed', or 'Needs Revision'.")
    feedback: str = Field(description="Concise explanation of grammar, vocabulary, or tone issues.")
    natural_translation: str = Field(description="A natural, idiomatic reference translation.")


# --- Self-Contained Sentence Splitter (No external NLTK data needed) ---
ABBREVIATIONS = (
    r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bProf)(?<!\bSr)(?<!\bSra)"
    r"(?<!\bSt)(?<!\bvs)(?<!\betc)(?<!\be\.g)(?<!\bi\.e)(?<!\bFig)(?<!\bVol)"
)
SENTENCE_SPLIT_RE = re.compile(ABBREVIATIONS + r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ\"'“‘(])")


def extract_sentences_from_pdf(pdf_path: Path) -> list[str]:
    """Extract text from PDF, clean hyphenated line breaks, and split into sentences."""
    doc = fitz.open(pdf_path)
    raw_pages = []

    for page in doc:
        text = page.get_text("text")
        text = re.sub(r"-\s*\n\s*", "", text)
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        raw_pages.append(text)

    full_text = "\n\n".join(raw_pages)
    full_text = re.sub(r"[ \t]+", " ", full_text)

    sentences = []
    for paragraph in full_text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        parts = SENTENCE_SPLIT_RE.split(paragraph)
        for s in parts:
            s = s.strip()
            if len(s) > 3 and not s.isdigit():
                sentences.append(s)
    return sentences


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
        self.config_data = self._load_config()

        self._build_ui()
        self._restore_last_session()

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"api_key": os.environ.get("GEMINI_API_KEY", ""), "src": "English", "tgt": "Portuguese"}

    def _save_config(self) -> None:
        self.config_data["api_key"] = self.api_key_entry.get().strip()
        self.config_data["src"] = self.src_entry.get().strip()
        self.config_data["tgt"] = self.tgt_entry.get().strip()
        if self.pdf_path:
            self.config_data["last_pdf"] = str(self.pdf_path)
        CONFIG_PATH.write_text(json.dumps(self.config_data, indent=2), encoding="utf-8")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Top Bar: File & Settings ---
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        self.open_btn = ctk.CTkButton(top_frame, text="Open PDF Book", command=self.open_pdf, width=130)
        self.open_btn.grid(row=0, column=0, padx=10, pady=10)

        self.file_label = ctk.CTkLabel(top_frame, text="No PDF loaded", anchor="w", text_color="gray")
        self.file_label.grid(row=0, column=1, padx=6, pady=10, sticky="ew")

        ctk.CTkLabel(top_frame, text="API Key:").grid(row=0, column=2, padx=(10, 4), pady=10)
        self.api_key_entry = ctk.CTkEntry(top_frame, show="*", width=180, placeholder_text="Gemini API Key")
        self.api_key_entry.insert(0, self.config_data.get("api_key", ""))
        self.api_key_entry.grid(row=0, column=3, padx=(0, 10), pady=10)

        # --- Second Bar: Languages & Navigation ---
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

        # Action Buttons
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

        # Feedback Area
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

        if self.progress_path.exists():
            self.state = json.loads(self.progress_path.read_text(encoding="utf-8"))
        else:
            sentences = extract_sentences_from_pdf(pdf_path)
            if not sentences:
                messagebox.showerror("Empty PDF", "No selectable text was found in this PDF.")
                return
            self.state = {"pdf_file": pdf_path.name, "current_index": 0, "sentences": sentences, "history": {}}
            self._save_progress()

        self._save_config()
        self._render_current_sentence()

    def _save_progress(self) -> None:
        if self.progress_path:
            self.progress_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

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
                self._save_progress()
                self._render_current_sentence()
            else:
                messagebox.showwarning("Out of Range", f"Enter a number between 1 and {total}.")
        except ValueError:
            pass

    def next_sentence(self) -> None:
        total = len(self.state.get("sentences", []))
        if total and self.state["current_index"] < total:
            self.state["current_index"] += 1
            self._save_progress()
            self._render_current_sentence()

    def submit_translation(self) -> None:
        sentences = self.state.get("sentences", [])
        idx = self.state.get("current_index", 0)
        if not sentences or idx >= len(sentences):
            return

        attempt = self.attempt_box.get("1.0", "end").strip()
        if not attempt:
            return

        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showwarning("Missing API Key", "Please paste your Gemini API key in the top-right box.")
            return

        self._save_config()
        source_sentence = sentences[idx]
        src_lang = self.src_entry.get().strip() or "English"
        tgt_lang = self.tgt_entry.get().strip() or "Portuguese"

        self.check_btn.configure(state="disabled", text="Grading...")
        self._set_feedback("Evaluating your translation...")

        threading.Thread(
            target=self._run_grading_worker,
            args=(api_key, idx, source_sentence, attempt, src_lang, tgt_lang),
            daemon=True,
        ).start()

    def _run_grading_worker(
        self, api_key: str, idx: int, source_sentence: str, attempt: str, src_lang: str, tgt_lang: str
    ) -> None:
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                f"You are an expert translation tutor.\n"
                f"Source language: {src_lang}\nTarget language: {tgt_lang}\n\n"
                f'Original sentence:\n"{source_sentence}"\n\n'
                f'Student\'s translation:\n"{attempt}"\n\n'
                f"Evaluate fairly. Accept valid synonyms and natural phrasing, "
                f"but flag mistranslations, missed idioms, tense errors, or awkward literalisms."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GradeResult,
                    temperature=0.2,
                ),
            )
            result = GradeResult.model_validate_json(response.text)
            self.after(0, lambda: self._on_grade_success(idx, source_sentence, attempt, result))
        except Exception as exc:
            self.after(0, lambda: self._on_grade_error(str(exc)))

    def _on_grade_success(self, idx: int, source_sentence: str, attempt: str, result: GradeResult) -> None:
        self.check_btn.configure(state="normal", text="Check Translation")
        report = (
            f"Score: {result.score}/10  —  {result.verdict}\n\n"
            f"Feedback:\n{result.feedback}\n\n"
            f"Reference Translation:\n{result.natural_translation}"
        )
        self._set_feedback(report)
        self.state["history"][str(idx)] = {
            "source": source_sentence,
            "attempt": attempt,
            "score": result.score,
            "verdict": result.verdict,
        }
        self._save_progress()

    def _on_grade_error(self, error_msg: str) -> None:
        self.check_btn.configure(state="normal", text="Check Translation")
        self._set_feedback(f"Error contacting Gemini API:\n{error_msg}")


if __name__ == "__main__":
    app = TranslationTrainerApp()
    app.mainloop()