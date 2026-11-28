# 📺 Anime
`/config` → **🎉 Crecimiento y Entretenimiento** → Anime: rol del equipo de anime, auditorio (escenario o voz), canal de
avisos al público, rol a avisar (opcional) y, en **⏰ Avisos**, cuántos minutos antes se avisa al público y al encargado y
el canal del staff (vacío = por MD). **📤 Publicar horario** deja el horario (imagen) en el canal de avisos y se actualiza solo.

## Comandos
- `/anime añadir titulo dia hora encargado [episodio] [total]` (equipo de anime o administración).
- `/anime editar anime …` (cambiar título, día, hora, encargado, episodio o total) y `/anime quitar anime`.
- `/horario anime` (cualquiera): el horario de la semana en imagen, de lunes a viernes (y el fin de semana si tiene algo).

## Cada transmisión
1. **X min antes (60 por defecto):** se avisa al encargado de que le toca (canal del staff o MD).
2. **X min antes (15 por defecto):** aviso al público con el rol, el episodio y el auditorio.
3. **Al empezar:** "🔴 ¡Empieza!" y al encargado le llegan botones para marcar **cuántos episodios** se emitieron
   (1, 2, 3 o "No se emitió"). La cuenta avanza sola y el horario se actualiza. Cuando se acaba el anime, LOJI lo dice.

Las horas son las del servidor (el desfase horario de `/config` → Economía).
