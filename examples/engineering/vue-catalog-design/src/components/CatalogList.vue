<template>
  <div class="catalog-list">
    <div v-if="loading" data-testid="loading">Loading...</div>
    <div v-else-if="error" class="error">
      <span data-testid="error">{{ error }}</span>
      <button data-testid="retry" @click="$emit('retry')">Retry</button>
    </div>
    <ul v-else>
      <li
        v-for="product in products"
        :key="product.id"
        :data-testid="'product-' + product.id"
      >
        {{ product.name || product.id }} - {{ product.priceCents }}¢
      </li>
    </ul>
  </div>
</template>

<script setup>
defineProps({
  products: { type: Array, required: true },
  loading: { type: Boolean, required: true },
  error: { type: String, default: '' }
})

defineEmits(['retry'])
</script>
