"""
GitHub repository analyzer for extracting project information.
Used by Remotion video generation to create branded launch videos.
"""

import base64
import json
import re
from typing import Optional, Tuple, Dict, List

import requests
from classes.logger import log

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 15  # seconds


def fetch_github_repo_data(repo_url: str) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Fetch comprehensive data about a GitHub repository for video generation.

    Args:
        repo_url: GitHub repository URL (e.g., "https://github.com/facebook/react")

    Returns:
        Tuple of (repo_data_dict, error_message)
        - repo_data_dict: Dictionary with name, description, stars, features, logo, etc.
        - error_message: Error string if fetch failed, None otherwise

    Example return:
        {
            "name": "React",
            "description": "A JavaScript library for building user interfaces",
            "stars": 220000,
            "language": "JavaScript",
            "website": "https://react.dev",
            "topics": ["javascript", "react", "ui"],
            "logo_url": "https://avatars.githubusercontent.com/u/...",
            "features": ["Component-Based", "Declarative", "Learn Once"],
            "github_url": "https://github.com/facebook/react"
        }
    """
    try:
        # Extract owner and repo name from URL
        owner, repo = _parse_github_url(repo_url)
        if not owner or not repo:
            return None, f"Invalid GitHub URL format: {repo_url}"

        log.info("Fetching GitHub repo data: %s/%s", owner, repo)

        # Fetch repository metadata
        repo_data, err = _fetch_repo_metadata(owner, repo)
        if err:
            return None, err

        # Fetch README for features
        readme_text, _ = _fetch_readme(owner, repo)

        # Fetch package.json if available
        package_data, _ = _fetch_package_json(owner, repo)

        # Extract features from README
        features = _extract_features_from_readme(readme_text) if readme_text else []

        # Get logo URL
        logo_url = _get_repo_logo(repo_data, readme_text)

        # Build result with smart defaults
        repo_name = repo_data.get("name", repo)
        description = repo_data.get("description") or f"An innovative {repo_data.get('language', '')} project"

        result = {
            "name": repo_name,
            "description": description,
            "stars": repo_data.get("stargazers_count", 0),
            "language": repo_data.get("language") or "Unknown",
            "website": repo_data.get("homepage") or f"https://github.com/{owner}/{repo}",
            "topics": repo_data.get("topics", [])[:5],  # Limit to 5 topics
            "logo_url": logo_url,
            "features": features[:5] if features else [],  # Limit to 5 features
            "github_url": f"https://github.com/{owner}/{repo}",
        }

        # Enhance name from package.json if available
        if package_data and package_data.get("name"):
            pkg_name = package_data["name"]
            # Convert package names like "@facebook/react" to "React"
            if "/" in pkg_name:
                pkg_name = pkg_name.split("/")[-1]
            result["name"] = pkg_name.replace("-", " ").title()

        # If no features found, generate from description and topics
        if not result["features"]:
            generated_features = []

            # Use topics as features
            if result["topics"]:
                generated_features.extend([t.replace("-", " ").title() for t in result["topics"][:3]])

            # Add language-based feature
            if result["language"] and result["language"] != "Unknown":
                generated_features.append(f"Built with {result['language']}")

            # Add star-based feature if popular
            if result["stars"] > 1000:
                generated_features.append(f"{result['stars']:,}+ GitHub Stars")

            result["features"] = generated_features[:5]

        # Fallback: ensure at least 1 feature
        if not result["features"]:
            result["features"] = ["Open Source", "Community Driven", "Well Documented"]

        log.info("Successfully fetched repo data: %s (%d stars)", result["name"], result["stars"])
        return result, None

    except Exception as e:
        log.error("GitHub repo fetch failed: %s", e, exc_info=True)
        return None, f"Failed to fetch GitHub data: {str(e)}"


def _parse_github_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract owner and repo name from GitHub URL."""
    # Match patterns like:
    # - https://github.com/owner/repo
    # - http://github.com/owner/repo
    # - github.com/owner/repo
    pattern = r'(?:https?://)?github\.com/([^/]+)/([^/\s]+)'
    match = re.search(pattern, url.strip())
    if match:
        owner, repo = match.groups()
        # Remove .git suffix if present
        repo = repo.replace('.git', '')
        return owner, repo
    return None, None


