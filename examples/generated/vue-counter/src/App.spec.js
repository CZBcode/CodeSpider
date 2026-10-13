import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import App from './App.vue'

describe('App.vue', () => {
  it('renders initial count as 0', () => {
    const wrapper = mount(App)
    expect(wrapper.find('[data-testid="count"]').text()).toBe('0')
  })

  it('increments count when increment button is clicked', async () => {
    const wrapper = mount(App)
    await wrapper.find('[data-testid="increment"]').trigger('click')
    expect(wrapper.find('[data-testid="count"]').text()).toBe('1')
  })

  it('decrements count when decrement button is clicked', async () => {
    const wrapper = mount(App)
    await wrapper.find('[data-testid="increment"]').trigger('click')
    await wrapper.find('[data-testid="decrement"]').trigger('click')
    expect(wrapper.find('[data-testid="count"]').text()).toBe('0')
  })

  it('does not decrement below 0', async () => {
    const wrapper = mount(App)
    await wrapper.find('[data-testid="decrement"]').trigger('click')
    expect(wrapper.find('[data-testid="count"]').text()).toBe('0')
  })

  it('resets count to 0 when reset button is clicked', async () => {
    const wrapper = mount(App)
    await wrapper.find('[data-testid="increment"]').trigger('click')
    await wrapper.find('[data-testid="increment"]').trigger('click')
    await wrapper.find('[data-testid="reset"]').trigger('click')
    expect(wrapper.find('[data-testid="count"]').text()).toBe('0')
  })
})
