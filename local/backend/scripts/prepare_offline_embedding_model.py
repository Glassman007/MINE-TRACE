"""Provision the pinned FastEmbed model before an edge node goes offline."""

from pathlib import Path

from fastembed import TextEmbedding

from app.integrations.embeddings.fastembed_local import PINNED_DIMENSION, PINNED_MODEL


def main() -> None:
    cache = Path("models/fastembed")
    cache.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(model_name=PINNED_MODEL, cache_dir=str(cache), local_files_only=False)
    vector = next(iter(model.query_embed(("MINE-TRACE cache validation",))))
    values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    if len(values) != PINNED_DIMENSION:
        raise RuntimeError(
            f"prepared model dimension {len(values)} does not match {PINNED_DIMENSION}"
        )
    print(f"Prepared {PINNED_MODEL} ({PINNED_DIMENSION} dimensions) in {cache}")


if __name__ == "__main__":
    main()
