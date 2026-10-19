# Kit A15 — caminho mais curto para rodar o ARTEMIS de verdade no Galaxy A15

Branch local `feat/termux-core-e1-final`, HEAD `fd1fd494a99eca1e95fe1e5c3defad610e2f18e7`.
Bases:
- `868dd1b` (relatório anterior)
- `3e8927fdfccdc6abf8320699641fd41c0e74cf6e` (PR #2, ainda é o head remoto; o push seria fast-forward, `merge-base --is-ancestor` = 0)

**Nada foi publicado.** Diffs: `full.diff` (868dd1b..HEAD) e `full-since-3e8927f.diff`.
Legenda: FATO = executado/medido aqui · HIPÓTESE = inferência · NÃO TESTADO.

## 0. O que precisa de autorização do Luiz
1. **Push** de `feat/termux-core-e1-final` (fast-forward, sem force) e **um** workflow_dispatch do probe. É o único jeito de gerar o wheelhouse aarch64/bionic e as métricas no container
2. **No A15, rodar a instalação**, que MUDA o aparelho:
   - `pkg install`
   - a venv em `~/.artemis-venv`
   - os arquivos do repositório em `~/google-artemis`
   - o wheelhouse em `~/artemis-wheelhouse`
3. **No A15, rodar a validação**, que escreve só em `~/artemis-validation/<data>`. O adb cria `~/.android/adbkey*`, inevitável para o pareamento. O teste de toque só acontece se ele digitar `SIM`
4. Pareamento de depuração sem fio (códigos digitados por ele)

## 1. Comando Artemis de controle do dispositivo, sem LLM (FATO: lido no código)
Os fluxos existentes que usam o dispositivo:
- `artemis run` exige LLM
- `artemis doctor` só lista dispositivos
- `artemis helper status|parity` consultam o dispositivo, mas `install`/`parity` dependem do APK auxiliar

Por isso foi criado `artemis device` (commit e1e00ae). Ele usa o mesmo `AndroidAdbDriver` (adbutils) das tarefas:
- `artemis device info --serial S --json`: modelo, versão, `wm size`, janela em foco (somente leitura)
- `artemis device screenshot --serial S --out F.png`: PNG, bytes e sha256; nunca sobrescreve
- `artemis device key home --serial S --yes`: um keyevent; mostra o foco antes e depois. Sem `--yes`, recusa (exit 3)
- Códigos de saída: 0 ok · 1 dispositivo ausente/não autorizado · 2 falha no ADB · 3 recusado · 124 timeout

O uiautomator2 **não** é usado por esse caminho: só o `run`/`parity` o usam. Por isso a validação não roda init/dump do u2.

**Bug corrigido (FATO, reproduzido com adb real 37.0.1):** `artemis helper status --serial does-not-exist-123 --json` imprimia `"installed": false` e saía com 0. Agora sai com 1 ("not attached") (99d10b1). Dois testes existentes foram ajustados para simular o dispositivo (a9f4242).

## 2. Os 13 pacotes compilados (FATO: artefatos do probe 39270598150 @3e8927f, Termux-in-Docker aarch64)
| pacote | versão | tag do wheel (arquivo real) | bytes | build (s) | pico temp | quem puxa (dep. direta) | carregado no caminho CLI+ADB |
|---|---|---|---|---|---|---|---|
| pydantic-core | 2.50.1 | `cp314-cp314-android_24_arm64_v8a` | 2096219 | 287.0 | 544.0 MB | ['pydantic'] | sim |
| jiter | 0.17.0 | `cp314-cp314-android_24_arm64_v8a` | 314808 | 28.8 | 173.3 MB | ['langchain-anthropic', 'langchain-openai'] | não |
| orjson | 3.13.0 | `cp314-cp314-android_24_arm64_v8a` | 303684 | 13.8 | 72.0 MB | ['langchain-community', 'langchain-core', 'langgraph'] | sim |
| ormsgpack | 1.13.0 | `cp314-cp314-android_24_arm64_v8a` | 253705 | 23.1 | 146.3 MB | ['langgraph'] | sim |
| uuid-utils | 0.17.1 | `cp314-cp314-android_24_arm64_v8a` | 346521 | 20.2 | 128.7 MB | ['uuid-utils'] | sim |
| tiktoken | 0.14.0 | `cp314-cp314-android_24_arm64_v8a` | 1128517 | 25.1 | 127.3 MB | ['langchain-openai'] | não |
| watchfiles | 1.3.0 | `cp310-abi3-android_24_arm64_v8a` | 468919 | 18.5 | 102.2 MB | ['uvicorn'] | não |
| zstandard | 0.25.0 | `cp314-cp314-android_24_arm64_v8a` | 2495305 | 36.1 | 23.4 MB | ['langchain-community', 'langchain-core'] | sim |
| regex | 2026.9.29 | `cp314-cp314-android_24_arm64_v8a` | 555969 | 7.9 | 9.6 MB | ['langchain-openai'] | não |
| tornado | 6.5.10 | `cp39-abi3-android_24_arm64_v8a` | 465752 | 2.6 | 7.7 MB | ['ipykernel', 'jupyter-client'] | sim |
| httptools | 0.9.0 | `cp314-cp314-android_24_arm64_v8a` | 373368 | 6.7 | 9.9 MB | ['uvicorn'] | não |
| uvloop | 0.23.0 | `cp314-cp314-android_24_arm64_v8a` | 2647337 | 43.7 | 50.4 MB | ['uvicorn'] | não |
| pyyaml | 6.0.3 | `cp314-cp314-android_24_arm64_v8a` | 45469 | 5.4 | 15.1 MB | ['langchain-community', 'langchain-core', 'uvicorn'] | sim |

Total dos 13 wheels: 11495573 bytes (11.0 MiB).

- **Origem:** sdist do PyPI na versão de `requirements/termux-constraints.txt`, compilado dentro de `termux/termux-docker:aarch64` (Python 3.14.8 do Termux, android-24) pelo `build-each` do probe
- **Compatibilidade Android/bionic (FATO agora, `logs/wheel-elf-check.txt`):**
  - todo `.so` é AArch64
  - tem a nota `.note.android.ident`
  - linka `libc.so` (bionic), nunca `libc.so.6` (glibc)
  - foi compilado com o clang Android
  - tag `android_24_arm64_v8a`, não `linux_aarch64`
  - o pyyaml veio sem extensão C (fallback puro)
- **Só depois do CI:** o wheelhouse completo (≈119 dists puras + artemis/artemis-client), o tamanho total e a instalação offline numa venv nova
- Os outros 6 nativos que o Termux precisa já vêm de `pkg` ou de wheels android no PyPI (markupsafe, pyzmq, xxhash: FATO via API do PyPI, `logs/pypi-android-wheel-coverage.txt`). adbutils e imageio-ffmpeg são só sdist, mas o build é puro (HIPÓTESE: sem compilador)
- **P0, de onde vem o disco** (FATO, probe 39270598150, amostragem a cada 5 s, o pico real pode ser maior):

| Caminho | Pico | Final |
|---|---|---|
| `$PREFIX` (inclui rust/clang/pkgs) | 3766,5 MB | 2483,5 MB |
| `$PREFIX/tmp` (diretórios de build do pip) | 1283 MB | 0 |
| `~/.cargo` (registro de crates) | 865,5 MB | — |
| cache do pip | 39 MB | — |
| **TOTAL** | **7250,7 MB** | **4707,4 MB** |

- **Perfil core (FATO, box x86, `sys.modules` de `doctor --json` + `artemis device`):** o caminho CLI+ADB carrega 7 dos 13 (pydantic-core, orjson, ormsgpack, uuid-utils, zstandard, tornado, pyyaml). Não carrega jiter, tiktoken e regex (langchain-openai/anthropic) nem watchfiles, httptools e uvloop (uvicorn). Só com extras, o device ainda compilaria 7, incluindo o pydantic-core (287 s, 544 MB) e o Rust, e economizaria ~131 s de 519 s
- **Decisão:** o P0 é resolvido pelo wheelhouse (0 compilações e sem rust/clang no aparelho). A divisão de extras no pyproject (E2) continua adiada porque mudaria o desktop/lock e não elimina o Rust. Economia de disco do wheelhouse: NÃO MEDIDA (HIPÓTESE: sem rust/clang/.cargo/tmp de build, ~3–4 GB a menos no pico)

## 3. Geração no CI, nome, download e verificação
- **Workflow** `termux-docker-probe.yml` (local, não publicado): `permissions: contents: read`, actions fixadas por SHA. Passa `SOURCE_COMMIT=${{ github.sha }}` e `RUN_ID` ao container
- **Probe:** depois do install, `build_wheelhouse` copia os 13 wheels, gera wheels `--no-deps` de cada dist da venv e o wheel de artemis/artemis-client. Em seguida, `wheelhouse-manifest` grava `manifest.json` (commit, run id, Python, versões dos pacotes Termux, arquivo/nome/versão/tags/bytes/sha256 de cada wheel) e `SHA256SUMS` (cobre todos os arquivos, inclusive o manifest), e imprime `SHA256SUMS sha256: <H>` no resumo do job
- **Prova no CI:** reinstala offline numa venv nova com `install_termux.sh --wheelhouse ... --expect-sums-sha256 <H>` e roda `artemis --help` (passos críticos)
- **Artefato:** `termux-wheelhouse-cp314-android24-arm64-<commit sha>`, retenção de 30 dias
- **Download:**
  - (a) pelo navegador no PC, na página do run, depois copiar para o celular
  - (b) `gh run download <RUN_ID> -R zenindiones-maker/google-artemis -n termux-wheelhouse-cp314-android24-arm64-<SHA> -D ~/artemis-wheelhouse` (exige `gh auth login` no aparelho; não recomendado)
- **Verificação ANTES de instalar** (`verify_artifacts.py --wheelhouse`):
  1. sha256(SHA256SUMS) == `<H>` fixado pelo Luiz a partir do run (vincula o run ao commit)
  2. todo arquivo listado, nenhum sobrando, nenhum faltando, hash conferido
  3. o manifest lista exatamente os wheels do SHA256SUMS, com os mesmos hashes
  4. plataforma `android_*_arm64_v8a` ou `any`; `linux_aarch64` é rejeitado
  5. versões iguais aos pins
  6. os 13 presentes
- **Hash = integridade, não proveniência.** A origem é comprovada pela página do run e, no futuro, por attestation (E4)

## 4. Instalador (`scripts/install_termux.sh`, cópia completa em `scripts/`)
- `--wheelhouse DIR --expect-sums-sha256 H [--allow-build] [--dry-run]`
- Pula rust, clang e build-essential
- Verifica antes de criar ou tocar na venv
- Instala com `--no-index --find-links DIR -c constraints --no-cache-dir`
- Se faltar um dos 13: exit 5, a menos que `--allow-build` seja dado; nesse caso instala o toolchain e permite o índice
- `--dry-run` mostra quantos wheels, o tamanho, o espaço livre no HOME e os comandos, sem executar nada
- **Nunca apaga nem sobrescreve dados:** a venv existente é reutilizada; uma venv de outro Python menor gera exit 1 com instrução de `mv`
- **Falha segura (FATO, testes):**
  - wheelhouse inexistente ou sem hash → exit 4, sem nenhum comando
  - wheel adulterado, run errado, wheel `linux_aarch64` ou manifest editado → exit 5, sem venv e sem pip
- **Testes:** `test_install_termux_wheelhouse.py` (11), `test_install_termux_contamination.py`, `test_install_termux_script.py`

## 5. Validação (`scripts/a15_validate.sh`): cada passo
Todo passo roda com `timeout STEP_TIMEOUT` (padrão 120 s). Log por passo em `logs/` e `summary.tsv`. Exit 1 se algum passo obrigatório falhar.

| Passo | Tipo | O que faz |
|---|---|---|
| info do aparelho/Termux | opcional | getprop (modelo, Android, abi), uname, versão do Termux e do Python |
| `artemis --version`, `--help` | obrigatório | |
| métricas de startup | obrigatório | 5 execuções + 1 de aquecimento; tempo mediano, `len(sys.modules)`, VmHWM, módulos pesados |
| `artemis doctor --json` | opcional | trechos de chave mascarados `xxxxxx...xxxx` são trocados por `<redacted>` |
| `adb version`, `adb devices -l` | obrigatório | sem dispositivo: imprime os passos de pareamento do Android 16 (`adb pair 127.0.0.1:<porta> <código>`, depois `adb connect 127.0.0.1:<porta>`) e falha; o script não executa nenhum dos dois |
| `artemis device info` | obrigatório | |
| `adb shell getprop ro.product.model` | obrigatório | comparação cruzada com o modelo informado pelo Artemis |
| `wm size` | opcional | |
| `artemis device screenshot` | obrigatório | grava `screen.png`, bytes e sha256 |
| erro proposital | obrigatório | `artemis device info` e `artemis helper status` num serial inexistente precisam sair com 1 |
| teste de input | obrigatório só se confirmado | pergunta no /dev/tty; só com `SIM` envia `artemis device key home --yes` e confere `focus_changed`; o padrão é pular |

Sem rede (FATO): o script não chama rede; teste estático e execução dentro de `unshare -rn`. O doctor não faz chamadas de rede (FATO, grep nos probes). Nada é enviado; o screenshot fica no diretório local.

## 6. Preflight somente leitura (`scripts/a15_preflight.sh` = `a15-preflight.sh` anterior)
Não instala, não pareia, não escreve (FATO, teste: HOME continua vazio). Só faz consultas `getprop`, `df`, `dpkg-query` e `--version`.

## 7. Resultados (box x86_64, Python 3.12.15)
- **FATO:** pytest completo 2668 passed / 11 skipped, cobertura 67,86%, exit 0 (sem chave exportada, adb real no PATH); ruff format/check, pyright-core e quality_ratchet com exit 0 (`logs/qa-final.log`)
- **FATO:** testes afetados executados: wheelhouse (11), a15 scripts (8), device CLI (8), helper serial (4), helper/diagnose existentes (59), probe/verify/ci (59)
- **FATO (rótulo: box x86, binários reais, SEM dispositivo):** `a15_validate.sh` com artemis real e adb 37.0.1 real
  - com rede: startup 1,242 s / 1778 módulos / 125,6 MiB, depois "device attached" FAIL e exit 1, como esperado
  - em `unshare -rn`: o adb não sobe o servidor (sem loopback), exit 1
  - arquivos fora do diretório de validação: só `~/.android/adbkey*` (criados pelo adb)
- **Estrutura** (stubs de adb e artemis; NÃO prova controle): sem dispositivo → pareamento e exit 1; sem `SIM` → nenhum input; `SIM` → exatamente 1 HOME; erro engolido → FAIL; travamento → TIMEOUT 124; nada fora de `~/artemis-validation`; chave mascarada não aparece nos logs
- **NÃO TESTADO:** container com o código novo (precisa de push); qualquer coisa no A15

## 8. Comandos para colar (Luiz)
**(a) Preflight, somente leitura:** o conteúdo completo está no fim (seção 9), dentro de `bash <<'EOF'`. Não muda nada.

**(b1) Instalação com wheelhouse** (precisa de push + run do CI; MUDA o aparelho):
```bash
pkg install -y git python                                    # muda: pacotes Termux
git clone -b feat/termux-core-e1-final https://github.com/zenindiones-maker/google-artemis ~/google-artemis
cd ~/google-artemis && git checkout <SHA do run>             # o mesmo commit do artefato
# copiar o zip do artefato para ~/storage/downloads (termux-setup-storage) e então:
mkdir -p ~/artemis-wheelhouse && unzip -o ~/storage/downloads/termux-wheelhouse-*.zip -d ~/artemis-wheelhouse
bash scripts/install_termux.sh --dry-run --wheelhouse ~/artemis-wheelhouse --expect-sums-sha256 <H do resumo do run>
bash scripts/install_termux.sh --wheelhouse ~/artemis-wheelhouse --expect-sums-sha256 <H do resumo do run>
```
O que muda: os pacotes `pkg` de `termux-pkg.txt` exceto rust/clang/build-essential, a venv `~/.artemis-venv`, o repo e o wheelhouse. Disco esperado: NÃO MEDIDO (wheels nativos 11,0 MiB + puros, tamanho desconhecido).

**(b2) Compilação no aparelho** (alternativa pesada, sem push): `cd ~/google-artemis && bash scripts/install_termux.sh`
- Instala rust/clang e compila 13 pacotes
- No probe aarch64: 519 s só de builds, pico de 7,25 GB, final de 4,7 GB
- No A15 deve ser mais lento (HIPÓTESE)

**(c) Validação** (escreve só em `~/artemis-validation`): `bash ~/google-artemis/scripts/a15_validate.sh`, ou o heredoc da seção 9. Depois, enviar `summary.tsv` e `startup-metrics.md`. **Não colar `screen.png`** (pode ter dados pessoais).

## 9. Scripts completos

### a15_preflight.sh
```bash
bash <<'EOF'
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Read-only Termux preflight for the A15: installs nothing, pairs nothing, writes nothing.
# Paste-able as bash <<'EOF' ... EOF. Prints device, Termux, disk, memory, tools and packages.
set -u
s(){ printf '\n== %s ==\n' "$1"; }
have(){ command -v "$1" >/dev/null 2>&1; }
ver(){ n="$1"; shift; if have "$n"; then printf '  %-10s ' "$n"; "$n" "$@" 2>&1 | head -n1; else printf '  %-10s ausente\n' "$n"; fi; }

# Estado de um pacote no banco local do dpkg (somente leitura).
pkgstate(){
  p="$1"
  status=$(dpkg-query -W -f='${Status}' "$p" 2>/dev/null); rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$status" ]; then
    echo "  [ausente]     $p"; return
  fi
  version=$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null)
  if [ "$status" = "install ok installed" ]; then
    echo "  [instalado]   $p ${version:-sem-versao}"
  elif [ "$status" = "unknown ok not-installed" ] || [ "$status" = "deinstall ok not-installed" ] || [ "$status" = "purge ok not-installed" ]; then
    echo "  [ausente]     $p"
  elif [ "$status" = "deinstall ok config-files" ] || [ "$status" = "purge ok config-files" ]; then
    echo "  [removido]    $p (restaram so arquivos de configuracao)"
  else
    echo "  [INCOMPLETO]  $p ${version:-sem-versao} (status: $status)"
  fi
}

s "Aparelho e Android"
if have getprop; then
  echo "  modelo: $(getprop ro.product.model 2>/dev/null)"
  echo "  android: $(getprop ro.build.version.release 2>/dev/null) (API $(getprop ro.build.version.sdk 2>/dev/null))"
  echo "  abi: $(getprop ro.product.cpu.abi 2>/dev/null)"
else
  echo "  getprop indisponivel (nao parece ser Android)"
fi
echo "  uname -m: $(uname -m) | nucleos: $(nproc 2>/dev/null || echo '?')"
echo "  kernel: $(uname -r)"

s "Termux"
if [ -n "${TERMUX_VERSION:-}" ]; then
  echo "  versao do app: $TERMUX_VERSION"
elif [ -n "${TERMUX_APP__APP_VERSION_NAME:-}" ]; then
  echo "  versao do app: $TERMUX_APP__APP_VERSION_NAME"
else
  echo "  versao do app: nao informada (TERMUX_VERSION ausente; app antigo, sessao sem variaveis ou fora do Termux)"
fi
if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX" ]; then
  echo "  PREFIX: $PREFIX"
else
  echo "  PREFIX: nao definido ou inexistente"
fi
echo "  ANDROID_API_LEVEL: ${ANDROID_API_LEVEL:-nao definido}"
srcs=""
for f in "${PREFIX:-/nao-existe}/etc/apt/sources.list" "${PREFIX:-/nao-existe}"/etc/apt/sources.list.d/*.list; do
  [ -r "$f" ] && srcs="$srcs $f"
done
if [ -z "$srcs" ]; then
  echo "  espelhos: nenhum arquivo de fontes do apt encontrado"
else
  m=$(grep -h '^[[:space:]]*deb[[:space:]]' $srcs 2>/dev/null | awk '{for(i=2;i<=NF;i++) if($i ~ /^https?:\/\//){print $i; break}}' | sort -u | tr '\n' ' ')
  if [ -n "$m" ]; then echo "  espelhos: $m"; else echo "  espelhos: arquivos encontrados, mas sem linhas 'deb' ativas"; fi
fi

s "Espaco livre"
for d in "$HOME" "${PREFIX:-}" /storage/emulated/0; do
  [ -n "$d" ] || continue
  if [ -d "$d" ]; then df -h "$d" 2>/dev/null | tail -n 1 | awk -v d="$d" '{print "  "d": livre "$4" de "$2" ("$5" usado)"}'
  else echo "  $d: inacessivel (sem permissao de armazenamento ou inexistente)"; fi
done
[ -n "${PREFIX:-}" ] && echo "  usado por \$PREFIX: $(du -sh "$PREFIX" 2>/dev/null | cut -f1)"
echo "  usado por \$HOME: $(du -sh "$HOME" 2>/dev/null | cut -f1)"

s "Memoria"
grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo 2>/dev/null | sed 's/^/  /' || echo "  /proc/meminfo indisponivel"

s "Ferramentas"
ver python --version; ver pip --version --disable-pip-version-check; ver uv --version
ver node --version; ver npm --version; ver git --version
ver rustc --version; ver cargo --version; ver clang --version; ver make --version
ver cmake --version; ver ninja --version; ver pkg-config --version; ver maturin --version
ver adb version; ver ffmpeg -version

s "Python"
if have python; then python - <<'PY'
import sys, sysconfig, platform, importlib.util
print("  versao:", sys.version.split()[0])
print("  plataforma:", sys.platform, sysconfig.get_platform(), platform.machine())
f = getattr(sys, "getandroidapilevel", None)
print("  android api (python):", f() if f else "n/a")
for m in ["numpy","scipy","PIL","cv2","matplotlib","lxml","cryptography","psutil",
          "grpc","pyarrow","pydantic_core","aiohttp","zmq","uiautomator2","adbutils","artemis"]:
    try: ok = importlib.util.find_spec(m) is not None
    except Exception: ok = False
    print(f"  {m}: {'presente' if ok else 'ausente'}")
PY
else echo "  python ausente"; fi

s "Pacotes Termux relevantes"
if have dpkg-query; then
  for p in python python-pip uv nodejs-lts nodejs git termux-exec x11-repo dbus \
    rust clang make cmake ninja binutils build-essential pkg-config \
    android-tools ffmpeg libjpeg-turbo libpng zlib openssl libffi \
    python-numpy python-scipy python-pillow python-cryptography python-lxml \
    python-psutil python-grpcio python-pyarrow matplotlib opencv-python python-opencv-python; do
    pkgstate "$p"
  done
  echo "  total instalados: $(dpkg-query -W -f='${Status}\n' 2>/dev/null | grep -c '^install ok installed$')"
  inc=$(dpkg-query -W -f='${Status}|${Package}\n' 2>/dev/null | grep -v '^install ok installed|' | grep -v 'not-installed|' | grep -v 'config-files|' | cut -d'|' -f2 | tr '\n' ' ')
  echo "  pacotes em estado incompleto (todos): ${inc:-nenhum}"
else
  echo "  dpkg-query indisponivel"
fi

s "Fim do diagnostico (nada foi alterado)"
EOF
```

### a15_validate.sh
```bash
bash <<'EOF'
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# On-device validation of ARTEMIS on the physical phone (Galaxy A15), in Termux.
# Paste-able: bash <<'EOF' ... EOF, or: bash scripts/a15_validate.sh
#
# Writes ONLY under ~/artemis-validation/<timestamp>/ (override the root with
# ARTEMIS_VALIDATION_ROOT). Makes no network calls itself; every device action goes
# through 'artemis device ...' (Artemis ADB driver, no LLM). The single input event
# (KEYCODE_HOME) is sent only after you type SIM on the terminal; default = skipped.
# Nothing is uploaded anywhere; the screenshot stays in the validation directory.
#
# Inputs (environment, all optional): ARTEMIS_VENV (default ~/.artemis-venv),
# ARTEMIS_REPO (default: this script's repo), ARTEMIS_SERIAL (default: the only
# attached device), STEP_TIMEOUT seconds (default 120), A15_TTY (default /dev/tty).
set -u

VENV="${ARTEMIS_VENV:-${HOME}/.artemis-venv}"
REPO="${ARTEMIS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)}"
# Pasted as a heredoc there is no script path: fall back to the clone location.
[ -f "${REPO}/scripts/termux_probe_metrics.py" ] || REPO="${HOME}/google-artemis"
ROOT="${ARTEMIS_VALIDATION_ROOT:-${HOME}/artemis-validation}"
OUT="${ROOT}/$(date +%Y%m%d-%H%M%S)"
STEP_TIMEOUT="${STEP_TIMEOUT:-120}"
TTY="${A15_TTY:-/dev/tty}"
ARTEMIS="${VENV}/bin/artemis"
export VENV
mkdir -p "${OUT}/logs" || exit 1
SUMMARY="${OUT}/summary.tsv"
printf 'step\tmandatory\tresult\texit\n' > "${SUMMARY}"
MANDATORY_FAILED=0
N=0

# step <mandatory|optional> <name> <command...>: run with a timeout, log, record.
step() {
    local kind="$1" name="$2"
    shift 2
    N=$((N + 1))
    local log="${OUT}/logs/$(printf '%02d' "${N}")-$(printf '%s' "${name}" | tr -c 'a-zA-Z0-9' '_').log"
    if declare -F "$1" > /dev/null; then
        # Shell functions cannot be exec'd by timeout; run them in a child bash.
        timeout "${STEP_TIMEOUT}" bash -c "$(declare -f "$1"); $*" > "${log}" 2>&1
    else
        timeout "${STEP_TIMEOUT}" "$@" > "${log}" 2>&1
    fi
    local rc=$?
    local result=PASS
    [ "${rc}" -eq 124 ] && result=TIMEOUT
    [ "${rc}" -ne 0 ] && [ "${rc}" -ne 124 ] && result=FAIL
    record "${kind}" "${name}" "${result}" "${rc}"
    LAST_LOG="${log}"
    return "${rc}"
}

# expect_fail <name> <expected-exit> <command...>: the error must propagate.
expect_fail() {
    local name="$1" want="$2"
    shift 2
    N=$((N + 1))
    local log="${OUT}/logs/$(printf '%02d' "${N}")-$(printf '%s' "${name}" | tr -c 'a-zA-Z0-9' '_').log"
    timeout "${STEP_TIMEOUT}" "$@" > "${log}" 2>&1
    local rc=$?
    if [ "${rc}" -eq "${want}" ]; then record mandatory "${name}" PASS "${rc}"; else record mandatory "${name}" FAIL "${rc}"; fi
}

record() {
    printf '%s\t%s\t%s\t%s\n' "$2" "$1" "$3" "$4" >> "${SUMMARY}"
    if [ "$1" = mandatory ] && [ "$3" != PASS ] && [ "$3" != SKIP ]; then MANDATORY_FAILED=1; fi
}


device_and_termux_info() {
    echo "model: $(getprop ro.product.model 2>/dev/null)"
    echo "android: $(getprop ro.build.version.release 2>/dev/null) (sdk $(getprop ro.build.version.sdk 2>/dev/null))"
    echo "abi: $(getprop ro.product.cpu.abi 2>/dev/null)"
    echo "uname: $(uname -srm)"
    echo "termux: ${TERMUX_VERSION:-unknown}  prefix: ${PREFIX:-unset}"
    "${VENV}/bin/python" -c 'import sys, sysconfig; print("python", sys.version.split()[0], sysconfig.get_platform())'
}

if command -v getprop > /dev/null 2>&1 && [ -n "$(getprop ro.product.model 2>/dev/null)" ]; then
    ENV_LABEL="Android $(getprop ro.build.version.release 2>/dev/null), $(getprop ro.product.model 2>/dev/null), Termux ${TERMUX_VERSION:-?}"
else
    ENV_LABEL="non-Android host $(uname -m) (NOT the phone)"
fi
echo "Validation directory: ${OUT}"
step optional "device and Termux info" device_and_termux_info
step mandatory "artemis --version" "${ARTEMIS}" --version
step mandatory "artemis --help" "${ARTEMIS}" --help
step mandatory "startup metrics (artemis --help, 5 runs)" "${VENV}/bin/python" \
    "${REPO}/scripts/termux_probe_metrics.py" startup --python "${VENV}/bin/python" \
    --out "${OUT}" --runs 5 --warmup 1 --environment "${ENV_LABEL}"
step optional "artemis doctor --json (keys redacted)" bash -c '"$1" doctor --json | sed -E "s/[A-Za-z0-9_-]{6}\.\.\.[A-Za-z0-9_-]{4}/<redacted>/g"' _ "${ARTEMIS}"
step mandatory "adb available" adb version
step mandatory "adb devices -l" adb devices -l
DEVICES_LOG="${LAST_LOG}"

SERIAL="${ARTEMIS_SERIAL:-}"
if [ -z "${SERIAL}" ]; then
    SERIAL="$(awk 'NR > 1 && $2 == "device" {print $1}' "${DEVICES_LOG}" | head -n 1)"
fi

if [ -z "${SERIAL}" ]; then
    record mandatory "device attached" FAIL 1
    cat <<'PAIR'

No authorized device. Pair this phone with itself over Wireless debugging (Android 16):
  1. Settings > Developer options > Wireless debugging: turn it on.
  2. Tap "Pair device with pairing code"; note the IP:PORT and the 6-digit code.
  3. In Termux (split screen):  adb pair 127.0.0.1:<pairing-port> <code>
  4. Back on the Wireless debugging screen, note the IP:PORT shown at the top.
  5. In Termux:                 adb connect 127.0.0.1:<connect-port>
  6. Run this validation again.
PAIR
else
    record mandatory "device attached (${SERIAL})" PASS 0
    step mandatory "artemis device info" "${ARTEMIS}" device info --serial "${SERIAL}" --json
    INFO_LOG="${LAST_LOG}"
    step mandatory "adb getprop ro.product.model (cross-check)" adb -s "${SERIAL}" shell getprop ro.product.model
    RAW_MODEL="$(tr -d '\r' < "${LAST_LOG}" | head -n 1)"
    if grep -q "\"model\": \"${RAW_MODEL}\"" "${INFO_LOG}" 2>/dev/null && [ -n "${RAW_MODEL}" ]; then
        record mandatory "model matches (${RAW_MODEL})" PASS 0
    else
        record mandatory "model matches" FAIL 1
    fi
    step optional "adb shell wm size" adb -s "${SERIAL}" shell wm size
    step mandatory "artemis device screenshot" "${ARTEMIS}" device screenshot --serial "${SERIAL}" --out "${OUT}/screen.png"
    if [ -s "${OUT}/screen.png" ]; then
        echo "screenshot: $(wc -c < "${OUT}/screen.png") bytes, sha256 $(sha256sum "${OUT}/screen.png" | cut -d' ' -f1)" | tee "${OUT}/screenshot.txt"
    fi
    expect_fail "error propagates: device info on a nonexistent serial (exit 1)" 1 \
        "${ARTEMIS}" device info --serial does-not-exist-000
    expect_fail "error propagates: helper status on a nonexistent serial (exit 1)" 1 \
        "${ARTEMIS}" helper status --serial does-not-exist-000 --json

    echo
    echo "Optional input test: sends KEYCODE_HOME (goes to the home screen) to ${SERIAL}."
    printf 'Type SIM and press Enter to send it, anything else to skip: '
    ANSWER=""
    read -r ANSWER < "${TTY}" 2>/dev/null || ANSWER=""
    if [ "${ANSWER}" = "SIM" ]; then
        step mandatory "artemis device key home (confirmed)" "${ARTEMIS}" device key home --serial "${SERIAL}" --yes
        cat "${LAST_LOG}"
        if grep -q '"focus_changed": true' "${LAST_LOG}"; then
            record mandatory "focus changed after HOME" PASS 0
        else
            record optional "focus changed after HOME (unchanged: already on home?)" FAIL 0
        fi
    else
        record optional "input test (not confirmed)" SKIP 0
    fi
fi

echo
echo "== Summary (${OUT}) =="
column -t -s "$(printf '\t')" "${SUMMARY}" 2>/dev/null || cat "${SUMMARY}"
if [ "${MANDATORY_FAILED}" -ne 0 ]; then
    echo "RESULT: FAIL (a mandatory step failed; see ${OUT}/logs)"
    exit 1
fi
echo "RESULT: PASS"
exit 0
EOF
```

### install_termux.sh
```bash
#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Explicit, pinned ARTEMIS install path for Termux (Android, aarch64).
#
#   bash scripts/install_termux.sh [--dry-run]
#   bash scripts/install_termux.sh --wheelhouse DIR --expect-sums-sha256 HEX [--allow-build] [--dry-run]
#
# 1. installs the Termux packages in requirements/termux-pkg.txt (warns when the
#    installed version differs from the one validated in CI),
# 2. creates a virtualenv with --system-site-packages so Termux's numpy, scipy,
#    opencv, pyarrow, ... are reused instead of compiled,
# 3. pip-installs ARTEMIS with requirements/termux-constraints.txt (exact versions
#    that passed in the Termux-in-Docker probe); Rust/C packages without a Termux
#    package are compiled locally (pydantic-core, jiter, orjson, ...);
#    with --wheelhouse, CI-built wheels are checked first (SHA256SUMS pinned by
#    --expect-sums-sha256: integrity, not provenance) and installed offline, so no
#    Rust/C toolchain is installed (unless --allow-build and a wheel is missing),
# 4. verifies 'artemis --help'.
#
# Validated only in a Termux aarch64 container (see docs/termux.md), not on a
# phone. Nothing is deleted; an existing virtualenv is reused.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
PKG_FILE="${REPO}/requirements/termux-pkg.txt"
CONSTRAINTS="${REPO}/requirements/termux-constraints.txt"
VENV="${ARTEMIS_VENV:-${HOME}/.artemis-venv}"
DRY_RUN=false
WHEELHOUSE=""
EXPECT_SUMS=""
ALLOW_BUILD=false
SOURCE_BUILT_FILE="${REPO}/requirements/termux-source-built.txt"
BUILD_PKGS=(rust clang build-essential)

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --wheelhouse)
            WHEELHOUSE="${2:?--wheelhouse needs a directory}"
            shift
            ;;
        --expect-sums-sha256)
            EXPECT_SUMS="${2:?--expect-sums-sha256 needs a hex digest}"
            shift
            ;;
        --allow-build) ALLOW_BUILD=true ;;
        -h | --help)
            sed -n '16,35p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if [ -n "${WHEELHOUSE}" ]; then
    if [ ! -d "${WHEELHOUSE}" ]; then
        echo "✖ Wheelhouse ${WHEELHOUSE} does not exist. Nothing was changed." >&2
        exit 4
    fi
    WHEELHOUSE="$(cd "${WHEELHOUSE}" && pwd)"
    if [ -z "${EXPECT_SUMS}" ]; then
        echo "✖ --wheelhouse needs --expect-sums-sha256 <hash printed by the CI run>. Nothing was changed." >&2
        exit 4
    fi
fi

run() {
    echo "+ $*"
    if [ "${DRY_RUN}" != true ]; then
        "$@"
    fi
}

if [ -z "${TERMUX_VERSION:-}" ] && [[ "${PREFIX:-}" != *"/com.termux/files/usr" ]]; then
    echo "This installer is for Termux on Android only. On desktop use ./start.sh." >&2
    exit 1
fi

# --- 1. Termux packages ------------------------------------------------------
MAIN_PKGS=()
X11_PKGS=()
declare -A EXPECTED=()
while read -r name version repo _; do
    case "${name}" in "" | \#*) continue ;; esac
    if [ "${version:-}" = "x11" ]; then
        repo="x11"
        version=""
    fi
    EXPECTED["${name}"]="${version:-}"
    if [ "${repo:-}" = "x11" ]; then
        X11_PKGS+=("${name}")
    else
        MAIN_PKGS+=("${name}")
    fi
done < "${PKG_FILE}"

is_build_pkg() {
    local p
    for p in "${BUILD_PKGS[@]}"; do [ "$1" = "${p}" ] && return 0; done
    return 1
}
if [ -n "${WHEELHOUSE}" ]; then
    # Prebuilt wheels replace on-device compilation: skip the Rust/C toolchain.
    KEEP=()
    for p in "${MAIN_PKGS[@]}"; do is_build_pkg "${p}" || KEEP+=("${p}"); done
    MAIN_PKGS=("${KEEP[@]}")
    echo "Wheelhouse mode: skipping build toolchain (${BUILD_PKGS[*]})"
fi
run pkg install -y "${MAIN_PKGS[@]}"
if [ ${#X11_PKGS[@]} -gt 0 ]; then
    run pkg install -y "${X11_PKGS[@]}"
fi

if [ "${DRY_RUN}" != true ]; then
    for name in "${!EXPECTED[@]}"; do
        want="${EXPECTED[${name}]}"
        [ -z "${want}" ] && continue
        have="$(dpkg-query -W -f='${Version}' "${name}" 2>/dev/null || true)"
        if [ "${have}" != "${want}" ]; then
            echo "⚠ ${name}: installed '${have:-none}', validated in CI '${want}'"
        fi
    done
fi

# --- 2. Build environment ---------------------------------------------------
# maturin (pydantic-core, jiter, orjson, ...) needs an explicit API level on Android.
if [ -z "${ANDROID_API_LEVEL:-}" ]; then
    if [ "${DRY_RUN}" = true ]; then
        ANDROID_API_LEVEL="<from python sys.getandroidapilevel()>"
    else
        ANDROID_API_LEVEL="$(python -c 'import sys; print(sys.getandroidapilevel())')"
    fi
fi
export ANDROID_API_LEVEL
echo "ANDROID_API_LEVEL=${ANDROID_API_LEVEL}"
# termux-exec lets './configure' scripts with '#!/bin/sh' run (e.g. uvloop's libuv).
if [ -z "${LD_PRELOAD:-}" ]; then
    for lib in "${PREFIX}/lib/libtermux-exec-ld-preload.so" "${PREFIX}/lib/libtermux-exec.so"; do
        if [ -f "${lib}" ]; then
            export LD_PRELOAD="${lib}"
            break
        fi
    done
fi
echo "LD_PRELOAD=${LD_PRELOAD:-<none>}"

# --- Wheelhouse: verify BEFORE creating or touching the venv ------------------
# SHA256SUMS proves integrity (bytes unchanged since the CI run whose hash you
# pinned with --expect-sums-sha256), not provenance: who built them is shown only by
# the GitHub run (and, later, an attestation), not by the hash.
PIP_SOURCE=(--prefer-binary)
if [ -n "${WHEELHOUSE}" ]; then
    WH_COUNT="$(find "${WHEELHOUSE}" -maxdepth 1 -name '*.whl' | wc -l)"
    WH_BYTES="$(du -sk "${WHEELHOUSE}" | cut -f1)"
    echo "Wheelhouse: ${WH_COUNT} wheels, ${WH_BYTES} KiB in ${WHEELHOUSE}"
    if [ "${DRY_RUN}" = true ]; then
        echo "Free space in HOME: $(df -k "${HOME}" 2>/dev/null | awk 'NR==2 {print $4}') KiB"
        echo "+ python scripts/verify_artifacts.py --wheelhouse ${WHEELHOUSE} --expect-sums-sha256 ${EXPECT_SUMS}"
    else
        set +e
        python "${REPO}/scripts/verify_artifacts.py" --wheelhouse "${WHEELHOUSE}" \
            --constraints "${CONSTRAINTS}" --source-built "${SOURCE_BUILT_FILE}" \
            --expect-sums-sha256 "${EXPECT_SUMS}" 2> "${TMPDIR:-/tmp}/artemis-wheelhouse-check.txt"
        rc=$?
        set -e
        problems="$(cat "${TMPDIR:-/tmp}/artemis-wheelhouse-check.txt")"
        if [ "${rc}" -ne 0 ]; then
            if [ "${ALLOW_BUILD}" = true ] && ! grep -qvE '^NOT COVERED ' <<< "${problems}"; then
                echo "⚠ Wheelhouse lacks some source-built packages; --allow-build given, compiling them:"
                echo "${problems}"
                run pkg install -y "${BUILD_PKGS[@]}"
            else
                echo "✖ Wheelhouse check failed. Nothing was installed into the venv:" >&2
                echo "${problems}" >&2
                exit 5
            fi
        fi
    fi
    if [ "${ALLOW_BUILD}" = true ]; then
        PIP_SOURCE=(--prefer-binary --find-links "${WHEELHOUSE}")
    else
        PIP_SOURCE=(--no-index --find-links "${WHEELHOUSE}")
    fi
fi

# --- 3. Virtualenv + ARTEMIS ---------------------------------------------------
# Contamination guard: variables from another Python environment must not leak into
# the venv creation or pip install.
for var in PYTHONPATH PYTHONHOME VIRTUAL_ENV PIP_TARGET PIP_PREFIX PIP_USER; do
    if [ -n "${!var:-}" ]; then
        echo "⚠ Ignoring ${var}=${!var} (set by another Python environment)"
        unset "${var}"
    fi
done

py_minor() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }

if [ ! -x "${VENV}/bin/python" ]; then
    run python -m venv --system-site-packages "${VENV}"
else
    if [ "${DRY_RUN}" != true ]; then
        venv_minor="$(py_minor "${VENV}/bin/python")"
        system_minor="$(py_minor python)"
        if [[ "${venv_minor}" =~ ^[0-9]+\.[0-9]+$ && "${system_minor}" =~ ^[0-9]+\.[0-9]+$ && "${venv_minor}" != "${system_minor}" ]]; then
            echo "✖ ${VENV} was created with Python ${venv_minor}, but Termux now has Python ${system_minor}." >&2
            echo "  It was left untouched. Move it aside (mv ${VENV} ${VENV}.old) and re-run this installer." >&2
            exit 1
        fi
    fi
    echo "Reusing existing virtualenv ${VENV}"
fi
if [ -n "${WHEELHOUSE}" ]; then
    run "${VENV}/bin/python" -m pip install --no-cache-dir "${PIP_SOURCE[@]}" -c "${CONSTRAINTS}" artemis-client artemis
else
    run "${VENV}/bin/python" -m pip install --prefer-binary -c "${CONSTRAINTS}" "${REPO}/packages/artemis-client"
    run "${VENV}/bin/python" -m pip install --prefer-binary -c "${CONSTRAINTS}" "${REPO}"
fi

# --- 4. Verify -----------------------------------------------------------------
run "${VENV}/bin/artemis" --help
echo "✔ ARTEMIS installed in ${VENV}. Start it with: ./start.sh"
```

### verify_artifacts.py
```python
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Verify artifacts (e.g. wheels, UI bundles) against a SHA256SUMS manifest.

Integrity only: a matching hash proves the bytes are the ones listed in the manifest,
not who produced them. Authenticity needs ``gh attestation verify`` on top.

Exit codes: 0 all OK, 1 mismatch/missing/unlisted artifact, 2 malformed manifest.

``--wheelhouse DIR`` additionally cross-checks a Termux wheelhouse built by CI:
SHA256SUMS covers every file (including manifest.json); manifest.json lists exactly
the wheels in SHA256SUMS with the same hashes; every wheel is Android arm64 or pure
Python (never generic linux_aarch64); versions match the constraints pins; and every
package from the source-built list is present. Optional ``--expect-sums-sha256``
pins SHA256SUMS itself to the value printed by the CI run that produced it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def read_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            raise ValueError(f"{path}:{number}: malformed line: {raw!r}")
        entries[Path(match.group(2)).name] = match.group(1)
    return entries


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_WHEEL = re.compile(
    r"^(?P<name>[^-]+)-(?P<version>[^-]+)(?:-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)
_ANDROID_ARM64 = re.compile(r"^android_\d+_arm64_v8a$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_wheel(filename: str) -> dict[str, str]:
    match = _WHEEL.match(filename)
    if not match:
        raise ValueError(f"not a wheel filename: {filename}")
    return {**match.groupdict(), "canonical": canonical(match.group("name"))}


def wheel_platform_ok(plat: str) -> bool:
    return plat == "any" or all(_ANDROID_ARM64.match(p) for p in plat.split("."))


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[canonical(name.split("[")[0].strip())] = version.strip()
    return pins


def read_names(path: Path) -> list[str]:
    return [
        canonical(x.strip())
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip() and not x.startswith("#")
    ]


def check_wheelhouse(
    directory: Path,
    constraints: Path | None = None,
    source_built: Path | None = None,
    expect_sums_sha256: str | None = None,
) -> list[str]:
    """Return a list of problems (empty = OK)."""
    import json

    problems: list[str] = []
    sums_path = directory / "SHA256SUMS"
    if not sums_path.is_file():
        return [f"MISSING {sums_path}"]
    if expect_sums_sha256 and sha256(sums_path) != expect_sums_sha256.lower():
        return [
            f"MISMATCH SHA256SUMS: expected {expect_sums_sha256}, got {sha256(sums_path)} (not the CI run you pinned)"
        ]
    try:
        sums = read_manifest(sums_path)
    except ValueError as exc:
        return [f"ERROR {exc}"]
    on_disk = {p.name for p in directory.iterdir() if p.is_file() and p.name != "SHA256SUMS"}
    problems += [f"UNLISTED {n}" for n in sorted(on_disk - set(sums))]
    problems += [f"MISSING {n}" for n in sorted(set(sums) - on_disk)]
    for name in sorted(set(sums) & on_disk):
        if sha256(directory / name) != sums[name]:
            problems.append(f"MISMATCH {name}")
    if "manifest.json" not in sums:
        problems.append("MISSING manifest.json in SHA256SUMS")
        return problems
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return problems + [f"ERROR manifest.json: {exc}"]
    listed = {w["file"]: w for w in manifest.get("wheels", [])}
    wheels = {n for n in sums if n.endswith(".whl")}
    if set(listed) != wheels:
        problems.append(f"INCONSISTENT manifest.json vs SHA256SUMS: {sorted(set(listed) ^ wheels)}")
    for file in sorted(set(listed) & wheels):
        if listed[file].get("sha256") != sums[file]:
            problems.append(f"INCONSISTENT hash for {file} in manifest.json")
    pins = read_pins(constraints) if constraints else {}
    present: set[str] = set()
    for file in sorted(wheels):
        try:
            info = parse_wheel(file)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        present.add(info["canonical"])
        if not wheel_platform_ok(info["plat"]):
            problems.append(
                f"WRONG PLATFORM {file}: {info['plat']} (need android_*_arm64_v8a or any)"
            )
        want = pins.get(info["canonical"])
        if want and want != info["version"]:
            problems.append(f"VERSION {file}: constraints pin {want}")
    if source_built:
        problems += [
            f"NOT COVERED {n} (would be compiled on the device)"
            for n in read_names(source_built)
            if n not in present
        ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--wheelhouse", type=Path, help="cross-check a CI-built Termux wheelhouse")
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--source-built", type=Path)
    parser.add_argument("--expect-sums-sha256")
    args = parser.parse_args(argv)
    if args.wheelhouse:
        problems = check_wheelhouse(
            args.wheelhouse, args.constraints, args.source_built, args.expect_sums_sha256
        )
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print(f"OK wheelhouse {args.wheelhouse}")
        return 1 if problems else 0
    if not args.manifest or not args.artifacts:
        parser.error("--manifest and artifacts are required without --wheelhouse")
    try:
        expected = read_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    failed = False
    for artifact in args.artifacts:
        want = expected.get(artifact.name)
        if want is None:
            print(f"UNLISTED {artifact.name}", file=sys.stderr)
            failed = True
        elif not artifact.is_file():
            print(f"MISSING {artifact}", file=sys.stderr)
            failed = True
        elif (have := sha256(artifact)) != want:
            print(f"MISMATCH {artifact.name}: expected {want}, got {have}", file=sys.stderr)
            failed = True
        else:
            print(f"OK {artifact.name} {want}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

### termux-docker-probe.yml
```yaml
name: ARTEMIS Termux-in-Docker probe (aarch64)

# Installs ARTEMIS inside a real Termux userland (termux/termux-docker, bionic
# libc) on a free GitHub-hosted ARM64 runner and reports which steps fail.
# This is NOT a device test: there is no Android framework, adb device or
# screen, so a green run does not prove ARTEMIS works on a phone.

on:
  workflow_dispatch:
  pull_request:
    paths:
      - "pyproject.toml"
      - "uv.lock"
      - "start.sh"
      - "scripts/termux_ci_probe.sh"
      - "scripts/install_termux.sh"
      - "requirements/**"
      - "scripts/termux_probe_metrics.py"
      - "scripts/verify_artifacts.py"
      - ".github/workflows/termux-docker-probe.yml"
  push:
    branches:
      - "ci/android-termux-compat-audit"
    paths:
      - "pyproject.toml"
      - "uv.lock"
      - "start.sh"
      - "scripts/termux_ci_probe.sh"
      - "scripts/install_termux.sh"
      - "requirements/**"
      - ".github/workflows/termux-docker-probe.yml"

permissions:
  contents: read

concurrency:
  group: termux-probe-${{ github.ref }}
  cancel-in-progress: true

jobs:
  termux-aarch64:
    name: Termux aarch64 install + import + CLI probe
    runs-on: ubuntu-24.04-arm
    timeout-minutes: 150
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Run probe inside termux/termux-docker:aarch64
        shell: bash
        run: |
          out="$RUNNER_TEMP/termux-probe"
          mkdir -p "$out"
          chmod 0777 "$out"
          docker run --rm \
            --security-opt seccomp=unconfined \
            -v "$GITHUB_WORKSPACE:/repo:ro" \
            -v "$out:/out" \
            -e SOURCE_COMMIT="${{ github.sha }}" \
            -e RUN_ID="${{ github.run_id }}" \
            termux/termux-docker:aarch64 \
            bash /repo/scripts/termux_ci_probe.sh /repo /out
      - name: Publish summary
        if: always()
        run: cat "$RUNNER_TEMP/termux-probe/termux-probe.md" >> "$GITHUB_STEP_SUMMARY" 2>/dev/null || true
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: always()
        with:
          name: termux-docker-probe
          path: ${{ runner.temp }}/termux-probe/
          if-no-files-found: warn
      # Device wheelhouse: name binds the commit; SHA256SUMS hash is in the summary.
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: success()
        with:
          name: termux-wheelhouse-cp314-android24-arm64-${{ github.sha }}
          path: ${{ runner.temp }}/termux-probe/wheelhouse/
          if-no-files-found: error
          retention-days: 30
```
