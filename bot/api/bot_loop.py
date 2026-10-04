"""Run Discord operations on the loop that owns its HTTP session."""

import asyncio


async def run_on_bot_loop(bot, operation):
    loop = bot.loop
    if loop is asyncio.get_running_loop():
        return await operation()
    if loop.is_closed() or not loop.is_running():
        raise RuntimeError("Discord bot event loop is unavailable")
    future = asyncio.run_coroutine_threadsafe(operation(), loop)
    return await asyncio.wrap_future(future)
