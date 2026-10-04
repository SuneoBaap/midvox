import asyncio
import threading
import unittest
from types import SimpleNamespace

from api.bot_loop import run_on_bot_loop


class BotLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def serve():
            asyncio.set_event_loop(self.loop)
            self.loop.call_soon(ready.set)
            self.loop.run_forever()

        self.thread = threading.Thread(target=serve)
        self.thread.start()
        ready.wait(5)
        self.bot = SimpleNamespace(loop=self.loop)

    async def asyncTearDown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()

    async def test_discord_operation_runs_on_owning_loop(self):
        async def operation():
            self.assertIs(asyncio.get_running_loop(), self.loop)
            return "created"
        self.assertEqual(await run_on_bot_loop(self.bot, operation), "created")

    async def test_discord_error_reaches_api_caller(self):
        async def operation():
            raise ValueError("Role cannot be placed above the bot")
        with self.assertRaisesRegex(ValueError, "above the bot"):
            await run_on_bot_loop(self.bot, operation)

    async def test_same_loop_operation(self):
        async def operation():
            return asyncio.get_running_loop()
        current = asyncio.get_running_loop()
        self.assertIs(await run_on_bot_loop(SimpleNamespace(loop=current), operation), current)

    async def test_stopped_loop_does_not_start_operation(self):
        stopped = asyncio.new_event_loop()
        async def operation():
            self.fail("An unavailable bot must not run a mutation")
        try:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                await run_on_bot_loop(SimpleNamespace(loop=stopped), operation)
        finally:
            stopped.close()


if __name__ == "__main__":
    unittest.main()
