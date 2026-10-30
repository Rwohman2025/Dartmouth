// INTENTIONAL DEMO BUG: discountPercent is expressed in percent units (0–100).
export function discountedTotal(total, discountPercent) {
  return total * (1 - discountPercent);
}
