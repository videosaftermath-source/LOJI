# Mapa de comandos de LOJI

Todo se **configura en `/config`** y todo se **explica en `/ayuda`**.

## Para todos
| Comando | Para qué |
|---|---|
| `/ayuda` | Guía de todo el bot, por secciones |
| `/saldo` · `/trabajar` · `/diario` · `/pagar` · `/top` | Economía básica |
| `/tienda` · `/inventario` · `/usar` · `/misiones` · `/canjear` | Tienda, misiones y códigos |
| `/banco ver · depositar · retirar` | Banco (si está activo) |
| `/gacha` | Tiradas y banners |
| `/mascota ver · lista · alimentar · jugar · renombrar · activar · cobrar` | Mascotas |
| `/casino …` | Moneda, slots, tragamonedas, crash, blackjack, ruleta, mines, mayor o menor, carrera, marcha, info |
| `/juegos` | Guía de los juegos del casino |
| `/tutorial marcha` | Práctica gratis de La Larga Marcha |
| `/privacidad` | Tus datos y si participas en las recompensas por vanity o tag |

## Staff
| Comando | Para qué |
|---|---|
| `/mail` | Escribir al Tenno (sugerencias, peticiones, dudas) |
| `/tareas` | Lista de tareas; **➕ Nueva tarea** para Tenno y Consejo Supremo |
| `/perfil ver · editar · panel` | Perfiles de staff y panel por departamento |
| Tickets de Birb | Al reclamar o responder, sale la tarjeta "Te atiende"  · Canales numerados por panel (`reporte-001`): `/config` → Tickets → panel → 🔢 Nombres (número) · `/admin unclaim` quita la reclamación a la fuerza (admins y altos cargos) · `/add usuario` añade a alguien al ticket (quien lo reclamó o admins) |

## Administración
| Comando | Para qué |
|---|---|
| `/config` | **Toda la configuración**: 📮 Mando Central, 🏷️ Vanity y tag, 🪙 Economía y los módulos de Birb |
| `/eco-admin …` | dar, quitar, tienda, códigos, misiones, mascotas, regalar-mascota, gacha, stats, hacienda, desbloquear, reiniciar, cancelar-marcha |
| `/perfil sincronizar · fecha` | Crear perfiles del staff y corregir fechas |
| `/anuncio` · `/embed` | Mensajes con diseño |

## Quitados en la organización
- `/buzon config` y `/eco-admin config` → ahora en `/config`.
- `/buzon departamentos` → `/perfil panel`.
- `/eco-ayuda` → `/ayuda` (el prefijo `eco-ayuda` sigue funcionando).
- Modmail → reemplazado por `/mail`.
- `/staff add · remove · edit · view · introduction · panel` (Birb) → `/perfil`. `/staff list` (lista automática por roles) sigue activo.

### Tickets: pregunta previa y anti-AFK
- **Pregunta previa:** `/config` → Tickets → elige el panel → **📝 Pregunta previa**. Por ejemplo, «Describe tu caso brevemente». El usuario la responde antes de que se abra el ticket, y la respuesta sale arriba en el ticket. Si la dejas vacía, el panel no pregunta nada.
- **Anti-AFK:** se activa y desactiva en `/config` → Mando Central → **⏰ Anti-AFK tickets**. Viene activado.
  - Si el staff contestó y el usuario no responde, el bot le avisa cada 6 horas.
  - Si el usuario escribe y nadie del staff le responde, el moderador que reclamó el ticket recibe un aviso a los 30 minutos y otro a los 60. Con el segundo, el ticket se libera para el resto del equipo y se avisa en el canal de feedback del staff.

### Quitado
- **Connection Roles**, **Forums** y **Daily Questions (QOTD)**: borrados por completo. Daily Questions se rehará más adelante.
- `/support` e `/invite`: llevaban al servidor y al bot de Birb.
