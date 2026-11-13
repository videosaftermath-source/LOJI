# Feedback del staff

- **`/feedback dar staff nota comentario`**: valora a alguien del staff del 1 al 10. El comentario es opcional. Puedes valorar a la misma persona una vez por semana, y no puedes valorarte a ti mismo.
- **`/feedback ver staff`**: muestra la media y las últimas valoraciones. Los administradores ven además quién la dio y el número de cada una.
- **`/feedback borrar id`**: borra una valoración (solo administradores).

**Al cerrar un ticket**
- Al pulsar 🔒 Close, el bot pide "¿Cómo se solucionó?".
- El usuario recibe un MD con la solución, quién le atendió y un botón **⭐ Dejar feedback**.
- Con ese botón valora a quien reclamó el ticket o, si nadie lo reclamó, a quien lo cerró. Puede hacerlo una vez por ticket, y el botón funciona aunque el bot se reinicie.

**¿Quién es staff?** Quien tenga el rol de staff, uno de los roles con perfil o uno de los cargos. Todo eso se configura en `/config` → Mando Central.

**¿Dónde se publica?** En el "Canal de feedback del staff" (`/config` → Mando Central). Si no hay uno puesto, usa el canal del módulo viejo de Birb.

La media de las valoraciones aparece en el perfil de staff (`/perfil`).
