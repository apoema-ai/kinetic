FROM ubuntu:26.04

ARG USERNAME=byond
ARG USER_UID=1000
ARG USER_GID=1000
ARG NODE_MAJOR=24

ENV DEBIAN_FRONTEND=noninteractive

# Baseline OS tooling - apt/NodeSource own this, not Homebrew (see docs/adr/0003)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
        build-essential \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Node.js, pinned to the current Active LTS major version
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Byond User: fixed non-root UID/GID, required because Homebrew refuses to run as root.
# ubuntu:26.04 ships a built-in "ubuntu" user/group already at 1000:1000 - drop it first.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupdel ubuntu 2>/dev/null || true \
    && groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} --create-home --shell /bin/bash ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME} \
    && mkdir -p /workspace \
    && chown ${USERNAME}:${USERNAME} /workspace

USER ${USERNAME}

# User-owned npm global prefix, so `npm install -g` (Claude Code) needs no sudo
RUN mkdir -p "$HOME/.npm-global" \
    && npm config set prefix "$HOME/.npm-global" \
    && echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$HOME/.bashrc"

# Homebrew (Linuxbrew) - installed for ad hoc extras, not the baseline toolchain (see docs/adr/0003)
RUN NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    && echo 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' >> "$HOME/.bashrc"

COPY --chown=root:root --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
