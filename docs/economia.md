# Economía de LOJI: diseño y pendientes

Documento vivo para no perder decisiones entre sesiones.

## Fases
| Fase | Estado | Qué incluye |
|---|---|---|
| 1 | ✅ | Servicio central (`core/economy/service.py`), `/saldo`, `/trabajar`, `/diario`, `/pagar`, `/top`, `/eco-admin` |
| 2 | ✅ | Pago por chat (canales elegidos, saldo mínimo 250, anti-spam, rachas, topes), voz opcional, impuesto de `/pagar` por tramos |
| 3 | ✅ | Tienda (rol, consumible, coleccionable), inventario, boosts con tope global, códigos de canje, misiones |
| 4 | ✅ | Mascotas: especies, rarezas, arquetipos, niveles, cuidado con desgaste perezoso, evolución, catálogo de 16 especies |
| 5a | ✅ | Gacha: banners, pity (soft/hard), 50/50, x1/x10, GIFs y tarjetas con Pillow |
| 5b | ✅ | Casino (`/casino`): crash, slots, moneda, blackjack. Ventaja de la casa exacta por juego, suerte del Suertudo baja la ventaja (nunca la invierte), estadísticas por usuario |
| 5c | ✅ | Ruleta europea, mines (20 casillas), mayor o menor y carrera de caballos. Todos con ventaja exacta y `Winnings()` para redondear sin errores de decimales |
| 6 | ✅ | Impuesto progresivo por tramos marginales en `/pagar`, inflación (multiplicador de precios según el dinero de los activos, revisado cada 6 h), precio por demanda por item, `/eco-admin stats` con gráfico, banco opcional (`/banco`) |
| 7 | ✅ | **Imágenes de mascotas y boosters** (más tarde: hasta 25 especies por rareza, 100 en total, y 100 mascotas por persona): tarjeta de mascota (`/mascota ver` y tras cuidar/activar), álbum en `/mascota lista`, animación al evolucionar (`core/economy/petcards.py`). Boosters: x1.3 en trabajar/diario/chat/voz, +20% de probabilidad de legendaria y épica en el gacha (la pity no cambia) y 500 al boostear, una vez por boost (`core/economy/boost.py`, sección **Booster** de `/eco-admin config`) |

## Balance

Objetivo: progreso **"middle game" estilo Mudae**: semanas o meses de grindeo, pero que se sienta gratificante.

### Ingresos por día (valores por defecto)

| Perfil | Trabajar | Diario | Chat | Total | Con boost (x1.3) |
|---|---|---|---|---|---|
| Casual (3 trabajos, racha 4, ~25 mensajes) | 300 | 300 | 250 | **~850** | ~1.100 |
| Activo (8 trabajos, racha 7, ~60 mensajes) | 800 | 375 | 600 | **~1.775** | ~2.300 |
| Muy activo (14 trabajos, ~100 mensajes) | 1.400 | 375 | 800 | **~2.575** | ~3.350 |

### Ritmo resultante

- **Gacha** (200 por tirada): una legendaria sale de media a las **62 tiradas (~12.500)** y está asegurada a las 90 (18.000). Una épica está asegurada cada 10 tiradas (2.000). Si alguien activo gasta la mitad de lo que gana, consigue una legendaria cada ~2 semanas; alguien casual, cada ~4 semanas. Los boosters necesitan un 10% menos de tiradas.
- **Mascotas**: mantener una al 100% cuesta ~130 al día (comida 82, juego 48). Sube al nivel 10 (evolución) en ~8 días, al 20 en ~1 mes y al 30 en ~2 meses.
- **Ventaja de una mascota al nivel 30**: común +11,7%, rara +19,5%, épica +28,3%, legendaria +41%. La suerte se queda en un máximo del 15% y el descuento en un máximo del 25%. Todos los bonus juntos suman como mucho +100%.
- **💸 Rentistas**: generan su ventaja en créditos. Por ejemplo, +10% da el 10% de `income_base` (800) al día y se acumula hasta 24 h. Así valen lo mismo que una Farmeadora para alguien activo, y la persona casual sale ganando. Una épica da 64 al día en nivel 1 y 226 en nivel 30; una legendaria, 96 y 328.
- **Inflación**: empieza a subir precios cuando la media de los activos pasa de 25.000 (~2 semanas de un jugador activo).

