import {
  bffDisabledResponse,
  forwardCodeSage,
  isBffEnabled,
} from "@/lib/server/codesage-api";

export async function GET(): Promise<Response> {
  if (!isBffEnabled()) {
    return bffDisabledResponse();
  }

  return forwardCodeSage("/repos", { method: "GET" });
}
