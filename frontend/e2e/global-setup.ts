import { request, type FullConfig } from '@playwright/test';

/** Before any test: stop early, with a clear message, if the API cannot be reached. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL;
  const api = await request.newContext({ baseURL });
  try {
    const health = await api.get('/api/health');
    if (!health.ok()) {
      throw new Error(`GET /api/health answered ${health.status()}`);
    }
  } catch (error) {
    throw new Error(
      `The API cannot be reached through ${baseURL}/api. ` +
        'Start it first (start-dev.ps1, or docker compose up). ' +
        `Details: ${(error as Error).message}`,
      { cause: error },
    );
  } finally {
    await api.dispose();
  }
}
