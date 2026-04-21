# Omni Core - Guía de instalación desde PowerShell

Esta guía es para lanzar `omni-core` desde una PC con Windows usando PowerShell, dejando el bootstrap real sobre un host Linux remoto.

La experiencia nueva recomendada es:

1. PowerShell entra al Linux remoto
2. Linux instala `omni-core`
3. tú usas `omni` o `omni start`
4. eliges `bridge`, `capture`, `restore`, `migrate` o `doctor`
5. si quieres llevarte todo `/home/ubuntu`, activas `omni init --profile full-home`

## Qué entra cuando usas `full-home`

Si activas `full-home`, Omni toma `/home/ubuntu` entero como estado. Eso incluye también `.codex`, `.agents`, `.nova`, `.n8n` y carpetas pesadas como `melissa-backups`.

`melissa-backups` importa si quieres una reconstrucción realmente completa. Es histórico de respaldos de Melissa y puede ocupar bastante disco.

## Si pones el repo público por unos segundos

Eso sí puede simplificar el `clone` inicial de `omni-core` desde una máquina virgen.

Pero no reemplaza una migración real. GitHub público solo te ayuda con el código del bootstrap. El resto sigue viajando por:

- `state bundle`
- `secrets bundle`
- restore/migrate

## Qué ya hace Omni automáticamente

Cuando el host ya tiene `capture summary`, Omni puede trabajar mucho más solo:

- `omni start` y `omni doctor` detectan drift de host
- `omni migrate` corrige referencias del host anterior automáticamente
- `omni rewrite-ip --apply` sigue disponible si quieres forzarlo a mano
- `omni init`, `omni restore`, `omni migrate` y `omni rewrite-ip --apply` dejan backup automático en `backups/auto-bundles`
- el timer diario también corre backup antes de `fix` y `sync`

Si no quieres entrar en claves, `pem` o SSH remoto desde PowerShell, usa mejor esta guía:

- [GUIA_INSTALACION_SIMPLE_GITHUB.md](/home/ubuntu/omni-core/GUIA_INSTALACION_SIMPLE_GITHUB.md)

El wrapper de entrada es:

- [bootstrap.ps1](/home/ubuntu/omni-core/bootstrap.ps1)

El bootstrap real ocurre en el servidor Linux.
PowerShell solo actúa como lanzador remoto por SSH.

## Qué necesitas antes

En tu PC con Windows:

- PowerShell 7 recomendado
- `ssh` disponible en la terminal
- acceso al repo privado `sxrubyo/omni-core`
- una clave SSH válida para entrar al servidor Linux

En el servidor Linux destino:

- Ubuntu o Linux con `sudo`
- acceso de salida a GitHub
- Docker permitido

## Paso 1. Llevar `omni-core` a tu PC

Puedes hacerlo de dos maneras.

### Opción A. Clonar el repo privado

```powershell
git clone https://github.com/sxrubyo/omni-core.git
cd .\omni-core
```

### Opción B. Copiar la carpeta actual

Si ya tienes la carpeta en otra máquina, cópiala a tu PC y entra a ella:

```powershell
cd C:\ruta\omni-core
```

## Paso 2. Verificar acceso SSH al servidor

Prueba primero que puedes entrar:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR
```

Si usas una clave concreta:

```powershell
ssh -i C:\ruta\tu-clave.pem ubuntu@IP_DEL_SERVIDOR
```

Si esto falla, no sigas con `bootstrap.ps1`.

## Paso 3. Ejecutar el bootstrap remoto

Ejemplo mínimo.
Si no pasas `-Destination`, el script ahora:

- escanea el host remoto
- recomienda ubicaciones típicas
- te deja elegir una opción
- o escribir una ruta personalizada

```powershell
pwsh .\bootstrap.ps1 `
  -TargetHost IP_DEL_SERVIDOR `
  -User ubuntu `
  -RepoUrl git@github.com:sxrubyo/omni-core.git `
  -Branch main
```

Ejemplo fijando destino manualmente:

```powershell
pwsh .\bootstrap.ps1 `
  -TargetHost IP_DEL_SERVIDOR `
  -User ubuntu `
  -RepoUrl git@github.com:sxrubyo/omni-core.git `
  -Destination /opt/omni-core `
  -Branch main
```

