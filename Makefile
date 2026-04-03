.PHONY: dev build server frontend install clean

# Install all dependencies
install:
	cd frontend && npm install
	cd server && go mod tidy

# Run frontend dev server (port 3000)
frontend:
	cd frontend && npm run dev

# Build and run Go backend (port 8080)
server:
	cd server && go build -o cutedsl-server . && ./cutedsl-server

# Run both in dev mode
dev:
	@echo "Run in two terminals:"
	@echo "  make frontend  (port 3000)"
	@echo "  make server    (port 8080)"

# Build frontend for production
build-frontend:
	cd frontend && npm run build

# Build backend for production
build-server:
	cd server && CGO_ENABLED=1 go build -o cutedsl-server .

# Build everything
build: build-frontend build-server

# Clean build artifacts
clean:
	rm -f server/cutedsl-server server/*.db
	cd frontend && npm run clean 2>/dev/null || true
