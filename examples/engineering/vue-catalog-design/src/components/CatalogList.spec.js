import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CatalogList from './CatalogList.vue'
import App from '../App.vue'

describe('CatalogList component', () => {
  it('renders loading state', () => {
    const wrapper = mount(CatalogList, {
      props: { products: [], loading: true, error: '' }
    })
    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(true)
  })

  it('renders error state with retry button', () => {
    const wrapper = mount(CatalogList, {
      props: { products: [], loading: false, error: 'fail' }
    })
    expect(wrapper.find('[data-testid="error"]').text()).toBe('fail')
    expect(wrapper.find('[data-testid="retry"]').exists()).toBe(true)
  })

  it('emits retry event when button clicked', async () => {
    const wrapper = mount(CatalogList, {
      props: { products: [], loading: false, error: 'fail' }
    })
    await wrapper.find('[data-testid="retry"]').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('renders products with correct data-testid', () => {
    const products = [
      { id: 'book', name: 'Book', priceCents: 1000 },
      { id: 'pen', name: 'Pen', priceCents: 200 }
    ]
    const wrapper = mount(CatalogList, {
      props: { products, loading: false, error: '' }
    })
    expect(wrapper.find('[data-testid="product-book"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="product-book"]').text()).toContain('Book')
    expect(wrapper.find('[data-testid="product-pen"]').exists()).toBe(true)
  })

  it('renders product id when name is not available', () => {
    const products = [
      { id: 'book', priceCents: 1000 }
    ]
    const wrapper = mount(CatalogList, {
      props: { products, loading: false, error: '' }
    })
    expect(wrapper.find('[data-testid="product-book"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="product-book"]').text()).toContain('book')
    expect(wrapper.find('[data-testid="product-book"]').text()).toContain('1000')
  })

  it('does not show error section when error is empty string', () => {
    const wrapper = mount(CatalogList, {
      props: { products: [{ id: 'book', priceCents: 1000 }], loading: false, error: '' }
    })
    expect(wrapper.find('[data-testid="error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="retry"]').exists()).toBe(false)
  })
})

describe('App integration', () => {
  it('mounts and uses useCatalog to render CatalogList', async () => {
    const wrapper = mount(App)
    // Initially loading or loaded depending on timing
    expect(wrapper.findComponent(CatalogList).exists()).toBe(true)
  })
})
