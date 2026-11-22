import "server-only";

const DEFAULT_TIMEOUT_MS = 30_000;

export function isBffEnabled(): boolean {
  return process.env.CODESAGE_BFF_ENABLED === "true";
}

export function isIngestionEnabled(): boolean {
  return process.env.CODESAGE_ENABLE_INGESTION === "true";
}

export function bffDisabledResponse(): Response {
  return Response.json({ error: "BFF_DISABLED" }, { status: 503 });
}

export function ingestionDisabledResponse(): Response {
  return Response.json({ error: "INGESTION_DISABLED" }, { status: 403 });
}

export function requestErrorResponse(
  error: string,
  status: number,
): Response {
  return Response.json({ error }, { status });
}

function isTimeoutError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "TimeoutError") ||
    (error instanceof Error && error.name === "TimeoutError")
  );
}

function createUpstreamUrl(path: string, baseUrl: string): URL | undefined {
  try {
    const url = new URL(
      path.replace(/^\/+/, ""),
      `${baseUrl.replace(/\/+$/, "")}/`,
    );
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return undefined;
    }
    return url;
  } catch {
    return undefined;
  }
}

export async function forwardCodeSage(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  if (!isBffEnabled()) {
    return bffDisabledResponse();
  }

  const baseUrl = process.env.CODESAGE_API_BASE_URL;
  const apiKey = process.env.CODESAGE_API_KEY;
  if (!baseUrl || !apiKey) {
    return requestErrorResponse("UPSTREAM_NOT_CONFIGURED", 503);
  }

  const url = createUpstreamUrl(path, baseUrl);
  if (!url) {
    return requestErrorResponse("UPSTREAM_NOT_CONFIGURED", 503);
  }

  const headers = new Headers(init.headers);
  headers.set("X-API-Key", apiKey);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  try {
    const upstream = await fetch(url, {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const body = await upstream.text();

    if (!upstream.ok) {
      return requestErrorResponse("UPSTREAM_REQUEST_FAILED", upstream.status);
    }
    if (body.includes(apiKey)) {
      return requestErrorResponse("UPSTREAM_RESPONSE_REJECTED", 502);
    }
    if (upstream.status === 204 || upstream.status === 205) {
      return new Response(null, { status: upstream.status });
    }

    return new Response(body || null, {
      status: upstream.status,
      headers: {
        "content-type": "application/json",
      },
    });
  } catch (error) {
    if (isTimeoutError(error)) {
      return requestErrorResponse("UPSTREAM_TIMEOUT", 504);
    }
    return requestErrorResponse("UPSTREAM_UNAVAILABLE", 502);
  }
}
