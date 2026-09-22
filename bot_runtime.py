"""Discord startup recovery and safe, observable nickname approvals."""
import asyncio
import functools
import logging
import math
import re
import time
from collections import Counter
from email.utils import parsedate_to_datetime

import aiohttp
import discord

log = logging.getLogger("bot.runtime")


def retry_delay(error, fallback=300):
    """Respect Discord's Retry-After, including HTTP dates; never retry early."""
    headers = getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("Retry-After")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError, AttributeError):
            seconds = fallback
    if not math.isfinite(seconds):
        seconds = fallback
    return max(1, seconds) + 1


def log_http_error(operation, error):
    headers = getattr(getattr(error, "response", None), "headers", {})
    log.warning(
        "[HTTP_FAILURE] operation=%s status=%s code=%s scope=%s "
        "global=%s retry_after=%s cf_ray=%s detail=%s",
        operation, error.status, error.code, headers.get("X-RateLimit-Scope"),
        headers.get("X-RateLimit-Global"), headers.get("Retry-After"),
        headers.get("CF-Ray"),
        str(error.text).replace("\n", " | ")[:600],
    )


async def start_with_retry(client, token, *, sleep=asyncio.sleep):
    """Keep client state open; recreate HTTP transport after a failed login."""
    backoff = 300
    async with client:
        while True:
            try:
                await client.login(token)
                break
            except discord.HTTPException as error:
                if error.status != 429:
                    raise
                log_http_error("login", error)
                delay = retry_delay(error, backoff)
                log.warning("[LOGIN_RETRY] waiting=%.1fs", delay)
                # static_login creates a new ClientSession on every call. Close
                # the failed one and reset its owned connector before retrying.
                # Do not close the Bot itself: connect checks its closed state.
                await client.http.close()
                client.http.connector = discord.utils.MISSING
                await sleep(delay)
                backoff = min(backoff * 2, 3600)
        await client.connect(reconnect=True)


class ApprovalGuard:
    """Serialize decisions for one application and pause approvals after a 429."""
    def __init__(self):
        self.active = set()
        self.blocked_until = 0.0

    async def notify(self, interaction, text):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException as error:
            log_http_error("approval_notification", error)

    def protect(self, callback):
        @functools.wraps(callback)
        async def wrapped(view, interaction):
            key = view.request_id
            if key in self.active:
                await self.notify(interaction, "⏳ 이미 처리 중인 신청입니다. 잠시 기다려주세요.")
                return
            remaining = self.blocked_until - time.monotonic()
            if remaining > 0:
                await self.notify(interaction, f"⏳ Discord 요청 제한으로 승인 처리를 대기 중입니다. 약 {math.ceil(remaining)}초 후 다시 시도해주세요.")
                return
            self.active.add(key)
            try:
                # Acknowledge before any slow REST call. No visible loading message.
                await interaction.response.defer()
                await callback(view, interaction)
            except discord.HTTPException as error:
                log_http_error(f"nickname_{callback.__name__}:{key}", error)
                if error.status == 429:
                    delay = retry_delay(error)
                    self.blocked_until = max(self.blocked_until, time.monotonic() + delay)
                    await self.notify(interaction, "⏳ Discord 요청 제한으로 처리가 중단됐습니다. 잠시 후 신청 상태를 확인해주세요. 반복 클릭하지 않아도 됩니다.")
                else:
                    await self.notify(interaction, "❌ Discord 요청에 실패했습니다. 신청 상태를 확인한 후 다시 시도해주세요.")
            finally:
                self.active.discard(key)
        return wrapped


def make_http_trace():
    """Aggregate real response counts; never log tokens, payloads or full URLs."""
    trace = aiohttp.TraceConfig()
    counts = Counter()
    window_start = time.monotonic()

    async def completed(session, context, params):
        nonlocal window_start
        path = params.url.path
        if "/webhooks/" in path or "/interactions/" in path:
            route = "interaction_or_webhook"
        else:
            route = re.sub(r"/\d+", "/:id", path)
        counts[(params.method, route, params.response.status)] += 1
        if params.response.status in (401, 403, 429):
            headers = params.response.headers
            log.warning(
                "[HTTP_RESPONSE] method=%s route=%s status=%s scope=%s "
                "global=%s retry_after=%s cf_ray=%s",
                params.method, route, params.response.status,
                headers.get("X-RateLimit-Scope"), headers.get("X-RateLimit-Global"),
                headers.get("Retry-After"), headers.get("CF-Ray"),
            )
        elapsed = time.monotonic() - window_start
        if elapsed >= 60:
            log.info("[HTTP_COUNTS] seconds=%.1f responses=%s", elapsed, dict(counts))
            counts.clear()
            window_start = time.monotonic()

    trace.on_request_end.append(completed)
    return trace
