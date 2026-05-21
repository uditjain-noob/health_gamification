// Helpers used by all pages.

export function getUrlParam(key) {
    return new URLSearchParams(window.location.search).get(key) ?? "";
}

/**
 * Point an iframe at the /render endpoint, which serves a full AppBridge host
 * page for the given tool.  The iframe handles MCP connection and Prefab
 * rendering internally — no MCP protocol needed on the caller side.
 */
export function loadIntoIframe(iframeEl, toolName, args) {
    const argsJson = JSON.stringify({ input: args });
    iframeEl.src =
        "/render?tool=" +
        encodeURIComponent(toolName) +
        "&args=" +
        encodeURIComponent(argsJson);
}

/**
 * Fetch dashboard JSON data from the REST endpoint.
 * Returns the object from get_dashboard_json() on the server.
 */
export async function fetchDashboardData(patientId) {
    const resp = await fetch("/api/dashboard/" + encodeURIComponent(patientId));
    if (!resp.ok) throw new Error("Dashboard fetch failed: " + resp.status);
    return resp.json();
}
