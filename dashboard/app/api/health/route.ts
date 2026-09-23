import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch("http://127.0.0.1:5001/health", {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      { status: "unavailable", detail: "Bot API is not responding" },
      { status: 503 },
    );
  }
}
