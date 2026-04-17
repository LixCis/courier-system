# Design Spec: WebSocket Real-time, Mapy, In-app Notifikace

**Datum:** 2026-04-05
**Přístup:** B — čistý refaktor, kompletní nahrazení AJAX pollingu

---

## 1. Přehled

Tři propojené features přidané do stávajícího Flask courier systému:

1. **WebSocket komunikace** — Flask-SocketIO nahradí veškerý AJAX polling
2. **Mapová vizualizace** — Leaflet.js mapy na dashboardech, interaktivní výběr adres, vizualizace tras
3. **In-app notifikace** — zvoneček v headeru, historie notifikací, real-time doručování přes WebSocket

---

## 2. WebSocket architektura

### 2.1 Závislosti

Přidat do `requirements.txt`:
```
flask-socketio==5.3.6
python-socketio==5.11.0
python-engineio==4.9.0
gevent==24.2.1          # async worker pro SocketIO
gevent-websocket==0.10.1
```

### 2.2 Inicializace SocketIO

V `app.py` (nebo nový `extensions.py`):
```python
from flask_socketio import SocketIO
socketio = SocketIO(app, manage_session=False, async_mode='gevent')
```

`manage_session=False` — SocketIO sdílí Flask-Login session, neřeší vlastní.

Spouštění serveru se změní z `app.run()` na `socketio.run(app)`.

### 2.3 Room struktura

Při připojení klienta se automaticky joinují rooms podle role:

| Room | Kdo joinuje | Co dostává |
|------|-------------|------------|
| `admin` | Všichni admini | Všechny eventy v systému |
| `restaurant_{user_id}` | Konkrétní restaurace | Eventy svých objednávek |
| `courier_{user_id}` | Konkrétní kurýr | Eventy přiřazených objednávek, nové nabídky |
| `order_{order_id}` | Kdokoliv s otevřeným detailem | Změny konkrétní objednávky |

Join/leave rooms řeší server-side `@socketio.on('connect')` handler na základě `current_user.role` a `current_user.id` z Flask-Login session.

### 2.4 Server → Client eventy

| Event | Payload | Emitováno do rooms | Trigger |
|-------|---------|-------------------|---------|
| `order:created` | `{order_id, order_number, restaurant_name, status, customer_name, delivery_address, created_at}` | `admin`, `restaurant_{restaurant_id}` | Vytvoření objednávky |
| `order:assigned` | `{order_id, order_number, courier_id, courier_name, estimated_pickup, estimated_delivery}` | `admin`, `restaurant_{restaurant_id}`, `courier_{courier_id}`, `order_{order_id}` | Přiřazení kurýra |
| `order:status_changed` | `{order_id, order_number, old_status, new_status, timestamp}` | `admin`, `restaurant_{restaurant_id}`, `courier_{courier_id}`, `order_{order_id}` | Změna statusu |
| `order:cancelled` | `{order_id, order_number, cancelled_by}` | `admin`, `restaurant_{restaurant_id}`, `courier_{courier_id}` (pokud přiřazen), `order_{order_id}` | Zrušení |
| `order:rejected` | `{order_id, order_number, courier_id, courier_name}` | `admin`, `restaurant_{restaurant_id}`, `order_{order_id}` | Kurýr odmítl |
| `courier:location_updated` | `{courier_id, latitude, longitude, location_description}` | `admin`, relevantní `order_{order_id}` rooms | Kurýr aktualizoval pozici |
| `courier:availability_changed` | `{courier_id, courier_name, is_available, pending_unavailable}` | `admin` | Změna dostupnosti |
| `notification:new` | `{id, type, title, message, link, created_at}` | `{role}_{user_id}` příjemce | Jakákoliv notifikace-generující událost |
| `ai:description_ready` | `{order_id, ai_enhanced_description}` | `restaurant_{restaurant_id}`, `order_{order_id}` | AI dokončí standardizaci |
| `ai:insights_ready` | `{user_id, summary_type, summary_text}` | Příslušná role room | AI dokončí statistiky |
| `dashboard:data` | `{...kompletní dashboard data...}` | Příslušná role room | Počáteční load po connect |

### 2.5 Client → Server eventy

