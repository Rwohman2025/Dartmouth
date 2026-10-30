// INTENTIONAL DEMO BUG: the final item is omitted.
export function copyAll(items) {
  const result = [];
  for (let index = 0; index < items.length - 1; index += 1) result.push(items[index]);
  return result;
}
