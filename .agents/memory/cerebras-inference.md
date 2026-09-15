---
name: Cerebras inference access
description: Cerebras API behavior when model listing and inference permissions differ.
---

A Cerebras secret may authenticate successfully for model discovery while chat-completions requests are rejected with HTTP 402. Treat model discovery as a credential check, not proof that inference is enabled, and keep the application's local summary fallback.

**Why:** The gallery must continue serving ratings and comments even when the external inference provider refuses a request.

**How to apply:** Log only the provider status, do not expose the secret, and preserve a useful local result for every summary request.