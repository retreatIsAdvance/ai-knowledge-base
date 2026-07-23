import logging
import os
import time
from typing import Optional, TypedDict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0


class RepoInfo(TypedDict):
    full_name: str
    description: Optional[str]
    stars: int
    forks: int
    language: Optional[str]
    topics: list[str]
    html_url: str


def _build_session() -> requests.Session:
    session = requests.Session()

    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_TOKEN")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})

    session.headers.update({"Accept": "application/vnd.github+json"})
    return session


def get_repo_info(full_name: str) -> Optional[RepoInfo]:
    """获取指定 GitHub 仓库的基本信息。

    Args:
        full_name: 仓库全名，格式为 "owner/repo"（如 "langchain-ai/langchain"）。

    Returns:
        RepoInfo 字典，包含仓库名称、描述、star 数、fork 数、语言、标签、链接。
        请求失败返回 None。

    Raises:
        ValueError: full_name 格式不合法时抛出。
    """
    if "/" not in full_name or full_name.count("/") != 1:
        raise ValueError(f"full_name 格式应为 'owner/repo'，实际值：{full_name}")

    url = f"{GITHUB_API_BASE}/repos/{full_name}"
    session = _build_session()

    try:
        logger.info("请求 GitHub API: %s", url)
        resp = session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("请求超时: %s（超时时间 %ds）", url, DEFAULT_TIMEOUT)
        return None
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.error("HTTP 错误 %s: %s", status, url)
        return None
    except requests.exceptions.ConnectionError:
        logger.error("网络不可达: %s", url)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("请求异常: %s", e)
        return None

    repo: RepoInfo = {
        "full_name": data.get("full_name", full_name),
        "description": data.get("description"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "language": data.get("language"),
        "topics": data.get("topics", []),
        "html_url": data.get("html_url", f"https://github.com/{full_name}"),
    }

    logger.info(
        "获取仓库信息成功: %s | stars=%d forks=%d language=%s",
        repo["full_name"],
        repo["stars"],
        repo["forks"],
        repo["language"],
    )
    return repo
