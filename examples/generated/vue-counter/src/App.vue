<template>
  <div>
    <span data-testid="count">{{ count }}</span>
    <button data-testid="increment" @click="increment">Increment</button>
    <button data-testid="decrement" @click="decrement">Decrement</button>
    <button data-testid="reset" @click="reset">Reset</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const count = ref(0)

function increment() {
  count.value++
}

function decrement() {
  if (count.value > 0) {
    count.value--
  }
}

function reset() {
  count.value = 0
}
</script>
