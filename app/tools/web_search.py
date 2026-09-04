import requests
from duckduckgo_search import DDGS
from app.config import settings
import argparse

class RateLimitError(Exception):
    pass

class WebSearchTool:
    def __init__(self):
        self.tavily_url = "https://api.tavily.com/search"

    def _search_tavily(self, query: str, max_results: int = 5) -> list[dict]:
        resp = requests.post(
            self.tavily_url,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={"query": query, "max_results": max_results, "include_answer": True},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("Tavily rate limit hit")
        resp.raise_for_status()
        data = resp.json()
        return [{"title": r["title"], "url": r["url"], "content": r["content"]} for r in data.get("results", [])]

    def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")} for r in results]

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            return self._search_tavily(query, max_results)
        except RateLimitError:
            print("[web_search] Tavily rate-limited, falling back to DuckDuckGo...")
            return self._search_duckduckgo(query, max_results)
        except requests.HTTPError as e:
            print(f"[web_search] Tavily failed: {e}, falling back to DuckDuckGo...")
            return self._search_duckduckgo(query, max_results)
        except Exception as e:
            print(f"[web_search] Tavily failed ({e}), falling back to DuckDuckGo...")
            return self._search_duckduckgo(query, max_results)

web_search_tool = WebSearchTool()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="python asyncio best practices")
    parser.add_argument("--max_results", type=int, default=3)
    args = parser.parse_args()
    for r in web_search_tool.search(args.query, args.max_results):
        print(f"- {r['title']} ({r['url']})")
        print(f"  {r['content'][:150]}...")

if __name__ == "__main__":
    main()