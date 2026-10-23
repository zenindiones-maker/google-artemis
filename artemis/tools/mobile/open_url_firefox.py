"""Abertura restrita de URLs no Firefox com aprovação interativa por chamada.

Este módulo ainda não deve ser registrado no Operator até que o canal de
aprovação seja verificado no contexto real de execução do Artemis.
"""
import subprocess
import sys
from urllib.parse import urlsplit


FIREFOX_PACKAGE = "org.mozilla.firefox"
APPROVAL_PROMPT = "Digite exatamente S para autorizar esta URL: "


def validate_http_url(url: str) -> str:
    """Aceita somente URLs HTTP(S) absolutas, sem credenciais ou controles."""
    if not isinstance(url, str) or not url:
        raise ValueError("URL obrigatória.")
    if url != url.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("URL contém espaços externos ou caracteres de controle.")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # Acessar .port também valida portas malformadas ou fora do intervalo.
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL malformada.") from exc

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("Somente URLs HTTP e HTTPS são permitidas.")
    if not parsed.netloc or not hostname:
        raise ValueError("A URL precisa conter um host válido.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs com credenciais embutidas são proibidas.")
    if any(ch.isspace() for ch in url):
        raise ValueError("Espaços não são permitidos na URL.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Porta inválida.")

    return url


def request_url_approval(url: str) -> bool:
    """Pede aprovação exata em terminal interativo; falha fechada."""
    try:
        url = validate_http_url(url)
        if not sys.stdin.isatty():
            return False
        print("\nARTEMIS — AUTORIZAÇÃO NECESSÁRIA")
        print(f"Destino: Firefox ({FIREFOX_PACKAGE})")
        print(f"URL exata: {url}")
        print("A autorização vale somente para esta chamada.")
        return input(APPROVAL_PROMPT) == "S"
    except (EOFError, KeyboardInterrupt, OSError, ValueError, TypeError):
        return False


def launch_url_in_firefox(url: str) -> str:
    """Solicita ao Android que abra a URL no Firefox, sem shell ou fallback."""
    try:
        url = validate_http_url(url)
    except (ValueError, TypeError) as exc:
        return f"URL recusada: {exc}"

    if not request_url_approval(url):
        return "Abertura negada ou cancelada; Firefox não foi acionado."

    command = [
        "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", url,
        "-p", FIREFOX_PACKAGE,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Falha ao solicitar abertura no Firefox: {exc}"

    if result.returncode != 0:
        return "Falha ao solicitar abertura no Firefox; nenhum fallback foi usado."

    # Código zero confirma a solicitação ao Android, não o carregamento da página.
    return "Solicitação de abertura enviada ao Android para o Firefox."


__all__ = [
    "validate_http_url",
    "request_url_approval",
    "launch_url_in_firefox",
]
