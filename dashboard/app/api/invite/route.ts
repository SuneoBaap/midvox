import { NextResponse } from "next/server";

export function GET() {
  const clientId = process.env.DISCORD_CLIENT_ID || process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID || "";

  if (!/^\d+$/.test(clientId)) {
    return NextResponse.json(
      { error: "Discord client ID is not configured." },
      { status: 503 },
    );
  }

  const inviteUrl = new URL("https://discord.com/oauth2/authorize");
  inviteUrl.searchParams.set("client_id", clientId);
  inviteUrl.searchParams.set("permissions", "8");
  inviteUrl.searchParams.set("integration_type", "0");
  inviteUrl.searchParams.set("scope", "bot applications.commands");

  return NextResponse.redirect(inviteUrl);
}
