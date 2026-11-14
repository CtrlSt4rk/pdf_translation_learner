# PDF Translation Trainer

A cross-platform desktop application for practicing sentence-by-sentence translation directly from PDF books, graded locally using **Ollama** or **LM Studio**.

## Features
- **Clean PDF Extraction:** Automatically stitches hyphenated line breaks and segments text into sentences.
- **Resumable Progress:** Saves your current sentence index and grading history in a `.progress.json` companion file alongside your PDF.
- **100% Local AI Grading:** Supports both **Ollama** (`gemma3:4b`, `qwen2.5:3b`, `qwen2.5:7b`) and **LM Studio**.
- **1-Click Setup:** Built-in Settings dialog can install Ollama, launch the local server, and download models automatically.

## Running from Source
```bash
pip install -r requirements.txt
python main.py
```

## Building Standalone Binaries (`.exe` & `.app`)
Push this repository to GitHub and trigger the **Build Desktop Apps** workflow in the **Actions** tab to download compiled Windows `.exe` and macOS `.app` artifacts.
