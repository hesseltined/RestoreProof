/**
 * Purpose: Synthetic console evidence image for demo restore runs.
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-07-22
 * Version: 1.1.0
 */

/** Fake VGA console screenshot — Windows Server 2025-style boot (SVG blob). */
export function buildDemoEvidenceBlob(guestName: string, vmid: number): Blob {
  const safe = guestName.replace(/[<>&"]/g, "");
  const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <rect width="960" height="540" fill="#000000"/>
  <!-- Stylized Windows logo (four panes) -->
  <g transform="translate(456,175)">
    <rect x="0" y="0" width="22" height="22" fill="#ffffff"/>
    <rect x="26" y="0" width="22" height="22" fill="#ffffff"/>
    <rect x="0" y="26" width="22" height="22" fill="#ffffff"/>
    <rect x="26" y="26" width="22" height="22" fill="#ffffff"/>
  </g>
  <text x="480" y="280" text-anchor="middle" fill="#ffffff"
        font-family="Segoe UI, Arial, sans-serif" font-size="20">
    Starting Windows Server 2025
  </text>
  <!-- Boot spinner dots -->
  <circle cx="448" cy="320" r="4" fill="#ffffff" opacity="0.95"/>
  <circle cx="464" cy="320" r="4" fill="#ffffff" opacity="0.7"/>
  <circle cx="480" cy="320" r="4" fill="#ffffff" opacity="0.5"/>
  <circle cx="496" cy="320" r="4" fill="#ffffff" opacity="0.35"/>
  <circle cx="512" cy="320" r="4" fill="#ffffff" opacity="0.2"/>
  <text x="480" y="500" text-anchor="middle" fill="#555555"
        font-family="Consolas, monospace" font-size="11">
    RestoreProof demo · ${safe} (VMID ${vmid}) · NICs detached
  </text>
</svg>`;
  return new Blob([svg], { type: "image/svg+xml" });
}
