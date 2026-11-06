# Perfiles y panel de staff

Todos los que tienen un rol **igual o superior al rol mínimo** (configurable en `/buzon config`, según la jerarquía de roles de Discord) tienen perfil de staff.

- **Automático:** `/perfil sincronizar` crea los perfiles del staff actual. Después se actualizan solos: si alguien sube de rango, su tiempo en el cargo vuelve a empezar; si deja el staff, el perfil se archiva y conserva su texto.
- **Cada perfil muestra:**
  - 🏷️ **Cargo**: su rol más alto.
  - ⏳ **Tiempo en el cargo**: se puede corregir con `/perfil fecha`.
  - 🏢 **Departamento**: sale de sus roles; Tenno, Consejo Supremo y Director forman el Departamento Administrativo.
  - 🎯 **Especialización** y 📝 **Descripción**: las escribe cada uno con `/perfil editar`.
  - ⭐ **Calificación**: media de `/feedback`, sobre 10.
- **`/perfil panel`:** busca por Departamento Administrativo, por sub-unidades (grupos, como Mod Senior) o por departamento, y abre el perfil de cualquiera.
- **Gestión** (Tenno, Consejo Supremo o administradores): `/perfil sincronizar` y `/perfil fecha`.

Los comandos viejos de Birb (`/staff add`, `remove`, `edit`, `view`, `introduction`, `panel` y `list`) están ocultos; queda `/staff leaderboard`.

Datos: `StaffProfiles` (la misma ficha que usa `/gestion` para comentarios y sanciones) y `feedback`.
