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
| 5c | ⏳ | Resto del casino: ruleta, mines, higher/lower, carrera de caballos (mismo patrón: `Casino.Start` / `Casino.Pay`, lógica pura en `core/economy/casino.py`) |
| 6 | ⏳ | Impuestos progresivos (sustituir `transfer.fee_percent` por tramos en `core/economy/tax.py`), inflación, precios dinámicos por demanda (`shop.Price`), `/economy stats`, banco opcional |
| 7 | ⏳ | **Imágenes de mascotas**: tarjeta generada con Pillow para `/mascota ver` (estilo de las tarjetas del gacha en `core/economy/cards.py`), con barras de cuidado, nivel, estado de ánimo y quizá animación al subir de nivel o evolucionar |

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

## Decisiones técnicas
- Todo cambio de saldo pasa por `EconomyService.Change` (atómico, con `$inc` y filtro condicional) y queda en `eco_ledger`.
- Transacciones solo si Mongo es replica set (Atlas lo es); el bot lo comprueba al arrancar.
- Locks por usuario en memoria: valen mientras el bot corra en un solo proceso.
- Los menús de Discord solo admiten 25 opciones, por eso hay máximo 25 items, códigos, misiones, especies, banners y premios por banner.
- Las imágenes usan fuentes incluidas en `assets/fonts` (DejaVu y Noto Color Emoji), así que no dependen del host. Los emojis personalizados de Discord se descargan al vuelo, y si fallan se dibuja un icono con la inicial.
- Los GIFs del gacha se generan una vez al arrancar. Se pueden reemplazar poniendo `assets/gacha/blue.gif`, `purple.gif` o `gold.gif`.
- Tests en `tests/economy/` (pytest + mongomock), sin efecto en el host.
