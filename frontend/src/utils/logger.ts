export function logEvent(message: string, context?: Record<string, unknown>) {
  if (context) {
    console.info(`[NeuroNarrative] ${message}`, context);
  } else {
    console.info(`[NeuroNarrative] ${message}`);
  }
}
