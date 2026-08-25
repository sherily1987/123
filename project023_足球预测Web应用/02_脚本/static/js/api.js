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
    throw error;
  }
  return response.json();
}
