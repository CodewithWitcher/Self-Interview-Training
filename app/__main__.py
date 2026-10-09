"""Start the app: uv run python -m app"""

import logging

import uvicorn

from app.config import load_settings
from app.main import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    app = create_app(settings)
    print(f"Self Interview Training is running at http://127.0.0.1:{settings.port}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
