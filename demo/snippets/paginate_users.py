from typing import Dict, List


def paginate_users(users: List[Dict], page: int, page_size: int = 10) -> Dict:
    """Return one page of users (pages are 1-indexed) plus paging metadata."""
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be positive")

    start = page * page_size
    end = start + page_size
    items = users[start:end]
    total_pages = (len(users) + page_size - 1) // page_size

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
    }
