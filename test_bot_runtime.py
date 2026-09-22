import ast
import asyncio
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands
from yarl import URL

from bot_runtime import ApprovalGuard, log_http_error, make_http_trace, retry_delay, start_with_retry


def http_error(status=429, headers=None):
    return discord.HTTPException(
        SimpleNamespace(status=status, reason="test", headers=headers or {}),
        "temporary block",
    )


def interaction():
    return SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
        followup=SimpleNamespace(send=AsyncMock()),
        channel=SimpleNamespace(send=AsyncMock()),
        message=SimpleNamespace(edit=AsyncMock()),
    )


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_client_transport_recreated_after_429(self):
        client = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        sessions = []

        async def request(route, **kwargs):
            # Real static_login creates the actual session and connector.
            session = client.http._HTTPClient__session
            self.assertFalse(session.closed)
            self.assertFalse(session.connector.closed)
            sessions.append(session)
            if len(sessions) < 3:
                raise http_error()
            return {"id": "123", "username": "test", "discriminator": "0", "avatar": None}

        async def connect(**kwargs):
            self.assertFalse(client.is_closed())
            self.assertFalse(sessions[-1].closed)

        client.http.request = request
        client.application_info = AsyncMock(return_value=SimpleNamespace(
            id=123, interactions_endpoint_url=None, flags=discord.ApplicationFlags()
        ))
        client.connect = AsyncMock(side_effect=connect)
        sleeper = AsyncMock()
        await start_with_retry(client, "fake-token", sleep=sleeper)
        self.assertEqual([c.args[0] for c in sleeper.await_args_list], [301, 601])
        self.assertTrue(all(s.closed for s in sessions))
        client.connect.assert_awaited_once_with(reconnect=True)
        self.assertTrue(client.is_closed())

    async def test_non_429_not_retried(self):
        client = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        client.login = AsyncMock(side_effect=http_error(401))
        sleeper = AsyncMock()
        with self.assertRaises(discord.HTTPException):
            await start_with_retry(client, "fake-token", sleep=sleeper)
        sleeper.assert_not_awaited()
        self.assertTrue(client.is_closed())

    async def test_duplicate_decisions_do_not_run_together(self):
        guard = ApprovalGuard()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        @guard.protect
        async def decide(view, event):
            calls.append(view.request_id)
            started.set()
            await release.wait()

        first, second = interaction(), interaction()
        task = asyncio.create_task(decide(SimpleNamespace(request_id="same"), first))
        await started.wait()
        await decide(SimpleNamespace(request_id="same"), second)
        self.assertEqual(calls, ["same"])
        second.followup.send.assert_awaited_once()
        release.set()
        await task
        self.assertFalse(guard.active)

    async def test_429_pauses_other_approvals_and_preserves_retry(self):
        guard = ApprovalGuard()
        callback = AsyncMock(side_effect=http_error(headers={"Retry-After": "20"}))
        callback.__name__ = "approve"
        protected = guard.protect(callback)
        await protected(SimpleNamespace(request_id="first"), interaction())
        await protected(SimpleNamespace(request_id="second"), interaction())
        self.assertEqual(callback.await_count, 1)
        self.assertFalse(guard.active)
        guard.blocked_until = 0
        callback.side_effect = None
        await protected(SimpleNamespace(request_id="first"), interaction())
        self.assertEqual(callback.await_count, 2)

    async def test_cancellation_releases_processing_guard(self):
        guard = ApprovalGuard()
        callback = AsyncMock(side_effect=asyncio.CancelledError())
        callback.__name__ = "approve"
        with self.assertRaises(asyncio.CancelledError):
            await guard.protect(callback)(SimpleNamespace(request_id="a"), interaction())
        self.assertFalse(guard.active)

    async def test_trace_redacts_webhook_token(self):
        trace = make_http_trace()
        params = SimpleNamespace(method="POST", url=URL("https://discord.com/api/v10/webhooks/123/SECRET"),
                                 response=SimpleNamespace(status=429, headers={}))
        with self.assertLogs("bot.runtime", "WARNING") as logs:
            await trace.on_request_end[0](None, None, params)
        self.assertNotIn("SECRET", str(logs.output))
        self.assertIn("status=429", str(logs.output))

    def test_retry_after_and_invalid_values(self):
        self.assertEqual(retry_delay(http_error(headers={"Retry-After": "900"})), 901)
        for value in ("bad", "nan", "inf", None):
            self.assertEqual(retry_delay(http_error(headers={"Retry-After": value})), 301)


class ApprovalIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Load the production view without executing bot.py's data-file startup.
        source = ast.parse(pathlib.Path(__file__).with_name("bot.py").read_text(encoding="utf-8"))
        nodes = [n for n in source.body if isinstance(n, (ast.ClassDef, ast.AsyncFunctionDef))
                 and n.name in ("ApproveView", "_disable_view", "on_message")]
        self.pending = {"a": {"user_id": 123, "new": "new", "previous": "old"}}
        self.member = SimpleNamespace(edit=AsyncMock(), send=AsyncMock(), mention="@test")
        self.env = {"discord": discord, "nickname_approval_guard": ApprovalGuard(),
                    "load_pending": lambda: self.pending,
                    "remove_pending": lambda key: self.pending.pop(key, None),
                    "record_change": Mock(), "update_server_role": AsyncMock(return_value=True),
                    "bot": SimpleNamespace(event=lambda f: f, process_commands=AsyncMock()),
                    "report_panel_info": {"1": {}}, "_report_repost_tasks": {}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "bot.py", "exec"), self.env)
        self.view = self.env["ApproveView"]("a")
        self.event = interaction()
        self.event.guild = SimpleNamespace(get_member=lambda uid: self.member)

    async def test_success_records_once_and_disables_buttons(self):
        await self.view.approve(self.event)
        await self.view.approve(interaction())
        self.member.edit.assert_awaited_once_with(nick="new")
        self.env["record_change"].assert_called_once()
        self.assertFalse(self.pending)
        self.assertTrue(all(b.disabled for b in self.view.children))
        self.event.response.defer.assert_awaited_once()

    async def test_failed_nickname_keeps_pending(self):
        self.member.edit.side_effect = http_error()
        await self.view.approve(self.event)
        self.assertIn("a", self.pending)
        self.env["record_change"].assert_not_called()
        self.assertTrue(all(not b.disabled for b in self.view.children))

    async def test_role_failure_does_not_mark_complete(self):
        self.pending["a"]["new_server"] = "server"
        self.env["update_server_role"].return_value = False
        await self.view.approve(self.event)
        self.assertIn("a", self.pending)
        self.env["record_change"].assert_not_called()

    async def test_bot_messages_never_schedule_reposts(self):
        await self.env["on_message"](SimpleNamespace(author=SimpleNamespace(bot=True)))
        self.assertFalse(self.env["_report_repost_tasks"])
        self.env["bot"].process_commands.assert_not_awaited()


class RoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        source = ast.parse(pathlib.Path(__file__).with_name("bot.py").read_text(encoding="utf-8"))
        node = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "update_server_role")
        self.role = SimpleNamespace(id=42, name="target", position=1)
        self.fresh = SimpleNamespace(roles=[], add_roles=AsyncMock(), edit=AsyncMock())
        guild = SimpleNamespace(roles=[self.role], owner_id=999,
                                me=SimpleNamespace(top_role=SimpleNamespace(position=10, name="bot")),
                                fetch_member=AsyncMock(return_value=self.fresh))
        self.member = SimpleNamespace(id=123, guild=guild)
        env = {"discord": discord, "SERVER_ROLES": {"server": "target"},
               "log_http_error": log_http_error}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "bot.py", "exec"), env)
        self.update = env["update_server_role"]

    async def test_existing_role_is_not_added_twice(self):
        self.fresh.roles = [self.role]
        self.assertTrue(await self.update(self.member, "server"))
        self.fresh.add_roles.assert_not_awaited()
        self.fresh.edit.assert_not_awaited()

    async def test_only_requested_role_is_added(self):
        self.fresh.roles = [SimpleNamespace(id=99, name="unrelated")]
        self.assertTrue(await self.update(self.member, "server"))
        self.fresh.add_roles.assert_awaited_once_with(self.role, atomic=True)
        self.fresh.edit.assert_not_awaited()

    async def test_invalid_role_response_keeps_details(self):
        error = discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request", headers={}),
                                      {"code": 50035, "message": "Invalid Form Body",
                                       "errors": {"roles": {"_errors": [{"message": "Invalid role"}]}}})
        self.fresh.add_roles.side_effect = error
        with self.assertLogs("bot.runtime", "WARNING") as logs:
            with self.assertRaises(discord.HTTPException):
                await self.update(self.member, "server")
        self.assertIn("Invalid role", str(logs.output))
        self.assertIn("server_role_add", str(logs.output))


if __name__ == "__main__":
    unittest.main()
