from pathlib import Path

# ---- настройки ----
ROOT = Path(".")
OUT = Path("project_dump.txt")

EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".tests", "tests",
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "node_modules", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build", ".eggs",
}

EXCLUDE_SUFFIXES = {
    ".db-wal", ".db-shm", ".db", ".sqlite", ".sqlite3",
    ".pyc", ".pyo", ".pyd",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".so", ".dll", ".dylib", ".exe", ".bin",
    ".lock",  # при желании закомментируй, если нужен uv.lock/poetry.lock
}

EXCLUDE_NAMES = {
    OUT.name,
    ".DS_Store", "Thumbs.db",
    ".env",  # ⚠️ секреты — не отправляй в LLM
}

MAX_FILE_SIZE = 200 * 1024  # 200 КБ на файл
# --------------------

def is_binary(path: Path, chunk_size: int = 8192) -> bool:
    """Эвристика: файл считается бинарным, если в первых байтах есть NUL."""
    try:
        with path.open("rb") as f:
            return b"\x00" in f.read(chunk_size)
    except OSError:
        return True

def walk(root: Path):
    """Рекурсивный обход файлов с исключениями."""
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if item.is_symlink():
            continue
        if item.is_dir():
            if item.name in EXCLUDE_DIRS:
                continue
            yield from walk(item)
            continue

        if item.name in EXCLUDE_NAMES:
            continue
        if item.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if item.name.startswith(".") and item.suffix == "":
            # скрытые файлы без расширения (.gitignore и т.п.) — при желании оставить
            pass

        try:
            if item.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue

        if is_binary(item):
            continue

        yield item

def relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()

def main() -> None:
    written = 0
    skipped = 0

    with OUT.open("w", encoding="utf-8") as out:
        for f in walk(ROOT):
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                skipped += 1
                continue

            rel = relative(f, ROOT)
            out.write(f"===== FILE: {rel} =====\n")
            out.write(text)
            if not text.endswith("\n"):
                out.write("\n")
            out.write("\n")
            written += 1

    size_kb = OUT.stat().st_size / 1024
    print(f"Готово: {OUT}  |  файлов: {written}, пропущено: {skipped}, размер: {size_kb:.1f} КБ")

if __name__ == "__main__":
    main()