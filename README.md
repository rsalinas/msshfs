# msshfs

`msshfs` és una utilitat personal per a muntar directoris remots via **SSHFS** de manera estructurada, previsible i còmoda.

La idea principal és evitar punts de muntatge improvisats com `/tmp/x` i usar una jerarquia estable dins del directori de l’usuari:

```text
~/mnt/sshfs/<host>/<ruta-absoluta-remota>
```

Per exemple:

```bash
msshfs myserver Project
```

pot acabar muntant:

```text
myserver:/home/myuser/Project
```

en:

```text
~/mnt/sshfs/myserver/home/myuser/Project
```

---

## Característiques

* Munta directoris remots amb `sshfs`.
* Accepta rutes remotes relatives al `$HOME` remot.
* Accepta rutes absolutes.
* Accepta rutes amb `~` remot.
* Crea una jerarquia local estructurada sota `~/mnt/sshfs`.
* Evita muntar damunt de directoris locals no buits, llevat que s’indique explícitament.
* Permet veure la ruta local abans o després del muntatge.
* Permet desmuntar amb `fusermount3`, `fusermount` o `umount`.
* Inclou completació Bash pròpia:

  * completa hosts SSH;
  * completa rutes remotes;
  * completa algunes opcions i subordres.

---

## Dependències

En Ubuntu/Debian:

```bash
sudo apt install sshfs bash-completion
```

També cal tindre accés SSH funcional als hosts que vulgues muntar.

Per exemple:

```bash
ssh myserver
```

hauria de funcionar abans d’usar:

```bash
msshfs myserver Project
```

---

## Instal·lació

Copia el script com a `msshfs` dins de `~/.local/bin`:

```bash
install -Dm755 msshfs ~/.local/bin/msshfs
```

Comprova que el shell troba l’executable correcte:

```bash
type -a msshfs
```

Si `~/.local/bin` no està al `PATH`, afegeix-lo al teu `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Després recarrega la configuració:

```bash
source ~/.bashrc
```

---

## Ús ràpid

### Muntar el `$HOME` remot

```bash
msshfs myserver
```

Equival a:

```bash
msshfs mount myserver ~
```

### Muntar una ruta relativa al `$HOME` remot

```bash
msshfs myserver Project
```

Resol remotament `Project` com:

```text
$HOME/Project
```

### Muntar una ruta absoluta

```bash
msshfs myserver /var/www
```

### Muntar una ruta amb `~` remot

```bash
msshfs myserver '~/Project'
```

Les cometes són recomanables perquè el `~` no l’expandisca el shell local.

---

## Sintaxi

```text
msshfs [OPCIONS_GLOBALS] HOST [REMOTE_PATH]
msshfs [OPCIONS_GLOBALS] mount HOST [REMOTE_PATH]
msshfs [OPCIONS_GLOBALS] umount HOST [REMOTE_PATH]
msshfs [OPCIONS_GLOBALS] status HOST [REMOTE_PATH]
msshfs [OPCIONS_GLOBALS] path HOST [REMOTE_PATH]
msshfs [OPCIONS_GLOBALS] list
msshfs completion bash
```

La forma curta:

```bash
msshfs HOST [REMOTE_PATH]
```

és equivalent a:

```bash
msshfs mount HOST [REMOTE_PATH]
```

---

## Resolució de rutes remotes

`msshfs` resol la ruta en la màquina remota abans de muntar.

| Entrada    | Interpretació remota |
| ---------- | -------------------- |
| sense ruta | `$HOME` remot        |
| `~`        | `$HOME` remot        |
| `~/dir`    | `$HOME/dir`          |
| `dir`      | `$HOME/dir`          |
| `/dir`     | `/dir`               |

Exemples:

```bash
msshfs myserver
msshfs myserver Project
msshfs myserver ~/Project
msshfs myserver /srv/dades
```

Compte amb `~/Project`: si no poses cometes, el teu shell local pot expandir `~` abans que el script el reba.

Millor:

```bash
msshfs myserver '~/Project'
```

---

## Jerarquia local de muntatge

Per defecte, els muntatges es creen sota:

```text
~/mnt/sshfs
```

La ruta remota absoluta queda reflectida dins del punt local.

Exemple:

```bash
msshfs myserver Project
```

Si `Project` es resol com:

```text
/home/myuser/Project
```

el punt local serà:

```text
~/mnt/sshfs/myserver/home/myuser/Project
```

Això fa que el resultat siga llarg, però molt explícit i sense ambigüitats.

---

## Canviar el directori base

Pots canviar el directori base amb `--base`:

```bash
msshfs --base ~/Mounts myserver Project
```

Això muntaria sota:

```text
~/Mounts/myserver/home/myuser/Project
```

En la versió actual, les opcions globals van abans de la subordre o del host:

```bash
msshfs --dry-run myserver Project
msshfs --base ~/Mounts myserver Project
```

---

## Veure què faria sense muntar

Usa `--dry-run`:

```bash
msshfs --dry-run myserver Project
```

Això imprimeix el comandament `sshfs` que s’executaria.

---

## Veure detalls de diagnòstic

Usa `--verbose` (o `-v`) per imprimir per `stderr` la ruta remota resolta, el
punt local de muntatge i els comandaments que s’executen:

```bash
msshfs -v myserver Project
msshfs -v umount myserver Project
```

A més, `-v` propaga la verbositat a l’`ssh` subjacent: la resolució de la ruta
remota s’executa amb `ssh -v` (i la seva sortida de depuració es mostra en
directe, sense capturar) i el muntatge afegeix `-o LogLevel=DEBUG` a `sshfs`.
Això és útil per veure on es queda penjada una connexió: un muntatge correcte
passa a segon pla com sempre, però un de penjat es queda en primer pla mostrant
la depuració d’`ssh`.

A diferència de `--dry-run`, `--verbose` sí que executa les accions.

---

## Imprimir només la ruta local

Amb la subordre `path`:

```bash
msshfs path myserver Project
```

O després de muntar, amb `--print`:

```bash
msshfs myserver Project --print
```

Nota: segons la versió actual del parser, és més segur usar les opcions globals abans del host; les opcions pròpies de `mount`, com `--print`, pertanyen a la subordre `mount`.

Forma explícita:

```bash
msshfs mount myserver Project --print
```

---

## Obrir el directori després de muntar

```bash
msshfs mount myserver Project --open
```

Això usa `xdg-open` sobre el punt local de muntatge.

---

## Desmuntar

```bash
msshfs umount myserver Project
```

Això resol la mateixa ruta remota, calcula el punt local i el desmunta.

Per a desmuntatge mandrós (*lazy unmount*):

```bash
msshfs umount myserver Project --lazy
```

O:

```bash
msshfs umount myserver Project -z
```

---

## Consultar l’estat

```bash
msshfs status myserver Project
```

Retorna estat d’èxit si està muntat i estat d’error si no ho està.

---

## Llistar muntatges actius

```bash
msshfs list
```

Mostra muntatges SSHFS actius sota el directori base configurat.

---

## Completació Bash

El script inclou un motor propi de completació Bash.

### Instal·lar la completació

```bash
mkdir -p ~/.local/share/bash-completion/completions
msshfs completion bash > ~/.local/share/bash-completion/completions/msshfs
```

Carrega-la en la sessió actual:

```bash
source ~/.local/share/bash-completion/completions/msshfs
```

O obri una terminal nova.

### Proves

```bash
msshfs <TAB>
msshfs mount <TAB>
msshfs mys<TAB>
msshfs myserver <TAB>
msshfs umount myserver <TAB>
```

### Fonts de hosts SSH

La completació de hosts llig principalment de:

```text
~/.ssh/config
~/.ssh/known_hosts
```

Els àlies definits en `~/.ssh/config` són els més útils:

```sshconfig
Host myserver
    HostName 203.0.113.10
    User myuser
