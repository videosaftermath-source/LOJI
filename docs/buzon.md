# Buzón (sugerencias y tareas del staff)

Reemplaza al modmail. Fases: 1) departamentos, cargos y credenciales ✅ · 2) `/mail` y decisiones · 3) `/tareas` · 4) quitar el modmail.

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

## Comandos
- `/buzon config`: panel para el rol de staff, el canal de sugerencias, el canal «Cosas por debatir», los roles de los cargos, los departamentos (rol y canal de tareas; crear, renombrar, borrar) y las credenciales.
- `/buzon departamentos`: cómo está organizado el staff.

Departamentos iniciales: Moderación, Comité de Ética, Control de Calidad, Gestión de la Comunidad y Gestión del Staff (estos 4, en el grupo Mod Senior).

Datos: colección `mail_config` (un documento por servidor). Código: `core/mail/config.py` y `cogs/Modules/Mail/config.py`.
