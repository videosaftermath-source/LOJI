# Vanity y tag

Se configura en `/config` → **🏷️ Vanity y tag (LOJI)**. Solo el Tenno o un administrador.

- Quien lleva **la vanity en su estado personalizado** (`discord.gg/animetv`, también `.gg/animetv` o `/animetv`) **o el tag del servidor** junto a su nombre recibe los beneficios. Tener las dos cosas **no los duplica**.
- **Roles:** uno por la vanity y otro por el tag (opcionales, pueden ser el mismo). Se quitan solos cuando alguien se quita la vanity o el tag.
- **Economía:** multiplicador de ganancias (×1,1 por defecto; se suma al de booster), más suerte en el gacha (+20 %) y un premio de bienvenida que se paga **una sola vez** (250).
- **Tarjeta de anuncio** en el canal elegido. Hay **dos versiones**: una para quien se equipa el **TAG** y otra para quien pone la **vanity**
  (si lleva las dos cosas, sale la del TAG). Los **beneficios son los mismos** y llevar las dos cosas no da nada extra.
  - *Tarjeta: textos del TAG / de la vanity:* título, primeras líneas y nota de cada versión.
  - *Tarjeta: beneficios y pie:* compartidos por las dos.
  - *Tarjeta: color, imagen y botones:* color, imagen (`avatar`, `servidor`, `ninguna` o un enlace) y hasta 3 botones,
    uno por línea: `Etiqueta | emoji | #canal o https://enlace`.
  - **👁️ Vista previa** te enseña las dos, solo a ti.
  - Variables: `{user}` `{nombre}` `{avatar}` `{server}` `{cosa}` `{rol}` `{vanity}` `{tareas}` `{tareas_link}`. Una línea con `{rol}` o `{tareas}` vacíos no se muestra.
  - No se repite para la misma persona en 12 horas.
- **Detección:** al momento, cuando alguien cambia su estado o su tag, más una revisión de todo el servidor cada 20 minutos. El botón **🔄 Revisar ahora** lo aplica al instante.
- **Privacidad:** el texto del estado solo se lee para buscar la vanity y **nunca se guarda**; solo se guarda si cumple o no, y desde cuándo. Cualquiera puede dejar de participar con `/privacidad`.

Necesita el **Presence Intent** activado en el portal de desarrolladores (ya activado) y que el rol del bot esté por encima de los roles que da.
