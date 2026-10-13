"""Export actual API and implemented read-tool schemas without starting a server."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent_tools import definitions  # noqa: E402
from app.main import create_app  # noqa: E402


def main():
    app = create_app()
    try:
        destination = ROOT / "docs" / "contracts"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "m5_openapi.json").write_text(
            json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (destination / "m5_tools.json").write_text(
            json.dumps(definitions(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("Exported api-v1-m5 and unchanged tools-v2-m4 schemas; historical contracts retained")
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
