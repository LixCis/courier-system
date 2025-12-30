"""
AI Statistics Service - Generates AI-powered insights with caching
"""
from datetime import datetime, timedelta
from models import db, Order, User, DeliveryLog, AIStatisticsSummary
from services.llm_service import llm_service  # Use global instance for thread safety
from sqlalchemy import func


def get_or_generate_ai_summary(user_id=None, summary_type='courier_daily', force_refresh=False):
    """
    Get cached AI summary or generate new one if expired/missing

    Args:
        user_id: User ID (None for admin summaries)
        summary_type: Type of summary ('courier_daily', 'restaurant_weekly', 'admin_system')
        force_refresh: Force regenerate even if cache is valid

    Returns:
        dict with 'summary_text', 'generated_at', 'is_cached'
    """
    # Check cache if not force refresh
    if not force_refresh:
        cached = AIStatisticsSummary.query.filter_by(
            user_id=user_id,
            summary_type=summary_type
        ).first()

        # Is cache valid? (< 24 hours)
        if cached and (datetime.utcnow() - cached.generated_at) < timedelta(hours=24):
            return {
                'summary_text': cached.summary_text,
                'generated_at': cached.generated_at,
                'is_cached': True,
                'stats_data': cached.stats_data
            }

    # Cache doesn't exist or is expired -> generate new
    if summary_type == 'courier_daily':
        stats_data = calculate_courier_stats(user_id)
        ai_summary = generate_courier_ai_summary(stats_data)
    elif summary_type == 'restaurant_weekly':
        stats_data = calculate_restaurant_stats(user_id)
        ai_summary = generate_restaurant_ai_summary(stats_data)
    elif summary_type == 'admin_system':
        stats_data = calculate_admin_stats()
        ai_summary = generate_admin_ai_summary(stats_data)
    else:
        return None

    # Save to cache
    save_ai_summary_to_cache(user_id, summary_type, ai_summary, stats_data)

    return {
        'summary_text': ai_summary,
        'generated_at': datetime.utcnow(),
        'is_cached': False,
        'stats_data': stats_data
    }


def calculate_courier_stats(courier_id):
    """Calculate courier statistics for AI summary"""
    courier = User.query.get(courier_id)
    if not courier or courier.role != 'courier':
        return None

    # Today's orders
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_orders = Order.query.filter_by(courier_id=courier_id, status='delivered').filter(
        Order.delivered_at >= today_start
    ).all()

    # This week's orders
    week_start = today_start - timedelta(days=today_start.weekday())
    week_orders = Order.query.filter_by(courier_id=courier_id, status='delivered').filter(
        Order.delivered_at >= week_start
    ).all()

    # All-time stats
    all_orders = Order.query.filter_by(courier_id=courier_id, status='delivered').all()

    # Calculate metrics
    stats = {
        'courier_name': courier.full_name,
        'today': {
            'total_deliveries': len(today_orders),
            'total_value': sum(o.order_value for o in today_orders),
            'avg_delivery_time': _calculate_avg_delivery_time(today_orders)
        },
        'week': {
            'total_deliveries': len(week_orders),
            'total_value': sum(o.order_value for o in week_orders),
            'avg_delivery_time': _calculate_avg_delivery_time(week_orders)
        },
        'all_time': {
            'total_deliveries': courier.successful_deliveries,
            'rejected_orders': courier.rejected_orders or 0,
            'success_rate': _calculate_success_rate(courier)
        },
        'top_areas': _get_top_delivery_areas(all_orders, limit=3),
        'vehicle_type': courier.vehicle_type
    }

    return stats


