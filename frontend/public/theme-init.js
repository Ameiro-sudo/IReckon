/* 主题引导：必须在首帧渲染前同步执行，避免暗色模式闪白/皮肤错帧。
 * 独立为外链文件以满足 CSP script-src 'self'（勿内联回 index.html）。
 * data-theme  = 明暗（dark | 默认亮）
 * data-palette = 配色皮肤（amber 琥珀工业 | 默认 frost 冰海 SnowBlock） */
(function () {
  var saved = localStorage.getItem('theme')
  var dark =
    saved === 'dark' ||
    (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.setAttribute('data-theme', 'dark')

  var palette = localStorage.getItem('palette')
  if (palette !== 'frost' && palette !== 'amber') palette = 'frost'
  document.documentElement.setAttribute('data-palette', palette)
})()
