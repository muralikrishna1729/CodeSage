import {
  bffDisabledResponse,
  forwardCodeSage,
  ingestionDisabledResponse,
  isBffEnabled,
  isIngestionEnabled,
} from "@/lib/server/codesage-api";
import {
  ingestRequestSchema,
  parseJsonRequest,
} from "@/lib/server/request-schemas";

export async function POST(request: Request): Promise<Response> {
  if (!isBffEnabled()) {
    return bffDisabledResponse();
  }
  if (!isIngestionEnabled()) {
    return ingestionDisabledResponse();
  }

  const parsed = await parseJsonRequest(request, ingestRequestSchema);
  if (!parsed.success) {
    return parsed.response;
  }

  return forwardCodeSage("/ingest/async", {
    method: "POST",
    body: JSON.stringify(parsed.data),
  });
}
