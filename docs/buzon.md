# Buzón (sugerencias y tareas del staff)

Reemplaza al modmail. Fases: 1) departamentos, cargos y credenciales ✅ · 2) `/mail` y decisiones ✅ · 3) `/tareas` ✅ · 4) quitar el modmail ✅.

## Permisos
- **Por rol.** Cada departamento y cada cargo está ligado a un rol de Discord.
- **Credenciales:** solo las tienen los 3 cargos (Tenno, Consejo Supremo, Director de Moderación). Son un **atajo opcional** para actuar sin el rol. Formato: letra + 4 números (`M-1808`). Se guardan **cifradas** (PBKDF2), nunca en el código, y solo se muestran una vez al crearlas. Tras 5 intentos fallidos, la persona queda bloqueada 10 minutos.

| Quién | Puede |
|---|---|
| Staff (rol de staff) | enviar sugerencias con `/mail` (con nombre) |
| Tenno, Consejo Supremo | decidir sugerencias (✅ / 💬 / ❌) |
| Tenno, Consejo Supremo, Director de Moderación | abrir, cerrar y reabrir cualquier tarea |
| Rol del departamento | reclamar y cerrar las tareas de su departamento |
| Tenno (o un administrador del servidor) | configurar el buzón |

## `/mail`
1. El staff escribe título y sugerencia, y se publica en el canal de sugerencias con **✅ Se realizará / 💬 Se debatirá / ❌ Rechazada**.
2. Al pulsar un botón se pide el **porqué**. Si no tienes el rol de Tenno o de Consejo Supremo, también la **credencial**.
3. **Se realizará:** además se elige **quién se encarga**: un departamento, **🙋 Lo haré yo** (la tarea queda a tu cargo y nadie más la toma) o **✅ Ya lo hice** (queda resuelta al momento). También la **prioridad** (alta, media o baja).
4. **Se debatirá:** se publica una copia en «Cosas por debatir», donde solo se puede aceptar o rechazar. Al decidir, se actualizan las dos.
5. El autor recibe cada decisión por **MD**. Los botones siguen funcionando aunque el bot se reinicie.

Datos: `mail_suggestions` (numeradas por servidor) y `mail_counters`.

## Tareas
- Cada **Se realizará** crea una **tarea** (con su propio número). Se publica en el **canal del departamento**, mencionando a su rol, y la sugerencia original muestra su estado.
- Botones: **🙋 Reclamar · ✅ Hecha · ↩️ Soltar · 🔄 Reabrir**. Siguen funcionando aunque el bot se reinicie.
  - Reclamar y marcar como hecha: cualquiera con **el rol del departamento**.
  - Soltar: quien la reclamó.
  - Reabrir y actuar sobre cualquier tarea: Tenno, Consejo Supremo y Director de Moderación, por rol o con su credencial.
- Al terminarla, el autor de la sugerencia recibe un MD.
- **➕ Nueva tarea** (botón en `/tareas`): Tenno y Consejo Supremo, por rol o con credencial, crean tareas sin pasar por `/mail`.
- `/tareas` (staff): lista ordenada por prioridad, con filtros por departamento y estado (abiertas, sin reclamar, reclamadas, hechas). Empieza en tu departamento si perteneces a uno solo.

Datos: `mail_tasks`.

## Comandos
- `/config` → 📮 Mando Central: lista de verificación (qué falta configurar), **🧭 asistente** paso a paso y panel para el rol de staff, el canal de sugerencias, el canal «Cosas por debatir», los roles de los cargos, los departamentos (rol y canal de tareas; crear, renombrar, borrar) y las credenciales.
- El organigrama del staff se ve en `/perfil panel`.

Departamentos iniciales: Moderación, Comité de Ética, Control de Calidad, Gestión de la Comunidad y Gestión del Staff (estos 4, en el grupo Mod Senior).

Datos: colección `mail_config` (un documento por servidor). Código: `core/mail/config.py` y `cogs/Modules/Mail/config.py`.
