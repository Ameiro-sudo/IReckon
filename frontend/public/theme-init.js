/* 主题引导：必须在首帧渲染前同步执行，避免暗色模式闪白。
 * 独立为外链文件以满足 CSP script-src 'self'（勿内联回 index.html）。 */
(function () {
  var saved = localStorage.getItem('theme')
  var dark =
    saved === 'dark' ||
    (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.setAttribute('data-theme', 'dark')
})()