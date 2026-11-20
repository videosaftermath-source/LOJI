# Comunidad (`/config` → 🌸 Comunidad)

Solo el Tenno o un administrador puede abrirlo.

La tarjeta de anuncio de supporters está en `/config` → **Vanity y tag** (ver `vanity.md`).
Si la misión "Llevar el TAG" ya da monedas, pon el premio de bienvenida de Vanity y tag a 0 para no pagar dos veces.

## 🪙 Tablero de misiones
Un mensaje fijo con banner, una fila por misión con botón **Reclamar** y **Ver mi progreso** (máximo 8 misiones).
Las misiones se crean en `/config` → Economía → Misiones; el tablero se actualiza solo.

Objetivos nuevos:
- **🎙️ Minutos en voz:** sin mute ni ensordecer, fuera del canal AFK y con al menos otra persona.
- **🏷️ Llevar el tag o la vanity** y **💎 Boostear el servidor:** se reclaman mientras se cumplan,
  una sola vez por cuenta (aunque se quiten y se vuelvan a poner).

`/misiones` sigue funcionando igual.

## 💬 Chat extra (General 2)
Cuando el chat principal recibe **X mensajes en Y segundos de al menos Z personas**, el bot abre el chat extra
y lo anuncia (en el extra y, si quieres, en el principal). Cuando el extra tiene **menos de X mensajes en Y minutos**
(y lleva abierto el mínimo), avisa "en 1 minuto cerraremos" y lo cierra; si alguien escribe en ese minuto, se cancela.

- Cerrado = **solo lectura** u **oculto** (en Umbrales).
- **Abrir ya / Cerrar ya** para probarlo a mano.
- El bot necesita **Gestionar canales** (o permisos) y **Enviar mensajes** en el chat extra.
- Funciona sin leer el contenido de los mensajes: solo cuenta cuántos hay y de quién.
