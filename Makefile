.PHONY: dev watch build server frontend inference install clean deploy test test-server test-inference bench-precision pregen-latents diffusion-frontier-preflight

# Install all dependencies
install:
	cd frontend && bun install
	cd server && go mod tidy
	cd inference && pip install -r requirements.txt

# Run frontend dev server with Turbopack (port 3000)
frontend:
	cd frontend && bun run dev

# Run frontend in watch mode (alias for dev)
watch:
	cd frontend && bun run watch

# Build and run Go backend (port 8080)
server:
	cd server && go build -o cutedsl-server . && ./cutedsl-server

# Run CuteDSL inference server (port 8100)
inference:
	cd inference && python server.py

# Run inference with NVFP4 quantization (RTX 5090)
inference-nvfp4:
	cd inference && ENABLE_NVFP4=1 python server.py

# Benchmark precision configs, write inference/autotune/<gpu_slug>.json
bench-precision:
	cd inference && python precision_bench.py

# Warm LatentCache with single-word latents (resumable, Ctrl-C safe)
pregen-latents:
	cd inference && python pregen_latents.py

# No-download feasibility report for the public diffusion model frontier.
diffusion-frontier-preflight:
	python scripts/diffusion_frontier_eval.py --preflight --models zimage-turbo flux-schnell proteus-v0.2 proteus-v0.4 realvisxl-v4 krea2-turbo

# Run all in dev mode
dev:
	@echo "Run in three terminals:"
	@echo "  make inference  (port 8100 - AI models)"
	@echo "  make server     (port 8080 - Go API)"
	@echo "  make frontend   (port 3000 - Next.js + Turbopack)"

# Build frontend for production (minified, compressed)
build-frontend:
	cd frontend && bun run build

# Build backend for production
build-server:
	cd server && CGO_ENABLED=1 go build -o cutedsl-server .

# Build everything
build: build-frontend build-server

# Deploy to appstatic.app.nz/cutedsl
deploy:
	./deploy.sh

# Run all tests
test: test-server test-inference

# Test Go API server (requires postgres cutedsl_test database)
test-server:
	cd server && go test -v -count=1 ./...

# Test inference server (requires server running on :8100)
test-inference:
	cd inference && python -m pytest test_server.py -v

# Clean build artifacts
clean:
	rm -f server/cutedsl-server server/*.db
	cd frontend && rm -rf .next out node_modules/.cache
