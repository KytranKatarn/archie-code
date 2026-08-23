VERSION ?= 0.1.0
BINARY_NAME = archie-code
GO ?= go
GOFLAGS = -ldflags "-s -w -X main.version=$(VERSION)"
PLATFORMS = linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64
INSTALL_DIR ?= $(HOME)/.local/bin

.PHONY: build clean all install

build:
	$(GO) build $(GOFLAGS) -o $(BINARY_NAME) .

# Put the built binary on PATH as `archie-code`, the name the README's Quick Start
# and every doc actually invoke. A SYMLINK, not a copy: a later `make build` then
# updates the installed command in place. A copy goes stale silently — which is
# exactly what happened between 2026-07-20 and 2026-08-23, when the installed
# binary predated the Ctrl+K skill palette and nothing said so.
install: build
	@mkdir -p "$(INSTALL_DIR)"
	@ln -sfn "$(CURDIR)/$(BINARY_NAME)" "$(INSTALL_DIR)/$(BINARY_NAME)"
	@echo "linked $(INSTALL_DIR)/$(BINARY_NAME) -> $(CURDIR)/$(BINARY_NAME)"
	@command -v $(BINARY_NAME) >/dev/null 2>&1 \
		|| echo "WARNING: $(INSTALL_DIR) is not on PATH — add it to your shell profile"

all: clean
	@for platform in $(PLATFORMS); do \
		os=$$(echo $$platform | cut -d/ -f1); \
		arch=$$(echo $$platform | cut -d/ -f2); \
		ext=""; \
		if [ "$$os" = "windows" ]; then ext=".exe"; fi; \
		output="dist/$(BINARY_NAME)-$$os-$$arch$$ext"; \
		echo "Building $$output..."; \
		GOOS=$$os GOARCH=$$arch $(GO) build $(GOFLAGS) -o $$output .; \
	done

clean:
	rm -f $(BINARY_NAME)
	rm -rf dist/
