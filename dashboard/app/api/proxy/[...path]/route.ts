import { NextRequest, NextResponse } from "next/server";
import { getToken } from "next-auth/jwt";

const API_URL = "http://localhost:5001/api/v1";

async function proxy(
  req: NextRequest,
  params: { path: string[] },
  method: string
) {
  const endpoint = "/" + params.path.join("/") + (req.nextUrl.pathname.endsWith("/") ? "/" : "") + req.nextUrl.search;
  const routePath = "/" + params.path.join("/");
  let parsedBody: any = undefined;

  // Role creation/editing changes the Discord server immediately. Confirm the
  // caller is logged in and can manage the requested guild before forwarding.
  const roleMutation = method !== "GET" && routePath.match(/^\/guilds\/(\d+)\/roles(?:\/\d+)?$/);
  if (roleMutation) {
    const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
    const accessToken = token?.accessToken as string | undefined;
    if (!accessToken) {
      return NextResponse.json({ detail: "Sign in with Discord again to manage roles" }, { status: 401 });
    }
    try {
      const guildsResponse = await fetch("https://discord.com/api/v10/users/@me/guilds", {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
      if (!guildsResponse.ok) {
        return NextResponse.json({ detail: "Discord session expired. Sign in again" }, { status: 401 });
      }
      const guilds = await guildsResponse.json() as Array<{ id: string; owner?: boolean; permissions?: string }>;
      const guild = guilds.find(item => item.id === roleMutation[1]);
      const permissions = BigInt(guild?.permissions || "0");
      const isAdministrator = Boolean(guild?.owner) || (permissions & BigInt(8)) !== BigInt(0);
      const canManage = isAdministrator || (permissions & BigInt(268435456)) !== BigInt(0);
      if (!guild || !canManage) {
        return NextResponse.json({ detail: "You need Manage Roles permission for this guild" }, { status: 403 });
      }
      parsedBody = await req.clone().json().catch(() => undefined);
      const grantsAdministrator = parsedBody?.preset === "all"
        || (Array.isArray(parsedBody?.permissions) && parsedBody.permissions.includes("administrator"));
      if (grantsAdministrator && !isAdministrator) {
        return NextResponse.json({ detail: "Only the server owner or an administrator can grant Administrator permission" }, { status: 403 });
      }
    } catch {
      return NextResponse.json({ detail: "Could not verify your Discord guild permissions" }, { status: 502 });
    }
  }
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  // Forward the API key from the client request
  const auth = req.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;

  try {
    const opts: RequestInit = {
      method,
      headers,
      signal: AbortSignal.timeout(15000),
    };
    if (method !== "GET" && method !== "HEAD") {
      try {
        opts.body = JSON.stringify(parsedBody ?? await req.json());
      } catch {}
    }
    const res = await fetch(`${API_URL}${endpoint}`, opts);
    const body = await res.arrayBuffer();
    const contentType = res.headers.get("content-type") || "application/json";
    return new Response(body, {
      status: res.status,
      headers: { "Content-Type": contentType },
    });
  } catch (e: any) {
    return NextResponse.json(
      { detail: e.message || "Failed to reach bot API" },
      { status: 502 }
    );
  }
}

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params, "GET");
}
export async function POST(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params, "POST");
}
export async function PATCH(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params, "PATCH");
}
export async function DELETE(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params, "DELETE");
}
