"""计费通道分层路由 + 一次性问答门面（调用次数套利的核心）。

架构约定：
- 主通道（默认，无 channel 标签或显式 channel:primary）：按次计费的 plan，
  只允许"判断点"使用——规划、审查判定、终审交付；
- 执行通道（实例打 channel:execution 标签）：按 token 计费或自托管端点，
  承接高频中间过程——写码、修补、摘要、抽取等，烧多少次都不心疼。

这样单任务的按次调用从 N 次（agent 循环）压缩到 2~4 次，
中间过程全部折叠进执行通道的 1 次粗粒度委托。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.config import get
from app.llm.cache import ResponseCache, response_cache
from app.llm.pool import AICapability, capability_pool

CHANNEL_PRIMARY_TAG = "channel:primary"
CHANNEL_EXECUTION_TAG = "channel:execution"

# tier → 通道映射：light/execution 走执行通道，heavy/judgment 走主通道
TIER_CHANNELS = {
    "light": "execution",
    "execution": "execution",
    "heavy": "primary",
    "judgment": "primary",
}

# 角色 → tier：高频执行角色走轻通道，判断点走重通道（调用次数套利的角色分工）
ROLE_TIERS = {
    "executor": "light",
    "deliverer": "light",
    "learner": "light",
    "tool_manager": "light",
    "content_filter": "light",
    "scheduler": "heavy",
    "creative": "heavy",
    "reviewer_correctness": "heavy",
    "reviewer_efficiency": "heavy",
}


def channel_of(cap: AICapability) -> str:
    """实例所属计费通道：打了执行标签的算执行通道，其余视为主通道。"""
    return "execution" if CHANNEL_EXECUTION_TAG in (cap.tags or []) else "primary"


async def acquire(
    tier: str = "light",
    required_tags: Optional[List[str]] = None,
    exclude_ids: Optional[set] = None,
) -> Optional[AICapability]:
    """按 tier 选实例。

    - light/execution：优先执行通道里最便宜的；无可用实例且配置允许时
      回退主通道（会消耗按次调用，打警告日志）；
    - heavy/judgment：只在主通道里选（排除执行通道实例，避免判断点被
      轻模型糊弄）。

    未知 tier 直接抛错而非静默落到主通道——主通道按次计费，拼写错误
    不该烧掉真实配额。
    """
    channel = TIER_CHANNELS.get(str(tier).lower())
    if channel is None:
        raise ValueError(
            f"未知 tier: {tier!r}（可选: {', '.join(sorted(TIER_CHANNELS))}）"
        )
    if channel == "execution":
        cap = await capability_pool.find_best_match(
            required_tags=(required_tags or []) + [CHANNEL_EXECUTION_TAG],
            exclude_ids=exclude_ids,
            prefer_cheapest=True,
        )
        if cap is None and get("ai_pool.routing.execution_fallback_to_primary", True):
            logger.warning("执行通道无可用实例，回退主通道（将消耗按次计费调用）")
            cap = await capability_pool.find_best_match(
                required_tags=required_tags,
                exclude_ids=exclude_ids,
                prefer_cheapest=True,
            )
        return cap  # type: ignore[no-any-return]  # 池 API 动态类型
    return await capability_pool.find_best_match(  # type: ignore[no-any-return]  # 池 API 动态类型
        required_tags=required_tags,
        exclude_tags=[CHANNEL_EXECUTION_TAG],
        exclude_ids=exclude_ids,
    )


async def ask(
    prompt: str,
    system_prompt: Optional[str] = None,
    tier: str = "light",
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    use_cache: bool = True,
    required_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """一次性问答：选通道实例 → 查缓存 → 调用 → 返回结构化结果。

    返回 dict：content/model/instance_id/instance_name/channel/cached/usage。
    抛出 LLMCallError 时向上透传（MCP 层转错误响应）。
    """
    from app.llm.client import llm_client  # 延迟导入避免循环依赖

    cap = await acquire(tier=tier, required_tags=required_tags)
    if cap is None:
        raise RuntimeError(f"tier={tier} 无可用 AI 实例（请检查 ai_pool 配置）")

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    cache: ResponseCache = response_cache
    cacheable = use_cache and cache.enabled and temperature in (None, 0, 0.0)
    key = None
    if cacheable:
        # scope 带实例 id：不同 tier 路由到不同实例时互不串缓存
        key = cache.make_key(cap.model, messages, temperature, max_tokens, scope=cap.id)
        hit = await cache.get(key)
        if hit is not None:
            logger.debug(f"响应缓存命中: {cap.model} tier={tier}")
            return {**hit, "cached": True}

    resp = await llm_client.call(
        cap,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    result = {
        "content": resp.content,
        "model": resp.model,
        "instance_id": cap.id,
        "instance_name": cap.name,
        "channel": channel_of(cap),
        "cached": False,
        "usage": resp.usage or {},
    }
    if cacheable and key:
        await cache.set(
            key,
            {
                k: result[k]
                for k in (
                    "content",
                    "model",
                    "instance_id",
                    "instance_name",
                    "channel",
                    "usage",
                )
            },
        )
    return result
