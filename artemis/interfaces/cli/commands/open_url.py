"""Open an HTTP(S) URL in Firefox on Android with explicit approval."""
import typer

from artemis.tools.mobile.open_url_firefox import launch_url_in_firefox


def open_url_command(
    url: str = typer.Argument(..., help="URL HTTP(S) para abrir no Firefox."),
) -> None:
    """Abrir uma URL no Firefox sem iniciar o agente ADB."""
    try:
        result = launch_url_in_firefox(url)
    except Exception as exc:
        typer.echo(f"Falha ao abrir URL: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(str(result))
