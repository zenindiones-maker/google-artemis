"""Local web search and page reading tools for Artemis."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from httpcore._backends.auto import AutoBackend


class _PinnedNetworkBackend:
    """Conecta somente aos IPs públicos previamente validados para cada host."""

    def __init__(self, host_addresses):
        self._host_addresses = {
            str(host).rstrip(".").lower(): tuple(str(ip) for ip in addresses)
            for host, addresses in host_addresses.items()
        }
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host,
        port,
        timeout=None,
        local_address=None,
        socket_options=None,
    ):
        import ipaddress

        key = str(host).rstrip(".").lower()
        addresses = self._host_addresses.get(key)
        if not addresses:
            raise OSError("Host sem IP validado; conexão bloqueada.")

        last_error = None
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise OSError("IP não público bloqueado.")

            try:
                return await self._backend.connect_tcp(
                    str(ip),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except OSError as exc:
                last_error = exc

        raise OSError("Não foi possível conectar aos IPs validados.") from last_error

    async def connect_unix_socket(
        self,
        path,
        timeout=None,
        socket_options=None,
    ):
        raise OSError("Sockets Unix não são permitidos neste cliente web.")

    async def sleep(self, seconds):
        import asyncio
        await asyncio.sleep(seconds)


def _validated_addresses(url):
    """Retorna host, porta e IPs públicos validados para uma URL."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    _validate_url(url)
    parsed = urlparse(url)
    host = parsed.hostname.rstrip(".").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        records = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
        addresses = list({
            ipaddress.ip_address(record[4][0])
            for record in records
        })

    if not addresses or any(not ip.is_global for ip in addresses):
        raise ValueError("Destino não público bloqueado.")

    return host, port, tuple(str(ip) for ip in addresses)


def _pinned_client_for_url(url):
    """Cria um cliente isolado com DNS validado e conexão TCP fixada."""
    host, _port, addresses = _validated_addresses(url)
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    pool = getattr(transport, "_pool", None)

    # Falhar fechado se a versão instalada não expuser o backend esperado.
    if pool is None or not hasattr(pool, "_network_backend"):
        raise RuntimeError(
            "Backend HTTPX incompatível; conexão bloqueada por segurança."
        )

    pool._network_backend = _PinnedNetworkBackend({host: addresses})
    return httpx.AsyncClient(
        transport=transport,
        timeout=TIMEOUT,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )

