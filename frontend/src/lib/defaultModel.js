// Preferred default model for course generation (splitting + AI generate/
// revise) — falls back to whatever the connected Open WebUI instance offers
// first if the preferred one isn't available there.
const PREFERRED_MODEL_ID = "gpt-5.4";

export function defaultModelId(models, preferred = PREFERRED_MODEL_ID) {
  if (!models || models.length === 0) return "";
  return models.find((m) => m.id === preferred)?.id ?? models[0].id;
}
