from datetime import date
from typing import Optional

MINIMUM_SIGNUP_AGE = 18


def calculate_age(birth_date: date, today: Optional[date] = None) -> int:
    """Return age in whole years as of today."""
    today = today or date.today()
    had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (0 if had_birthday else 1)


def can_sign_up(birth_date: date, today: Optional[date] = None) -> bool:
    """Return True if the user meets the minimum age to create an account."""
    age = calculate_age(birth_date, today)
    return age > MINIMUM_SIGNUP_AGE