def _fetch_repo_metadata(owner: str, repo: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch repository metadata from GitHub API."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if r.status_code == 404:
            return None, f"Repository not found: {owner}/{repo}"
        elif r.status_code == 403:
            return None, "GitHub API rate limit exceeded. Try again later."

        r.raise_for_status()
        return r.json(), None

    except requests.RequestException as e:
        return None, f"GitHub API error: {str(e)}"


def _fetch_readme(owner: str, repo: str) -> Tuple[Optional[str], Optional[str]]:
    """Fetch and decode README content."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
    headers = {"Accept": "application/vnd.github.v3+json"}

    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if r.status_code == 404:
            log.warning("No README found for %s/%s", owner, repo)
            return None, "README not found"

        r.raise_for_status()
        data = r.json()

        # Decode base64 content
        content_b64 = data.get("content", "")
        if content_b64:
            content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return content, None

        return None, "Empty README"

    except Exception as e:
        log.warning("Failed to fetch README: %s", e)
        return None, str(e)


def _fetch_package_json(owner: str, repo: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch package.json if it exists (for JS/TS projects)."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/package.json"
    headers = {"Accept": "application/vnd.github.v3+json"}

    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if r.status_code == 404:
            return None, "No package.json"

        r.raise_for_status()
        data = r.json()

        # Decode base64 content
        content_b64 = data.get("content", "")
        if content_b64:
            content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return json.loads(content), None

        return None, "Empty package.json"

    except Exception as e:
        return None, str(e)


def _extract_features_from_readme(readme_text: str) -> List[str]:
    """
    Extract key features from README content.
    Looks for common patterns like bullet lists, feature sections, etc.
    """
    features = []

    # Look for feature sections (multiple patterns for flexibility)
    feature_patterns = [
        r'##\s+Features?\s*\n(.*?)(?=\n##|\Z)',  # ## Features
        r'###\s+Features?\s*\n(.*?)(?=\n###|\Z)',  # ### Features
        r'##\s+Key Features?\s*\n(.*?)(?=\n##|\Z)',  # ## Key Features
        r'##\s+Highlights?\s*\n(.*?)(?=\n##|\Z)',  # ## Highlights
        r'##\s+Why.*?\s*\n(.*?)(?=\n##|\Z)',  # ## Why [Project]
        r'##\s+What.*?\s*\n(.*?)(?=\n##|\Z)',  # ## What is [Project]
        r'##\s+Capabilities?\s*\n(.*?)(?=\n##|\Z)',  # ## Capabilities
        r'##\s+Benefits?\s*\n(.*?)(?=\n##|\Z)',  # ## Benefits
    ]

    for pattern in feature_patterns:
        match = re.search(pattern, readme_text, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)
            # Extract bullet points (both - and *)
            bullets = re.findall(r'^\s*[-*+]\s+(.+)$', section, re.MULTILINE)
            features.extend([b.strip() for b in bullets if b.strip()])
            if features:
                break  # Found features, no need to continue

    # If no explicit feature section, try to extract from description/intro
    if not features:
        # Look for bullets in first 2000 chars
        intro = readme_text[:2000]
        bullets = re.findall(r'^\s*[-*+]\s+(.+)$', intro, re.MULTILINE)

        # Filter out non-feature bullets (like TOC, badges, etc.)
        for b in bullets:
            b = b.strip()
            # Skip if it looks like a link/TOC entry
            if b.lower().startswith(('installation', 'getting started', 'documentation',
                                     'license', 'contributing', 'table of contents')):
                continue
            features.append(b)

    # Also try to extract from description paragraphs if still empty
    if not features:
        # Look for sentences that sound like features
        sentences = re.split(r'[.!]\s+', readme_text[:1500])
        for sent in sentences:
            # Match sentences with feature-like keywords
            if any(keyword in sent.lower() for keyword in
                   ['build', 'create', 'support', 'provide', 'enable', 'allow', 'help',
                    'fast', 'easy', 'simple', 'powerful', 'flexible']):
                if 10 < len(sent) < 150:  # Reasonable length
                    features.append(sent.strip())

    # Clean up features
    cleaned = []
    for f in features:
        # Remove markdown links, bold, italics
        f = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', f)  # [text](url) -> text
        f = re.sub(r'\*\*([^\*]+)\*\*', r'\1', f)  # **bold** -> bold
        f = re.sub(r'__([^_]+)__', r'\1', f)  # __bold__ -> bold
        f = re.sub(r'\*([^\*]+)\*', r'\1', f)  # *italic* -> italic
        f = re.sub(r'_([^_]+)_', r'\1', f)  # _italic_ -> italic
        f = re.sub(r'`([^`]+)`', r'\1', f)  # `code` -> code
        f = re.sub(r'~~([^~]+)~~', r'\1', f)  # ~~strike~~ -> strike

        # Remove emoji codes (like :rocket:)
        f = re.sub(r':[a-z_]+:', '', f)

        # Remove actual emoji (unicode)
        f = re.sub(r'[^\w\s\-,.!?()]', '', f)

        # Remove trailing punctuation
        f = f.rstrip('.,;:')

        # Truncate long features
        if len(f) > 100:
            # Try to truncate at a word boundary
            f = f[:97].rsplit(' ', 1)[0] + "..."

        # Only keep meaningful features (not too short, not empty)
        if f and 10 < len(f) < 150:
            cleaned.append(f.strip())

    return cleaned[:5]  # Return top 5


def _get_repo_logo(repo_metadata: Dict, readme_text: Optional[str] = None) -> str:
    """
    Extract logo URL from repository metadata or README.
    Returns organization/owner avatar as fallback.
    """
    # Try organization logo first
    if repo_metadata.get("organization"):
        org_avatar = repo_metadata["organization"].get("avatar_url")
        if org_avatar:
            return org_avatar

    # Try owner avatar
    if repo_metadata.get("owner"):
        owner_avatar = repo_metadata["owner"].get("avatar_url")
        if owner_avatar:
            return owner_avatar

    # Try to find logo in README
    if readme_text:
        # Look for common logo patterns (first image in README)
        img_patterns = [
            r'!\[.*?\]\((https?://[^\)]+\.(?:png|jpg|jpeg|svg))\)',  # Markdown image
            r'<img[^>]+src=["\']([^"\']+)["\']',  # HTML img tag
        ]
        for pattern in img_patterns:
            match = re.search(pattern, readme_text, re.IGNORECASE)
            if match:
                return match.group(1)

    # Default fallback - GitHub icon
    return "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