| Event | Payload | Kdo posílá | Akce na serveru |
|-------|---------|------------|-----------------|
| `courier:update_location` | `{latitude, longitude, location_description}` | Kurýr | Uloží pozici, emituje `courier:location_updated` |
| `order:join` | `{order_id}` | Kdokoliv | Join `order_{order_id}` room |
| `order:leave` | `{order_id}` | Kdokoliv | Leave `order_{order_id}` room |
| `notification:mark_read` | `{notification_id}` | Kdokoliv | Označí notifikaci jako přečtenou |
| `notification:mark_all_read` | `{}` | Kdokoliv | Označí všechny jako přečtené |

### 2.6 Autentizace a bezpečnost

- SocketIO automaticky sdílí Flask session cookies → `current_user` dostupný v handlerech
- `@socketio.on('connect')` handler: ověří `current_user.is_authenticated`, jinak `disconnect()`
- Všechny client→server eventy kontrolují oprávnění (kurýr nemůže poslouchat cizí objednávky)
- Room membership je řízena server-side, klient nemůže joinovat libovolnou room

### 2.7 Nový service: `services/socketio_service.py`

Centrální modul, který zapouzdřuje veškeré emitování. Funkce v `app.py` volají tento service místo přímého `emit()`:

```python
class SocketIOService:
    def __init__(self, socketio):
        self.socketio = socketio

    def emit_order_created(self, order):
        """Emituje order:created do admin a restaurant rooms + generuje notifikace"""

    def emit_order_status_changed(self, order, old_status, new_status):
        """Emituje order:status_changed + notification:new do příslušných rooms"""

    def emit_courier_location(self, courier):
        """Emituje courier:location_updated do admin + relevantních order rooms"""

    def emit_notification(self, user_id, notification):
        """Emituje notification:new do specifické user room"""
    # ... atd.
```

Každá metoda:
1. Sestaví payload
2. Emituje data event do příslušných rooms
3. Vytvoří Notification záznam v DB (pokud je to notifikace-generující event)
4. Emituje `notification:new` příjemcům

### 2.8 Co se odstraní

**API endpointy k smazání (11 endpointů):**
- `GET /api/admin/dashboard-data`
- `GET /api/admin/order/<id>`
- `GET /api/admin/ai-insights`
- `GET /api/restaurant/dashboard-data`
- `GET /api/restaurant/order/<id>`
- `GET /api/restaurant/ai-insights`
- `GET /api/courier/dashboard-data`
- `GET /api/courier/order/<id>`
- `GET /api/courier/ai-insights`
- `GET /api/order/<id>/ai-description`

**JavaScript soubory k smazání (5 souborů):**
- `static/js/auto-refresh.js`
- `static/js/dashboard-updater.js`
- `static/js/order-detail-polling.js`
- `static/js/order-detail-updater.js`
- `static/js/page-refresh-polling.js`

**Nahrazení:**
- `static/js/socket_base.js` — připojení, reconnect, notifikační zvoneček
- `static/js/map_utils.js` — Leaflet mapy, markery, routing

---

## 3. Mapová vizualizace

### 3.1 Stávající stav

Už existuje `templates/components/location_map.html` s Leaflet.js — interaktivní mapa pro výběr adresy (search + klik) s reverse geocodingem přes Nominatim. Centrována na Ostravu. Tato komponenta zůstane a rozšíří se.

### 3.2 Admin dashboard — přehledová mapa

Nová sekce na admin dashboardu s full-width mapou:

**Markery kurýrů:**
- Zelená ikona = dostupný, bez aktivní objednávky
- Oranžová ikona = na cestě (má aktivní objednávku)
- Šedá ikona = nedostupný
- Popup: jméno, vozidlo, počet aktivních objednávek, poslední aktualizace pozice
- Pozice se aktualizují live přes `courier:location_updated` WebSocket event

**Markery objednávek:**
- Modrá ikona = pickup bod (restaurace)
- Červená ikona = delivery bod (zákazník)
- Propojení čárou (polyline) mezi pickup a delivery
- Popup: číslo objednávky, status, restaurace, zákazník
- Pouze aktivní objednávky (ne delivered/cancelled)

