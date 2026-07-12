# Purpose: Forum-oriented announcement draft for RestoreProof
# Author: Doug Hesseltine
# Created: 2026-07-12
# Version: 1.0.0

# RestoreProof — forum announcement draft

**Title:** RestoreProof: automated PBS restore drills with console screenshots (Docker / LXC)

---

Hi all —

I built a small open-source appliance called **RestoreProof** for people who want more confidence than “backup job finished OK.”

### What it does

- Connects to your Proxmox host/cluster via **API token**
- Uses a dedicated **SSH key** only for QEMU console screenshots
- On a schedule (or Run now): restores the **latest PBS backup** to a throwaway VMID in a reserved pool (default 9000–9099), **detaches NICs**, boots, waits ~1 minute, captures evidence, destroys the test guest, and emails you
- **Original VMs stay online** — this is not a destructive DR overwrite
- LXC containers get a structured “running/uptime” proof (no VGA framebuffer)
- Admin UI: guests list with excludes + per-VM schedule overrides, run history with screenshots, SMTP presets (M365, SMTP2GO, Zoho, etc.), TOTP 2FA

### Deploy

Ubuntu LXC + Docker Compose (nesting required). Details in the repo README / INSTALL-LXC.md.

GitHub: https://github.com/hesseltined/RestoreProof  
License: Apache-2.0 (community edition)

Feedback welcome — especially around PBS edge cases and screenshot reliability across GPU types.

---

Doug Hesseltine
