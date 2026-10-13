"""Create and verify a local source ZIP with an explicit release manifest."""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md",
    "PROJECT_STATUS.md",
    "AGENTS.md",
    "PRODUCT.md",
    "DESIGN.md",
    ".gitignore",
    ".env.example",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
}
FOLDERS = {"backend", "frontend", "scripts", "docs", "data", "evals", "artifacts"}
EXCLUDED = {
    ".git",
    ".env",
    ".runtime",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "test-results",
    "playwright-report",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def allowed(path):
    parts = path.parts
    return (
        (len(parts) == 1 and parts[0] in ROOT_FILES or parts[0] in FOLDERS)
        and not any(p in EXCLUDED for p in parts)
        and not path.name.startswith(".env")
        or path.as_posix() == ".env.example"
    ) and path.suffix.lower() not in {".pyc", ".pyo", ".log", ".tsbuildinfo", ".webm"}


def pack(destination):
    if destination.exists():
        raise RuntimeError("Use a new ZIP filename; existing evidence is never overwritten")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings

    settings = Settings()
    secrets = [settings.database_url.get_secret_value().encode()]
    if settings.deepseek_api_key:
        secrets.append(settings.deepseek_api_key.get_secret_value().encode())
    for name in ("admin-password", "app-password"):
        file = ROOT / ".runtime" / name
        if file.exists():
            secrets.append(file.read_bytes().strip())
    entries = {}
    for folder in sorted(FOLDERS):
        for file in sorted((ROOT / folder).rglob("*")):
            relative = file.relative_to(ROOT)
            if file.is_file() and allowed(relative):
                if file.is_symlink():
                    raise RuntimeError("Symlinks are not release files")
                entries[relative.as_posix()] = file.read_bytes()
    for name in sorted(ROOT_FILES):
        file = ROOT / name
        if file.is_file():
            entries[name] = file.read_bytes()
    for name, data in entries.items():
        if any(secret and secret in data for secret in secrets):
            raise RuntimeError(f"Private value detected in {name}; value suppressed")
    manifest = {
        "release": "0.6.0-local-m6",
        "scope": "Local simulated source; video distributed separately",
        "files": {name: digest(data) for name, data in entries.items()},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        archive.writestr("RELEASE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    verify(destination)
    destination.with_suffix(".sha256").write_text(
        digest(destination.read_bytes()) + "  " + destination.name + "\n", encoding="utf-8"
    )
    return manifest


def verify(source):
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)), "Duplicate ZIP entry"
        assert archive.testzip() is None, "Corrupt ZIP"
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        assert set(names) == set(manifest["files"]) | {"RELEASE_MANIFEST.json"}
        for name, expected in manifest["files"].items():
            path = Path(name)
            assert not path.is_absolute() and ".." not in path.parts and "\\" not in name
            assert allowed(path), f"Disallowed release path: {name}"
            assert digest(archive.read(name)) == expected, f"Hash mismatch: {name}"
        for name in ("uv.lock", "frontend/package-lock.json", ".env.example", "README.md"):
            assert name in names
    print(
        json.dumps(
            {
                "status": "PASS",
                "files": len(manifest["files"]),
                "zip_sha256": digest(source.read_bytes()),
            }
        )
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["pack", "verify"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.action == "pack":
        pack(args.path.resolve())
    else:
        verify(args.path.resolve())
