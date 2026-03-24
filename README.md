# Omni Core v2.1 - The Supreme Coordinator

Omni Core ahora está pensado para Ubuntu real, migración rápida y recuperación automática.

Si copias esta carpeta por `scp`, funciona.
Si prefieres GitHub privado, también.
Si quieres traer snapshots de otros servidores, también.

## Cómo quedó apuntando

Si no existe `config/repos.json`, Omni conserva estos defaults lógicos:

- `~/melissa`
- `~/nova-cli`
- `~/.nova`
- la carpeta actual de `omni-core`

Eso mantiene la intención de tu Ubuntu original, pero sin amarrarlo a una ruta fija como `/home/ubuntu/omni-core`.

## Modos de despliegue

### 1. Carpeta copiada por SCP

```bash
scp -r omni-core ubuntu@tu-servidor:/opt/omni-core
ssh ubuntu@tu-servidor
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync
```

### 2. GitHub privado

```bash
git clone git@github.com:tu-org/omni-core-private.git /opt/omni-core
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync
```

### 3. Bootstrap de un solo comando

Si el servidor ya tiene acceso SSH a tu repo privado:

```bash
bash bootstrap.sh git@github.com:tu-org/omni-core-private.git /opt/omni-core main
```

Ese flujo:

- instala dependencias base de Ubuntu
- clona o actualiza el repo privado
- crea `.env`, `config/repos.json` y `config/servers.json` si faltan
- ejecuta `omni sync`
- levanta `docker compose`

## Recuperación automática

La carpeta ya incluye persistencia local:

- `config/`
- `data/`
- `backups/`
- `logs/`
- `tasks.json`

Y además puede jalar snapshots de otros servidores definidos en `config/servers.json`.

Los snapshots quedan en:

```text
data/servers/<server>/<ruta-remota-normalizada>/
```

## Inventario de servidores

Plantilla en:

- `config/servers.example.json`

Ejemplo:

```json
{
  "servers": [
    {
      "name": "main-ubuntu",
      "host": "1.2.3.4",
      "user": "ubuntu",
      "port": 22,
      "protocol": "rsync",
      "paths": [
        "/home/ubuntu/melissa",
        "/home/ubuntu/nova-cli",
        "/home/ubuntu/.nova",
        "/home/ubuntu/omni-core"
      ],
      "excludes": [".git", "__pycache__", "*.pyc", "node_modules"]
    }
  ]
}
```

## Comandos clave

```bash
omni help
omni status
omni sync
omni install
docker compose up -d --build
docker compose logs -f omni-core
```

## Instalación automática recomendada

```bash
cd /opt/omni-core
cp .env.example .env
cp config/repos.example.json config/repos.json
cp config/servers.example.json config/servers.json
nano .env
nano config/repos.json
nano config/servers.json
./install.sh --compose --sync
```

## Notas operativas

- `omni sync` trae archivos remotos por `rsync` o `scp`
- para GitHub privado, el servidor destino debe tener clave SSH o credenciales válidas
- dentro de Docker, el mantenimiento del sistema afecta al contenedor; los snapshots remotos se siguen trayendo desde el host donde corre Omni
- si quieres automatización total al migrar, la mejor base es: repo privado + `bootstrap.sh` + `config/servers.json`
