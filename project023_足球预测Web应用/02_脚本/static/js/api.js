export async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    cache: options.cache ?? "no-store",
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const error = new Error(`请求失败 (${response.status}): ${path}`);
    error.status = response.status;
    error.path = path;
    try {
      const payload = await response.json();
      const detail = payload?.detail;
      if (detail && typeof detail === "object") {
        error.detail = detail;
        error.code = detail.code;
      }
    } catch (_ignored) {
      // The status/path contract remains available for non-JSON failures.
    }
    throw error;
  }
  return response.json();
}
