# Economía de LOJI: diseño y pendientes

Documento vivo para no perder decisiones entre sesiones.

## Fases
| Fase | Estado | Qué incluye |
|---|---|---|
| 1 | ✅ | Servicio central (`core/economy/service.py`), `/saldo`, `/trabajar`, `/diario`, `/pagar`, `/top`, `/eco-admin` |
| 2 | ✅ | Pago por chat (canales elegidos, saldo mínimo 250, anti-spam, rachas, topes), voz opcional, comisión de `/pagar` (7%) |
| 3 | ✅ | Tienda (rol, consumible, coleccionable), inventario, boosts con tope global, códigos de canje, misiones |
| 4 | ✅ | Mascotas: especies, rarezas, arquetipos, niveles, cuidado con desgaste perezoso, evolución, catálogo de 16 especies |
| 5a | ✅ | Gacha: banners, pity (soft/hard), 50/50, x1/x10, GIFs y tarjetas con Pillow |
| 5b | ✅ | Casino (`/casino`): crash, slots, moneda, blackjack. Ventaja de la casa exacta por juego, suerte del Suertudo baja la ventaja (nunca la invierte), estadísticas por usuario |
| 5c | ✅ | Ruleta europea, mines (20 casillas), mayor o menor y carrera de caballos. Todos con ventaja exacta y `Winnings()` para redondear sin errores de decimales |
| 6 | ✅ | Impuesto progresivo por tramos marginales en `/pagar`, inflación (multiplicador de precios según el dinero de los activos, revisado cada 6 h), precio por demanda por item, `/eco-admin stats` con gráfico, banco opcional (`/banco`) |
| 7 | ✅ | **Imágenes de mascotas y boosters**: tarjeta de mascota (`/mascota ver` y tras cuidar/activar), álbum en `/mascota lista`, animación al evolucionar (`core/economy/petcards.py`). Boosters: x1.3 en trabajar/diario/chat/voz, +20% de probabilidad de legendaria y épica en el gacha (la pity no cambia) y 500 al boostear, una vez por boost (`core/economy/boost.py`, sección **Booster** de `/eco-admin config`) |

## Balance (pendiente de una pasada)
Objetivo: progreso **"middle game" estilo Mudae**: semanas o meses de grindeo, pero que se sienta gratificante.

Ingresos aproximados de un usuario activo al día con los valores por defecto:
- `/diario`: 200 a 350
- `/trabajar`: unas 100 por hora (si lo usa a menudo, entre 500 y 1.500)
- Chat: hasta 1.000 (el tope)
- Total: entre 1.500 y 2.500 al día

Gastos:
- Gacha: 150 por tirada. La legendaria asegurada (90 tiradas) cuesta unos 13.500, más o menos 1 o 2 semanas. La destacada asegurada (hasta 180 tiradas) cuesta unos 27.000.
- Mascota: comida 60, jugar 40 y evolucionar 2.500.

Cosas que revisar en la pasada de balance:
- Curva de XP de las mascotas (`xp_base`/`xp_per_level`)
- Precios de la tienda
- Topes del chat
- Premios de créditos del gacha (`FILLER_CREDITS`)
- Coste de evolucionar
- Que las rarezas legendarias se sientan especiales pero alcanzables

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
