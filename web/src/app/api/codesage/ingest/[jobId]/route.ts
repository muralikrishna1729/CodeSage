import {
  bffDisabledResponse,
  forwardCodeSage,
  isBffEnabled,
  requestErrorResponse,
} from "@/lib/server/codesage-api";

const JOB_ID_PATTERN = /^[0-9a-f]{8}[0-9a-f]{4}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/;

export async function GET(
  _request: Request,
  context: { params: Promise<{ jobId: string }> },
): Promise<Response> {
  if (!isBffEnabled()) {
    return bffDisabledResponse();
  }

  const { jobId } = await context.params;
  if (!JOB_ID_PATTERN.test(jobId)) {
    return requestErrorResponse("INVALID_JOB_ID", 400);
  }

  return forwardCodeSage(`/ingest/status/${jobId}`, { method: "GET" });
}
