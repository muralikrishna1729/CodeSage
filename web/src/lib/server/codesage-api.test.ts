
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiKey = "server-test-api-key";
const backendUrl = "http://backend.test";
const validRepoUrl = "https://github.com/acme/widget";
const validJobId = "0123456789ab4def8abcdef012345678";

const routePaths = {
  ingest: "../../app/api/codesage/ingest/route.ts",
  job: "../../app/api/codesage/ingest/[jobId]/route.ts",
  chat: "../../app/api/codesage/chat/route.ts",
  repos: "../../app/api/codesage/repos/route.ts",
  metrics: "../../app/api/codesage/metrics/route.ts",
} as const;

const routeModules = import.meta.glob("../../app/api/codesage/**/route.ts");

type RouteModule = {
  GET?: (
    request: Request,
    context?: { params: Promise<{ jobId: string }> },
  ) => Promise<Response>;
  POST?: (request: Request) => Promise<Response>;
};

const originalBffFlag = process.env.CODESAGE_BFF_ENABLED;
let upstreamFetch: ReturnType<typeof vi.fn<typeof fetch>>;

async function loadRoute(name: keyof typeof routePaths): Promise<RouteModule> {
  const load = routeModules[routePaths[name]];
  expect(load, `${name} route should be registered`).toBeTypeOf("function");
  return (await load!()) as RouteModule;
}

function jsonRequest(path: string, body: unknown): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function enableBff(ingestionEnabled = false): void {
  vi.stubEnv("CODESAGE_BFF_ENABLED", "true");
  vi.stubEnv("CODESAGE_ENABLE_INGESTION", String(ingestionEnabled));
  vi.stubEnv("CODESAGE_API_BASE_URL", backendUrl);
  vi.stubEnv("CODESAGE_API_KEY", apiKey);
}

beforeEach(() => {
  delete process.env.CODESAGE_BFF_ENABLED;
  vi.stubEnv("CODESAGE_ENABLE_INGESTION", "false");
  vi.stubEnv("CODESAGE_API_BASE_URL", "");
  vi.stubEnv("CODESAGE_API_KEY", "");
  upstreamFetch = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", upstreamFetch);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();

  if (originalBffFlag === undefined) {
    delete process.env.CODESAGE_BFF_ENABLED;
  } else {
    process.env.CODESAGE_BFF_ENABLED = originalBffFlag;
  }
});

const closedRoutes = [
  {
    name: "ingestion",
    invoke: async () => {
      const route = await loadRoute("ingest");
      return route.POST!(
        jsonRequest("/api/codesage/ingest", { repo_url: validRepoUrl }),
      );
    },
  },
  {
    name: "job status",
    invoke: async () => {
      const route = await loadRoute("job");
      return route.GET!(
        new Request(`http://localhost/api/codesage/ingest/${validJobId}`),
        { params: Promise.resolve({ jobId: validJobId }) },
      );
    },
  },
  {
    name: "chat",
    invoke: async () => {
      const route = await loadRoute("chat");
      return route.POST!(
        jsonRequest("/api/codesage/chat", {
          question: "How does routing work?",
          repo_name: "acme/widget",
        }),
      );
    },
  },
  {
    name: "repository list",
    invoke: async () => {
      const route = await loadRoute("repos");
      return route.GET!(new Request("http://localhost/api/codesage/repos"));
    },
  },
  {
    name: "metrics",
    invoke: async () => {
      const route = await loadRoute("metrics");
      return route.GET!(new Request("http://localhost/api/codesage/metrics"));
    },
  },
];

describe("BFF closed by default", () => {
  it.each(closedRoutes)(
    "$name returns 503 without accessing the upstream",
    async ({ invoke }) => {
      const response = await invoke();

      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({ error: "BFF_DISABLED" });
      expect(upstreamFetch).not.toHaveBeenCalled();
    },
  );
});

describe("request validation and access gates", () => {
  it("blocks ingestion independently when the BFF is enabled", async () => {
    enableBff(false);
    const route = await loadRoute("ingest");

    const response = await route.POST!(
      jsonRequest("/api/codesage/ingest", { repo_url: validRepoUrl }),
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "INGESTION_DISABLED" });
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: "ingestion with an unsupported repository URL",
      invoke: async () => {
        const route = await loadRoute("ingest");
        return route.POST!(
          jsonRequest("/api/codesage/ingest", {
            repo_url: "http://github.com/acme/widget",
          }),
        );
      },
    },
    {
      name: "chat with an invalid history message",
      invoke: async () => {
        const route = await loadRoute("chat");
        return route.POST!(
          jsonRequest("/api/codesage/chat", {
            question: "How does routing work?",
            repo_name: "acme/widget",
            history: [{ role: "user" }],
          }),
        );
      },
    },
  ])("rejects $name before an upstream request", async ({ invoke }) => {
    enableBff(true);

    const response = await invoke();

    expect(response.status).toBe(400);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it.each([
    "not-a-uuid",
    "0123456789abcdef0123456789abcdef",
  ])("rejects job ID %s outside the backend UUIDv4 hex format", async (jobId) => {
    enableBff(true);
    const route = await loadRoute("job");

    const response = await route.GET!(
      new Request(`http://localhost/api/codesage/ingest/${jobId}`),
      { params: Promise.resolve({ jobId }) },
    );

    expect(response.status).toBe(400);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });
});

