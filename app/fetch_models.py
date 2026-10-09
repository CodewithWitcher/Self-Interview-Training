"""Download model files into data/models/: uv run python -m app.fetch_models

This runs outside create_app, so the offline rule of AR 9 rule 11 does not apply to it.
"""

import argparse

from app import embeddings
from app.config import load_settings


def fetch_embedding_model(settings) -> None:
    from fastembed import TextEmbedding

    target = embeddings.cache_dir(settings)
    target.mkdir(parents=True, exist_ok=True)
    print(f"Embedding model {embeddings.MODEL_NAME}: downloading into {target}")
    model = TextEmbedding(embeddings.MODEL_NAME, cache_dir=str(target))
    dim = len(next(iter(model.embed(["check"]))))
    print(f"Embedding model ready: {dim} dimensions")


def fetch_speech_model(settings) -> None:
    from app import voice

    target = voice.model_dir(settings)
    target.mkdir(parents=True, exist_ok=True)
    print(f"Speech model {settings.whisper_model}: downloading into {target}")
    voice.load_model(settings, local_files_only=False)
    print("Speech model ready")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download model files into the data folder.")
    parser.add_argument("--voice", action="store_true", help="also download the speech model")
    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        fetch_embedding_model(settings)
        if args.voice:
            fetch_speech_model(settings)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Download failed: {exc}".encode("ascii", "replace").decode("ascii"))
        print("Check the network connection and try again.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
