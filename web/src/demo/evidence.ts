/**
 * Purpose: Synthetic console evidence images for demo restore runs.
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-10-07
 * Version: 1.2.0
 */

function xmlEscape(value: string): string {
  return value.replace(/[<>&"]/g, (ch) => {
    if (ch === "<") return "&lt;";
    if (ch === ">") return "&gt;";
    if (ch === "&") return "&amp;";
    return "&quot;";
  });
}

function svgBlob(svg: string): Blob {
  return new Blob([svg], { type: "image/svg+xml" });
}

/** Win11* guests are desktops. Other Windows ostype guests are servers. */
function windowsEdition(guestName: string): "desktop" | "server" {
  return /win11/i.test(guestName) ? "desktop" : "server";
}

function windowsDesktopSvg(guestName: string, vmid: number): string {
  const safe = xmlEscape(guestName);
  const edition = windowsEdition(guestName);
  const title = edition === "desktop" ? "Windows 11 Pro" : "Windows Server";
  const subtitle =
    edition === "desktop" ? "Desktop" : "Server Manager — Dashboard";
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="wall" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0a2f6b"/>
      <stop offset="42%" stop-color="#1a6fd4"/>
      <stop offset="100%" stop-color="#8ec8ff"/>
    </linearGradient>
    <radialGradient id="bloom" cx="58%" cy="36%" r="46%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.55"/>
      <stop offset="30%" stop-color="#b9dcff" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#0a2f6b" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#wall)"/>
  <rect width="1280" height="720" fill="url(#bloom)"/>
  <g transform="translate(36,36)">
    <rect width="46" height="36" rx="3" fill="#e8eef6"/>
    <rect x="8" y="8" width="30" height="16" rx="1" fill="#3b82f6"/>
    <text x="0" y="54" fill="#ffffff" font-family="Segoe UI, Arial, sans-serif" font-size="13">This PC</text>
    <rect y="78" width="46" height="40" rx="3" fill="none" stroke="#dbe7f5" stroke-width="2"/>
    <path d="M10 100 h26 l-4 12 h-18 z" fill="#9fb4c9"/>
    <text x="0" y="136" fill="#ffffff" font-family="Segoe UI, Arial, sans-serif" font-size="13">Recycle Bin</text>
  </g>
  <g transform="translate(330,168)">
    <rect width="620" height="340" rx="10" fill="#f4f6f8"/>
    <rect width="620" height="42" rx="10" fill="#ffffff"/>
    <rect y="22" width="620" height="20" fill="#ffffff"/>
    <g transform="translate(16,10)">
      <rect width="10" height="10" fill="#f25022"/>
      <rect x="12" width="10" height="10" fill="#7fba00"/>
      <rect y="12" width="10" height="10" fill="#00a4ef"/>
      <rect x="12" y="12" width="10" height="10" fill="#ffb900"/>
    </g>
    <text x="48" y="27" fill="#1b1b1b" font-family="Segoe UI, Arial, sans-serif" font-size="15">${title}</text>
    <text x="28" y="84" fill="#5b6775" font-family="Segoe UI, Arial, sans-serif" font-size="14">${subtitle}</text>
    <text x="28" y="132" fill="#5b6775" font-family="Segoe UI, Arial, sans-serif" font-size="15">Computer name</text>
    <text x="220" y="132" fill="#1b1b1b" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="600">${safe}</text>
    <text x="28" y="176" fill="#5b6775" font-family="Segoe UI, Arial, sans-serif" font-size="15">Operating system</text>
    <text x="220" y="176" fill="#1b1b1b" font-family="Segoe UI, Arial, sans-serif" font-size="16">${title}</text>
    <text x="28" y="220" fill="#5b6775" font-family="Segoe UI, Arial, sans-serif" font-size="15">VMID</text>
    <text x="220" y="220" fill="#1b1b1b" font-family="Segoe UI, Arial, sans-serif" font-size="16">${vmid}</text>
    <text x="28" y="264" fill="#5b6775" font-family="Segoe UI, Arial, sans-serif" font-size="15">Status</text>
    <text x="220" y="264" fill="#107c10" font-family="Segoe UI, Arial, sans-serif" font-size="16">Running</text>
  </g>
  <rect y="672" width="1280" height="48" fill="#1c1c1c"/>
  <g transform="translate(18,684)">
    <rect width="11" height="11" fill="#f25022"/>
    <rect x="13" width="11" height="11" fill="#7fba00"/>
    <rect y="13" width="11" height="11" fill="#00a4ef"/>
    <rect x="13" y="13" width="11" height="11" fill="#ffb900"/>
  </g>
  <text x="1180" y="702" text-anchor="end" fill="#ffffff" font-family="Segoe UI, Arial, sans-serif" font-size="13">${safe}</text>
</svg>`;
}

function linuxConsoleSvg(guestName: string, vmid: number, osLabel: string): string {
  const safe = xmlEscape(guestName);
  const distro = xmlEscape(osLabel === "Other" || osLabel === "Unknown" ? "Linux" : osLabel);
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect width="1280" height="720" fill="#0c0c0c"/>
  <text x="48" y="72" fill="#d0d0d0" font-family="Consolas, monospace" font-size="22">${distro} tty1</text>
  <text x="48" y="120" fill="#d0d0d0" font-family="Consolas, monospace" font-size="22">${safe} login: _</text>
  <text x="48" y="168" fill="#8d8d8d" font-family="Consolas, monospace" font-size="18">VMID ${vmid}</text>
</svg>`;
}

/** Fake VGA console screenshot. Windows guests get a desktop; other VMs get a text console. */
export function buildDemoEvidenceBlob(guestName: string, vmid: number, osLabel = ""): Blob {
  const windows = osLabel.trim().toLowerCase().startsWith("windows");
  const svg = windows
    ? windowsDesktopSvg(guestName, vmid)
    : linuxConsoleSvg(guestName, vmid, osLabel || "Linux");
  return svgBlob(svg);
}
