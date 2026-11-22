import { z } from "zod";

const githubRepoUrlSchema = z.string().url().refine((value) => {
  const url = new URL(value);
  const pathParts = url.pathname.split("/").filter(Boolean);
  return (
    url.protocol === "https:" &&
    url.hostname === "github.com" &&
    !url.username &&
    !url.password &&
    pathParts.length === 2
  );
});

export const ingestRequestSchema = z.object({
  repo_url: githubRepoUrlSchema,
  force: z.boolean().default(false),
});

export const chatRequestSchema = z.object({
  question: z.string(),
  repo_name: z.string(),
  history: z
    .array(
      z.object({
        role: z.string(),
        content: z.string(),
      }),
    )
    .default([]),
});

export async function parseJsonRequest<T>(
  request: Request,
  schema: z.ZodType<T>,
): Promise<{ success: true; data: T } | { success: false; response: Response }> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return {
      success: false,
      response: Response.json({ error: "INVALID_JSON" }, { status: 400 }),
    };
  }

  const result = schema.safeParse(body);
  if (!result.success) {
    return {
      success: false,
      response: Response.json({ error: "INVALID_REQUEST" }, { status: 400 }),
    };
  }

  return { success: true, data: result.data };
}
