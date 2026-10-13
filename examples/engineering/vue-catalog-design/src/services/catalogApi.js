const MOCK_PRODUCTS = [
  { id: 'book', name: 'Book', priceCents: 1000 },
  { id: 'pen', name: 'Pen', priceCents: 200 }
]

/**
 * Fetch products from catalog.
 * In-memory implementation for demo purposes.
 * @returns {Promise<Array<{id: string, name: string, priceCents: number}>>}
 */
export async function fetchProducts() {
  return Promise.resolve(MOCK_PRODUCTS.map(p => ({ ...p })))
}
