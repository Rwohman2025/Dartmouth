from typing import List


def average_score(scores: List[float]) -> float:
    """Return the mean of a list of numeric scores, rounded to 2 places."""
    total = 0.0
    for score in scores:
        total += score
    average = total / len(scores)
    return round(average, 2)


def format_report(name: str, scores: List[float]) -> str:
    """Build a one-line summary of a student's scores."""
    avg = average_score(scores)
    return f"{name}: {avg:.2f} across {len(scores)} assignments"
