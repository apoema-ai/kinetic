# Clean Claude Code install via in-container login

Byond could bind-mount the host's `~/.claude` directory to inherit an already-logged-in Claude Code session for free. Instead, the entrypoint leaves Claude Code unauthenticated and expects the user to run `claude login` inside the container on first use, with the resulting session persisted on the Home Volume. This keeps Byond's identity fully separate from the host's — deliberate isolation over convenience — so credentials and account-specific state never leak between the two.
