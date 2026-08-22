// IR-01「我看行」人格层：七角色识别物 + 阶段加载文案池
// 纯映射与文案，零业务逻辑；角色色点颜色复用 markdown.js 的 roleMeta

// 七个智能体角色各配一枚识别 emoji（不做插画）；衍生/系统角色同表覆盖，
// 键值与后端 sender_role / roleMeta 保持一致
export const ROLE_EMOJI = {
  scheduler: '🧭', // 调度员：定方向、排兵布阵
  creative: '💡', // 创意官：出点子
  executor: '⚡', // 执行者：手速拉满
  reviewer: '🔍', // 审查员：逐行过目
  reviewer_correctness: '🔬', // 正确性审查：动手验证
  reviewer_efficiency: '📐', // 架构审查：量结构
  deliverer: '📦', // 交付员：打包出库
  learner: '📚', // 学习者：空闲充电
  tool_manager: '🧰', // 工具管理员：家伙事儿齐全
  security_scanner: '🛡️', // 安全扫描：站岗放哨
  system: '⚙️',
  user: '🙋'
}

export function roleEmoji(role) {
  return ROLE_EMOJI[role] || ''
}

// 任务阶段 → 人格化加载文案池（同一阶段多条轮换，避免一句文案看到腻）
export const LOADING_COPY = {
  creating: ['我看行，这就安排…', '需求已收到，智能体团队集合中…'],
  pending: ['任务已进场，排队等开箱…', '前面还有几位，稍安勿躁…'],
  planning: ['调度员正在看需求…', '调度员正在拆任务、排兵布阵…'],
  executing: ['执行者正在埋头写码…', '执行者键盘冒烟中…'],
  reviewing: ['审查员正在逐行过目…', '双流水线全开，挑刺进行时…'],
  revising: ['审查意见已下达，回炉重铸中…', '按审查意见返工，这次稳了…'],
  delivering: ['交付员正在打包产物…', '清点货件，马上出库…']
}

// 取阶段文案：tick 用于同池内轮换（确定性取模，渲染路径无随机性）
export function loadingCopy(phase, tick = 0) {
  const pool = LOADING_COPY[phase]
  if (!pool || !pool.length) return ''
  return pool[Math.abs(Number(tick) || 0) % pool.length]
}