### Casino

La casa siempre gana un poco a la larga (eso quita dinero de la economía), pero cada premio es real.

| Juego | Ventaja casa | Apuesta máx. | Premio máximo |
|---|---|---|---|
| 🪙 Moneda | 2% | 20.000 | x1,96 |
| 🃏 Blackjack | Paga como un casino real (x2, blackjack x2,5); por sus reglas la casa gana ~1,4% jugando bien y ~5% jugando mal | 20.000 | x2,5 (blackjack natural, doblando x4) |
| 🎡 Ruleta | 2,7% (como la europea) | 20.000 | x36 (un número) |
| 🚀 Crash | 12% (explota al instante 1 de cada 8 veces) | 3.000 | x20 |
| 💣 Mines | 3% | 10.000 | x100 (cobra solo al llegar) |
| 🔼 Mayor o menor | 3% | 10.000 | x100 (cobra solo al llegar) |
| 🎰 Slots | 10% (como una tragamonedas real) | 5.000 | x832 (7️⃣7️⃣7️⃣, 1 de cada 125.000) |
| 🎰✨ Tragamonedas de lujo (animada) | 8% | 5.000 | x832, la misma tabla que Slots |
| 🏇 Carrera | 4% | 10.000 | x12 (Turbo Burro) |

- **Slots**: se gana en 1 de cada 3 tiradas y **todo premio paga más de lo apostado**, pero las parejas pagan poco (x1,28 a x5,35). La casa se queda con el 10%. Antes un 53% de las tiradas "ganaba", pero casi todas devolvían menos de lo apostado.
- Las apuestas máximas son más o menos una semana de ingresos de alguien activo, para que una sola apuesta no decida el top.
- La mascota Suertuda reduce la ventaja de la casa como mucho un 15% (por ejemplo, del 3% al 2,55%). Nunca la vuelve a favor del jugador.

### Precios recomendados para la tienda

Son **precios base**: la inflación y la demanda los suben solos. Los calculé con el ingreso de un jugador activo (~1.775 al día).

**Consumibles** (boosts). Cuestan ~70% de lo que le hacen ganar de más a alguien activo, para que valga la pena usarlos sin regalar dinero:

| Objeto | Efecto | Duración | Precio | Ganancia extra (activo) |
|---|---|---|---|---|
| ☕ Café | +25% trabajar | 24 h | **150** | ~200 |
| 💼 Turno extra | +50% trabajar | 24 h | **300** | ~400 |
| ⚡ Bebida energética | +100% trabajar | 12 h | **350** | ~500 |
| 🗣️ Megáfono | +50% chat | 24 h | **220** | ~300 |
| 🎁 Caja sorpresa del diario | +100% diario | 24 h | **250** | ~375 |
| 📅 Contrato semanal | +25% trabajar | 7 días | **1.000** | ~1.400 |

**Roles** (permanentes; son el sumidero principal de dinero). Pon límite de 1 por persona:

| Rol | Precio | Días de un jugador activo |
|---|---|---|
| 🎨 Color básico | **2.500** | ~1,5 |
| 🌈 Color premium | **7.500** | ~4 |
| ⭐ VIP (título, canal o emojis exclusivos) | **20.000** | ~11 |
| 👑 Prestigio | **50.000** | ~1 mes |
| 💎 Leyenda (stock 1 o 3, único en el servidor) | **150.000** | ~3 meses |

**Coleccionables** (para presumir en el inventario):

| Rareza | Precio | Stock recomendado |
|---|---|---|
| Común | **500** | sin límite |
| Raro | **2.500** | sin límite |
| Épico | **10.000** | 10 a 25 |
| Legendario | **50.000 a 100.000** | 1 a 5 |

Consejos:
- No pongas consumibles que den más de +100%: el tope de bonus los recorta igual.
- Evita premios de dinero real (Nitro y similares) en la tienda: hacen que la gente quiera abusar del sistema y el casino deja de ser un juego.
- Si tras unas semanas el top tiene mucho más que 25.000 de media, sube los roles caros antes de bajar los ingresos: quitarle ingresos a la gente se siente peor que ver precios más altos.

