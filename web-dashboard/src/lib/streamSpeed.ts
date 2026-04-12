let speedMultiplier = 8;

const clampMultiplier = (value: unknown): number => {
  if (typeof value !== "number" || Number.isNaN(value) || !Number.isFinite(value)) {
    return 1;
  }
  return Math.min(64, Math.max(0.25, value));
};

export const getSpeedMultiplier = (): number => speedMultiplier;

export const getReplayDelayMs = (baseMs: number): number => {
  const delay = Math.round(baseMs / speedMultiplier);
  return Math.max(1, delay);
};

export const getTextRevealIntervalMs = (baseMs: number): number => {
  const delay = Math.round(baseMs / speedMultiplier);
  return Math.max(1, delay);
};

export const getLivePollIntervalMs = (baseMs: number): number => {
  const interval = Math.round(baseMs / speedMultiplier);
  return Math.max(60, interval);
};

export async function refreshStreamSpeedFromApi(apiBase: string, timeoutMs = 1200): Promise<void> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${apiBase}/api/replay/speed`, {
      signal: controller.signal,
    });

    if (!response.ok) {
      return;
    }

    const payload = (await response.json()) as { speedMultiplier?: number };
    speedMultiplier = clampMultiplier(payload.speedMultiplier);
  } catch {
    // Keep the last known speed when endpoint is unavailable.
  } finally {
    window.clearTimeout(timeoutId);
  }
}
