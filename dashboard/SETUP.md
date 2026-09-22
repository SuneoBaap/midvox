# Connect MidVox through the dashboard

Open `/setup` on your deployed dashboard. The home page's login and invite
buttons lead here, as does the Servers menu.

1. The page checks whether the bot has connected to Discord and whether its
   application ID matches the dashboard's OAuth application.
2. Choose **Connect with Discord**. Discord handles account sign-in, server
   selection, and approval of the bot's administrator permissions.
3. After returning, the page lists only servers you own or have Manage Server
   or Administrator permission for. Once the bot joins, **Open dashboard**
   appears. Checks repeat every 30 seconds while the page is visible; **Check
   again** refreshes immediately.

This flow does not enable moderation rules, create channels, or change roles.
Configure those features from the server dashboard after connecting.

## One-time deployment configuration

The deployment owner must still set `TOKEN`, `DISCORD_CLIENT_ID`,
`DISCORD_CLIENT_SECRET`, `NEXTAUTH_SECRET`, and `NEXTAUTH_URL` in Railway.
The token and OAuth credentials must belong to the same Discord application.
Keep the existing matching dashboard API keys configured as well.

In that application's Discord Developer Portal, register the redirect URL:

```text
https://YOUR-DASHBOARD-DOMAIN/api/auth/callback/discord
```

Discord OAuth does not issue a bot token or an OAuth client secret. These
credentials stay in the deployment environment, and the setup endpoint never
returns them. Authorization also cannot start a stopped hosting service.

## Verification

From the `dashboard` directory, after installing dependencies:

```sh
node --test tests/setup.test.cjs
npx tsc --noEmit
npm run build
```

The tests mock Discord and the bot API. Testing the complete OAuth round trip
requires the deployed Discord application's registered callback URL.
