"""Flask CLI commands: init-db, seed-db, seed-enhanced."""
import os
import random
import secrets
import sys
from datetime import timedelta

from models import db, User, Order
from common.utils import utcnow
from common.logging_config import get_logger

logger = get_logger(__name__)


def register(app):
    @app.cli.command()
    def init_db():
        """Initialize the database."""
        with app.app_context():
            db.create_all()
            print('Database initialized!')

    @app.cli.command()
    def seed_db():
        """Seed the database with sample data."""
        with app.app_context():
            if User.query.first():
                print('Database already contains data. Skipping seed.')
                return

            admin = User(username='admin', email='admin@courier.com',
                         full_name='System Administrator', role='admin')
            admin.set_password('admin123')

            restaurant1 = User(
                username='pizza_palace', email='contact@pizzapalace.com',
                full_name='Pizza Palace Ostrava', role='restaurant',
                current_location='Nádražní 164/215, 702 00 Moravská Ostrava, Czechia',
                last_known_latitude=49.8348, last_known_longitude=18.2820,
            )
            restaurant1.set_password('rest123')

            restaurant2 = User(
                username='burger_king', email='info@burgerking.com',
                full_name='Burger Kingdom Stodolní', role='restaurant',
                current_location='Stodolní 3, 702 00 Ostrava-Moravská Ostrava, Czechia',
                last_known_latitude=49.8385, last_known_longitude=18.2875,
            )
            restaurant2.set_password('rest123')

            courier1 = User(
                username='john_courier', email='john@courier.com',
                full_name='John Doe', role='courier', is_available=True, vehicle_type='bike',
                last_known_latitude=49.8209, last_known_longitude=18.2625,
                total_deliveries=0, successful_deliveries=0,
            )
            courier1.set_password('courier123')

            courier2 = User(
                username='jane_courier', email='jane@courier.com',
                full_name='Jane Smith', role='courier', is_available=True, vehicle_type='scooter',
                last_known_latitude=49.8350, last_known_longitude=18.2820,
                total_deliveries=0, successful_deliveries=0,
            )
            courier2.set_password('courier123')

            courier3 = User(
                username='mike_courier', email='mike@courier.com',
                full_name='Mike Johnson', role='courier', is_available=False, vehicle_type='motorcycle',
                last_known_latitude=49.8050, last_known_longitude=18.2500,
                total_deliveries=0, successful_deliveries=0,
            )
            courier3.set_password('courier123')

            db.session.add_all([admin, restaurant1, restaurant2, courier1, courier2, courier3])
            db.session.commit()

            print('Database seeded successfully!')
            print('\nLogin Credentials:')
            print('Admin: admin / admin123')
            print('Restaurant: pizza_palace / rest123')
            print('Restaurant: burger_king / rest123')
            print('Courier: john_courier / courier123')
            print('Courier: jane_courier / courier123')
            print('Courier: mike_courier / courier123')

    @app.cli.command()
    def seed_enhanced():
        """Seed database with enhanced realistic data for AI statistics."""
        with app.app_context():
            print("Running basic seed...")
            if not User.query.first():
                print("No users found, running standard seed first...")
                os.system(f"{sys.executable} -m flask seed-db")

            restaurant1 = User.query.filter_by(username='pizza_palace').first()
            restaurant2 = User.query.filter_by(username='burger_king').first()
            courier1 = User.query.filter_by(username='john_courier').first()
            courier2 = User.query.filter_by(username='jane_courier').first()
            courier3 = User.query.filter_by(username='mike_courier').first()

            if not all([restaurant1, restaurant2, courier1, courier2, courier3]):
                print("Error: Users not found. Run 'flask seed-db' first.")
                return

            delivery_areas = [
                {'area': 'Poruba', 'lat': 49.8209, 'lon': 18.1625, 'address': 'Opavská 1234, Poruba'},
                {'area': 'Stodolní', 'lat': 49.8385, 'lon': 18.2875, 'address': 'Stodolní 15, Moravská Ostrava'},
                {'area': 'Vítkovice', 'lat': 49.7987, 'lon': 18.2656, 'address': 'Ruská 567, Vítkovice'},
                {'area': 'Dubina', 'lat': 49.8123, 'lon': 18.2945, 'address': 'Dubinská 890, Dubina'},
                {'area': 'Zábřeh', 'lat': 49.8456, 'lon': 18.2234, 'address': 'Výškovická 321, Zábřeh'},
                {'area': 'Mariánské Hory', 'lat': 49.8234, 'lon': 18.2678, 'address': 'Horní 456, Mariánské Hory'},
            ]

            food_items = [
                "2x Pizza Margherita, 1x Coca Cola",
                "Velký burger s hranolky, 2x kečup",
                "3x Sushi set, wasabi extra",
                "Pizza Pepperoni (velká), 2x sprite",
                "Burger menu, bez okurek, přidat sýr",
                "4x Pizza (2x Margherita, 2x Salami)",
                "Kebab box, extra omáčka",
                "2x Burger, 3x hranolky, 2x cola",
                "Caesar salát s kuřecím, bez cibule, extra dresink",
                "Pasta Carbonara, extra parmezan, česnekový chléb",
                "2x Chicken wings (BBQ), 1x ranch omáčka",
                "Vegetarian wrap, avokádo, extra zelenina",
                "Pho bowl s hovězím, extra lime, sriracha",
                "Fish & chips, tartar omáčka, citron",
                "Pad Thai s krevetami, medium spicy",
                "3x Tacos (beef, chicken, veggie)",
                "Ramen s vepřovým, extra egg, nori",
                "Falafel wrap, hummus, extra tahini",
                "Chicken tikka masala, naan bread, 2x rice",
                "Poke bowl s lososem, extra wasabi, soy sauce",
            ]

            print("\nGenerating enhanced order data...")
            orders_created = 0
            now = utcnow()

            for days_ago in range(14):
                day_date = now - timedelta(days=days_ago)
                num_orders_per_day = random.randint(8, 15) if day_date.weekday() >= 5 else random.randint(4, 8)

                for _ in range(num_orders_per_day):
                    restaurant = random.choice([restaurant1, restaurant2])
                    delivery_loc = random.choice(delivery_areas)
                    hour = random.randint(11, 14) if random.random() > 0.5 else random.randint(17, 22)
                    minute = random.randint(0, 59)
                    created_time = day_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

                    order_number = f"ORD-{created_time.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
                    order = Order(
                        order_number=order_number,
                        restaurant_id=restaurant.id, restaurant_name=restaurant.full_name,
                        customer_name=random.choice(['Jan Novák', 'Petra Svobodová', 'Martin Dvořák', 'Eva Kučerová', 'Tomáš Procházka']),
                        customer_phone=f"+420{random.randint(600000000, 799999999)}",
                        delivery_address=delivery_loc['address'], pickup_address=restaurant.current_location,
                        items_description=random.choice(food_items),
                        order_value=random.randint(150, 800), status='delivered',
                        pickup_latitude=restaurant.last_known_latitude,
                        pickup_longitude=restaurant.last_known_longitude,
                        delivery_latitude=delivery_loc['lat'],
                        delivery_longitude=delivery_loc['lon'],
                        created_at=created_time,
                    )
                    courier = random.choice([courier1, courier2, courier3])
                    order.courier_id = courier.id
                    order.assigned_at = created_time + timedelta(minutes=random.randint(1, 5))
                    order.picked_up_at = order.assigned_at + timedelta(minutes=random.randint(5, 15))
                    order.in_transit_at = order.picked_up_at + timedelta(seconds=5)
                    order.delivered_at = order.in_transit_at + timedelta(minutes=random.randint(10, 30))

                    courier.total_deliveries += 1
                    courier.successful_deliveries += 1

                    db.session.add(order)
                    orders_created += 1

                    if random.random() < 0.1:
                        cancelled = Order(
                            order_number=f"ORD-{created_time.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
                            restaurant_id=restaurant.id, restaurant_name=restaurant.full_name,
                            customer_name=random.choice(['Jan Novák', 'Petra Svobodová']),
                            customer_phone=f"+420{random.randint(600000000, 799999999)}",
                            delivery_address=delivery_loc['address'],
                            pickup_address=restaurant.current_location,
                            items_description=random.choice(food_items),
                            order_value=random.randint(150, 800), status='cancelled',
                            pickup_latitude=restaurant.last_known_latitude,
                            pickup_longitude=restaurant.last_known_longitude,
                            delivery_latitude=delivery_loc['lat'],
                            delivery_longitude=delivery_loc['lon'],
                            created_at=created_time + timedelta(minutes=5),
                        )
                        db.session.add(cancelled)
                        orders_created += 1

            db.session.commit()
            print(f'\n[SUCCESS] Enhanced seed completed!')
            print(f'   - Created {orders_created} historical orders')
            print(f'   - Courier stats updated')
            print(f'   - Ready for AI statistics generation!')