def calculate_restaurant_stats(restaurant_id):
    """Calculate restaurant statistics for AI summary"""
    restaurant = User.query.get(restaurant_id)
    if not restaurant or restaurant.role != 'restaurant':
        return None

    # This week's orders
    week_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.utcnow().weekday())
    week_orders = Order.query.filter_by(restaurant_id=restaurant_id).filter(
        Order.created_at >= week_start
    ).all()

    # This month's orders
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_orders = Order.query.filter_by(restaurant_id=restaurant_id).filter(
        Order.created_at >= month_start
    ).all()

    # All orders
    all_orders = Order.query.filter_by(restaurant_id=restaurant_id).all()
    delivered_orders = [o for o in all_orders if o.status == 'delivered']

    stats = {
        'restaurant_name': restaurant.full_name,
        'week': {
            'total_orders': len(week_orders),
            'delivered': len([o for o in week_orders if o.status == 'delivered']),
            'total_value': sum(o.order_value for o in week_orders),
            'avg_order_value': sum(o.order_value for o in week_orders) / len(week_orders) if week_orders else 0
        },
        'month': {
            'total_orders': len(month_orders),
            'total_value': sum(o.order_value for o in month_orders)
        },
        'all_time': {
            'total_orders': len(all_orders),
            'delivered': len(delivered_orders),
            'cancelled': len([o for o in all_orders if o.status == 'cancelled'])
        },
        'top_delivery_areas': _get_top_delivery_areas(delivered_orders, limit=5),
        'peak_hours': _get_peak_hours(all_orders)
    }

    return stats


def calculate_admin_stats():
    """Calculate system-wide statistics for admin AI summary"""
    # Today's metrics
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_orders = Order.query.filter(Order.created_at >= today_start).all()

    # Active users
    active_couriers = User.query.filter_by(role='courier', is_available=True, is_active=True).count()
    total_couriers = User.query.filter_by(role='courier', is_active=True).count()
    total_restaurants = User.query.filter_by(role='restaurant', is_active=True).count()

    # System performance
    all_orders = Order.query.all()
    delivered_orders = [o for o in all_orders if o.status == 'delivered']

    stats = {
        'today': {
            'total_orders': len(today_orders),
            'pending': len([o for o in today_orders if o.status == 'pending']),
            'active': len([o for o in today_orders if o.status in ['assigned', 'picked_up', 'in_transit']]),
            'delivered': len([o for o in today_orders if o.status == 'delivered'])
        },
        'system': {
            'active_couriers': active_couriers,
            'total_couriers': total_couriers,
            'total_restaurants': total_restaurants,
            'courier_utilization': (active_couriers / total_couriers * 100) if total_couriers > 0 else 0
        },
        'performance': {
            'total_deliveries': len(delivered_orders),
            'avg_delivery_time': _calculate_avg_delivery_time(delivered_orders),
            'success_rate': (len(delivered_orders) / len(all_orders) * 100) if all_orders else 0
        },
        'top_performing_couriers': _get_top_couriers(limit=3),
        'busiest_restaurants': _get_busiest_restaurants(limit=3)
    }

    return stats


def generate_courier_ai_summary(stats):
    """Generate AI summary for courier using LLM (uses global thread-safe instance)"""
    if not stats:
        return "Statistics not available."

    if not llm_service.is_available():
        return "AI summary temporarily unavailable. AI model is not loaded."

    prompt = f"""Task: Create a personalized summary for courier {stats['courier_name']}.

YOUR STATISTICS:
Today: {stats['today']['total_deliveries']} deliveries, avg time {stats['today']['avg_delivery_time']} min, value {stats['today']['total_value']:.0f} CZK
This week: {stats['week']['total_deliveries']} deliveries, avg time {stats['week']['avg_delivery_time']} min
Total: {stats['all_time']['total_deliveries']} successful, {stats['all_time']['rejected_orders']} rejected (success rate {stats['all_time']['success_rate']:.1f}%)
Your most frequent areas: {', '.join(stats['top_areas']) if stats['top_areas'] else 'none yet'}
Vehicle: {stats['vehicle_type']}

RULES:
- Speak directly to the user (use "you", "your")
- Analyze ONLY their numbers (no comparison with others)
- If 0 deliveries today, say "You haven't delivered anything today yet"
- Give recommendations directly for them (e.g., "Try optimizing routes in Poruba")
- If little data, acknowledge it ("You have limited data for detailed analysis yet")
- 3-5 sentences, motivating tone, use a few emojis
- Output MUST be in English

Personalized summary:"""

    try:
        output = llm_service.llm(
            prompt,
            max_tokens=300,
            temperature=0.2,  # Nízká pro lepší následování promptu
            top_p=0.85,
            repeat_penalty=1.15,
            stop=["\n\n\n", "YOUR STATISTICS", "RULES", "Task:"],
            echo=False
        )
        summary = output['choices'][0]['text'].strip()
        return summary if summary else "AI summary generation failed."
    except Exception as e:
        print(f"Error generating courier AI summary: {e}")
        return f"Chyba při generování AI shrnutí: {str(e)}"


