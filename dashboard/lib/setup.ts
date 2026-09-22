export type DiscordGuild = {
  id: string;
  name: string;
  permissions: string;
  owner?: boolean;
};

export function canManageGuild(guild: DiscordGuild): boolean {
  if (guild.owner === true) return true;
  try {
    const permissions = BigInt(guild.permissions);
    return (permissions & BigInt(0x28)) !== BigInt(0);
  } catch {
    return false;
  }
}

export function inviteUrl(applicationId: string, guildId: string): string {
  const params = new URLSearchParams({
    client_id: applicationId,
    scope: "bot applications.commands",
    permissions: "8",
    guild_id: guildId,
    disable_guild_select: "true",
  });
  return `https://discord.com/oauth2/authorize?${params}`;
}

export type SetupState = {
  online: boolean;
  botName: string | null;
  applicationId: string | null;
  configurationReady: boolean;
  idMismatch: boolean;
  missing: string[];
  guilds: { id: string; name: string; installed: boolean; inviteUrl: string | null }[];
  guildError: string | null;
};
