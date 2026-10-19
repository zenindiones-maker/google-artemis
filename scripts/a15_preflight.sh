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
