from __future__ import annotations

import os
TRUSTED_DOMAINS = [
    "aspca.org",
    "fda.gov",
    "merckvetmanual.com",
    "petpoisonhelpline.com",
]


def web_search(item: str, species: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    from tavily import TavilyClient
    client = TavilyClient(api_key=api_key)
    query = f"{species} 宠物 {item} 是否有毒 能否食用 玩耍 危险 veterinary toxicity safety"
    response = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
        include_domains=TRUSTED_DOMAINS,
    )
    return [
        {
            "title": row.get("title", "网络资料"),
            "url": row.get("url", ""),
            "snippet": row.get("content", "")[:900],
            "source_type": "网络检索",
        }
        for row in response.get("results", [])
        if row.get("url")
    ]
