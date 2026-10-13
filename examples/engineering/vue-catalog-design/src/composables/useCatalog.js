import { ref } from 'vue'
import { fetchProducts } from '../services/catalogApi.js'

/**
 * Composable for catalog management.
 * @param {Function} [fetcher=fetchProducts] - dependency-injected fetch function
 * @returns {{ products: import('vue').Ref<Array>, loading: import('vue').Ref<boolean>, error: import('vue').Ref<string>, load: Function }}
 */
export function useCatalog(fetcher = fetchProducts) {
  const products = ref([])
  const loading = ref(false)
  const error = ref('')
  let callId = 0

  async function load() {
    callId++
    const currentCallId = callId
    loading.value = true
    error.value = ''
    try {
      const result = await fetcher()
      if (currentCallId === callId) {
        products.value = result
        loading.value = false
      }
    } catch (e) {
      if (currentCallId === callId) {
        error.value = e instanceof Error ? e.message : String(e)
        loading.value = false
      }
    }
  }

  return { products, loading, error, load }
}
