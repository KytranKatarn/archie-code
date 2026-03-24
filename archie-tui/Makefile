VERSION ?= 0.1.0
BINARY_NAME = archie-code
GO ?= go
GOFLAGS = -ldflags "-s -w -X main.version=$(VERSION)"
PLATFORMS = linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64

.PHONY: build clean all

build:
	$(GO) build $(GOFLAGS) -o $(BINARY_NAME) .

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
