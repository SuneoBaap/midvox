"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import type { SetupState } from "@/lib/setup";

export default function SetupPage() {
  const { data: session, status } = useSession();
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        if (document.visibilityState === "visible") {
          const response = await fetch("/api/setup", { cache: "no-store", signal: controller.signal });
          if (!response.ok) throw new Error("Could not check setup. Please retry.");
          const data: SetupState = await response.json();
          if (!controller.signal.aborted) { setSetup(data); setError(""); }
        }
      } catch {
        if (!controller.signal.aborted) setError("Could not check setup. Please retry.");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 30000);
      }
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [status, revision]);

  const authorize = async () => {
    setSigningIn(true);
    try {
      await signIn("discord", { callbackUrl: "/setup" }, {
        scope: "identify guilds bot applications.commands", permissions: "8",
      });
    } catch { setError("Could not open Discord authorization. Please retry."); }
    finally { setSigningIn(false); }
  };
  const button = "inline-flex items-center justify-center rounded-lg bg-amber-400 px-5 py-3 text-sm font-semibold text-black disabled:opacity-40";

  return (
    <main className="min-h-screen bg-[#0c0c0c] px-5 py-12 text-white">
      <div className="mx-auto max-w-2xl space-y-6">
        <Link href="/" className="text-sm text-neutral-400">← Home</Link>
        <header><p className="text-sm text-amber-400">MidVox setup</p><h1 className="mt-2 text-3xl font-bold">Connect your server</h1>
          <p className="mt-3 text-neutral-400">Authorize with Discord, choose your server, and start managing it here.</p></header>
        <section className="rounded-xl border border-white/10 bg-white/[0.03] p-6" aria-live="polite">
          <h2 className="font-semibold">1. Check the bot</h2>
          <p className="mt-3 text-sm text-neutral-300">{!setup ? "Checking connection…" : setup.online ? `${setup.botName || "Your bot"} is connected to Discord.` : "Waiting for the bot to connect to Discord. This page checks again automatically."}</p>
          {setup?.missing.length ? <p className="mt-3 text-sm text-amber-300">The deployment owner needs to set {setup.missing.join(", ")} once in Railway. Discord authorization cannot supply these credentials.</p> : null}
          {setup?.idMismatch && <p className="mt-3 text-sm text-amber-300">The running bot and dashboard use different Discord applications. Set DISCORD_CLIENT_ID to {setup.applicationId} and use that application&apos;s OAuth2 client secret, then redeploy.</p>}
          {!setup?.online && setup?.configurationReady && <p className="mt-3 text-sm text-neutral-400">Authorization does not start the hosted bot. If this continues, check Railway&apos;s Deploy Logs for a login or startup error.</p>}
          <button className="mt-4 text-sm text-amber-300 underline" onClick={() => setRevision(value => value + 1)}>Check again</button>
        </section>
        <section className="rounded-xl border border-white/10 bg-white/[0.03] p-6">
          <h2 className="font-semibold">2. Authorize with Discord</h2>
          <p className="my-3 text-sm text-neutral-400">{session ? `Signed in as ${session.user.name || "a Discord user"}. You can add the bot to another server below.` : "Discord will ask you to sign in, select a server, and approve the bot’s administrator permissions. Your bot token stays on the server."}</p>
          <button className={button} disabled={!setup?.configurationReady || signingIn || status === "loading"} onClick={authorize}>{signingIn ? "Opening Discord…" : session ? "Authorize another server" : "Connect with Discord"}</button>
        </section>
        {session && <section className="rounded-xl border border-white/10 bg-white/[0.03] p-6">
          <h2 className="font-semibold">3. Open your server</h2>
          <p className="mt-2 text-sm text-neutral-400">Only servers you own or can manage appear here. After approving an invite, return here; the connection is detected automatically.</p>
          {setup?.guildError && <p className="mt-3 text-sm text-amber-300">{setup.guildError}</p>}
          {setup && !setup.guildError && setup.guilds.length === 0 && <p className="mt-4 text-sm text-neutral-400">No manageable servers found. Make sure you used the correct Discord account.</p>}
          <div className="mt-4 space-y-3">{setup?.guilds.map(guild => <div key={guild.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 p-4">
            <div><p className="font-medium">{guild.name}</p><p className="text-xs text-neutral-400">{guild.installed ? "Connected — ready to configure" : setup.online ? "Bot not yet detected in this server" : "Waiting for bot connection"}</p></div>
            {guild.installed ? <Link className={button} href={`/dashboard/guild/${guild.id}`}>Open dashboard</Link> : guild.inviteUrl ? <a className={button} href={guild.inviteUrl} target="_blank" rel="noopener noreferrer">Add bot</a> : null}
          </div>)}</div>
        </section>}
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      </div>
    </main>
  );
}
