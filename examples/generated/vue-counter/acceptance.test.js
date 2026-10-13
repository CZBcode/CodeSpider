import {describe,it,expect} from 'vitest';
import {mount} from '@vue/test-utils';
import App from './src/App.vue';
describe('independent acceptance', () => {
 it('increments, decrements, resets, and never goes negative', async () => {
  const w=mount(App); const value=()=>w.get('[data-testid="count"]').text();
  expect(value()).toBe('0');
  await w.get('[data-testid="decrement"]').trigger('click'); expect(value()).toBe('0');
  await w.get('[data-testid="increment"]').trigger('click');
  await w.get('[data-testid="increment"]').trigger('click'); expect(value()).toBe('2');
  await w.get('[data-testid="decrement"]').trigger('click'); expect(value()).toBe('1');
  await w.get('[data-testid="reset"]').trigger('click'); expect(value()).toBe('0'); w.unmount();
 });
});
