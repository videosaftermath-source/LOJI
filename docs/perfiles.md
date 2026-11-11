# Perfiles y panel de staff

Tienen perfil de staff quienes tienen alguno de los **roles con perfil** que eligen los admins en `/config` → 📮 Mando Central. Es una lista propia, independiente de la jerarquía de Birb. El **cargo** de cada uno es el más alto de esos roles que tenga, según el orden de roles de Discord.

- **Automático:** `/perfil sincronizar` crea los perfiles del staff actual. Después se actualizan solos: si alguien sube de rango, su tiempo en el cargo vuelve a empezar; si deja el staff, el perfil se archiva y conserva su texto.
- **Cada perfil muestra:**
  - 🏷️ **Cargo**: su rol más alto.
  - ⏳ **Tiempo en el cargo**: se puede corregir con `/perfil fecha`.
  - 🏢 **Departamento**: sale de sus roles; Tenno, Consejo Supremo y Director forman el Departamento Administrativo.
  - 🎯 **Especialización** y 📝 **Descripción**: las escribe cada uno con `/perfil editar`.
  - ⭐ **Calificación**: media de `/feedback`, sobre 10.
- **`/perfil panel`:** busca por Departamento Administrativo, por sub-unidades (grupos, como Mod Senior) o por departamento, y abre el perfil de cualquiera.
- **Gestión** (Tenno, Consejo Supremo o administradores): `/perfil sincronizar` y `/perfil fecha`.

Los comandos viejos de Birb (`/staff add`, `remove`, `edit`, `view`, `introduction` y `panel`) están ocultos; quedan `/staff leaderboard` y `/staff list` (add/remove/send).

Datos: `StaffProfiles` (la misma ficha que usa `/gestion` para comentarios y sanciones) y `feedback`.

## Tickets
Los tickets son los de Birb, y se configuran en `/config` → Tickets.
- **Al reclamar** un ticket (con el botón o con `/tickets claim`), el bot publica la tarjeta **"🎫 Te atiende…"** con el perfil de quien lo reclamó: cargo, tiempo, departamento, especialización y calificación.
- Si alguien del staff **escribe en un ticket sin reclamarlo**, su tarjeta sale con su primer mensaje.
- Sale **una vez por persona y ticket**.

### Varias clases de ticket (p. ej. Comité de Ética)
Birb permite tantos paneles como quieras:
1. `/config` → **Tickets** → crea un **panel simple** por cada clase (por ejemplo «Reporte», «Reporte a staff», «Apelación»). Cada uno tiene su categoría, sus roles de staff y sus nombres de canal.
2. Para que el usuario elija la clase desde un solo mensaje, crea un **panel múltiple** que agrupe esos paneles.
3. Envíalo con `/tickets panel`.

Así «Reporte a staff» puede ir solo al rol del Comité de Ética, y «Reporte» a Moderación.

### Tickets privados al reclamar
Con la opción **🔒 Tickets privados** activada en `/config` → 📮 Mando Central (viene activada):
- Al **reclamar** un ticket, los roles de staff de su panel dejan de verlo. Solo lo ven quien lo reclamó y el autor.
- Al **transferirlo**, el acceso pasa a la otra persona.
- Al **soltarlo** (`/tickets unclaim`), el equipo vuelve a verlo.

Los administradores (permiso de Administrador de Discord) siempre ven todos los canales: eso no se puede cambiar.
