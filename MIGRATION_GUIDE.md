OMNI CORE
Guia breve de migracion y recuperacion
Repositorio privado: sxrubyo/omni-core

========================================================================
1. OBJETIVO
========================================================================

Esta guia sirve para migrar Omni Core a una nueva instancia Ubuntu y
recuperar la operacion con el menor numero de pasos posible.

Modos soportados:

1. Copiar la carpeta por SCP
2. Clonar desde GitHub privado
3. Bootstrap automatico con un solo comando


========================================================================
2. OPCION RECOMENDADA
========================================================================

Usar GitHub privado + bootstrap:

1. El nuevo servidor obtiene acceso al repo privado
2. Se clona o actualiza sxrubyo/omni-core
3. Se ejecuta install.sh con sincronizacion y Docker Compose

Comando recomendado:

  bash bootstrap.sh git@github.com:sxrubyo/omni-core.git /opt/omni-core main


========================================================================
3. PREPARACION DE ACCESO A GITHUB
========================================================================

Opcion A. SSH con deploy key o clave del servidor

Generar clave en el servidor:

  ssh-keygen -t ed25519 -C "omni-core-migration" -f ~/.ssh/id_ed25519

Ver la clave publica:

  cat ~/.ssh/id_ed25519.pub

Agregar esa clave en GitHub:

  Repo: sxrubyo/omni-core
  Settings -> Deploy keys -> Add deploy key

Probar acceso:

  ssh -T git@github.com


Opcion B. GitHub CLI

Instalar GitHub CLI:

  sudo apt-get update
  sudo apt-get install -y gh

Iniciar sesion:

  gh auth login

Verificar sesion:

  gh auth status


========================================================================
4. MIGRACION DESDE GITHUB PRIVADO
========================================================================

Clonar manualmente:

  git clone git@github.com:sxrubyo/omni-core.git /opt/omni-core
  cd /opt/omni-core
  chmod +x install.sh bin/omni bootstrap.sh
  cp .env.example .env
  cp config/repos.example.json config/repos.json
  cp config/servers.example.json config/servers.json
  ./install.sh --compose --sync

Actualizacion posterior:

  cd /opt/omni-core
  git pull --ff-only
  ./install.sh --compose --sync


========================================================================
5. MIGRACION DESDE CARPETA COPIADA POR SCP
========================================================================

Desde el servidor origen o desde tu maquina:

  scp -r omni-core ubuntu@IP_DESTINO:/opt/omni-core

Luego en el servidor destino:

  ssh ubuntu@IP_DESTINO
  cd /opt/omni-core
  chmod +x install.sh bin/omni bootstrap.sh
  cp .env.example .env
  cp config/repos.example.json config/repos.json
  cp config/servers.example.json config/servers.json
  ./install.sh --compose --sync


========================================================================
6. BOOTSTRAP AUTOMATICO
========================================================================

Si el servidor ya tiene acceso al repo privado, usar directamente:

  bash bootstrap.sh git@github.com:sxrubyo/omni-core.git /opt/omni-core main

Este comando:

  - instala dependencias base
  - clona o actualiza el repo
  - prepara .env y archivos de config si faltan
  - ejecuta omni sync
  - levanta Docker Compose


========================================================================
7. ARCHIVOS A REVISAR ANTES DE LEVANTAR
========================================================================

Editar:

  /opt/omni-core/.env
  /opt/omni-core/config/repos.json
  /opt/omni-core/config/servers.json
  /opt/omni-core/tasks.json

Puntos importantes:

  - OMNI_TELEGRAM_TOKEN
  - SANTIAGO_CHAT_ID
  - rutas reales de repositorios en Ubuntu
  - inventario de servidores remotos para omni sync


========================================================================
8. COMANDOS OPERATIVOS
========================================================================

Ayuda:

  omni help

Estado:

  omni status

Sincronizar snapshots remotos:

  omni sync

Ver configuracion:

  omni config

Levantar stack:

  docker compose up -d --build

Ver contenedores:

  docker compose ps

Ver logs:

  docker compose logs -f omni-core

Reinstalar o reconciliar:

  ./install.sh --compose --sync


========================================================================
9. VALIDACION POST-MIGRACION
========================================================================

Ejecutar:

  docker compose ps
  docker compose logs -f omni-core
  omni status
  omni sync

Comprobar que existan:

  /opt/omni-core/config
  /opt/omni-core/data
  /opt/omni-core/backups
  /opt/omni-core/logs


========================================================================
10. RECOMENDACION FINAL
========================================================================

El camino mas limpio para futuras migraciones es:

  GitHub privado + bootstrap.sh + config/servers.json

Con eso, una nueva instancia Ubuntu puede quedar operativa con:

  git clone o bootstrap
  ./install.sh --compose --sync

Fin.
