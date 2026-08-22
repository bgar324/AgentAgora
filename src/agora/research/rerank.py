import logging
import os

import httpx

LOG = logging.getLogger("agora.rerank")

RERANK_URL = "https://openrouter.ai/api/v1/rerank"
RERANK_MODEL = "voyageai/rerank-2.5"


async def rerank(
    query: str,
    texts: list[str],
    *,
    top_k: int,
    instruction: str | None = None,
) -> list[int]:
    if not texts:
        return []

    limit = min(top_k, len(texts))
    key = os.environ.get("OPENROUTER_API_KEY", "")

    if key:
        try:
            full_query = f"{instruction} {query}" if instruction else query

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    RERANK_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": RERANK_MODEL,
                        "query": full_query,
                        "documents": texts,
                        "top_n": limit,
                    },
                )
                response.raise_for_status()

            results = response.json()["results"]
            ranked = [
                r["index"]
                for r in results
                if isinstance(r.get("index"), int)
            ]

            if ranked:
                return ranked[:limit]
        except Exception as error:
            LOG.warning("rerank degraded to input order: %s", error)
    else:
        LOG.warning("rerank degraded to input order: OPENROUTER_API_KEY unset")

    return list(range(limit))