def generate_restaurant_ai_summary(stats):
    """Generate AI summary for restaurant using LLM (uses global thread-safe instance)"""
    if not stats:
        return "Statistics not available."

    if not llm_service.is_available():
        return "AI summary temporarily unavailable. AI model is not loaded."

    prompt = f"""Task: Create business insights for restaurant {stats['restaurant_name']}.

YOUR BUSINESS DATA:
This week: {stats['week']['total_orders']} orders ({stats['week']['delivered']} delivered), revenue {stats['week']['total_value']:.0f} CZK, average {stats['week']['avg_order_value']:.0f} CZK/order
This month: {stats['month']['total_orders']} orders, revenue {stats['month']['total_value']:.0f} CZK
Total history: {stats['all_time']['total_orders']} orders ({stats['all_time']['delivered']} delivered, {stats['all_time']['cancelled']} cancelled)
Your most requested areas: {', '.join(stats['top_delivery_areas']) if stats['top_delivery_areas'] else 'none yet'}
Your peak hours: {stats['peak_hours']}

RULES:
- Speak directly to the restaurant (use "you", "your")
- Analyze ONLY their numbers (no "market trends" or "competition")
- Compare their data (week vs month: growing? declining? stable?)
- Give recommendations directly from their data (e.g., "High cancellation rate - try reducing preparation time")
- If little data, acknowledge it ("You have limited data for detailed analysis yet")
- 4-6 sentences, professional but friendly tone, use a few emojis
- Output MUST be in English

Your business insights:"""

    try:
        output = llm_service.llm(
            prompt,
            max_tokens=350,
            temperature=0.2,  # Nízká pro lepší následování promptu
            top_p=0.85,
            repeat_penalty=1.15,
            stop=["\n\n\n", "YOUR BUSINESS", "RULES", "Task:"],
            echo=False
        )
        summary = output['choices'][0]['text'].strip()
        return summary if summary else "AI summary generation failed."
    except Exception as e:
        print(f"Error generating restaurant AI summary: {e}")
        return f"Chyba při generování AI shrnutí: {str(e)}"


def generate_admin_ai_summary(stats):
    """Generate AI summary for admin using LLM (uses global thread-safe instance)"""
    if not stats:
        return "Statistics not available."

    if not llm_service.is_available():
        return "AI summary temporarily unavailable. AI model is not loaded."

    prompt = f"""Task: Create a system overview for the administrator.

YOUR SYSTEM DATA:
Today: {stats['today']['total_orders']} orders ({stats['today']['pending']} pending, {stats['today']['active']} active, {stats['today']['delivered']} completed)
Your couriers: {stats['system']['active_couriers']} active / {stats['system']['total_couriers']} total (utilization {stats['system']['courier_utilization']:.1f}%)
Your restaurants: {stats['system']['total_restaurants']} active
Overall performance: {stats['performance']['total_deliveries']} delivered, average {stats['performance']['avg_delivery_time']} min, success rate {stats['performance']['success_rate']:.1f}%
Top couriers: {', '.join(stats['top_performing_couriers']) if stats['top_performing_couriers'] else 'none yet'}
Busiest restaurants: {', '.join(stats['busiest_restaurants']) if stats['busiest_restaurants'] else 'none yet'}

RULES:
- Speak directly to the admin (use "you", "your system")
- Analyze ONLY these real numbers (no assumptions about "ideal state")
- Identify problems if visible in data (e.g., "You have 8 pending orders but only 1 active courier")
- Give recommendations directly from data (e.g., "Low courier utilization - consider adding more restaurants")
- If everything is fine, say "System is running smoothly"
- 5-7 sentences, analytical but direct tone, use emojis occasionally
- Output MUST be in English

Your system analysis:"""

    try:
        output = llm_service.llm(
            prompt,
            max_tokens=400,
            temperature=0.2,  # Nízká pro lepší následování promptu
            top_p=0.85,
            repeat_penalty=1.15,
            stop=["\n\n\n", "YOUR SYSTEM", "RULES", "Task:"],
            echo=False
        )
        summary = output['choices'][0]['text'].strip()
        return summary if summary else "AI summary generation failed."
    except Exception as e:
        print(f"Error generating admin AI summary: {e}")
        return f"Chyba při generování AI shrnutí: {str(e)}"


