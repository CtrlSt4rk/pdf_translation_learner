"""Local LLM backend management (Ollama & LM Studio): detection, setup, and grading."""

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

ProgressCallback = Callable[[float, str], None]


def extract_json_object(raw_text: str) -> dict:
    """Parse JSON safely even if a GGUF model wraps it in markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


# --- Binary & App Detection ---
def find_ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found

    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        candidates = [
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
        ]
    elif system == "Windows":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        candidates = [
            local_app / "Programs/Ollama/ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
        ]
    else:
        candidates = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]

    for path in candidates:
        if path.exists():
            return str(path)
    return None


def find_lmstudio_paths() -> tuple[str | None, str | None]:
    """Return (lms_cli_path, gui_app_path) if LM Studio is installed."""
    lms_cli = shutil.which("lms")
    if not lms_cli:
        home_lms = Path.home() / ".lmstudio/bin" / ("lms.exe" if platform.system() == "Windows" else "lms")
        if home_lms.exists():
            lms_cli = str(home_lms)

    system = platform.system()
    gui_app = None
    if system == "Darwin":
        for p in [Path("/Applications/LM Studio.app"), Path.home() / "Applications/LM Studio.app"]:
            if p.exists():
                gui_app = str(p)
                break
    elif system == "Windows":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        for p in [
            local_app / "Programs/LM Studio/LM Studio.exe",
            local_app / "LM-Studio/LM Studio.exe",
            Path("C:/Program Files/LM Studio/LM Studio.exe"),
        ]:
            if p.exists():
                gui_app = str(p)
                break

    return lms_cli, gui_app


# --- Server & Model Queries ---
def is_server_running(provider: str, host: str) -> bool:
    endpoint = "/api/tags" if provider == "Ollama" else "/v1/models"
    try:
        req = urllib.request.Request(f"{host.rstrip('/')}{endpoint}", method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def get_installed_models(provider: str, host: str) -> list[str]:
    endpoint = "/api/tags" if provider == "Ollama" else "/v1/models"
    try:
        req = urllib.request.Request(f"{host.rstrip('/')}{endpoint}", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if provider == "Ollama":
            return [m["name"] for m in data.get("models", [])]
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []


def warm_up_ollama_model(host: str, model: str) -> None:
    try:
        payload = json.dumps({"model": model, "keep_alive": "15m"}).encode("utf-8")
        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


# --- Installation & Process Control ---
def start_ollama_server(binary: str | None) -> None:
    system = platform.system()
    if system == "Darwin" and Path("/Applications/Ollama.app").exists():
        subprocess.Popen(["open", "-gj", "/Applications/Ollama.app"])
        return
    if binary:
        creationflags = subprocess.CREATE_NO_WINDOW if system == "Windows" else 0
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )


def start_lmstudio_server(lms_cli: str | None, gui_app: str | None) -> None:
    if lms_cli:
        creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        subprocess.run(
            [lms_cli, "server", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    elif gui_app:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", gui_app])
        else:
            subprocess.Popen([gui_app])


def load_lmstudio_model(lms_cli: str, model: str) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    subprocess.run(
        [lms_cli, "load", model, "--yes"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def install_ollama_for_os(on_progress: ProgressCallback) -> None:
    system = platform.system()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ollama_setup_"))

    if system == "Windows":
        url = "https://ollama.com/download/OllamaSetup.exe"
        installer = tmp_dir / "OllamaSetup.exe"
        _download_file(url, installer, "Downloading Ollama for Windows", 0.05, 0.20, on_progress)
        on_progress(0.22, "Installing Ollama silently (please wait)...")
        subprocess.run([str(installer), "/VERYSILENT", "/NORESTART"], check=True)

    elif system == "Darwin":
        url = "https://ollama.com/download/Ollama-darwin.zip"
        zip_path = tmp_dir / "Ollama-darwin.zip"
        _download_file(url, zip_path, "Downloading Ollama for macOS", 0.05, 0.20, on_progress)
        on_progress(0.22, "Installing Ollama.app to /Applications...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
        extracted_app = tmp_dir / "Ollama.app"
        dest_app = Path("/Applications/Ollama.app")
        if dest_app.exists():
            shutil.rmtree(dest_app, ignore_errors=True)
        shutil.move(str(extracted_app), str(dest_app))

    elif system == "Linux":
        on_progress(0.15, "Running official Ollama Linux installer...")
        subprocess.run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
    else:
        raise RuntimeError(f"Unsupported OS for automatic installation: {system}")


def pull_ollama_model(host: str, model: str, on_progress: ProgressCallback) -> None:
    on_progress(0.30, f"Requesting {model} from Ollama library...")
    payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw_line in resp:
            if not raw_line.strip():
                continue
            event = json.loads(raw_line.decode("utf-8"))
            if "error" in event:
                raise RuntimeError(event["error"])
            status = event.get("status", "Downloading...")
            total = event.get("total", 0)
            completed = event.get("completed", 0)
            if total > 0:
                ratio = completed / total
                prog = 0.30 + 0.68 * ratio
                gb_done = completed / (1024**3)
                gb_tot = total / (1024**3)
                on_progress(prog, f"Pulling {model}: {gb_done:.2f} / {gb_tot:.2f} GB ({ratio * 100:.0f}%)")
            else:
                on_progress(0.95, f"Pulling {model}: {status}")


def _download_file(
    url: str, dest: Path, label: str, start_p: float, end_p: float, on_progress: ProgressCallback
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "TranslationTrainer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    ratio = downloaded / total
                    prog = start_p + (end_p - start_p) * ratio
                    mb_done = downloaded / (1024 * 1024)
                    mb_tot = total / (1024 * 1024)
                    on_progress(prog, f"{label}: {mb_done:.0f} / {mb_tot:.0f} MB ({ratio * 100:.0f}%)")


# --- Translation Grading ---
def grade_sentence(
    provider: str,
    host: str,
    model: str,
    source_sentence: str,
    attempt: str,
    src_lang: str,
    tgt_lang: str,
) -> dict:
    prompt = (
        f"You are a concise, expert translation tutor.\n"
        f"Source language: {src_lang}\n"
        f"Target language: {tgt_lang}\n\n"
        f'Original sentence:\n"{source_sentence}"\n\n'
        f'Student translation:\n"{attempt}"\n\n'
        f"Evaluate fairly. Accept valid synonyms and natural phrasing, but flag mistranslations, "
        f"missed idioms, tense errors, or awkward literalisms.\n"
        f"Respond ONLY with a valid JSON object matching this exact schema:\n"
        f'{{"score": <int 1-10>, "verdict": "<Accurate | Minor Nuance Missed | Needs Revision>", '
        f'"feedback": "<concise explanation>", "natural_translation": "<idiomatic reference translation>"}}'
    )

    host = host.rstrip("/")
    if provider == "Ollama":
        url = f"{host}/api/generate"
        body = {
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": 0.2},
        }
    else:
        url = f"{host}/v1/chat/completions"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You output only valid JSON objects."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": False,
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    content_str = raw.get("response", "{}") if provider == "Ollama" else raw["choices"][0]["message"]["content"]
    return extract_json_object(content_str)
