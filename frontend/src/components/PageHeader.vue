<template>
  <div class="page">
    <div class="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <h1 class="font-display text-[22px] font-bold leading-tight tracking-wide text-ink">{{ title }}</h1>
        <p v-if="subtitle" class="mt-1.5 text-[13px] text-ink-2">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' }
})
</script>
