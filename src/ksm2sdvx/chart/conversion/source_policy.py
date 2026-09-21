"""Source presentation data deliberately excluded from the target package."""

IGNORED_RESOURCE_ROLES = frozenset({"background", "title_img", "artist_img", "icon"})


def ignored_source_path(path: str) -> bool:
    """Ignore annotations and source presentation, including their extensions."""
    return any(
        path == root or path.startswith(root + "/")
        for root in ("/bg", "/editor", "/compat", "/meta/information")
    )
