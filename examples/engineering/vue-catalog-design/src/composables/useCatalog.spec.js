import { describe, it, expect, vi } from 'vitest'
import { useCatalog } from './useCatalog.js'

describe('useCatalog', () => {
  it('returns isolated instances', () => {
    const a = useCatalog()
    const b = useCatalog()
    expect(a.products).not.toBe(b.products)
    expect(a.loading).not.toBe(b.loading)
    expect(a.error).not.toBe(b.error)
  })

  it('loads products successfully', async () => {
    const mockData = [{ id: 'book', priceCents: 1000 }]
    const fetcher = vi.fn().mockResolvedValue(mockData)
    const { products, loading, error, load } = useCatalog(fetcher)

    expect(loading.value).toBe(false)
    expect(error.value).toBe('')
    const promise = load()
    expect(loading.value).toBe(true)
    expect(error.value).toBe('')
    await promise
    expect(products.value).toEqual(mockData)
    expect(loading.value).toBe(false)
    expect(error.value).toBe('')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('captures errors as string without throwing', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('network fail'))
    const { error, loading, load } = useCatalog(fetcher)

    await load()
    expect(error.value).toBe('network fail')
    expect(loading.value).toBe(false)
  })

  it('clears error on retry', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce([{ id: 'book', priceCents: 1000 }])
    const { error, products, load } = useCatalog(fetcher)

    await load()
    expect(error.value).toBe('fail')

    await load()
    expect(error.value).toBe('')
    expect(products.value).toEqual([{ id: 'book', priceCents: 1000 }])
  })

  it('only accepts latest concurrent call result', async () => {
    let resolveFirst
    let resolveSecond
    const fetcher = vi.fn()
      .mockImplementationOnce(() => new Promise(r => { resolveFirst = r }))
      .mockImplementationOnce(() => new Promise(r => { resolveSecond = r }))

    const { products, loading, error, load } = useCatalog(fetcher)

    const p1 = load()
    const p2 = load()

    // Resolve second (latest) first
    resolveSecond([{ id: 'new', priceCents: 2000 }])
    await p2
    expect(products.value).toEqual([{ id: 'new', priceCents: 2000 }])
    expect(loading.value).toBe(false)
    expect(error.value).toBe('')

    // Resolve first (stale) - should be ignored
    resolveFirst([{ id: 'old', priceCents: 100 }])
    await p1
    expect(products.value).toEqual([{ id: 'new', priceCents: 2000 }])
  })

  it('initializes error as empty string', () => {
    const { error } = useCatalog()
    expect(error.value).toBe('')
  })
})
