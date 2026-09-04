# Baseline tools via apt/NodeSource; Homebrew reserved for extras

Byond installs git, build-essential, and Node.js 24 through apt and the NodeSource repo at image-build time (as root), even though the project's whole reason for including Homebrew is Mac-like package management. Homebrew is installed and left available for whatever the Byond User wants to add later, but it doesn't own the baseline toolchain. apt/NodeSource give a faster, more reliable build for the tools every session needs and keep the pinned Node version reproducible; Homebrew's job is ad hoc extras, not the critical path.
