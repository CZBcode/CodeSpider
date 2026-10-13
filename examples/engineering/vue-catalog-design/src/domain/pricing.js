/**
 * Calculate total price in cents.
 * @param {Array<{priceCents: number, quantity: number}>} rows
 * @returns {number} total in cents
 */
export function totalCents(rows) {
  if (!Array.isArray(rows)) {
    throw new Error('rows must be an array')
  }
  let total = 0
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (
      !Number.isInteger(row.priceCents) ||
      row.priceCents < 0
    ) {
      throw new Error('priceCents must be a non-negative integer')
    }
    if (
      !Number.isInteger(row.quantity) ||
      row.quantity <= 0
    ) {
      throw new Error('quantity must be a positive integer')
    }
    total += row.priceCents * row.quantity
  }
  return total
}