```

Això permet:

```bash
msshfs myserver Project
```

---

## Fer ràpida la completació remota

La completació de rutes remotes fa consultes SSH.

Per evitar que cada pulsació de `<TAB>` òbriga una connexió nova, és molt recomanable activar multiplexació SSH en `~/.ssh/config`:

```sshconfig
Host *
    ControlMaster auto
    ControlPath ~/.ssh/control-%C
    ControlPersist 10m
```

Això reutilitza connexions SSH durant uns minuts i fa la completació molt més fluida.

---

## Opcions SSHFS addicionals

Pots passar opcions extra a `sshfs` amb `--sshfs-option` o `-o`:

```bash
msshfs --sshfs-option follow_symlinks myserver Project
```

O:

```bash
msshfs -o follow_symlinks myserver Project
```

Les opcions per defecte són:

```text
reconnect
ServerAliveInterval=15
ServerAliveCountMax=3
```

---

## Seguretat i comportament prudent

Per defecte, `msshfs` evita muntar sobre un directori local que ja conté fitxers.

Això evita accidents com escriure dades locals pensant que s’està treballant sobre el muntatge remot.

Si realment vols permetre-ho:

```bash
msshfs mount myserver Project --allow-non-empty
```

No s’usa `allow_other` per defecte. Això és intencionat: els muntatges són personals de l’usuari que els crea.

---

## Diferència amb la sintaxi clàssica de SSHFS

`sshfs` normalment usa:

```bash
sshfs myserver:Project ~/punt-local
```

`msshfs` separa host i ruta en dos arguments:

```bash
msshfs myserver Project
```

No uses:

```bash
msshfs myserver:Project
```

Això no és la sintaxi esperada per esta eina.

---

## Exemples habituals

```bash
# Muntar el HOME remot
msshfs myserver

# Muntar ~/Project remot
msshfs myserver Project

# Muntar ruta absoluta
msshfs myserver /srv/dades

# Veure el comandament sshfs sense executar-lo
msshfs --dry-run myserver Project

# Saber on quedarà muntat
msshfs path myserver Project

# Desmuntar
msshfs umount myserver Project

# Llistar muntatges actius
msshfs list
```

---

## Limitacions conegudes

* La completació remota depén de poder entrar per SSH sense interacció.
* Si el host no és accessible, la completació de rutes simplement no mostrarà resultats.
* Les rutes amb espais haurien de citar-se correctament en el shell.
* La sintaxi `host:ruta` no està suportada; usa `host ruta`.
* Les opcions globals són més fiables abans de la subordre o del host.

---

## Filosofia

`msshfs` prioritza una convenció clara:

```text
~/mnt/sshfs/<host>/<ruta-remota-absoluta>
```

Això fa que els punts de muntatge siguen previsibles, inspeccionables i fàcils d’automatitzar.

És menys curt que muntar en `/tmp/x`, però és més segur, més llegible i més fàcil de mantindre.
