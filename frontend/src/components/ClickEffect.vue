<template>
  <canvas ref="canvas" class="click-canvas" @click="handleClick"></canvas>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const canvas = ref(null)
let ctx = null
let ripples = []
let animId = null

function handleClick(e) {
  const rect = canvas.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  ripples.push({ x, y, radius: 0, maxRadius: 60, opacity: 0.6 })
}

function draw() {
  ctx.clearRect(0, 0, canvas.value.width, canvas.value.height)
  ripples = ripples.filter(r => r.opacity > 0)
  for (const r of ripples) {
    r.radius += 2.5
    r.opacity -= 0.015
    ctx.beginPath()
    ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(60, 150, 202, ${r.opacity * 0.5})`
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(r.x, r.y, r.radius * 0.3, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(60, 150, 202, ${r.opacity * 0.15})`
    ctx.fill()
  }
  animId = requestAnimationFrame(draw)
}

function resize() {
  canvas.value.width = window.innerWidth
  canvas.value.height = window.innerHeight
}

onMounted(() => {
  ctx = canvas.value.getContext('2d')
  resize()
  window.addEventListener('resize', resize)
  draw()
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  if (animId) cancelAnimationFrame(animId)
})
</script>

<style scoped>
.click-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 9998;
  pointer-events: none;
}
</style>