Ejemplo completo con clave SSH y timer diario:

```powershell
pwsh .\bootstrap.ps1 `
  -TargetHost IP_DEL_SERVIDOR `
  -User ubuntu `
  -Port 22 `
  -IdentityFile C:\ruta\tu-clave.pem `
  -RepoUrl git@github.com:sxrubyo/omni-core.git `
  -Destination /opt/omni-core `
  -Branch main `
  -InstallTimer `
  -TimerOnCalendar daily
```

Qué hace ese comando:

- entra por SSH al servidor Linux
- si no fijaste `-Destination`, escanea y recomienda rutas como `/opt/omni-core`, `/home/ubuntu/omni-core` o `/srv/omni-core`
- instala paquetes base si faltan
- clona o actualiza `omni-core`
- puedes activar `omni init --profile full-home` antes de capturar si quieres migrar todo `/home/ubuntu`
- ejecuta `install.sh --compose --sync`
- opcionalmente instala el timer diario

## Paso 4. Verificar que quedó bien

Desde tu PowerShell:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni"
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni doctor"
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni inventory"
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && docker compose ps"
```

Si instalaste el timer:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "sudo systemctl status omni-update.timer --no-pager"
```

## Paso 5. Exportar bundles desde el servidor actual

Si quieres mover también estado real y secretos desde otra máquina Linux:

```bash
cd /opt/omni-core
export OMNI_SECRET_PASSPHRASE='TU_PASSPHRASE'
omni capture --accept-all
```

Eso te dejará bundles en:

- `/opt/omni-core/backups/host-bundles/`

## Paso 6. Copiar bundles al nuevo servidor

Desde tu PowerShell:

```powershell
scp .\state_bundle_YYYYMMDD_HHMMSS.tar.gz ubuntu@IP_DEL_SERVIDOR:/tmp/
scp .\secrets_bundle_YYYYMMDD_HHMMSS.tar.gz.enc ubuntu@IP_DEL_SERVIDOR:/tmp/
```

## Paso 7. Restaurar estado y secretos en el servidor nuevo

Desde PowerShell:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "export OMNI_SECRET_PASSPHRASE='TU_PASSPHRASE' && cd /opt/omni-core && omni restore --bundle /tmp/state_bundle_YYYYMMDD_HHMMSS.tar.gz --secrets /tmp/secrets_bundle_YYYYMMDD_HHMMSS.tar.gz.enc --accept-all"
```

Si además quieres reconstruir y corregir referencias del host:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "export OMNI_SECRET_PASSPHRASE='TU_PASSPHRASE' && cd /opt/omni-core && omni migrate --bundle /tmp/state_bundle_YYYYMMDD_HHMMSS.tar.gz --secrets /tmp/secrets_bundle_YYYYMMDD_HHMMSS.tar.gz.enc --accept-all --apply"
```

## Paso 8. Liberar espacio después

Si el host ya quedó instalado y quieres recuperar disco:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni purge"
```

Para borrar de verdad:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni purge --yes"
```

Si además quieres incluir secretos restaurados:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni purge --include-secrets --yes"
```

## Errores comunes

### `pwsh` no existe

Instala PowerShell 7 o ejecuta el script desde una consola PowerShell que soporte `.ps1`.

### `ssh` no existe

Activa OpenSSH Client en Windows o instala Git for Windows.

### No puede clonar el repo privado

Revisa:

- tu acceso al repo
- la clave SSH del servidor Linux
- que GitHub acepte esa clave

### `sudo` pide interacción en el servidor

El usuario remoto debe tener permisos suficientes para instalar paquetes y timer.

## Comando recomendado para tu primera prueba

Si quieres probar lo mínimo desde tu PowerShell:

```powershell
pwsh .\bootstrap.ps1 `
  -TargetHost IP_DEL_SERVIDOR `
  -User ubuntu `
  -IdentityFile C:\ruta\tu-clave.pem `
  -RepoUrl git@github.com:sxrubyo/omni-core.git `
  -Destination /opt/omni-core `
  -Branch main `
  -InstallTimer
```

Luego valida:

```powershell
ssh ubuntu@IP_DEL_SERVIDOR "cd /opt/omni-core && omni doctor && omni inventory"
```
