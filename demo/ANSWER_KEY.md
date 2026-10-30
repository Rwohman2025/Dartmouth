# Answer Key

Each snippet in `demo/snippets/` contains exactly one subtle bug.

## 1. `average_scores.py` — missing empty-list check

- **Line:** 9 (`average = total / len(scores)`)
- **Bug:** An empty `scores` list raises `ZeroDivisionError`. `format_report` inherits the crash.
- **Question that catches it:** "What does `average_score([])` do?"
- **Good answer:** "It raises `ZeroDivisionError`, because `len(scores)` is 0. It needs a guard that returns 0.0 or `None`, or raises a clear `ValueError`. The caller has to be told which one."
- **Bad answer:** "It returns 0.0, since the total is 0." (Wrong: the division happens first and raises. This answer reasons from the loop and never reaches the divide.)

## 2. `paginate_users.py` — off-by-one in pagination

- **Line:** 9 (`start = page * page_size`)
- **Bug:** The docstring says pages are 1-indexed, but the offset should be `(page - 1) * page_size`. Page 1 skips the first `page_size` users, and the last page comes back empty.
- **Question that catches it:** "With 25 users and `page_size=10`, which users does `page=1` return?"
- **Good answer:** "Users at indices 10-19, not 0-9. The offset is `page * page_size`, which is wrong for 1-indexed pages. It should be `(page - 1) * page_size`. As a result `page=3` returns an empty list even though `total_pages` is 3."
- **Bad answer:** "The first 10 users. It slices `users[start:end]` with a page size of 10, so that's correct." (Never computes `start` for `page=1`.)

## 3. `signup_age.py` — `>` that should be `>=`

- **Line:** 17 (`return age > MINIMUM_SIGNUP_AGE`)
- **Bug:** A user who is exactly 18 is rejected. The check should be `age >= MINIMUM_SIGNUP_AGE`.
- **Question that catches it:** "Can someone who turns 18 today sign up?"
- **Good answer:** "No. `calculate_age` returns 18 for them, and `18 > 18` is False. They are blocked until they turn 19. It should be `>=`."
- **Bad answer:** "Yes. `calculate_age` handles the birthday correctly and the minimum age is 18." (Checks the age calculation but not the boundary comparison.)