def save_ai_summary_to_cache(user_id, summary_type, summary_text, stats_data):
    """Save or update AI summary in cache"""
    # Check if exists
    existing = AIStatisticsSummary.query.filter_by(
        user_id=user_id,
        summary_type=summary_type
    ).first()

    if existing:
        # Update existing
        existing.summary_text = summary_text
        existing.generated_at = datetime.utcnow()
        existing.stats_data = stats_data
    else:
        # Create new
        new_summary = AIStatisticsSummary(
            user_id=user_id,
            summary_type=summary_type,
            summary_text=summary_text,
            stats_data=stats_data
        )
        db.session.add(new_summary)

    db.session.commit()
    print(f"AI summary cached: {summary_type} for user {user_id}")


def clear_all_ai_cache():
    """Clear all AI summary cache (for admin force refresh)"""
    try:
        deleted_count = AIStatisticsSummary.query.delete()
        db.session.commit()
        print(f"Cleared {deleted_count} AI summary cache entries")
        return deleted_count
    except Exception as e:
        db.session.rollback()
        print(f"Error clearing AI cache: {e}")
        return 0


# Helper functions
def _calculate_avg_delivery_time(orders):
    """Calculate average delivery time in minutes"""
    if not orders:
        return 0

    times = []
    for order in orders:
        if order.created_at and order.delivered_at:
            delta = order.delivered_at - order.created_at
            times.append(delta.total_seconds() / 60)

    return round(sum(times) / len(times)) if times else 0


def _calculate_success_rate(courier):
    """Calculate courier success rate"""
    total = courier.total_deliveries or 0
    successful = courier.successful_deliveries or 0

    if total == 0:
        return 100.0

    return (successful / total) * 100


def _get_top_delivery_areas(orders, limit=3):
    """Get top delivery areas from orders"""
    if not orders:
        return []

    # Count deliveries by area (simplified - using first part of address)
    area_counts = {}
    for order in orders:
        if order.delivery_address:
            # Extract first part (street or area name)
            area = order.delivery_address.split(',')[0].strip()
            area_counts[area] = area_counts.get(area, 0) + 1

    # Sort and get top areas
    top_areas = sorted(area_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [area[0] for area in top_areas]


def _get_peak_hours(orders):
    """Get peak hours from orders"""
    if not orders:
        return "N/A"

    hour_counts = {}
    for order in orders:
        if order.created_at:
            hour = order.created_at.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

    if not hour_counts:
        return "N/A"

    peak_hour = max(hour_counts.items(), key=lambda x: x[1])[0]
    return f"{peak_hour}:00-{peak_hour+1}:00"


def _get_top_couriers(limit=3):
    """Get top performing couriers"""
    couriers = User.query.filter_by(role='courier', is_active=True).all()

    # Sort by successful deliveries
    sorted_couriers = sorted(couriers, key=lambda c: c.successful_deliveries or 0, reverse=True)[:limit]

    return [f"{c.full_name} ({c.successful_deliveries})" for c in sorted_couriers]


def _get_busiest_restaurants(limit=3):
    """Get busiest restaurants by order count"""
    # Query to count orders per restaurant
    restaurant_counts = db.session.query(
        User.full_name,
        func.count(Order.id).label('order_count')
    ).join(Order, User.id == Order.restaurant_id).filter(
        User.role == 'restaurant'
    ).group_by(User.id, User.full_name).order_by(
        func.count(Order.id).desc()
    ).limit(limit).all()

    return [f"{r.full_name} ({r.order_count})" for r in restaurant_counts]
