import {
  bffDisabledResponse,
  forwardCodeSage,
  isBffEnabled,
} from "@/lib/server/codesage-api";
import {
  chatRequestSchema,
  parseJsonRequest,
} from "@/lib/server/request-schemas";

const CHAT_TIMEOUT_MS = 120_000;

export async function POST(request: Request): Promise<Response> {
  if (!isBffEnabled()) {
    return bffDisabledResponse();
  }

  const parsed = await parseJsonRequest(request, chatRequestSchema);
  if (!parsed.success) {
    return parsed.response;
  }

  return forwardCodeSage(
    "/chat",
    {
      method: "POST",
      body: JSON.stringify(parsed.data),
    },
    CHAT_TIMEOUT_MS,
  );
}
