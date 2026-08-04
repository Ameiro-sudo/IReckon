# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-03

### Added
- Initial release of IReckon multi-agent autonomous programming system
- 7 specialized AI agents: Scheduler, Executor, Reviewer, Deliverer, Creative, Learner, Tool Manager
- LangGraph-powered workflow engine with conditional routing and loop detection
- Dual-review pipeline (correctness + efficiency/architecture)
- Adaptive model escalation on repeated revision failures
- Provider-agnostic LLM integration via litellm (100+ model support)
- Intelligent capability pool with health checks, circuit breakers, and automatic failover
- Vue 3 frontend with glassmorphism design system
- Real-time WebSocket streaming for task progress, logs, and messages
- Multiple UI themes (catgirl, programmer)
- Multi-layer security: Bandit/semgrep scanning, command filtering, udocker sandbox
- Supply chain firewall with pip/npm blacklist
- Crypto mining detection
- Task snapshot and restore with full state persistence
- Configuration hot-reload via watchdog
- Idle-time self-learning from GitHub Trending
- Self-improvement system (analyze → modify → PR)
- Windows executable build via PyInstaller
- Android APK build via Buildozer
- REST API with OpenAPI documentation
- WebSocket API for real-time communication
- MIT License