**Ovládání:**
- Checkbox filtry: zobrazit/skrýt kurýry, zobrazit/skrýt objednávky
- Auto-fit bounds na všechny viditelné markery
- Výchozí centrum: Ostrava (49.8209, 18.2625)

### 3.3 Restaurant — vytváření objednávky

Stávající `create_order.html` se rozšíří:

- Mapa vedle formuláře (nebo pod ním na mobilu) pro delivery adresu
- Využije existující `location_map.html` komponentu
- Textové pole pro adresu zůstává — při psaní se geocoduje a pin se posouvá
- Klik na mapu → reverse geocoding → vyplní textové pole adresy
- Pickup adresa restaurace = fixní marker (z profilu restaurace)
- GPS souřadnice se automaticky ukládají do hidden polí

### 3.4 Courier dashboard — mapa s objednávkami

Nová sekce na courier dashboardu:

- Marker kurýrovy aktuální pozice (modrý)
- Markery pickup bodů přiřazených objednávek (zelené)
- Markery delivery bodů (červené)
- **Vizualizace trasy:** Polyline od kurýra → pickup → delivery. Pro reálné trasy po silnicích se použije OSRM (Open Source Routing Machine) — `https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson` (free, bez API klíče)
- Pokud kurýr nemá GPS souřadnice, mapa se zobrazí centrovaná na Ostravu s upozorněním "Aktualizujte svou polohu"

### 3.5 Detail objednávky — mapa (všechny role)

Na stránce `view_order.html` (admin, restaurant, courier verze):

- Mapa s pickup markerem + delivery markerem
- Trasa mezi nimi (OSRM polyline)
- Pokud je kurýr přiřazen a má GPS → jeho pozice jako třetí marker
- Live aktualizace pozice kurýra přes `courier:location_updated` (klient joinuje `order_{id}` room)

### 3.6 Geocoding rozšíření

`services/geocoding_service.py` — přidat reverse geocoding metodu:

```python
def reverse_geocode(self, latitude, longitude):
    """
    Convert GPS coordinates to address string

    Returns:
        str: Address string or None
    """
```

Toto je potřeba pro server-side reverse geocoding. Klientský reverse geocoding (při kliku na mapu) zůstává přes přímé volání Nominatim API z JavaScriptu (jak je teď v `location_map.html`).

### 3.7 OSRM routing

Volání OSRM API bude probíhat na klientu (JavaScript), ne na serveru. Je to free API bez klíče s limitem cca 5000 req/den. Pro výukový projekt dostačující.

```javascript
async function getRoute(startLat, startLon, endLat, endLon) {
    const url = `https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${endLon},${endLat}?overview=full&geometries=geojson`;
    const response = await fetch(url);
    const data = await response.json();
    return data.routes[0].geometry; // GeoJSON LineString
}
```

---

## 4. In-app notifikační systém

### 4.1 Nový databázový model

Přidat do `models.py`:

```python
class Notification(db.Model):
    """In-app notifications for users"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    # Typy: order_created, order_assigned, order_status_changed,
    #        order_rejected, order_cancelled, courier_availability, system
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500))  # URL pro přesměrování po kliknutí
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))
```

### 4.2 Tabulka notifikačních pravidel

| Událost | Příjemce | type | title | message | link |
|---------|----------|------|-------|---------|------|
| Nová objednávka | Admin | `order_created` | "Nová objednávka #{number}" | "Restaurace {name} vytvořila objednávku pro {customer}" | `/admin/order/{id}` |
| Objednávka přiřazena | Kurýr | `order_assigned` | "Nová objednávka #{number}" | "Objednávka k vyzvednutí z {restaurant}, doručit na {address}" | `/courier/order/{id}` |
| Objednávka přiřazena | Restaurace | `order_assigned` | "Kurýr přiřazen k #{number}" | "Kurýr {name} ({vehicle}) vyzvedne objednávku" | `/restaurant/order/{id}` |
| Vyzvednuto | Restaurace | `order_status_changed` | "Objednávka #{number} vyzvednuta" | "Kurýr {name} vyzvednul objednávku" | `/restaurant/order/{id}` |
| Doručeno | Restaurace | `order_status_changed` | "Objednávka #{number} doručena" | "Objednávka úspěšně doručena zákazníkovi" | `/restaurant/order/{id}` |
| Doručeno | Admin | `order_status_changed` | "Objednávka #{number} doručena" | "Doručena kurýrem {name}" | `/admin/order/{id}` |
| Odmítnuto | Admin | `order_rejected` | "Objednávka #{number} odmítnuta" | "Kurýr {name} odmítl objednávku" | `/admin/order/{id}` |
| Odmítnuto | Restaurace | `order_rejected` | "Objednávka #{number} odmítnuta kurýrem" | "Hledá se nový kurýr..." | `/restaurant/order/{id}` |
| Zrušeno | Kurýr (pokud přiřazen) | `order_cancelled` | "Objednávka #{number} zrušena" | "Restaurace {name} zrušila objednávku" | `/courier/order/{id}` |

