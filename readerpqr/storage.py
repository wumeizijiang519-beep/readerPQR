"""Settings, Windows user-bound DPAPI protection, and resumable SQLite cache."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sqlite3
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PROMPT_VERSION = "pqr-translate-v1"
DEFAULT_GLOSSARY = "world model=世界模型\naction chunk=动作块\nimitation learning=模仿学习\npolicy=策略\nlatent representation=潜在表征"


def data_dir() -> Path:
    if os.environ.get("READERPQR_DATA_DIR"):
        path = Path(os.environ["READERPQR_DATA_DIR"])
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "readerPQR"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "readerPQR"
    path.mkdir(parents=True, exist_ok=True)
    return path


def endpoint_url(value: str) -> str:
    value = value.strip().rstrip("/")
    url = urlsplit(value)
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("API 地址必须是无账号、查询参数和片段的有效 URL。")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("远程 API 必须使用 HTTPS；仅本机地址允许 HTTP。")
    return value if value.endswith("/chat/completions") else value + "/chat/completions"


@dataclass
class Settings:
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4.7-flash"
    api_key: str = field(default="", repr=False)
    remember_key: bool = False
    auto_translate: bool = True
    consent_endpoint: str = ""
    timeout: int = 90
    batch_chars: int = 4500
    glossary: str = DEFAULT_GLOSSARY
    extra_json: str = '{"thinking":{"type":"disabled"}}'

    def extra(self) -> dict:
        try:
            result = json.loads(self.extra_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("高级参数必须是合法 JSON 对象。") from exc
        if not isinstance(result, dict):
            raise ValueError("高级参数必须是 JSON 对象。")
        forbidden = {"model", "messages", "stream", "tools", "tool_choice", "functions", "function_call"}
        if forbidden.intersection(result):
            raise ValueError("高级参数不能覆盖模型、消息、流式设置或工具调用。")
        return result

    def validate(self):
        endpoint_url(self.base_url)
        if not self.model.strip():
            raise ValueError("请输入模型名称。")
        if not 10 <= self.timeout <= 300 or not 500 <= self.batch_chars <= 12000:
            raise ValueError("超时应为 10–300 秒，批次字符数应为 500–12000。")
        self.extra()

    def profile_id(self) -> str:
        # Keys never appear in cache identities; model/endpoint/prompts all do.
        payload = [endpoint_url(self.base_url), self.model, self.glossary,
                   self.extra(), self.batch_chars, PROMPT_VERSION]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("仅 Windows 支持持久保存密钥；其他平台仅在内存使用。")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buf)
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Windows 无法加密/解密密钥，请重新输入并检查当前用户权限。")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def save_settings(settings: Settings, directory: Path | None = None):
    settings.validate()
    path = (directory or data_dir()) / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    values = asdict(settings)
    key = values.pop("api_key")
    if settings.remember_key and key:
        values["protected_key"] = base64.b64encode(_dpapi(key.encode())).decode()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


def load_settings(directory: Path | None = None) -> Settings:
    path = (directory or data_dir()) / "settings.json"
    if not path.exists():
        return Settings()
    values = json.loads(path.read_text(encoding="utf-8"))
    protected = values.pop("protected_key", "")
    fields = Settings.__dataclass_fields__
    settings = Settings(**{k: v for k, v in values.items() if k in fields and k != "api_key"})
    if protected:
        try:
            settings.api_key = _dpapi(base64.b64decode(protected), decrypt=True).decode()
        except Exception:
            settings.api_key = ""  # Never fall back to plaintext storage.
    settings.validate()
    return settings


class Cache:
    """One connection per thread; safe to use concurrently through SQLite WAL."""
    def __init__(self, directory: Path | None = None):
        self.path = (directory or data_dir()) / "translations.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=20)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS translations (
            document TEXT, profile TEXT, block TEXT, source_hash TEXT, translation TEXT,
            PRIMARY KEY(document, profile, block, source_hash))""")
        self.db.commit()

    def get(self, document: str, profile: str, block: str, text: str) -> str | None:
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self.db.execute("SELECT translation FROM translations WHERE document=? AND profile=? AND block=? AND source_hash=?",
                              (document, profile, block, digest)).fetchone()
        return row[0] if row else None

    def put(self, document: str, profile: str, block: str, text: str, translation: str):
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.db.execute("INSERT OR REPLACE INTO translations VALUES (?,?,?,?,?)",
                        (document, profile, block, digest, translation))
        self.db.commit()  # A finished batch survives a crash or cancellation.

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
