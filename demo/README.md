# Planted-bug demo inputs

These snippets contain intentional bugs. They are review fixtures, not production helpers. Do not automatically repair them during unrelated work.

| File | Planted behavior | Intended question |
| --- | --- | --- |
| off-by-one.mjs | Drops the final item | Which boundary inputs expose the missing element? |
| discount.mjs | Applies a percent as an absolute multiplier | What units does the discount argument use? |

Example expected behavior: copyAll([1, 2]) should return [1, 2]; discountedTotal(100, 20) should return 80. Submit a proposed correction as a new revision, obtain questions, answer them, grade, and inspect the proposal log after those components are implemented.
