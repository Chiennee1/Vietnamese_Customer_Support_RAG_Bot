import type { ChatResponse } from "../types";

const inferredLocalApi =
  window.location.port === "5173"
    ? `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
    : "/api/v1";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? inferredLocalApi;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "REQUEST_FAILED") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

function authHeaders(token?: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: ErrorEnvelope = {};
  try {
    payload = (await response.json()) as ErrorEnvelope;
  } catch {
    // The fallback below intentionally hides proxy/server internals.
  }
  const message =
    payload.error?.message ??
    (response.status >= 500
      ? "Dịch vụ đang tạm gián đoạn. Hãy thử lại sau."
      : "Yêu cầu chưa thể hoàn tất.");
  return new ApiError(message, response.status, payload.error?.code);
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const error = await parseError(response);
    if (error.status === 401) {
      window.dispatchEvent(new Event("support:auth-expired"));
    }
    throw error;
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

interface StreamCallbacks {
  onMeta: (data: { conversation_id: string; message_id: string }) => void;
  onDelta: (text: string) => void;
  onDone: (data: Omit<ChatResponse, "answer">) => void;
}

function processEventBlock(block: string, callbacks: StreamCallbacks): void {
  const lines = block.split(/\r?\n/);
  const event = lines
    .find((line) => line.startsWith("event:"))
    ?.slice("event:".length)
    .trim();
  const dataText = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (!event || !dataText) return;
  const data = JSON.parse(dataText) as Record<string, unknown>;
  if (event === "meta") {
    callbacks.onMeta(data as { conversation_id: string; message_id: string });
  } else if (event === "delta") {
    callbacks.onDelta(String(data.text ?? ""));
  } else if (event === "done") {
    callbacks.onDone(data as unknown as Omit<ChatResponse, "answer">);
  }
}

export async function streamChat(
  body: { conversation_id: string | null; message: string },
  token: string,
  callbacks: StreamCallbacks,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      ...authHeaders(token),
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await parseError(response);
    if (error.status === 401) {
      window.dispatchEvent(new Event("support:auth-expired"));
    }
    throw error;
  }
  if (!response.body) {
    throw new ApiError("Trình duyệt không nhận được luồng phản hồi.", 502);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    blocks.forEach((block) => processEventBlock(block, callbacks));
    if (done) break;
  }
  if (buffer.trim()) {
    processEventBlock(buffer, callbacks);
  }
}
