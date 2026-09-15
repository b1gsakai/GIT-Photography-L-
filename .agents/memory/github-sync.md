---
name: GitHub sync
description: Repository synchronization when local git remotes cannot authenticate.
---

Use the attached GitHub connector's authenticated proxy for repository writes when the workspace HTTPS remote rejects pushes for missing credentials.

**Why:** The local remote may be readable but still reject HTTPS pushes, while the Replit-managed GitHub connection can publish the validated tree without exposing credentials.

**How to apply:** Verify the remote branch first, publish only the intended tracked files through the connector, and keep generated runtime data ignored.