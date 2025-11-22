# Courier System MVP

A functional web-based courier management system built with Python, Flask, and Tailwind CSS. Features role-based authentication, automatic order assignment, and comprehensive delivery tracking.

## Features

### Role-Based Access Control
- **Admin**: Full system oversight, user management, and order monitoring
- **Restaurant**: Order creation and tracking
- **Courier**: Delivery management and status updates

### Core Functionality
- Secure authentication with Flask-Login and password hashing
- Automatic order assignment algorithm (easily replaceable with AI)
- Real-time order tracking and status updates
- Comprehensive delivery logging for future AI analysis
- Responsive UI with Tailwind CSS

### Security
- Password hashing with Werkzeug
- Session management with Flask-Login
- Role-based route protection
- CSRF protection

## Tech Stack

- **Backend**: Python 3.x, Flask 3.0
- **Database**: SQLAlchemy with SQLite
- **Authentication**: Flask-Login
- **Frontend**: Jinja2 templates, Tailwind CSS (CDN)
- **Password Security**: Werkzeug

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Setup Instructions

1. **Clone or navigate to the project directory**
   ```bash
   cd courier-system
   ```

2. **Create and activate virtual environment** (if not already done)
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # Linux/Mac
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize the database**
   ```bash
   flask init-db
   ```

5. **Seed the database with demo data**
   ```bash
   flask seed-db
   ```

6. **Run the application**
   ```bash
   python app.py
   ```

7. **Access the application**
   Open your browser and navigate to: `http://localhost:5000`

## Demo Accounts

After seeding the database, use these credentials to log in:

| Role | Username | Password |
|------|----------|----------|
| Admin | admin | admin123 |
| Restaurant | pizza_palace | rest123 |
| Restaurant | burger_king | rest123 |
| Courier | john_courier | courier123 |
| Courier | jane_courier | courier123 |
| Courier | mike_courier | courier123 |

## Project Structure

```
courier-system/
├── app.py                          # Main Flask application
├── config.py                       # Configuration settings
├── models.py                       # Database models
├── requirements.txt                # Python dependencies
├── .env                           # Environment variables
├── services/
│   └── assignment_algorithm.py    # Modular order assignment logic
├── templates/
│   ├── base.html                  # Base template
│   ├── login.html                 # Login page
│   ├── admin/                     # Admin templates
│   │   ├── dashboard.html
│   │   ├── orders.html
│   │   └── users.html
│   ├── restaurant/                # Restaurant templates
│   │   ├── dashboard.html
│   │   ├── create_order.html
│   │   └── view_order.html
│   ├── courier/                   # Courier templates
│   │   ├── dashboard.html
│   │   └── view_order.html
│   └── errors/                    # Error pages
│       ├── 404.html
│       └── 500.html
└── README.md
```

## Database Models

### User
- Stores user information with role differentiation (admin, restaurant, courier)
- Password hashing for security
- Courier-specific fields (availability, location)

### Order
- Tracks delivery orders from creation to completion
- Links restaurants and couriers
- Comprehensive timestamp tracking for AI analysis

### DeliveryLog
- Logs all order events and status changes
- Captures timing data for route optimization
- Flexible JSON metadata field for future AI features

## Assignment Algorithm

The system uses a modular assignment strategy pattern located in `services/assignment_algorithm.py`:

### Current Strategies
1. **FirstAvailableStrategy** (default): Assigns to the first available courier
2. **LeastLoadedStrategy**: Assigns to courier with fewest active orders

### Replacing with AI
The modular design allows easy replacement:

```python
# In services/assignment_algorithm.py
class AIBasedStrategy(AssignmentStrategy):
    def assign_courier(self, order):
        # Your AI logic here
        # Consider: location, traffic, courier rating, etc.
        return optimal_courier

# Update the service
assignment_service = AssignmentService(AIBasedStrategy())
```

## Order Status Flow

1. **pending** → Order created, waiting for courier
2. **assigned** → Courier automatically assigned
3. **picked_up** → Courier picked up from restaurant
4. **in_transit** → Order on the way to customer
5. **delivered** → Order completed

## Delivery Logging

All order events are logged to the `delivery_logs` table with:
- Event type and description
- Timestamps (critical for AI route optimization)
- User information (who performed the action)
- Location data (for future GPS integration)
- Flexible metadata field (JSON)

## Future Enhancements

### AI Integration Points
1. **Route Optimization**: Use delivery logs to train ML models
2. **Demand Prediction**: Analyze order patterns
3. **Courier Assignment**: ML-based assignment considering traffic, location, ratings
4. **Delivery Time Estimation**: Predict accurate delivery times

### Suggested Features
- Real-time GPS tracking
- Push notifications
- Customer rating system
- Advanced analytics dashboard
- Payment integration
- Mobile app

## Development

### Adding New Features

1. **New Routes**: Add to `app.py`
2. **Database Changes**: Update `models.py` and migrate
3. **New Templates**: Add to appropriate folder in `templates/`
4. **Assignment Logic**: Modify `services/assignment_algorithm.py`

### Running in Production

1. Change `SECRET_KEY` in `.env` to a secure random string
2. Use a production database (PostgreSQL recommended)
3. Set `FLASK_ENV=production`
4. Use a production WSGI server (Gunicorn, uWSGI)
5. Set up HTTPS
6. Configure proper session security

## License

MIT License - Feel free to use for your projects

## Support

For issues or questions, please create an issue in the repository.
