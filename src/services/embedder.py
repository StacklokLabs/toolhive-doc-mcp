"""Embedding generation service using local models via fastembed"""

from fastembed import TextEmbedding

from src.config import config


class Embedder:
    """Generate embeddings using local models (fastembed) with caching"""

    def __init__(self):
        """Initialize embedding model with local caching"""
        # Initialize fastembed with local caching
        self.model = TextEmbedding(model_name=config.embedding_model, threads=6)

    async def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text

        Args:
            text: Text to embed

        Returns:
            list[float]: 384-dimensional embedding vector (for bge-small-en-v1.5)
        """
        # fastembed returns generator, convert to list
        embeddings = list(self.model.embed([text]))
        return embeddings[0].tolist()

    async def embed_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches

        Args:
            texts: List of texts to embed
            batch_size: Number of texts to process per batch (default from config)

        Returns:
            list[list[float]]: List of embedding vectors
        """
        if not texts:
            return []

        batch_size = batch_size or config.embedding_batch_size

        # Process in batches for memory efficiency
        embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            # fastembed processes batches efficiently
            batch_embeddings = list(self.model.embed(batch))

            # Convert numpy arrays to lists
            embeddings.extend([emb.tolist() for emb in batch_embeddings])

            if i % 100 == 0 or i == len(texts):
                print(f"  Embedded {i}/{len(texts)} texts")

        return embeddings

    async def close(self) -> None:
        """Cleanup resources (fastembed handles cleanup automatically)"""
        # fastembed doesn't require explicit cleanup
        pass

    def download_model(self) -> None:
        """
        Pre-download model to cache directory

        Call this during build to ensure model is cached locally.
        Subsequent runs will use the cached model without re-downloading.
        """
        # This method is provided for explicit pre-download calls
        print("Downloading embedding model...")
        _ = TextEmbedding(model_name=config.embedding_model)
        print(f"Model {config.embedding_model} cached in {config.fastembed_cache_dir}")
