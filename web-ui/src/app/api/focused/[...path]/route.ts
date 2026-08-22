import type { NextRequest } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const maxDuration = 300

const RESPONSE_HEADERS = ["cache-control", "content-disposition", "content-type"]

type RouteContext = {
  params: Promise<{ path: string[] }>
}

async function proxy(request: NextRequest, context: RouteContext) {
  const apiUrl = (process.env.API_URL ?? "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  )
  const proxyToken = process.env.AGORA_PROXY_TOKEN
  if (process.env.VERCEL && (!process.env.API_URL || !proxyToken)) {
    return Response.json(
      { detail: "The production API proxy is not configured." },
      { status: 503 },
    )
  }

  const { path } = await context.params
  const incomingUrl = new URL(request.url)
  const target = new URL(
    `${apiUrl}/api/v1/focused/${path.map(encodeURIComponent).join("/")}`,
  )
  target.search = incomingUrl.search

  const headers = new Headers()
  for (const name of ["accept", "content-type"]) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  if (proxyToken) headers.set("x-agora-proxy-token", proxyToken)

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
    })
    const responseHeaders = new Headers()
    for (const name of RESPONSE_HEADERS) {
      const value = upstream.headers.get(name)
      if (value) responseHeaders.set(name, value)
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    })
  } catch (cause) {
    console.error("Focused API proxy failed", cause)
    return Response.json({ detail: "The API is unavailable." }, { status: 502 })
  }
}

export const PUT = proxy
export const GET = proxy
export const POST = proxy
export const PATCH = proxy
export const DELETE = proxy
