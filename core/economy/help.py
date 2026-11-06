"""The bot's guide: shown by /ayuda (one menu for everything) and copied into docs/comandos-economia.md."""

# (key, title, text). Each text stays under Discord's 4096-character embed description limit.
HELP_SECTIONS: list[tuple[str, str, str]] = [
    ("inicio", "🪙 Lo básico", """\
Gana créditos, colecciona mascotas y gástalos en la tienda, el gacha o el casino.

**`/saldo [usuario]`**: tu dinero en cartera y banco, tu racha y cuándo puedes volver a trabajar.
**`/trabajar`**: gana entre 50 y 150 créditos. Se puede usar cada hora.
**`/diario`**: recompensa diaria. Si lo reclamas todos los días, la racha da más (hasta 7 días). Si pasan 48 h sin reclamarlo, la racha se pierde.
**`/pagar <usuario> <cantidad>`**: pásale créditos a alguien. Paga un impuesto por tramos: cuanto más mandas, más porcentaje se cobra de la parte alta.
**`/top`**: los más ricos del servidor.

💬 **Chatear también da dinero** en los canales elegidos por el staff, si tienes al menos 250 créditos. Hay un tope diario y el spam no cuenta.
-# Los precios pueden subir si hay mucho dinero en circulación (inflación)."""),
    ("mascotas", "🐾 Mascotas", """\
Las mascotas salen del gacha. La **activa** te da una ventaja según su tipo:
🌾 **Farmeador**: más dinero en `/trabajar` · 🗣️ **Charlatán**: más dinero por chatear
🍀 **Suertudo**: menos ventaja para la casa en el casino · 💰 **Ahorrador**: descuento en tienda e impuestos
💸 **Rentista**: genera créditos con el tiempo. Cóbralos con **`/mascota cobrar`** (o el botón 💸). Se acumulan hasta 24 h y solo mientras esté activa, así que cobra antes de cambiarla.

**`/mascota ver [usuario]`**: la tarjeta de tu mascota, con botones para cuidarla.
**`/mascota lista`**: el álbum con todas tus mascotas.
**`/mascota alimentar`** / **`/mascota jugar`**: suben la comida y la felicidad (cuestan créditos).
**`/mascota renombrar`**: ponle un apodo.
**`/mascota activar <mascota>`**: elige cuál te acompaña.

📈 Ganan XP cuando trabajas, chateas, juegas y la cuidas. Con más nivel, la ventaja es mayor.
😿 Si no la cuidas, su ventaja baja. Al nivel indicado puede **evolucionar** (botón ✨ en la tarjeta)."""),
    ("gacha", "🎰 Gacha", """\
**`/gacha`**: abre los banners activos y tira x1 o x10. Salen mascotas, items y créditos.

⭐ Común · ⭐⭐ Rara · ⭐⭐⭐ Épica · ⭐⭐⭐⭐ Legendaria
• **Épica o mejor asegurada** cada 10 tiradas.
• **Legendaria asegurada** a las 90 tiradas. Desde la 74 la probabilidad sube mucho.
• **50/50:** si la legendaria no es la destacada del banner, la siguiente sí lo será.
• Si te sale una mascota repetida, la que ya tienes gana XP.
Las tiradas se cuentan por banner, y en el banner se ve cuánto te falta."""),
    ("casino", "🎲 Casino", """\
Todas las apuestas aceptan `500`, `1.5k`, `todo` o `mitad`. La casa gana un poco a la larga: juega por diversión.

**`/casino moneda`**: cara o cruz, casi doblas.
**`/casino slots`**: tragamonedas. Las parejas pagan poco; los tríos, mucho más (7️⃣7️⃣7️⃣ paga x832).
**`/casino tragamonedas`**: ✨ versión de lujo animada, con los mismos premios y un poco mejor para ti.
**`/casino crash`**: el multiplicador sube; retírate antes de que explote (hasta x20).
**`/casino blackjack`**: llega a 21 sin pasarte. Puedes pedir, plantarte o doblar.
**`/casino ruleta`**: color, par/impar, mitades, docenas o un número (x36).
**`/casino mines`**: abre casillas sin tocar minas. Más minas, más paga cada diamante. Al terminar: 🔁 Jugar de nuevo.
**`/casino mayormenor`**: adivina si la siguiente carta es mayor o menor.
**`/casino carrera`**: apuesta a un caballo. El favorito paga poco y el tapado mucho.
**`/casino marcha`**: 🃏 *La Larga Marcha*, un póker por antes estilo Balatro. Supera ciegas sumando señal, gana ◈ y compra comodines y mejoras en la tienda. Tras cada jefe, cobra (×0,6 a ×10) o sigue. Cada jefe tiene una regla especial, y el último es LOJI. 5 al día; sin cantidad, retomas la tuya.
**`/juegos`**: guía visual de todos los juegos del casino.
**`/tutorial marcha`**: aprende La Larga Marcha con una práctica gratis.
**`/casino info`**: límites, ventaja de la casa y tus estadísticas."""),
    ("tienda", "🛒 Tienda, misiones y banco", """\
**`/tienda`**: compra roles, consumibles y coleccionables. Si algo se compra mucho, sube de precio un tiempo.
**`/inventario [usuario]`**: lo que tienes.
**`/usar <item>`**: usa un consumible (boost temporal en trabajar, diario o chat).
**`/misiones`**: misiones diarias, semanales y únicas. Reclama el premio al completarlas.
**`/canjear <código>`**: canjea un código de regalo.

🏦 **Banco** (si el staff lo activa):
**`/banco ver`** · **`/banco depositar <cantidad>`** · **`/banco retirar <cantidad>`**
El dinero del banco genera intereses diarios. Retirar tiene una pequeña comisión."""),
    ("booster", "💎 Beneficios de booster", """\
Si boosteas el servidor:
• **x1.3** en todo lo que ganas con trabajar, diario, chat y voz.
• **Más suerte en el gacha:** la legendaria y la épica salen un 50% más. La pity es la misma para todos.
• **500 créditos** de regalo al boostear, una vez por boost.
Los beneficios duran mientras mantengas el boost."""),
    ("mando", "📮 Mando Central (staff)", """\
Herramientas del staff de LOJI:

**`/mail`**: escribe al Tenno: sugerencias, peticiones, dudas o reportes. Recibes la respuesta por MD.
**`/tareas`**: lo que hay que hacer, ordenado por prioridad y con filtros por departamento. Reclámalas y márcalas como hechas desde su mensaje.
-# Tenno y Consejo Supremo: botón **➕ Nueva tarea** para crearlas sin pasar por `/mail`.
**`/perfil ver [usuario]`**: el perfil de staff: cargo, tiempo en el cargo, departamento, especialización y calificación.
**`/perfil editar`**: escribe tu descripción y tu especialización.
**`/perfil panel`**: busca al staff por Departamento Administrativo, sub-unidades o departamento.
🎫 **Tickets:** al reclamar un ticket (o en tu primer mensaje en él), aparece tu tarjeta de perfil."""),
    ("admin", "🛠️ Administración", """\
**`/config`**: **todo** se configura aquí:
> 📮 **Mando Central**: departamentos, cargos, credenciales, canales y roles con perfil de staff (con asistente)
> 🪙 **Economía**: ganancias, chat, mascotas, gacha, casino, La Larga Marcha, inflación, banco y boosters
> Y lo de Birb: módulos, permisos, tickets, feedback...

**`/eco-admin`**: `dar` · `quitar` · `tienda` · `codigos` · `misiones` · `mascotas` · `regalar-mascota` · `gacha` · `stats` · `hacienda` · `desbloquear` · `reiniciar` · `cancelar-marcha`
**`/perfil sincronizar`** · **`/perfil fecha`**: perfiles de staff.
**`/anuncio`** y **`/embed`**: mensajes con el diseño de LOJI.
-# Precios recomendados y balance: docs/economia.md"""),

]


def HelpMarkdown() -> str:
    """The whole guide as Markdown (for the docs file)."""
    Parts = ["# Guía de LOJI\n", "En Discord: `/ayuda` (con un menú para cada sección).\n"]
    for _, Title, Text in HELP_SECTIONS:
        Body = "\n".join(L[3:] if L.startswith("-# ") else L for L in Text.splitlines())
        Parts.append(f"## {Title}\n\n{Body}\n")
    return "\n".join(Parts)