### 4.3 UI — zvoneček v headeru

V `templates/base.html` přidat do navigace (vedle uživatelského jména):

```html
<!-- Notification bell -->
<div id="notification-bell" class="relative cursor-pointer">
    <!-- Bell icon (SVG) -->
    <svg>...</svg>
    <!-- Badge s počtem nepřečtených -->
    <span id="notification-badge" class="hidden absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">0</span>
</div>

<!-- Dropdown -->
<div id="notification-dropdown" class="hidden absolute right-0 mt-2 w-80 bg-white rounded-lg shadow-xl border max-h-96 overflow-y-auto z-50">
    <div class="p-3 border-b flex justify-between items-center">
        <span class="font-semibold">Notifikace</span>
        <button id="mark-all-read" class="text-sm text-blue-600 hover:underline">Označit vše</button>
    </div>
    <div id="notification-list">
        <!-- Dynamicky plněno přes JS -->
    </div>
    <div id="notification-empty" class="p-4 text-center text-gray-500 hidden">
        Žádné notifikace
    </div>
</div>
```

**Chování:**
- Badge ukazuje počet nepřečtených (skrytý pokud 0)
- Klik na zvoneček → toggle dropdown
- Klik na notifikaci → `notification:mark_read` event + redirect na `link`
- "Označit vše" → `notification:mark_all_read` event
- Nepřečtené notifikace mají modré pozadí, přečtené bílé
- Dropdown zobrazuje max 20 posledních notifikací

### 4.4 Načtení při připojení

Při WebSocket `connect` server pošle `dashboard:data` event obsahující mimo jiné:
```json
{
    "unread_notifications_count": 5,
    "recent_notifications": [
        {"id": 1, "type": "order_assigned", "title": "...", "message": "...", "link": "...", "is_read": false, "created_at": "..."},
        ...
    ]
}
```

Tím se pokryjí notifikace, které přišly když uživatel nebyl online.

### 4.5 REST endpoint pro historii (ponechat)

Přidat jeden HTTP endpoint pro stránkovaný seznam notifikací (pro případné "zobrazit všechny"):
- `GET /notifications?page=1&per_page=20` — vrací HTML stránku se seznamem všech notifikací

Tento endpoint není polling — slouží jen pro zobrazení kompletní historie.

---

## 5. Frontend JavaScript architektura

### 5.1 Nové soubory

**`static/js/socket_base.js`** — společný základ pro všechny stránky:
```javascript
// Připojení k SocketIO
const socket = io({
    transports: ['websocket', 'polling']  // preferuj websocket
});

// Reconnect logika
socket.on('connect', () => {
    console.log('Connected to server');
    // Server automaticky joinuje rooms na základě session
});

socket.on('disconnect', () => {
    // Zobrazit "Odpojeno" indikátor v headeru
});

socket.on('reconnect', () => {
    // Skrýt indikátor, refreshnout data
});

// Notifikační zvoneček - globální handler
socket.on('notification:new', (data) => {
    addNotificationToDropdown(data);
    updateBadgeCount();
    showNotificationToast(data);  // krátký toast v rohu
});

// Funkce pro notifikace
function addNotificationToDropdown(notification) { ... }
function updateBadgeCount() { ... }
function showNotificationToast(notification) { ... }
function markNotificationRead(id) {
    socket.emit('notification:mark_read', {notification_id: id});
}
function markAllRead() {
    socket.emit('notification:mark_all_read', {});
}
```

