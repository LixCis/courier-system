# AI-Enhanced Courier Delivery System

Flask courier management system with real-time WebSocket tracking, AI order standardization, and AI delivery-proof verification. Student project demonstrating practical AI integration.

## Features

### Core
- **Role-based access** — Admin, Restaurant, Courier dashboards
- **Automatic courier assignment** — distance- and availability-aware
- **Real-time live updates** — Flask-SocketIO over gevent (no polling)
- **In-app notifications** — persisted in DB, pushed live over WebSocket
- **Live maps** — Leaflet + OSRM routing, color-coded per order, live courier position
- **Delivery proof** — photo upload with EXIF GPS extraction and AI analysis

### AI-Powered (all via Ollama)
- **Order standardization** — Qwen2.5 3B enhances free-form order text
- **Delivery-photo analysis** — Moondream multimodal verifies photos
- **AI insights** — per-user analytics generated on startup, cached 24 h

### Security & Reliability
- **CSRF protection** on every form (Flask-WTF)
- **Server-side sessions**, HTTPOnly cookies, SameSite=Lax
- **Database migrations** via Alembic (Flask-Migrate)
- **Automated pytest smoke suite** (22 tests)

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.13, Flask 3, Flask-SocketIO, gevent |
| Database | PostgreSQL 16 (SQLite supported for local dev) |
| Migrations | Alembic / Flask-Migrate |
| AI inference | [Ollama](https://ollama.com) — HTTP API, separate container |
| Text model | `qwen2.5:3b` (~1.9 GB, strong in Czech/EN) |
| Vision model | `moondream` (~1.7 GB, multimodal) |
| Frontend | Jinja2, Tailwind CSS, Leaflet, Socket.IO client |
| Container runtime | Docker Compose (web + postgres + ollama) |
| GPU | Optional NVIDIA passthrough (auto-fallback to CPU) |

## Quick Start — Docker (recommended)

One command spins up web + Postgres + Ollama:

```bash
docker compose up -d --build
```

The `web` container's entrypoint waits for Postgres, creates tables, and auto-seeds demo data on first run.

Pull the AI models into the Ollama container once (~3.6 GB total):

```bash
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull moondream
```

Open **http://localhost:5000** and log in with a demo account.

### GPU acceleration (optional)

Uncomment nothing — `docker-compose.yml` already reserves the NVIDIA GPU. Requirements:

- **Windows:** Docker Desktop on WSL2 with current NVIDIA driver (CUDA on WSL is built in)
- **Linux:** [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

If no GPU is available, comment out the `deploy:` block in the `ollama` service — Ollama silently falls back to CPU.

## Quick Start — Native dev (no Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

pip install -r requirements.txt

# Start Ollama separately
ollama serve
ollama pull qwen2.5:3b
ollama pull moondream

# Optional: Postgres via Docker or local install
# Default falls back to sqlite:///courier.db

flask db upgrade  # or flask init-db on fresh DB
flask seed-db
python app.py
```

## Configuration

All settings via env vars (see `.env`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URI` | `sqlite:///courier.db` | Connection string (use `postgresql://…` in prod) |
| `SECRET_KEY` | `dev-secret-change-in-production` | Flask session signing |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Text model tag |
| `OLLAMA_VISION_MODEL` | `moondream` | Multimodal model tag |
| `OLLAMA_VISION_TIMEOUT` | `180` | Seconds to wait for vision inference |
| `WTF_CSRF_ENABLED` | `true` | Disable only in tests |

Switch text model without rebuilding:

```bash
echo "OLLAMA_MODEL=phi3.5" >> .env
docker compose up -d web
```

## Demo Accounts

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin123` |
| Restaurant | `pizza_palace` | `rest123` |
| Restaurant | `burger_king` | `rest123` |
| Courier | `john_courier` | `courier123` |
| Courier | `jane_courier` | `courier123` |
| Courier | `mike_courier` | `courier123` |

## Project Structure

```
courier-system/
├── app.py                  # Factory — ~65 LoC, no business logic
├── config.py               # Config class (env-driven)
├── extensions.py           # Shared extension instances (socketio, db, login, …)
├── models.py               # SQLAlchemy models
├── docker-compose.yml      # 3 services: web, db, ollama
├── Dockerfile              # ~335 MB final image (no torch/transformers)
├── docker-entrypoint.sh    # DB wait, migrate, seed, start app
├── requirements.txt
├── pytest.ini
├── blueprints/             # Role-based route modules
│   ├── auth.py             # /, /login, /logout, /dashboard
│   ├── admin.py            # /admin/* + /api/admin/*
│   ├── restaurant.py       # /restaurant/* + /api/restaurant/*
│   ├── courier.py          # /courier/* + /api/courier/*
│   ├── notifications.py    # /notifications
│   ├── sockets.py          # @socketio.on event handlers
│   ├── errors.py           # 404/500
│   └── cli.py              # flask init-db, seed-db, seed-enhanced
├── common/
│   ├── decorators.py       # role_required
│   ├── utils.py            # utcnow, allowed_file
│   ├── logging_config.py   # Structured logger setup
│   └── background.py       # Gevent greenlets (AI, auto-transitions)
├── services/
│   ├── llm_service.py      # Ollama HTTP client for text
│   ├── image_analyzer.py   # EXIF/GPS + Ollama multimodal
│   ├── ai_statistics.py    # Per-user insights generator
│   ├── assignment_algorithm.py
│   ├── socketio_service.py
│   ├── geocoding_service.py
│   ├── distance_calculator.py
│   └── order_scheduler.py  # APScheduler auto-assign
├── templates/
│   ├── admin/ restaurant/ courier/
│   ├── components/         # Reusable Jinja macros
│   └── errors/
├── static/js/              # Leaflet + Socket.IO client
├── tests/                  # Pytest smoke suite (22 tests)
└── migrations/             # Alembic version tree
```

## Testing

```bash
pytest                              # native venv
docker compose exec web pytest      # inside container
```

22 smoke tests cover auth flow, role gating, and every major route.

## Migrations

Make a schema change? Generate + apply:

```bash
docker compose exec web python -m flask db migrate -m "add whatever"
docker compose exec web python -m flask db upgrade
```

## How It Works

### Order flow
1. Restaurant creates order → Ollama standardizes description in background
2. Auto-assignment picks nearest available courier
3. Courier marks picked up → system auto-transitions to *in transit* after 3 s (via gevent greenlet, no page reload needed)
4. Courier uploads delivery proof → Moondream analyzes photo + checks match against order description
5. Every state change is emitted over WebSocket to all interested parties

### Real-time architecture
- **Socket.IO rooms**: `admin`, `admin_{id}`, `restaurant_{id}`, `courier_{id}`, `order_{id}`
- On connect: client receives unread notification count + last 20 notifications
- State changes fan out to relevant rooms — no AJAX polling anywhere

### AI pipeline
- LLM + vision model **pre-warmed** in background at startup (first real call is instant)
- 60 s availability cache — no hammering of Ollama
- Graceful degradation — if Ollama is unreachable, AI features disable themselves; the rest of the app keeps working
- Results persisted into the order row, so UI picks them up via a single `ai:description_ready` socket event

## Performance

| Metric | Before refactor | After |
|--------|-----------------|-------|
| Docker image size | ~7 GB (torch + transformers + GGUF) | **335 MB** |
| Model inference | CPU only (~5–10 s / photo) | **GPU ~1 s / photo** (RTX 3050) |
| App startup | Blocks on 2.5 GB model load | Instant — model loads in background |
| `app.py` | 2000 lines monolith | ~65 lines (factory) |
| Database | SQLite (dev only) | Postgres 16 (prod-ready) |
| Schema mgmt | `db.create_all()` | Alembic migrations |

Tested on Ryzen 7 5800H, 16 GB RAM, RTX 3050 Laptop (4 GB VRAM). Both Qwen2.5 3B + Moondream fit in VRAM simultaneously (~3.8 GB used).

## Troubleshooting

**Vision analysis keeps timing out**
Cold start loads the model into VRAM (takes ~30 s). Warm-up runs on app start; if you restarted Ollama, give it a minute. Increase `OLLAMA_VISION_TIMEOUT` if needed.

**"Ollama model not available"**
Make sure you've pulled it: `docker compose exec ollama ollama pull qwen2.5:3b`

**GPU not detected in Ollama container**
Check `docker compose logs ollama` for the GPU discovery line. Windows: update NVIDIA driver + Docker Desktop. Linux: install NVIDIA Container Toolkit.

**Postgres volume contains old data**
`docker compose down -v` wipes all volumes (DB + sessions + uploads). Next `up` re-seeds from scratch.

**CSRF errors on POST**
Every form needs `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. Set `WTF_CSRF_ENABLED=false` only in tests.

## License

MIT — free for educational and personal use.

## Author

Student project — extended across multiple semesters to explore AI integration, real-time systems, and modern deployment.

## Acknowledgments

- **Qwen2.5** by Alibaba — primary text model
- **Moondream** by vikhyat — lightweight multimodal model
- **Ollama** for the HTTP inference server
- **Meta Llama 3.2** (early iterations used llama-cpp-python with GGUF)
