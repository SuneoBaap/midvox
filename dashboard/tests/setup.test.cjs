const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Exercise the actual route with isolated Discord/session/HTTP boundaries.
function load(file, globals = {}) {
  const exports = {};
  const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  vm.runInNewContext(compiled.outputText, { exports, URL, URLSearchParams, AbortSignal, ...globals });
  return exports;
}
const helpers = load("lib/setup.ts");
const environment = {
  TOKEN: "private-bot-token", DISCORD_CLIENT_ID: "123",
  DISCORD_CLIENT_SECRET: "private-client-secret", NEXTAUTH_SECRET: "private-session-secret",
  NEXTAUTH_URL: "https://example.com",
};
async function run({ session = null, health = { status: "ok", bot_id: "123", bot_name: "Test bot" }, guilds = [], botGuilds = [], discordError = false, env = {} } = {}) {
  const calls = [];
  const route = load("app/api/setup/route.ts", {
    process: { env: { ...environment, ...env } },
    require: (name) => {
      if (name === "next-auth") return { getServerSession: async () => session };
      if (name === "next/server") return { NextResponse: { json: (body) => body } };
      if (name === "@/lib/auth") return { authOptions: {} };
      if (name === "@/lib/setup") return helpers;
      throw new Error(`Unexpected module ${name}`);
    },
    fetch: async (url, options) => {
      calls.push({ url, options });
      if (url.includes("discord.com")) return { ok: !discordError, status: 401, json: async () => guilds };
      if (url.endsWith("/health")) return { ok: true, json: async () => health };
      if (url.endsWith("/guilds/")) return { ok: true, json: async () => botGuilds };
      throw new Error(`Unexpected fetch ${url}`);
    },
  });
  return { result: await route.GET(), calls };
}
test("permissions require ownership, administrator, or manage server", () => {
  for (const permissions of ["8", "32", "40", "1099511627808"]) {
    assert.equal(helpers.canManageGuild({ permissions }), true);
  }
  for (const permissions of ["0", "1024", "invalid", undefined]) {
    assert.equal(helpers.canManageGuild({ permissions }), false);
  }
  assert.equal(helpers.canManageGuild({ owner: true, permissions: "invalid" }), true);
});
test("signed-out readiness never requests a user's servers or exposes credentials", async () => {
  const { result, calls } = await run();
  assert.equal(calls.length, 1);
  assert.equal(result.guilds.length, 0);
  for (const value of Object.values(environment).filter(value => value.startsWith("private-"))) {
    assert.equal(JSON.stringify(result).includes(value), false);
  }
});
const session = { user: { id: "owner" }, accessToken: "private-user-token" };
test("authorized flow offers only manageable servers and detects existing installation", async () => {
  const { result } = await run({ session, guilds: [
    { id: "1", name: "Managed", permissions: "32" },
    { id: "2", name: "Member only", permissions: "1024" },
    { id: "3", name: "New server", permissions: "8" },
  ], botGuilds: [{ id: "1" }, { id: "2" }] });
  assert.equal(result.guilds.length, 2);
  assert.equal(result.guilds[0].installed, true);
  assert.equal(result.guilds[1].installed, false);
  const invite = new URL(result.guilds[1].inviteUrl);
  assert.equal(invite.searchParams.get("client_id"), "123");
  assert.equal(invite.searchParams.get("guild_id"), "3");
  assert.equal(invite.searchParams.get("scope"), "bot applications.commands");
  assert.equal(JSON.stringify(result).includes(session.accessToken), false);
});
test("expired Discord authorization fails closed instead of listing all bot servers", async () => {
  const { result } = await run({ session, discordError: true, botGuilds: [{ id: "1" }] });
  assert.equal(result.guilds.length, 0);
  assert.ok(result.guildError);
});
test("an offline bot never marks server setup complete", async () => {
  const { result } = await run({ session, health: { status: "starting" }, guilds: [{ id: "1", name: "Mine", permissions: "32" }] });
  assert.equal(result.online, false);
  assert.equal(result.guilds[0].installed, false);
});
test("mismatched application ID blocks authorization and identifies the running bot", async () => {
  const { result } = await run({ health: { status: "ok", bot_id: "456" } });
  assert.equal(result.idMismatch, true);
  assert.equal(result.configurationReady, false);
  assert.equal(result.applicationId, "456");
});
test("missing or placeholder credentials are reported without their values", async () => {
  const { result } = await run({ env: { TOKEN: "REPLACE_WITH_NEW_DISCORD_BOT_TOKEN", DISCORD_CLIENT_SECRET: "" } });
  assert.equal(result.configurationReady, false);
  assert.ok(result.missing.includes("TOKEN"));
  assert.ok(result.missing.includes("DISCORD_CLIENT_SECRET"));
});