## La Larga Marcha (`/casino marcha`)

Juego de póker por antes, lo más parecido posible a Balatro, con estética LOJI.
- **8 antes** de 3 ciegas cada uno: Patrulla (×1), Muralla (×1,5) y Jefe (×2). Objetivo base por ante: 300, 800, 2.000, 5.000, 11.000, 20.000, 35.000 y 50.000 (como en Balatro).
- Por ciega: mano de 8 cartas, 4 manos y 3 descartes. Puntos = (fichas de la jugada + cartas que puntúan) × multi, y luego los comodines de izquierda a derecha.
- **◈ Datos** (dinero dentro de la partida): empiezas con 4; al superar una ciega ganas 3/4/5, más 1 por mano sobrante, más intereses (1 por cada 5, máximo 5).
- **Tienda** tras cada ciega: 2 ofertas (comodín o actualización de jugada), renovar por 5 (+1 cada vez) y vender comodines por la mitad. Máximo 5 comodines. Hay 24 comodines propios (comunes, poco comunes y raros).
- **Cobrar** tras cada jefe: ×0,6 · ×0,8 · ×1 · ×1,6 · ×4 · ×10 · ×25 · ×60. Un bot simple vence los antes 1-6 el 96/95/91/48/14/5% de las veces: los primeros son el calentamiento.
- Límite diario (5) y apuesta máxima de 3.000 (también por el límite global del casino).
- Se guarda en `eco_marcha` y sobrevive a reinicios.
- **Fase C (pendiente):** jefes con reglas especiales (LOJI como jefe final), arte de TFR y torneo semanal.

## Boosters

- Se detecta con `premium_since` del miembro: en cuanto deja de boostear pierde los beneficios.
- El premio de 500 se guarda con la fecha del boost (`boost_rewarded`), así que reiniciar el bot o recibir el evento dos veces no paga doble. Si vuelve a boostear más adelante, cobra de nuevo.
- La suerte multiplica las tasas de legendaria y épica; si un admin la sube mucho, se recortan para que siempre quede sitio para las demás rarezas.
- El x1.3 se aplica después de los bonus de mascota y objetos, y no cuenta para el tope diario del chat y la voz (el tope mira la cantidad base).

## Cómo se calcula el precio de algo
`base × inflación × (1 + subida por demanda) × (1 − descuento del Ahorrador)`
- La inflación afecta a la tienda, al cuidado y la evolución de las mascotas, y al gacha (este último se puede desactivar).
- No afecta al casino ni a lo que se gana (trabajar, diario, chat).

## Decisiones técnicas
- En el libro de movimientos (`eco_ledger`), `amount` es el cambio en la cartera y `bank` el cambio en el banco, así que el dinero que entra o sale con cada movimiento es `amount + bank`. Las estadísticas suman eso y el test `test_flows_add_up_to_the_real_change` comprueba que cuadra.
- PyMongo async: `aggregate()` se hace con `await` y devuelve un cursor, así que va `await (await col.aggregate(...)).to_list()`. Con `find()` no hace falta ese primer `await`.
- Todo cambio de saldo pasa por `EconomyService.Change` (atómico, con `$inc` y filtro condicional) y queda en `eco_ledger`.
- Transacciones solo si Mongo es replica set (Atlas lo es); el bot lo comprueba al arrancar.
- Locks por usuario en memoria: valen mientras el bot corra en un solo proceso.
- Los menús de Discord solo admiten 25 opciones, por eso hay máximo 25 items, códigos, misiones, especies, banners y premios por banner.
- Las imágenes usan fuentes incluidas en `assets/fonts` (DejaVu y Noto Color Emoji), así que no dependen del host. Los emojis personalizados de Discord se descargan al vuelo, y si fallan se dibuja un icono con la inicial.
- Los GIFs del gacha se generan una vez al arrancar. Se pueden reemplazar poniendo `assets/gacha/blue.gif`, `purple.gif` o `gold.gif`.
- Tests en `tests/economy/` (pytest + mongomock), sin efecto en el host.
