"""Reviewed Qdrant Local contract smoke; emits no benchmark claims."""

import json
import tempfile

from qdrant_client import QdrantClient, models


def main() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        client = QdrantClient(path=directory)
        client.create_collection(
            collection_name="techscout_smoke",
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        client.upsert(
            collection_name="techscout_smoke",
            points=[
                models.PointStruct(id=1, vector=[1.0, 0.0], payload={"group": "a"}),
                models.PointStruct(id=2, vector=[0.0, 1.0], payload={"group": "b"}),
            ],
            wait=True,
        )
        matches = client.query_points(
            collection_name="techscout_smoke",
            query=[1.0, 0.0],
            query_filter=models.Filter(
                must=[models.FieldCondition(key="group", match=models.MatchValue(value="a"))]
            ),
            limit=1,
        ).points
        assert [point.id for point in matches] == [1]
        client.close()

        reopened = QdrantClient(path=directory)
        assert reopened.count("techscout_smoke", exact=True).count == 2
        reopened.close()
        print(
            json.dumps(
                {
                    "checks": [
                        "import",
                        "create",
                        "persistence",
                        "upsert",
                        "query",
                        "filter",
                    ]
                }
            )
        )


if __name__ == "__main__":
    main()
