<template>
  <div id="app">
    <h1>Catalog</h1>
    <CatalogList
      :products="products"
      :loading="loading"
      :error="error"
      @retry="load"
    />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import CatalogList from './components/CatalogList.vue'
import { useCatalog } from './composables/useCatalog.js'

const { products, loading, error, load } = useCatalog()

onMounted(() => {
  load()
})
</script>
