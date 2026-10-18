from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "start.sh"


def test_startup_detects_termux_before_host_tool_installation() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert 'IS_TERMUX=false' in source
    assert '"${TERMUX_VERSION:-}"' in source
    assert '"${PREFIX:-}" == *"/com.termux/files/usr"' in source
    assert 'if [ "${IS_TERMUX}" = true ]; then' in source
    assert 'export PATH="${PREFIX}/bin:${PATH}"' in source


def test_termux_never_uses_desktop_linux_node_fallback() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert 'if ! is_node_compatible && [ "${IS_TERMUX}" != true ]; then' in source
    assert 'rm -rf "${NODE_DIR}"' not in source


def test_portable_node_install_is_versioned_and_preserves_existing_files() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert 'NODE_DIR="${HOME}/.local/share/node-${NODE_VER}"' in source
    assert 'npm ci --silent' in source