MAX_BODY_BYTES = 1_000_000
MAX_TEXT_CHARS = 10_000
TIMEOUT = 12.0
USER_AGENT = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36"


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("URL inválida ou longa demais.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Somente URLs HTTP ou HTTPS são permitidas.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL sem host válido ou com credenciais.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".localhost", ".local", ".internal", ".test")
    ):
        raise ValueError("Destino local não permitido.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            records = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        except OSError as exc:
            raise ValueError(f"Não foi possível resolver o host: {host}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Destino não público bloqueado.")
    return url


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg", "iframe"}:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "iframe"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)
            if self.in_title:
                self.title_parts.append(text)


async def _get_limited(
    client: httpx.AsyncClient | None,
    url: str,
    allow_statuses: tuple[int, ...] = (),
) -> tuple[httpx.Response, bytes]:
    """Busca uma URL; cada salto usa DNS validado e conexão TCP fixada."""
    current = _validate_url(url)

    for _ in range(4):
        if client is None:
            # Um cliente novo por salto impede reutilização de conexões
            # validadas para outro host ou por uma resolução DNS anterior.
            async with _pinned_client_for_url(current) as pinned:
                response, body = await _read_one_response(pinned, current)
        else:
            # Compatibilidade com testes que injetam clientes simulados.
            response, body = await _read_one_response(client, current)

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ValueError("Redirecionamento sem destino.")
            current = _validate_url(urljoin(current, location))
            continue

        if response.status_code >= 400 and response.status_code not in allow_statuses:
            raise ValueError(f"Servidor respondeu HTTP {response.status_code}.")

        return response, body

    raise ValueError("Limite de redirecionamentos excedido.")


async def _read_one_response(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[httpx.Response, bytes]:
    """Lê a resposta sem permitir que o corpo ultrapasse 1 MB."""
    async with client.stream(
        "GET",
        url,
        follow_redirects=False,
    ) as response:
        # Clientes simulados usados nos testes podem expor apenas status e
        # headers. HTTPX real sempre fornece aiter_bytes().
        aiter_bytes = getattr(response, "aiter_bytes", None)
        if aiter_bytes is None:
            return response, b""

        data = bytearray()
        async for chunk in aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_BODY_BYTES:
                raise ValueError("Página excede o limite de 1 MB.")

        # O corpo fica limitado e disponível mesmo após fechar o stream.
        response._content = bytes(data)
        return response, bytes(data)



async def web_fetch(url: str) -> str:
    """Lê texto de uma página pública usando IP validado e conexão fixada."""
    try:
        response, body = await _get_limited(None, url)
        content_type = response.headers.get("content-type", "").lower()
        decoded = body.decode(response.encoding or "utf-8", errors="replace")

        if "html" in content_type or "<html" in decoded[:1000].lower():
            parser = _TextExtractor()
            parser.feed(decoded)
            title = " ".join(parser.title_parts)
            text = re.sub(r"[ \t]+", " ", " ".join(parser.parts))
            text = re.sub(r"\n\s*\n+", "\n", text).strip()
            return (
                f"URL: {response.url}\n"
                f"Título: {title or '(sem título)'}\n\n"
                f"{text[:MAX_TEXT_CHARS]}"
            )

        return f"URL: {response.url}\n\n{decoded[:MAX_TEXT_CHARS]}"
    except Exception as exc:
        return f"Falha ao consultar página: {type(exc).__name__}: {exc}"



class _SearchParser(HTMLParser):
    """Extract DuckDuckGo Lite result links and decode their destination URLs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._active: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        if "uddg=" not in href:
            return
        self._active = {"title": "", "url": href, "snippet": ""}

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            self._active["title"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._active is None:
            return
        from urllib.parse import parse_qs, urljoin, urlparse
        href = urljoin("https://lite.duckduckgo.com", self._active["url"])
        destination = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        parsed = urlparse(destination)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            self._active["url"] = destination
            self._active["title"] = " ".join(self._active["title"].split())
            self.results.append(self._active)
        self._active = None

async def web_search(query: str, max_results: int = 5) -> str:
    """Busca na web usando cliente com DNS validado e redirecionamentos manuais."""
    if not isinstance(query, str) or not query.strip():
        return "Informe uma consulta de busca."

    query = query.strip()[:300]
    try:
        max_results = max(1, min(int(max_results), 8))
    except (TypeError, ValueError):
        return "Quantidade de resultados inválida."

    endpoint = "https://lite.duckduckgo.com/lite/?" + urlencode({"q": query})

    try:
        response, body = await _get_limited(
            None,
            endpoint,
            allow_statuses=(202, 403, 429),
        )

        if response.status_code in {202, 403, 429}:
            return (
                f"A busca foi limitada pelo DuckDuckGo (HTTP {response.status_code}). "
                "Tente novamente mais tarde ou use web_fetch com uma URL pública conhecida."
            )

        decoded = body.decode(response.encoding or "utf-8", errors="replace")
        parser = _SearchParser()
        parser.feed(decoded)

        valid = [
            item for item in parser.results
            if item.get("title", "").strip()
            and item.get("url", "").startswith(("http://", "https://"))
        ][:max_results]

        if not valid:
            return "Nenhum resultado legível foi retornado pelo mecanismo de busca."

        lines = [f"Resultados para: {query}"]
        for index, item in enumerate(valid, 1):
            lines.append(
                f"{index}. {item['title'].strip()}\n"
                f"URL: {item['url']}\n"
                f"{item.get('snippet', '').strip()}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"Falha na busca: {type(exc).__name__}: {exc}"