describe("upstream contract mapping", () => {
  it.each([
    {
      name: "ingestion",
      call: async () => {
        const route = await loadRoute("ingest");
        return route.POST!(
          jsonRequest("/api/codesage/ingest", { repo_url: validRepoUrl }),
        );
      },
      method: "POST",
      path: "/ingest/async",
      status: 202,
      payload: { job_id: validJobId, repo_name: "acme/widget" },
      expectedBody: { repo_url: validRepoUrl, force: false },
    },
    {
      name: "job status",
      call: async () => {
        const route = await loadRoute("job");
        return route.GET!(
          new Request(`http://localhost/api/codesage/ingest/${validJobId}`),
          { params: Promise.resolve({ jobId: validJobId }) },
        );
      },
      method: "GET",
      path: `/ingest/status/${validJobId}`,
      status: 200,
      payload: {
        job_id: validJobId,
        repo_name: "acme/widget",
        status: "running",
        stage: "Chunking repository",
        chunks_stored: null,
        elapsed_s: 2.1,
        error: null,
      },
    },
    {
      name: "chat",
      call: async () => {
        const route = await loadRoute("chat");
        return route.POST!(
          jsonRequest("/api/codesage/chat", {
            question: "How does routing work?",
            repo_name: "acme/widget",
          }),
        );
      },
      method: "POST",
      path: "/chat",
      status: 200,
      payload: { answer: "The router dispatches requests.", source: "kb" },
      expectedBody: {
        question: "How does routing work?",
        repo_name: "acme/widget",
        history: [],
      },
    },
    {
      name: "repositories",
      call: async () => {
        const route = await loadRoute("repos");
        return route.GET!(new Request("http://localhost/api/codesage/repos"));
      },
      method: "GET",
      path: "/repos",
      status: 200,
      payload: [{ repo_name: "acme/widget", points: 15 }],
    },
    {
      name: "metrics",
      call: async () => {
        const route = await loadRoute("metrics");
        return route.GET!(new Request("http://localhost/api/codesage/metrics"));
      },
      method: "GET",
      path: "/metrics",
      status: 200,
      payload: { latency: [] },
    },
  ])("maps $name to its FastAPI endpoint", async (contract) => {
    enableBff(contract.name === "ingestion");

    upstreamFetch.mockResolvedValue(
      Response.json(contract.payload, { status: contract.status }),
    );

    const response = await contract.call();

    expect(response.status).toBe(contract.status);
    const responseText = await response.text();
    expect(JSON.parse(responseText)).toEqual(contract.payload);
    expect(responseText).not.toContain(apiKey);
    expect(upstreamFetch).toHaveBeenCalledOnce();

    const [url, init] = upstreamFetch.mock.calls[0];
    expect(String(url)).toBe(`${backendUrl}${contract.path}`);
    expect(init?.method).toBe(contract.method);
    expect(new Headers(init?.headers).get("X-API-Key")).toBe(apiKey);

    if (contract.expectedBody) {
      expect(JSON.parse(String(init?.body))).toEqual(contract.expectedBody);
    }
  });

  it("preserves upstream error status without forwarding its body", async () => {
    enableBff(true);
    const route = await loadRoute("repos");

    upstreamFetch.mockResolvedValue(
      new Response(`upstream details contain ${apiKey}`, { status: 429 }),
    );

    const response = await route.GET!(
      new Request("http://localhost/api/codesage/repos"),
    );
    const responseBody = await response.text();

    expect(response.status).toBe(429);
    expect(responseBody).not.toContain(apiKey);
    expect(responseBody).not.toContain("upstream details");
  });

  it("maps network failures to a safe 502 response", async () => {
    enableBff(true);
    const route = await loadRoute("repos");

    upstreamFetch.mockRejectedValue(new TypeError(`failed with ${apiKey}`));

    const response = await route.GET!(
      new Request("http://localhost/api/codesage/repos"),
    );
    const responseBody = await response.text();

    expect(response.status).toBe(502);
    expect(responseBody).not.toContain(apiKey);
    expect(responseBody).not.toContain("failed with");
  });

  it("maps timeouts to a safe 504 response", async () => {
    enableBff(true);
    const route = await loadRoute("metrics");

    upstreamFetch.mockRejectedValue(
      new DOMException(`timed out with ${apiKey}`, "TimeoutError"),
    );

    const response = await route.GET!(
      new Request("http://localhost/api/codesage/metrics"),
    );
    const responseBody = await response.text();

    expect(response.status).toBe(504);
    expect(responseBody).not.toContain(apiKey);
    expect(responseBody).not.toContain("timed out with");
  });

  it("rejects successful upstream responses that contain the API key", async () => {
    enableBff(true);
    const route = await loadRoute("repos");

    upstreamFetch.mockResolvedValue(Response.json({ leaked: apiKey }));

    const response = await route.GET!(
      new Request("http://localhost/api/codesage/repos"),
    );
    const responseBody = await response.text();

    expect(response.status).toBe(502);
    expect(responseBody).not.toContain(apiKey);
  });

  it("does not expose upstream headers containing the API key", async () => {
    enableBff(true);
    const route = await loadRoute("repos");

    upstreamFetch.mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "content-type": `application/json; token=${apiKey}` },
      }),
    );

    const response = await route.GET!(
      new Request("http://localhost/api/codesage/repos"),
    );

    expect(response.status).toBe(200);
    expect([...response.headers.entries()].join(" ")).not.toContain(apiKey);
  });
});
