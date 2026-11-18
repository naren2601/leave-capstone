import { HttpErrorResponse } from '@angular/common/http';

/** The API's error body: {"error": {"code", "message", "request_id", "details"}}. */
export interface ApiError {
  code: string;
  message: string;
  details: { field: string | null; problem: string }[];
}

/** The API's error, or a stand-in when the server could not be reached at all. */
export function apiError(error: unknown): ApiError {
  if (error instanceof HttpErrorResponse) {
    const body = error.error as { error?: Partial<ApiError> } | null;
    if (body?.error?.message) {
      return {
        code: body.error.code ?? 'ERROR',
        message: body.error.message,
        details: body.error.details ?? [],
      };
    }
    if (error.status === 0) {
      return { code: 'OFFLINE', message: 'Cannot reach the server. Try again.', details: [] };
    }
  }
  return { code: 'ERROR', message: 'Something went wrong. Try again.', details: [] };
}

/** A sentence to show the user, starting with a capital letter. */
export function errorMessage(error: unknown): string {
  const message = apiError(error).message;
  return message.charAt(0).toUpperCase() + message.slice(1);
}
