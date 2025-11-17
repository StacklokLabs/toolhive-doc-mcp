"""GitHub repository fetcher service for documentation files"""

import asyncio
import fnmatch
import logging
import os
from base64 import b64decode

import httpx

from src.config import config
from src.models.sources_config import GitHubConfig, GitHubRepoSource

logger = logging.getLogger(__name__)


class GitHubFetchError(Exception):
    """Raised when GitHub API fetch fails"""

    pass


class GitHubFetchResult:
    """Result of fetching a file from GitHub"""

    def __init__(
        self,
        path: str,
        content: str | None = None,
        url: str | None = None,
        success: bool = False,
        error_message: str | None = None,
    ):
        self.path = path
        self.content = content
        self.url = url
        self.success = success
        self.error_message = error_message


class GitHubFetcher:
    """Fetch markdown files from GitHub repositories"""

    def __init__(self, github_config: GitHubConfig | None = None):
        """
        Initialize GitHub fetcher

        Args:
            github_config: GitHub API configuration
        """
        self.github_config = github_config or GitHubConfig()
        self.token = self.github_config.token or os.getenv("GITHUB_TOKEN")
        self.api_url = self.github_config.api_url

        # Setup HTTP client with auth if token is available
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            # Use 'token' prefix for classic GitHub tokens (ghp_*)
            # Use 'Bearer' prefix for fine-grained tokens (github_pat_*)
            prefix = "Bearer" if self.token.startswith("github_pat_") else "token"
            headers["Authorization"] = f"{prefix} {self.token}"

        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

    async def fetch_repo_files(
        self, repo_source: GitHubRepoSource
    ) -> tuple[list[GitHubFetchResult], str]:
        """
        Fetch markdown files from a GitHub repository

        Args:
            repo_source: GitHub repository source configuration

        Returns:
            Tuple of (fetch_results, cache_base_path)
            - fetch_results: List of GitHubFetchResult objects
            - cache_base_path: Base path for caching files

        Raises:
            GitHubFetchError: If fetch fails
        """
        logger.info(f"Fetching files from {repo_source.repo_owner}/{repo_source.repo_name}")

        try:
            # Get the default branch if not specified
            branch = repo_source.branch
            if not branch:
                branch = await self._get_default_branch(
                    repo_source.repo_owner, repo_source.repo_name
                )
                logger.info(f"Using default branch: {branch}")

            # Get the repository tree
            tree = await self._get_repo_tree(repo_source.repo_owner, repo_source.repo_name, branch)

            # Filter files matching the glob patterns
            matching_files = self._filter_files_by_patterns(tree, repo_source.paths)
            logger.info(f"Found {len(matching_files)} matching files")

            # Fetch all matching files
            results = await self._fetch_files_content(
                repo_source.repo_owner,
                repo_source.repo_name,
                matching_files,
                branch,
            )

            # Create cache base path
            cache_base_path = (
                f"{config.docs_website_cache_path}/github/"
                f"{repo_source.repo_owner}/{repo_source.repo_name}"
            )

            return results, cache_base_path

        except Exception as e:
            logger.error(f"Failed to fetch from GitHub repo: {e}")
            raise GitHubFetchError(f"Failed to fetch from GitHub: {e}") from e

    async def _get_default_branch(self, owner: str, repo: str) -> str:
        """Get the default branch of a repository"""
        url = f"{self.api_url}/repos/{owner}/{repo}"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data["default_branch"]
        except Exception as e:
            logger.error(f"Failed to get default branch for {owner}/{repo}: {e}")
            return "main"  # Fallback to main

    async def _get_repo_tree(self, owner: str, repo: str, branch: str) -> list[dict]:
        """
        Get the complete file tree of a repository

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name

        Returns:
            List of file/directory entries
        """
        url = f"{self.api_url}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("tree", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get repo tree: {e}")
            raise GitHubFetchError(f"Failed to get repo tree: {e}") from e

    def _filter_files_by_patterns(self, tree: list[dict], patterns: list[str]) -> list[dict]:
        """
        Filter tree entries by glob patterns

        Args:
            tree: Repository tree entries
            patterns: Glob patterns to match

        Returns:
            Filtered list of file entries
        """
        matching_files = []

        for entry in tree:
            # Only consider blob (file) entries
            if entry["type"] != "blob":
                continue

            path = entry["path"]

            # Check if path matches any pattern
            for pattern in patterns:
                if fnmatch.fnmatch(path, pattern):
                    matching_files.append(entry)
                    break

        return matching_files

    async def _fetch_files_content(
        self,
        owner: str,
        repo: str,
        files: list[dict],
        branch: str,
    ) -> list[GitHubFetchResult]:
        """
        Fetch content for all files

        Args:
            owner: Repository owner
            repo: Repository name
            files: List of file entries from tree
            branch: Branch name

        Returns:
            List of GitHubFetchResult objects
        """
        # Create tasks for concurrent fetching
        tasks = [self._fetch_file_content(owner, repo, file_entry, branch) for file_entry in files]

        # Execute all tasks with concurrency limit
        semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests

        async def fetch_with_limit(task):
            async with semaphore:
                return await task

        results = await asyncio.gather(*[fetch_with_limit(task) for task in tasks])
        return results

    async def _fetch_file_content(
        self, owner: str, repo: str, file_entry: dict, branch: str
    ) -> GitHubFetchResult:
        """
        Fetch content for a single file

        Args:
            owner: Repository owner
            repo: Repository name
            file_entry: File entry from tree
            branch: Branch name

        Returns:
            GitHubFetchResult object
        """
        path = file_entry["path"]
        url = f"{self.api_url}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        html_url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()

            # Decode base64 content
            content_b64 = data.get("content", "")
            content = b64decode(content_b64).decode("utf-8")

            logger.debug(f"✓ Fetched {path}")
            return GitHubFetchResult(path=path, content=content, url=html_url, success=True)

        except Exception as e:
            logger.warning(f"✗ Failed to fetch {path}: {e}")
            return GitHubFetchResult(path=path, success=False, error_message=str(e))

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
