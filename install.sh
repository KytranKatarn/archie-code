#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-latest}"
REPO="KytranKatarn/archie-code"
INSTALL_DIR="${HOME}/.local/bin"

echo ""
echo "  A.R.C.H.I.E. Code CLI Installer"
echo "  ================================"
echo ""

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    arm64)   ARCH="arm64" ;;
    *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

echo "Detected: $OS/$ARCH"

echo ""
echo "Step 1: Installing ARCHIE Engine (Python)..."
if command -v pip3 &>/dev/null; then
    pip3 install archie-engine 2>/dev/null || pip3 install --user archie-engine || echo "pip install failed — install manually"
else
    echo "WARNING: pip3 not found. Install Python 3.11+ and run: pip install archie-engine"
fi

echo ""
echo "Step 2: Downloading ARCHIE Code TUI..."
mkdir -p "$INSTALL_DIR"

if [ "$VERSION" = "latest" ]; then
    DOWNLOAD_URL="https://github.com/$REPO/releases/latest/download/archie-code-$OS-$ARCH"
else
    DOWNLOAD_URL="https://github.com/$REPO/releases/download/v$VERSION/archie-code-$OS-$ARCH"
fi

if command -v curl &>/dev/null; then
    curl -sL "$DOWNLOAD_URL" -o "$INSTALL_DIR/archie-code" 2>/dev/null && chmod +x "$INSTALL_DIR/archie-code" || {
        echo "Download failed — binary not yet published. Build from source:"
        echo "  cd archie-tui && go build -o archie-code ."
    }
fi

echo ""
echo "Done! Usage:"
echo "  1. Start engine:  python -m archie_engine"
echo "  2. Launch TUI:    archie-code"
echo ""
echo "Ensure $INSTALL_DIR is in your PATH."
