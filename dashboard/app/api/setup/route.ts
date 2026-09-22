import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";
import { canManageGuild, inviteUrl, type DiscordGuild, type SetupState } from "@/lib/setup";

export const dynamic = "force-dynamic";

async function getJson(url: string, headers?: HeadersInit) {
  const response = await fetch(url, {
    headers, cache: "no-store", signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export async function GET() {
  const apiUrl = process.env.API_INTERNAL_URL || "http://127.0.0.1:5001/api/v1";
  const missing = ["TOKEN", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "NEXTAUTH_SECRET", "NEXTAUTH_URL"]
    .filter(key => !process.env[key]?.trim() || /REPLACE_|paste here|your_discord/i.test(process.env[key] || ""));
  const [session, health] = await Promise.all([
    getServerSession(authOptions),
    getJson(new URL("/health", apiUrl).toString()).catch(() => null),
  ]);
  const online = health?.status === "ok";
  const configuredId = process.env.DISCORD_CLIENT_ID?.trim() || null;
  const applicationId = online ? health.bot_id || configuredId : configuredId;
  const idMismatch = Boolean(online && health.bot_id && configuredId && health.bot_id !== configuredId);
  const result: SetupState = {
    online, botName: online ? health.bot_name || null : null,
    applicationId, idMismatch, missing,
    configurationReady: missing.length === 0 && !idMismatch,
    guilds: [], guildError: null,
  };

  if (session?.user) {
    if (!session.accessToken) {
      result.guildError = "Your Discord session expired. Sign in again to load your servers.";
    } else {
      try {
        // Fail closed if the bot or Discord cannot confirm server membership.
        const botGuilds = online ? await getJson(`${apiUrl}/guilds/`) : [];
        const installed = new Set<string>(botGuilds.map((guild: { id: string }) => String(guild.id)));
        const guilds: DiscordGuild[] = [];
        let after = "";
        for (;;) {
          const params = new URLSearchParams({ limit: "200", ...(after ? { after } : {}) });
          const page: DiscordGuild[] = await getJson(`https://discord.com/api/v10/users/@me/guilds?${params}`, {
            Authorization: `Bearer ${session.accessToken}`,
          });
          guilds.push(...page);
          if (page.length < 200) break;
          const next = page[page.length - 1].id;
          if (next === after) throw new Error("Pagination did not advance");
          after = next;
        }
        result.guilds = guilds.filter(canManageGuild).map(guild => ({
          id: guild.id, name: guild.name, installed: installed.has(guild.id),
          inviteUrl: applicationId && !idMismatch ? inviteUrl(applicationId, guild.id) : null,
        }));
      } catch {
        result.guildError = "Unable to verify your servers. Retry in a moment; if it persists, sign in again.";
      }
    }
  }
  return NextResponse.json(result, { headers: { "Cache-Control": "private, no-store" } });
}
