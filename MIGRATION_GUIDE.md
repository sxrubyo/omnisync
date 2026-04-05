# Omni Core - Migration Guide

Repositorio: `sxrubyo/omni-core`

Esta guía describe el flujo productivo limpio recomendado para mover Omni Core entre máquinas, reconstruir un host desde cero y mantener el estado sincronizado sin arrastrar ruido innecesario.

## 1. Principio de migración

No se recomienda clonar `/home/ubuntu` completo.

La estrategia correcta es separar:

- **inventory**: qué existe y cómo se clasifica
- **bundle state**: lo restaurable y productivo
- **secrets pack**: credenciales y secretos cifrados
- **reconcile**: restauración idempotente
- **timer**: mantenimiento diario automático

## 2. Qué entra en cada paquete

### Bundle state

Debe incluir, como mínimo:

- `config/`
- `data/`
- `backups/`
- `logs/`
- `tasks.json`
- manifests de despliegue útiles
- snapshots de servidores remotos definidos por Omni Core

### Secrets pack

Debe incluir por separado y cifrado:

- `.env`
- tokens de API
- credenciales SSH
- llaves de despliegue
- sesiones sensibles
- cualquier dato que no deba quedar en Git

### Qué no viajar por defecto

- `node_modules`
- `.cache`
- `__pycache__`
- logs históricos que se regeneran solos
- temporales
- artefactos de build

## 3. Flujo recomendado

### Paso 1. Exportar inventario

Antes de migrar:

- revisar rutas reales
- clasificar estado vs. ruido
- identificar repos, configs y servidores remotos

### Paso 2. Exportar bundle de estado

Guardar:

- `config/`
- `data/`
- `backups/`
- `logs/`
- `tasks.json`

### Paso 3. Exportar secretos

Guardar aparte y cifrar.

Nunca mezclar con el bundle de estado.

### Paso 4. Bootstrap del host nuevo

Usar uno de estos caminos:

```bash
bash bootstrap.sh git@github.com:sxrubyo/omni-core.git /opt/omni-core main
```

o desde otra máquina:

```powershell
pwsh ./bootstrap.ps1 -TargetHost 1.2.3.4 -User ubuntu -RepoUrl git@github.com:sxrubyo/omni-core.git -Destination /opt/omni-core -Branch main
```

### Paso 5. Importar bundle y secretos

Restaurar primero el bundle de estado.

Después importar el secrets pack cifrado.

### Paso 6. Reconciliar

Ejecutar:

```bash
omni fix
omni sync
```

La idea es que la operación sea repetible y no destructiva.

### Paso 7. Dejar el timer diario

El host debe quedar con una tarea programada cada 24 horas para:

- refrescar el repo
- ejecutar `omni fix`
- ejecutar `omni sync`
- validar salud del stack

## 4. Migración desde GitHub privado

Si el host tiene acceso SSH al repo privado:

```bash
git clone git@github.com:sxrubyo/omni-core.git /opt/omni-core
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
cp .env.example .env
cp config/repos.example.json config/repos.json
cp config/servers.example.json config/servers.json
./install.sh --compose --sync
```

Actualización posterior:

```bash
cd /opt/omni-core
git pull --ff-only
./install.sh --compose --sync
omni fix
omni sync
```

## 5. Migración desde SCP

Si ya copiaste la carpeta:

```bash
scp -r omni-core ubuntu@IP_DESTINO:/opt/omni-core
ssh ubuntu@IP_DESTINO
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync
```

## 6. Bootstrap remoto por PowerShell

El archivo `bootstrap.ps1` sirve para lanzar el bootstrap remoto sobre un host Linux por SSH.

Uso típico:

```powershell
pwsh ./bootstrap.ps1 -TargetHost 1.2.3.4 -User ubuntu -RepoUrl git@github.com:sxrubyo/omni-core.git -Destination /opt/omni-core -Branch main -InstallTimer
```

Ese wrapper:

- valida que exista `ssh`
- se conecta al host Linux
- instala dependencias base
- clona o actualiza el repo
- ejecuta `install.sh --compose --sync`
- puede instalar el timer diario si se solicita con `-InstallTimer`

## 7. Validación después de migrar

Comprobar:

```bash
omni status
omni inventory
omni bundle-create
omni secrets-export
omni reconcile --bundle-latest --secrets-latest
omni purge
omni sync
omni fix
docker compose ps
docker compose logs -f omni-core
```

Verificar también:

- `/opt/omni-core/config`
- `/opt/omni-core/data`
- `/opt/omni-core/backups`
- `/opt/omni-core/logs`

## 8. Liberar espacio sin romper el host

Si el host ya quedó reconstruido y necesitas recuperar disco, sin borrar los repos que se pueden volver a clonar desde GitHub:

```bash
omni purge
omni purge --yes
```

Si también quieres borrar secretos restaurados desde bundle:

```bash
omni purge --include-secrets --yes
```

Ese comando:

- elimina bundles, snapshots y backups locales de Omni
- borra estado transferido que no vive en Git
- limpia artefactos pesados dentro de repos Git como `node_modules`, `.venv`, `build` y `dist`

## 9. Recomendación final

El mejor flujo para reinstalaciones futuras es:

1. repo privado
2. bundle de estado
3. secrets pack cifrado
4. bootstrap remoto
5. reconcile
6. timer diario

Con eso se puede levantar Omni Core en otra máquina sin depender de copiar basura ni de restauraciones manuales una por una.