**`static/js/map_utils.js`** — Leaflet utility funkce:
```javascript
// Inicializace mapy
function initMap(containerId, options = {}) { ... }

// Marker management
function addCourierMarker(map, courier) { ... }
function updateCourierMarker(map, courier) { ... }
function addOrderMarkers(map, order) { ... }

// Routing přes OSRM
async function drawRoute(map, startLatLng, endLatLng) { ... }

// Marker ikony podle stavu
function getCourierIcon(status) { ... }  // zelená/oranžová/šedá
function getPickupIcon() { ... }  // modrá
function getDeliveryIcon() { ... }  // červená
```

### 5.2 Stránkově specifické handlery

Každá šablona si přidá inline `<script>` blok s handlery pro eventy relevantní pro danou stránku. Příklady:

**Admin dashboard:**
```javascript
socket.on('order:created', (data) => { /* přidej řádek do tabulky */ });
socket.on('order:status_changed', (data) => { /* aktualizuj status v tabulce */ });
socket.on('courier:location_updated', (data) => { /* posuň marker na mapě */ });
socket.on('courier:availability_changed', (data) => { /* změň barvu markeru */ });
socket.on('dashboard:data', (data) => { /* initial load celého dashboardu */ });
```

**Courier dashboard:**
```javascript
socket.on('order:assigned', (data) => { /* nová objednávka v seznamu + marker na mapě */ });
socket.on('order:cancelled', (data) => { /* odeber z seznamu */ });
socket.on('dashboard:data', (data) => { /* initial load */ });
```

**Order detail (všechny role):**
```javascript
// Při otevření stránky
socket.emit('order:join', {order_id: ORDER_ID});

socket.on('order:status_changed', (data) => { /* aktualizuj status indikátor */ });
socket.on('courier:location_updated', (data) => { /* posuň marker kurýra na mapě */ });
socket.on('ai:description_ready', (data) => { /* zobraz AI popis */ });

// Při opuštění stránky
window.addEventListener('beforeunload', () => {
    socket.emit('order:leave', {order_id: ORDER_ID});
});
```

### 5.3 Inclusion v base.html

```html
<!-- V <head> -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.4/socket.io.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<!-- Před </body> -->
<script src="{{ url_for('static', filename='js/socket_base.js') }}"></script>
<script src="{{ url_for('static', filename='js/map_utils.js') }}"></script>
```

Leaflet CSS/JS se načte na všech stránkách (malý overhead ~40KB gzip), aby mapa byla okamžitě dostupná bez dalšího loadu.

---

## 6. Backend integrace

### 6.1 Změny v `app.py`

Každá route, která mění stav objednávky/kurýra, přidá volání `socketio_service`:

**Příklad — update statusu objednávky:**
```python
@app.route('/courier/order/<int:order_id>/update', methods=['POST'])
@login_required
@role_required('courier')
def courier_update_order(order_id):
    # ... existující logika ...
    old_status = order.status
    order.status = new_status
    db.session.commit()

    # NOVÉ: emit přes WebSocket
    socketio_service.emit_order_status_changed(order, old_status, new_status)
```

**Místa v app.py kde přidat emit volání:**
- Vytvoření objednávky (`restaurant_create_order`)
- Přiřazení kurýra (`assign_courier` / auto-assign v scheduleru)
- Změna statusu (`courier_update_order`, `restaurant_update_status`)
- Zrušení objednávky (`restaurant_cancel_order`)
- Odmítnutí objednávky (`courier_reject_order`)
- Aktualizace pozice kurýra (`courier_update_location`)
- Změna dostupnosti (`courier_toggle_availability`, admin verze)
- AI popis hotový (background thread v `enhance_order_description`)
- AI statistiky hotové (background thread v `ai_statistics.py`)

### 6.2 Změny v `services/order_scheduler.py`

Auto-assign scheduler musí emitovat přes SocketIO když přiřadí kurýra:

```python
def auto_assign_order(self, order):
    # ... existující logika ...
    if assigned_courier:
        socketio_service.emit_order_assigned(order)
```

Pozor: scheduler běží v jiném threadu. Flask-SocketIO umí emitovat z background threadů pokud se použije `socketio.emit()` s `namespace='/'`.

