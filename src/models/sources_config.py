"""Models for sources configuration (sources.yaml)"""

from pydantic import BaseModel, Field, HttpUrl


class WebsiteSource(BaseModel):
    """Configuration for a website documentation source"""

    name: str = Field(description="Human-readable name for this source")
    url: HttpUrl = Field(description="Base URL of the website to crawl")
    path_prefix: str = Field(
        default="/", description="URL path prefix to limit crawling (e.g., /docs)"
    )
    enabled: bool = Field(default=True, description="Whether this source is enabled")


class GitHubRepoSource(BaseModel):
    """Configuration for a GitHub repository documentation source"""

    name: str = Field(description="Human-readable name for this source")
    repo_owner: str = Field(description="GitHub repository owner (username or org)")
    repo_name: str = Field(description="GitHub repository name")
    branch: str | None = Field(
        default=None, description="Branch to fetch from (None = default branch)"
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Glob patterns for files to fetch (e.g., 'docs/**/*.md')",
    )
    enabled: bool = Field(default=True, description="Whether this source is enabled")


class FetchingConfig(BaseModel):
    """Configuration for fetching behavior"""

    timeout: int = Field(default=30, ge=5, le=300, description="HTTP timeout in seconds")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max retry attempts")
    concurrent_limit: int = Field(default=5, ge=1, le=20, description="Max concurrent requests")
    delay_ms: int = Field(default=100, ge=0, le=5000, description="Delay between requests (ms)")
    max_depth: int = Field(default=5, ge=1, le=10, description="Max crawl depth for websites")


class GitHubConfig(BaseModel):
    """Configuration for GitHub API access"""

    token: str | None = Field(
        default=None, description="GitHub personal access token (or use GITHUB_TOKEN env var)"
    )
    api_url: str = Field(default="https://api.github.com", description="GitHub API base URL")


class SourcesConfig(BaseModel):
    """Complete sources configuration"""

    class Sources(BaseModel):
        """Container for all source types"""

        websites: list[WebsiteSource] = Field(default_factory=list)
        github_repos: list[GitHubRepoSource] = Field(default_factory=list)

    sources: Sources = Field(default_factory=Sources)
    fetching: FetchingConfig = Field(default_factory=FetchingConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    def get_enabled_websites(self) -> list[WebsiteSource]:
        """Get all enabled website sources"""
        return [source for source in self.sources.websites if source.enabled]

    def get_enabled_github_repos(self) -> list[GitHubRepoSource]:
        """Get all enabled GitHub repository sources"""
        return [source for source in self.sources.github_repos if source.enabled]
