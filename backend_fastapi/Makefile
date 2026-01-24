.PHONY: dev stop worker api temporal logs clean help

# 默认目标
help:
	@echo "可用命令："
	@echo "  make dev      - 启动所有服务（Temporal + Worker + FastAPI）"
	@echo "  make stop     - 停止所有服务"
	@echo "  make temporal - 仅启动 Temporal Server"
	@echo "  make worker   - 仅启动 Worker"
	@echo "  make api      - 仅启动 FastAPI"
	@echo "  make logs     - 查看后台服务日志"
	@echo "  make clean    - 清理日志文件"

# 一键启动所有服务
dev:
	@echo "🚀 启动 Temporal Server..."
	@temporal server start-dev > /tmp/temporal.log 2>&1 &
	@sleep 3
	@echo "⚙️  启动 Worker..."
	@.venv/bin/python -m workflow.run_worker > /tmp/worker.log 2>&1 &
	@sleep 1
	@echo "🌐 启动 FastAPI（Ctrl+C 停止所有服务）..."
	@.venv/bin/uvicorn app.main:app --reload --port 8000 || make stop

# 停止所有服务
stop:
	@echo "停止服务..."
	@pkill -f "temporal server" 2>/dev/null || true
	@pkill -f "workflow.run_worker" 2>/dev/null || true
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@echo "✅ 所有服务已停止"

# 仅启动 Temporal
temporal:
	@echo "🚀 启动 Temporal Server..."
	@temporal server start-dev

# 仅启动 Worker
worker:
	@echo "⚙️  启动 Worker..."
	@.venv/bin/python -m workflow.run_worker

# 仅启动 FastAPI
api:
	@echo "🌐 启动 FastAPI..."
	@.venv/bin/uvicorn app.main:app --reload --port 8000

# 查看日志
logs:
	@echo "=== Temporal 日志 ==="
	@tail -20 /tmp/temporal.log 2>/dev/null || echo "(无日志)"
	@echo ""
	@echo "=== Worker 日志 ==="
	@tail -20 /tmp/worker.log 2>/dev/null || echo "(无日志)"

# 清理日志
clean:
	@rm -f /tmp/temporal.log /tmp/worker.log
	@echo "✅ 日志已清理"
