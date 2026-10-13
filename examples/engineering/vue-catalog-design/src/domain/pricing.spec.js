import { describe, it, expect } from 'vitest'
import { totalCents } from './pricing.js'

describe('totalCents', () => {
  it('returns 0 for empty array', () => {
    expect(totalCents([])).toBe(0)
  })

  it('calculates single row correctly', () => {
    expect(totalCents([{ priceCents: 1000, quantity: 2 }])).toBe(2000)
  })

  it('calculates multiple rows correctly', () => {
    const rows = [
      { priceCents: 1000, quantity: 1 },
      { priceCents: 500, quantity: 3 }
    ]
    expect(totalCents(rows)).toBe(2500)
  })

  it('does not mutate input', () => {
    const rows = [{ priceCents: 100, quantity: 1 }]
    const copy = JSON.parse(JSON.stringify(rows))
    totalCents(rows)
    expect(rows).toEqual(copy)
  })

  it('throws on negative priceCents', () => {
    expect(() => totalCents([{ priceCents: -1, quantity: 1 }])).toThrow(Error)
  })

  it('throws on zero quantity', () => {
    expect(() => totalCents([{ priceCents: 100, quantity: 0 }])).toThrow(Error)
  })

  it('throws on float priceCents', () => {
    expect(() => totalCents([{ priceCents: 1.5, quantity: 1 }])).toThrow(Error)
  })

  it('throws on non-array input', () => {
    expect(() => totalCents(null)).toThrow(Error)
  })
})
