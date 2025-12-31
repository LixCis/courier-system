# AI-Enhanced Courier Delivery System

Flask-based courier management system with AI-powered order processing and delivery verification. Student project demonstrating practical AI integration in web applications.

## Features

### Core Functionality
- **Role-Based Access** - Admin, Restaurant, and Courier dashboards
- **Automatic Courier Assignment** - Intelligent assignment based on availability and location
- **Real-time Order Tracking** - Live status updates and delivery monitoring
- **Delivery Proof System** - Photo upload with GPS verification and image quality checks

### AI-Powered Features
- **Order Standardization** - Llama 3.2-3B automatically formats order descriptions
- **Photo Analysis** - BLIP vision model verifies delivery photos and detects fraud
- **AI Insights** - Personalized performance analytics for all user roles
- **Background Processing** - Non-blocking AI with thread-safe model access

## Tech Stack

- **Backend**: Python 3.8+, Flask 3.0, SQLAlchemy (SQLite)
- **AI Models**: Llama 3.2-3B (GGUF), BLIP (vision-language)
- **Frontend**: Jinja2, Tailwind CSS, JavaScript

## Quick Start

### Prerequisites

1. **Python 3.8+** - [Download](https://python.org)
2. **Visual C++ Build Tools** (Windows) - [Download](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
   - Select "Desktop development with C++" during installation
3. **Llama Model** - Download and place in `models/` folder:
   - Model: [Llama-3.2-3B-Instruct-Q6_K.gguf](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q6_K.gguf) (~2.5GB)
   - Rename to: `llama-3.2-3b.gguf`
   - Location: `models/llama-3.2-3b.gguf`

### Installation

**Windows - One Click:**
```bash
run.bat
```

**Manual Install:**
```bash
# 1. Create & activate virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

# 2. Install dependencies (~5-10 minutes first time)
pip install -r requirements.txt

# 3. Setup database
flask init-db
flask seed-db

# 4. Run
python app.py
```

Access at: **http://localhost:5000**

## Demo Accounts

| Role | Username | Password | Description |
|------|----------|----------|-------------|
| **Admin** | admin | admin123 | System administration |
| **Restaurant** | pizza_palace | rest123 | Pizza Palace Ostrava |
| **Restaurant** | burger_king | rest123 | Burger Kingdom Stodolní |
| **Courier** | john_courier | courier123 | John Doe |
| **Courier** | jane_courier | courier123 | Jane Smith |
| **Courier** | mike_courier | courier123 | Mike Johnson |

## AI Features

### 1. Order Description Standardization
- **Model**: Llama 3.2-3B Instruct (3B parameters, Q6_K quantization)
- **Example**: "dvě pizzy margherita jedna bez sýra" → "2x pizza Margherita (1x bez sýra)"
- **Processing**: Background threads, non-blocking UI
- **Performance**: 5-10s first load, <1s subsequent calls
- **Size**: ~2.5GB (Q6_K offers excellent quality/size balance)

### 2. Delivery Photo Analysis
- **Model**: BLIP (Salesforce vision-language)
- **Features**:
  - Automatic photo captioning
  - Legitimacy detection (0-100% confidence)
  - Suspicious photo flagging
  - GPS coordinate extraction from EXIF
  - Image quality validation
  - Device metadata extraction

### 3. AI Insights & Analytics
- **Personalized summaries** for couriers, restaurants, and admins
- **24-hour caching** to reduce model calls
- **Asynchronous loading** - pages render instantly, AI loads in background
- **Performance metrics** and actionable recommendations

## Project Structure

```
courier-system/
├── app.py                      # Main Flask application
├── models.py                   # Database models (User, Order, etc.)
├── config.py                   # Configuration
├── requirements.txt            # Dependencies
├── setup.py                    # Automated setup wizard
├── run.bat                     # Windows quick start
├── models/
│   └── llama-3.2-3b.gguf      # Llama 3.2-3B Q6_K (~2.5GB) - not in Git
├── services/
│   ├── llm_service.py         # Thread-safe LLM wrapper
│   ├── image_analyzer.py      # Vision AI + GPS/quality checks
│   ├── ai_statistics.py       # AI insights generation
│   └── assignment_algorithm.py # Courier assignment
├── templates/
│   ├── admin/                 # Admin dashboard, analytics, user mgmt
│   ├── restaurant/            # Order creation, tracking
│   ├── courier/               # Delivery management
│   └── components/            # Reusable UI components
└── static/
    ├── uploads/               # Delivery proof photos
    └── js/                    # Frontend scripts
```

## How It Works

### Order Flow
1. **Restaurant** creates order with customer details
2. **System** assigns available courier automatically
3. **Courier** picks up order → Auto-transitions to "in transit" after 3s
4. **Courier** delivers and uploads proof photo
5. **AI** analyzes photo for legitimacy

### AI Processing
- **Order descriptions**: Enhanced in background on order creation
- **Photo analysis**: Triggered on delivery proof upload
- **Insights**: Pre-generated on startup, cached for 24h

### Thread Safety
- Models use locks to prevent concurrent access
- Background threads for non-blocking operations
- Connection pool management to prevent timeouts

## Database Models

- **User** - Role-based auth (admin/restaurant/courier), location tracking
- **Order** - Full delivery lifecycle with timestamps
- **DeliveryLog** - Event logging for all order actions
- **SavedCustomer** - Frequent delivery addresses
- **AIStatisticsSummary** - Cached AI-generated insights

## Performance Notes

- **RAM**: ~4GB recommended (2.5GB model + overhead)
- **Disk space**: ~3.5GB total (Llama 2.5GB + BLIP 990MB)
- **First run**: Model loading ~5-10 seconds
- **Subsequent**: <1 second per AI request
- **Vision model**: Downloads automatically on first use (~990MB)
- **CPU-only**: GPU acceleration not implemented

## Development

**Reset database:**
```bash
flask init-db && flask seed-db
```

**Clear AI cache:**
Admin panel → "Force Clear AI Cache" button

**Add test orders:**
Seed data includes 100+ historical orders for testing analytics

## Troubleshooting

**"Llama model not found"**
- Download: [Llama-3.2-3B-Instruct-Q6_K.gguf](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q6_K.gguf) (~2.5GB)
- Rename to `llama-3.2-3b.gguf`
- Place in `models/` folder

**"llama-cpp-python compilation failed"**
- Install Visual C++ Build Tools (Windows)
- Install `build-essential` (Linux)

**"Out of memory"**
- Close other applications
- AI models need ~4GB RAM

**"Connection pool timeout"**
- Restart application
- Reduced by thread-safe model access

## Known Limitations

- **Language**: BLIP is English-focused (Czech analysis less accurate)
- **Performance**: CPU-only (no GPU acceleration)
- **Scalability**: SQLite database (use PostgreSQL for production)

## Future Enhancements

- GPU acceleration for faster inference
- Real-time GPS tracking
- Push notifications
- Advanced route optimization ML
- Mobile app
- Multi-language vision support

## Production Deployment

**⚠ Not recommended for production** - This is an educational project.

For production use:
- Use PostgreSQL instead of SQLite
- Implement GPU acceleration
- Add rate limiting
- Use production WSGI server (Gunicorn)
- Configure HTTPS
- Set strong SECRET_KEY

## License

MIT License - Free for educational and personal use

## Author

Student project - Semester work demonstrating AI integration in web applications

## Acknowledgments

- **Llama 3.2-3B Instruct** by Meta AI
- **Q6_K Quantization** by @bartowski on HuggingFace
- **BLIP** by Salesforce Research
- **llama-cpp-python** for efficient CPU inference
- **Transformers** by HuggingFace
