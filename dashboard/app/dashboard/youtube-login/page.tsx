"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function YouTubeLogin() {
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Open the Railway browser and sign in to YouTube yourself.");
  const [text, setText] = useState("");
  const [image, setImage] = useState("");
  const imageUrl = useRef("");

  const refresh = async () => {
    const response = await fetch("/api/youtube-login", { cache: "no-store" });
    if (!response.ok) {
      const error = await response.json();
      setMessage(error.detail);
      if (response.status === 401 || response.status === 403) setRunning(false);
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = url;
    setImage(url);
  };

  const action = async (action: string, values: Record<string, unknown> = {}) => {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch("/api/youtube-login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...values }),
      });
      const result = await response.json();
      setMessage(result.detail || result.message);
      if (!response.ok) return;
      if (action === "stop" || action === "save") {
        setRunning(false);
        setImage("");
      } else {
        setRunning(true);
        await refresh();
      }
    } catch {
      setMessage("Could not reach the Railway browser. Try opening it again.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!running || busy) return;
    const timer = setInterval(() => { refresh().catch(() => setMessage("Browser connection interrupted.")); }, 2500);
    return () => clearInterval(timer);
  }, [running, busy]);

  useEffect(() => () => { if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); }, []);

  return <section className="mx-auto max-w-6xl space-y-5 p-6">
    <h1 className="text-2xl font-bold">YouTube login on Railway</h1>
    <p className="text-sm text-[var(--panel-muted)]">Click inside the browser image, enter text below, and complete Google verification on your phone if asked. Return to YouTube after signing in, then save the session.</p>
    <div className="flex flex-wrap gap-2">
      <Button disabled={busy} onClick={() => action("start")}>Open browser</Button>
      <Button variant="outline" disabled={busy || !running} onClick={() => action("youtube")}>Return to YouTube</Button>
      <Button disabled={busy || !running} onClick={() => action("save")}>Save session and close</Button>
      <Button variant="outline" disabled={busy || !running} onClick={() => action("stop")}>Close browser</Button>
    </div>
    <p role="status" className="text-sm">{busy ? "Working…" : message}</p>
    {running && <>
      <form className="flex flex-wrap gap-2" onSubmit={event => {
        event.preventDefault(); action("text", { text }); setText("");
      }}>
        <Input type="password" autoComplete="off" value={text} onChange={event => setText(event.target.value)} placeholder="Text for the selected browser field" className="max-w-md" />
        <Button type="submit" disabled={busy || !text}>Type into browser</Button>
        {["Enter", "Tab", "Backspace"].map(key => <Button type="button" variant="outline" disabled={busy} key={key} onClick={() => action("key", { key })}>{key}</Button>)}
        <Button type="button" variant="outline" disabled={busy} onClick={() => action("scroll", { delta: 500 })}>Scroll down</Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => action("scroll", { delta: -500 })}>Scroll up</Button>
      </form>
      {image && <img src={image} alt="Live YouTube browser on Railway — click to interact" className="w-full rounded-xl border cursor-pointer" draggable={false} onClick={event => {
        const box = event.currentTarget.getBoundingClientRect();
        action("click", { x: (event.clientX - box.left) * 1100 / box.width, y: (event.clientY - box.top) * 800 / box.height });
      }} />}
    </>}
    <p className="text-xs text-[var(--panel-muted)]">The browser runs only during login. Saved cookies stay private on this Railway container; a redeploy without persistent storage requires signing in again. Signing in does not guarantee YouTube will accept this server connection.</p>
  </section>;
}