### 6.3 Spouštění serveru

`run.bat` a `setup.py` se aktualizují:

```python
# Místo: app.run(debug=True)
# Nově:
socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
```

`allow_unsafe_werkzeug=True` je potřeba pro development mode s gevent.

---

## 7. Struktura souborů — co přibude, co se odstraní

### Nové soubory:
```
services/socketio_service.py    # Centrální emit logika + notifikace
static/js/socket_base.js        # SocketIO klient + notifikační zvoneček
static/js/map_utils.js          # Leaflet utility funkce (markery, routing, ikony)
```

### Smazané soubory:
```
static/js/auto-refresh.js
static/js/dashboard-updater.js
static/js/order-detail-polling.js
static/js/order-detail-updater.js
static/js/page-refresh-polling.js
```

### Upravené soubory:
```
requirements.txt                          # + flask-socketio, gevent
models.py                                 # + Notification model
config.py                                 # (beze změn, SocketIO sdílí SECRET_KEY)
app.py                                    # SocketIO init, connect/disconnect handlery,
                                          #   emit volání ve všech state-changing routes,
                                          #   smazat /api/* polling endpointy,
                                          #   přidat GET /notifications endpoint
services/geocoding_service.py             # + reverse_geocode() metoda
services/order_scheduler.py               # + emit po auto-assign
templates/base.html                       # + SocketIO/Leaflet CDN, socket_base.js,
                                          #   map_utils.js, notifikační zvoneček v headeru
templates/admin/dashboard.html            # + přehledová mapa, SocketIO handlery místo polling
templates/admin/view_order.html           # + mapa s trasou, SocketIO handlery
templates/courier/dashboard.html          # + mapa s objednávkami, SocketIO handlery
templates/courier/view_order.html         # + mapa s trasou, SocketIO handlery
templates/courier/update_location.html    # + emit přes SocketIO po update
templates/restaurant/create_order.html    # rozšíření mapy (už má location_map komponentu)
templates/restaurant/dashboard.html       # SocketIO handlery místo polling
templates/restaurant/view_order.html      # + mapa s trasou, SocketIO handlery
templates/components/location_map.html    # beze změn (už funguje správně)
setup.py                                  # socketio.run místo app.run
run.bat                                   # beze změn (spouští setup.py)
```

---

## 8. Databázová migrace

Přidat tabulku `notifications`. Protože projekt používá SQLite bez Alembic migrací (používá `flask init-db` s `db.create_all()`), stačí přidat model a znovu spustit `flask init-db` — existující tabulky zůstanou, přibude jen nová.

Pokud existující DB nemá tabulku, přidat fallback:
```python
with app.app_context():
    db.create_all()  # Vytvoří chybějící tabulky
```

---

## 9. Testování

### Manuální testovací scénáře:

1. **WebSocket připojení:** Otevřít 3 prohlížeče (admin, restaurace, kurýr). Ověřit že všichni jsou připojeni (žádný "Odpojeno" indikátor).

2. **Order flow:** Restaurace vytvoří objednávku → admin vidí okamžitě nový řádek → kurýr dostane notifikaci + objednávku na dashboardu → kurýr vyzvednul → restaurace vidí změnu statusu → kurýr doručil → restaurace + admin dostanou notifikaci.

3. **Mapa admin:** Ověřit že se zobrazují markery kurýrů a objednávek. Kurýr aktualizuje pozici → marker se posune na admin mapě.

4. **Mapa restaurace:** Při vytváření objednávky kliknout na mapu → adresa se vyplní. Zadat adresu textově → pin se posune.

5. **Mapa kurýr:** Zobrazení přiřazených objednávek s trasou. Trasa přes OSRM ukazuje reálnou cestu.

6. **Notifikace:** Zvoneček ukazuje správný počet. Klik → dropdown s historií. Klik na notifikaci → přesměrování. "Označit vše" funguje.

7. **Reconnect:** Zastavit server, restartovat → klient se automaticky připojí a notifikace se dohrají z DB.

8. **Offline notifikace:** Kurýr se odpojí. Restaurace vytvoří objednávku. Kurýr se připojí → vidí notifikaci v dropdown (načtená z DB).
