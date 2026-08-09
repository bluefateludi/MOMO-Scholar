"""Reviewed Chroma local contract smoke; emits no benchmark claims."""

import json
import tempfile
from pathlib import Path

import chromadb


def main() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        path = Path(directory) / "chroma"
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_or_create_collection("techscout_smoke")
        collection.upsert(
            ids=["one", "two"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            documents=["alpha", "beta"],
            metadatas=[{"group": "a"}, {"group": "b"}],
        )
        result = collection.query(
            query_embeddings=[[1.0, 0.0]],
            n_results=1,
            where={"group": "a"},
        )
        reopened = chromadb.PersistentClient(path=str(path)).get_collection(
            "techscout_smoke"
        )
        assert result["ids"] == [["one"]]
        assert reopened.count() == 2
        print(json.dumps({"checks": ["import", "persistence", "upsert", "query", "filter"]}))


if __name__ == "__main__":
    main()
