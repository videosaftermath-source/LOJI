# Comunidad (`/config` → 🌸 Comunidad)

Solo el Tenno o un administrador puede abrirlo.

La tarjeta de anuncio de supporters está en `/config` → **Vanity y tag** (ver `vanity.md`).
Si la misión "Llevar el TAG" ya da monedas, pon el premio de bienvenida de Vanity y tag a 0 para no pagar dos veces.

## 🪙 Tablero de misiones
Un mensaje fijo con banner, una fila por misión con botón **Cobrar** y **📊 Mi progreso** (máximo 8 misiones).
Viene preparado para Sótano Social (banner, color `#BBA896`, emoji de moneda); todo se cambia en **Textos y banner** y **Moneda y botones**.
**🪄 Misiones de ejemplo** crea las 4 de serie: 25 mensajes (250, diaria), 15 min en voz (300, diaria), llevar el tag (250, una vez)
y boostear (1.000, una vez).
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

## 💎 Boosts
Cuando alguien boostea, LOJI publica una tarjeta (Components V2) en el canal elegido: una vez por boost.
- **Textos:** título, línea bajo el título (`{fecha}` = booster desde), ventajas (una por línea) y pie.
- **Aspecto y botones:** color (por defecto rosa boost `#F47FFF`), imagen y hasta 3 botones de enlace.
- Las ventajas por defecto son **solo las de la economía** y salen de `/config` → Economía → Boosters:
  `{multiplicador}` (ganancias), `{suerte}` (gacha) y `{premio}` (lo que se regala al boostear, una vez).
  Si están apagadas, esas líneas no se muestran.
- Variables: `{user}` `{nombre}` `{server}` `{fecha}` `{boosts}` `{multiplicador}` `{suerte}` `{premio}` `{tareas}` `{tareas_link}`.
